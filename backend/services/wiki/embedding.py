"""
向量嵌入服务模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/embedding.ts 移植。
提供文档分块 → 逐块嵌入 → 向量存储 → 向量搜索 → 页面级评分聚合的完整 RAG 流程。

核心功能：
- fetch_embedding: 调用 Embedding API 获取向量，支持自动减半重试
- embed_page: 对单个 Wiki 页面进行分块和嵌入
- embed_all_pages: 批量嵌入所有 Wiki 页面
- search_by_embedding: 向量搜索，页面级评分聚合

存储方案：
- 使用 numpy + JSON 文件存储向量索引
- 存储在 .llm-wiki/vector-index/ 目录下
- 向量搜索使用 numpy 余弦相似度
"""

import json
import logging
import math
import os
import time
from typing import Callable, Awaitable

import httpx
import numpy as np

from backend.services.wiki.text_chunker import chunk_markdown, Chunk

logger = logging.getLogger(__name__)

# 最近一次嵌入失败的描述，供 UI 展示
_last_embedding_error: str | None = None


def get_last_embedding_error() -> str | None:
    """获取最近一次嵌入失败的错误描述

    Returns:
        错误描述字符串，无错误时返回 None
    """
    return _last_embedding_error


# ---------------------------------------------------------------------------
# 错误判断
# ---------------------------------------------------------------------------

def _looks_like_oversize_error(http_status: int, body: str) -> bool:
    """判断错误响应是否为"输入过长"类型

    启发式匹配：覆盖 OpenAI、LM Studio、llama.cpp、Ollama、Azure 等的常见措辞。
    宁可多匹配也不漏匹配——误判只是多一次减半重试。

    Args:
        http_status: HTTP 状态码
        body: 响应体文本
    Returns:
        是否为输入过长错误
    """
    if http_status == 413:
        return True
    lower = body.lower()
    return any(
        keyword in lower
        for keyword in [
            "too long",
            "maximum context",
            "max_tokens",
            "max tokens",
            "context length",
            "token limit",
            "exceeds",
            "input length",
        ]
    )


# ---------------------------------------------------------------------------
# fetch_embedding：带自动减半重试的嵌入请求
# ---------------------------------------------------------------------------

async def fetch_embedding(
    text: str,
    config: dict,
    max_retries: int = 3,
) -> list[float] | None:
    """调用 Embedding API 获取文本向量

    遇到"输入过长"错误时，将文本长度减半重试，最多 max_retries 次，
    下限 64 字符。返回 None 表示最终失败。

    Args:
        text: 待嵌入的文本
        config: 嵌入配置字典
            - endpoint: Embedding API 端点 URL
            - model: 嵌入模型名称
            - apiKey: API 密钥（可选）
        max_retries: 最大重试次数
    Returns:
        浮点数向量列表，失败时返回 None
    """
    global _last_embedding_error

    endpoint = config.get("endpoint", "")
    if not endpoint:
        return None

    headers = {"Content-Type": "application/json"}
    api_key = config.get("apiKey", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    current = text
    attempts = 0

    while attempts <= max_retries:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    endpoint,
                    headers=headers,
                    json={"model": config.get("model", ""), "input": current},
                )

            if resp.status_code == 200:
                data = resp.json()
                embedding = data.get("data", [{}])[0].get("embedding")
                if embedding:
                    _last_embedding_error = None
                    return embedding
                _last_embedding_error = (
                    f"Embedding 响应缺少 data[0].embedding "
                    f"(得到 {json.dumps(data, ensure_ascii=False)[:200]})"
                )
                logger.warning("[Embedding] %s", _last_embedding_error)
                return None

            # 非 200：读取响应体判断是否为输入过长
            body_text = ""
            try:
                body_text = resp.text
            except Exception:
                pass

            if _looks_like_oversize_error(resp.status_code, body_text):
                if len(current) > 64 and attempts <= max_retries:
                    prev_len = len(current)
                    current = current[: len(current) // 2]
                    logger.warning(
                        "[Embedding] 自动减半重试：HTTP %d，%d 字符 → %d 字符 "
                        "(尝试 %d/%d)",
                        resp.status_code,
                        prev_len,
                        len(current),
                        attempts,
                        max_retries + 1,
                    )
                    continue

                _last_embedding_error = (
                    f"端点在 {len(current)} 字符时仍拒绝输入 — "
                    f"服务器上下文小于预期。"
                    f"请降低嵌入设置中的最大分块字符数。"
                    f"({body_text[:160]})"
                )
                logger.warning("[Embedding] %s", _last_embedding_error)
                return None

            # 非输入过长的确定性失败（认证、限流、服务器宕机等）
            _last_embedding_error = (
                f"API {resp.status_code} "
                f"{body_text[:200] if body_text else ''} "
                f"at {endpoint}"
            )
            logger.warning("[Embedding] %s", _last_embedding_error)
            return None

        except httpx.ConnectError:
            _last_embedding_error = (
                f"无法连接到 {endpoint}。请检查端点 URL、API 密钥和网络连接。"
            )
            logger.warning("[Embedding] %s", _last_embedding_error)
            return None
        except Exception as err:
            _last_embedding_error = str(err)
            logger.warning("[Embedding] %s", _last_embedding_error)
            return None

    # 重试次数耗尽
    _last_embedding_error = (
        f"Embedding 端点在减半到 {len(current)} 字符后仍拒绝输入 — "
        f"服务器上下文小于 {len(current) * 2}。"
        f"请降低嵌入设置中的最大分块字符数。"
    )
    logger.warning("[Embedding] %s", _last_embedding_error)
    return None


# ---------------------------------------------------------------------------
# 向量索引存储（numpy + JSON 文件方案）
# ---------------------------------------------------------------------------

def _get_vector_index_dir(project_path: str, custom_path: str | None = None) -> str:
    """获取向量索引存储目录

    优先使用自定义路径（来自 storage.vectorPath 配置），
    未提供或为空时使用默认路径（项目目录下 .llm-wiki/vector-index/）。

    Args:
        project_path: 项目路径
        custom_path: 自定义向量索引路径（可选）
    Returns:
        向量索引目录路径
    """
    if custom_path and custom_path.strip():
        return custom_path.strip()
    return os.path.join(project_path, ".llm-wiki", "vector-index")


def _ensure_index_dir(project_path: str, custom_path: str | None = None) -> str:
    """确保向量索引目录存在

    Args:
        project_path: 项目路径
        custom_path: 自定义向量索引路径（可选）
    Returns:
        向量索引目录路径
    """
    index_dir = _get_vector_index_dir(project_path, custom_path)
    os.makedirs(index_dir, exist_ok=True)
    return index_dir


class VectorStore:
    """基于 numpy + JSON 的向量存储

    存储结构：
    - {index_dir}/meta.json: 元数据（页面ID → 分块索引列表）
    - {index_dir}/vectors.npy: 所有向量拼接的 numpy 矩阵
    - {index_dir}/chunks.json: 分块文本和元信息

    Attributes:
        index_dir: 索引目录路径
        vectors: numpy 向量矩阵 (N, D)
        chunks: 分块信息列表
        page_map: 页面ID → 分块索引列表的映射
    """

    def __init__(self, index_dir: str):
        self.index_dir = index_dir
        self.vectors: np.ndarray | None = None
        self.chunks: list[dict] = []
        self.page_map: dict[str, list[int]] = {}

    def load(self) -> bool:
        """从磁盘加载索引

            Returns:
                是否成功加载
        """
        vectors_path = os.path.join(self.index_dir, "vectors.npy")
        chunks_path = os.path.join(self.index_dir, "chunks.json")
        meta_path = os.path.join(self.index_dir, "meta.json")

        if not os.path.exists(vectors_path) or not os.path.exists(chunks_path):
            return False

        try:
            self.vectors = np.load(vectors_path)
            with open(chunks_path, "r", encoding="utf-8") as f:
                self.chunks = json.load(f)
            with open(meta_path, "r", encoding="utf-8") as f:
                self.page_map = json.load(f)
            return True
        except Exception as err:
            logger.warning("[VectorStore] 加载索引失败: %s", err)
            return False

    def save(self) -> None:
        """将索引保存到磁盘"""
        if self.vectors is not None:
            np.save(os.path.join(self.index_dir, "vectors.npy"), self.vectors)
        with open(os.path.join(self.index_dir, "chunks.json"), "w", encoding="utf-8") as f:
            json.dump(self.chunks, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.index_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(self.page_map, f, ensure_ascii=False, indent=2)

    def upsert_page(
        self,
        page_id: str,
        chunks_data: list[dict],
    ) -> None:
        """插入或替换一个页面的向量数据

        先删除该页面的旧数据，再插入新数据。

        Args:
            page_id: 页面 ID
            chunks_data: 分块数据列表，每项包含
                - chunk_index: 分块序号
                - chunk_text: 分块文本
                - heading_path: 标题面包屑
                - embedding: 嵌入向量
        """
        # 删除旧数据
        self.delete_page(page_id)

        # 插入新数据
        new_indices = []
        new_vectors = []

        for chunk in chunks_data:
            idx = len(self.chunks)
            new_indices.append(idx)
            new_vectors.append(chunk["embedding"])

            self.chunks.append({
                "page_id": page_id,
                "chunk_index": chunk["chunk_index"],
                "chunk_text": chunk["chunk_text"],
                "heading_path": chunk["heading_path"],
            })

        # 更新向量矩阵
        new_vec_array = np.array(new_vectors, dtype=np.float32)
        if self.vectors is None or len(self.vectors) == 0:
            self.vectors = new_vec_array
        else:
            self.vectors = np.vstack([self.vectors, new_vec_array])

        self.page_map[page_id] = new_indices

    def delete_page(self, page_id: str) -> None:
        """删除一个页面的所有向量数据

        通过重建索引实现删除（简单方案）。

        Args:
            page_id: 页面 ID
        """
        if page_id not in self.page_map:
            return

        # 收集要保留的索引
        remove_indices = set(self.page_map[page_id])
        keep_indices = [
            i for i in range(len(self.chunks)) if i not in remove_indices
        ]

        # 重建 chunks 和 vectors
        new_chunks = [self.chunks[i] for i in keep_indices]
        new_vectors = (
            self.vectors[keep_indices] if self.vectors is not None and len(self.vectors) > 0
            else None
        )

        # 重建 page_map（索引重新编号）
        old_to_new = {old: new for new, old in enumerate(keep_indices)}
        new_page_map: dict[str, list[int]] = {}
        for pid, indices in self.page_map.items():
            if pid == page_id:
                continue
            new_page_map[pid] = [old_to_new[i] for i in indices if i in old_to_new]

        self.chunks = new_chunks
        self.vectors = new_vectors
        del self.page_map[page_id]
        # 合并新 page_map
        self.page_map = new_page_map

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 30,
    ) -> list[dict]:
        """向量搜索：使用余弦相似度查找最相关的分块

        Args:
            query_embedding: 查询向量
            top_k: 返回前 K 个结果
        Returns:
            搜索结果列表，每项包含 page_id, chunk_index, chunk_text, heading_path, score
        """
        if self.vectors is None or len(self.vectors) == 0:
            return []

        query_vec = np.array(query_embedding, dtype=np.float32)

        # 归一化
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        query_vec = query_vec / query_norm

        vecs_norm = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        vecs_norm = np.maximum(vecs_norm, 1e-8)  # 防止除零
        normalized_vecs = self.vectors / vecs_norm

        # 余弦相似度
        scores = normalized_vecs @ query_vec

        # 取 top_k
        if len(scores) <= top_k:
            top_indices = np.argsort(scores)[::-1]
        else:
            top_indices = np.argpartition(scores, -top_k)[-top_k:]
            top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        results = []
        for idx in top_indices:
            if scores[idx] <= 0:
                continue
            chunk_info = self.chunks[idx]
            results.append({
                "page_id": chunk_info["page_id"],
                "chunk_index": chunk_info["chunk_index"],
                "chunk_text": chunk_info["chunk_text"],
                "heading_path": chunk_info["heading_path"],
                "score": float(scores[idx]),
            })

        return results

    def count_chunks(self) -> int:
        """获取索引中的分块总数

        Returns:
            分块数量
        """
        return len(self.chunks)


def _get_vector_store(project_path: str, custom_path: str | None = None) -> VectorStore:
    """获取项目的向量存储实例

    Args:
        project_path: 项目路径
        custom_path: 自定义向量索引路径（可选）
    Returns:
        VectorStore 实例
    """
    index_dir = _ensure_index_dir(project_path, custom_path)
    store = VectorStore(index_dir)
    store.load()
    return store


# ---------------------------------------------------------------------------
# 分块富化
# ---------------------------------------------------------------------------

def _enrich_chunk_for_embedding(page_title: str, chunk: Chunk) -> str:
    """构建嵌入文本：页面标题 + 标题面包屑 + 分块内容

    面包屑是短分块最重要的上下文——一段关于"Mixture of Experts"的 300 字摘录，
    在嵌入文本显式命名其所属章节时更容易被检索到。

    Args:
        page_title: 页面标题
        chunk: 分块对象
    Returns:
        富化后的嵌入文本
    """
    parts: list[str] = []
    if page_title.strip():
        parts.append(page_title.strip())
    if chunk.heading_path.strip():
        parts.append(chunk.heading_path.strip())
    parts.append(chunk.text.strip())
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# 公共 API：embed_page / embed_all_pages / search_by_embedding
# ---------------------------------------------------------------------------

async def embed_page(
    project_path: str,
    page_id: str,
    title: str,
    content: str,
    config: dict,
    custom_path: str | None = None,
) -> None:
    """嵌入单个 Wiki 页面：分块 → 逐块嵌入 → 替换该页面的向量

    每次瞬态失败都保留已有的向量行（空 upsert 是无操作）。

    Args:
        project_path: 项目路径
        page_id: 页面 ID（文件名去掉 .md）
        title: 页面标题
        content: 页面完整内容（含 frontmatter）
        config: 嵌入配置字典
            - enabled: 是否启用嵌入
            - model: 嵌入模型名称
            - endpoint: Embedding API 端点
            - apiKey: API 密钥（可选）
            - maxChunkChars: 最大分块字符数（默认 1000）
            - overlapChunkChars: 重叠字符数（默认 200）
        custom_path: 自定义向量索引路径（可选，来自 storage.vectorPath）
    """
    if not config.get("enabled") or not config.get("model"):
        return

    t0 = time.perf_counter()

    # 分块
    chunks = chunk_markdown(
        content,
        target_chars=config.get("maxChunkChars", 1000),
        overlap_chars=config.get("overlapChunkChars", 200),
    )
    if not chunks:
        return

    # 逐块嵌入
    rows: list[dict] = []
    failed_chunks = 0
    for chunk in chunks:
        embed_text = _enrich_chunk_for_embedding(title, chunk)
        vec = await fetch_embedding(embed_text, config)
        if vec:
            rows.append({
                "chunk_index": chunk.index,
                "chunk_text": chunk.text,
                "heading_path": chunk.heading_path,
                "embedding": vec,
            })
        else:
            failed_chunks += 1

    if not rows:
        logger.info(
            '[Embedding] 页面 "%s" 未索引 — 所有 %d 个分块均失败。'
            "请检查 get_last_embedding_error()。",
            page_id,
            len(chunks),
        )
        return

    # 写入向量存储
    store = _get_vector_store(project_path, custom_path)
    store.upsert_page(page_id, rows)
    store.save()

    elapsed = round((time.perf_counter() - t0) * 1000)
    logger.info(
        '[Embedding] 页面 "%s" 已索引: %d/%d 分块 '
        "(%d 跳过)，耗时 %dms",
        page_id,
        len(rows),
        len(chunks),
        failed_chunks,
        elapsed,
    )


async def embed_all_pages(
    project_path: str,
    config: dict,
    on_progress: Callable[[int, int], Awaitable[None] | None] | None = None,
    custom_path: str | None = None,
) -> int:
    """批量嵌入所有 Wiki 内容页面

    跳过结构页面（index / log / overview / purpose / schema）——它们是聚合视图，不是检索目标。

    Args:
        project_path: 项目路径
        config: 嵌入配置字典
        on_progress: 进度回调 (done, total)
        custom_path: 自定义向量索引路径（可选，来自 storage.vectorPath）
    Returns:
        已处理的页面数
    """
    if not config.get("enabled") or not config.get("model"):
        return 0

    wiki_dir = os.path.join(project_path, "wiki")
    if not os.path.exists(wiki_dir):
        return 0

    # 递归收集所有 .md 文件
    md_files: list[tuple[str, str]] = []  # (page_id, file_path)
    _skip_ids = {"index", "log", "overview", "purpose", "schema"}

    for root, dirs, files in os.walk(wiki_dir):
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for fname in files:
            if fname.endswith(".md"):
                page_id = fname[:-3]
                if page_id not in _skip_ids:
                    md_files.append((page_id, os.path.join(root, fname)))

    done = 0
    for page_id, file_path in md_files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 提取标题
            import re
            title_match = re.search(
                r"^title:\s*[\"']?(.+?)[\"']?\s*$", content, re.MULTILINE
            )
            title = title_match.group(1).strip() if title_match else page_id

            await embed_page(project_path, page_id, title, content, config, custom_path=custom_path)
        except Exception:
            # 单文件失败不中断批量处理
            pass

        done += 1
        if on_progress:
            result = on_progress(done, len(md_files))
            if asyncio.iscoroutine(result):
                await result

    return done


# 需要导入 asyncio
import asyncio


class PageSearchResult:
    """页面级搜索结果

    Attributes:
        id: 页面 ID
        score: 混合评分
        matched_chunks: 匹配的分块信息列表（可选）
    """

    def __init__(
        self,
        id: str,
        score: float,
        matched_chunks: list[dict] | None = None,
    ):
        self.id = id
        self.score = score
        self.matched_chunks = matched_chunks or []

    def to_dict(self) -> dict:
        """转为字典

        Returns:
            字典表示
        """
        result = {"id": self.id, "score": self.score}
        if self.matched_chunks:
            result["matchedChunks"] = self.matched_chunks
        return result


async def search_by_embedding(
    project_path: str,
    query: str,
    config: dict,
    top_k: int = 10,
    custom_path: str | None = None,
) -> list[PageSearchResult]:
    """向量搜索：嵌入查询 → 搜索分块 → 页面级评分聚合

    评分公式：
    blended = top_score + min(tail_sum * 0.3, max(0, 1 - top_score))

    多个分块属于同一页面时，最高分作为主分，其余分块的加权和作为补充，
    但补充分不超过 (1 - 主分)，防止多个弱分块淹没单个强分块页面。

    Args:
        project_path: 项目路径
        query: 查询文本
        config: 嵌入配置字典
        top_k: 返回前 K 个页面
        custom_path: 自定义向量索引路径（可选，来自 storage.vectorPath）
    Returns:
        PageSearchResult 列表，按分数降序排列
    """
    if not config.get("enabled") or not config.get("model"):
        return []

    # 嵌入查询
    query_emb = await fetch_embedding(query, config)
    if not query_emb:
        return []

    t0 = time.perf_counter()

    # 搜索分块
    store = _get_vector_store(project_path, custom_path)
    raw_chunks = store.search(query_emb, top_k=max(top_k * 3, 30))

    if not raw_chunks:
        return []

    # 按页面分组
    by_page: dict[str, list[dict]] = {}
    for c in raw_chunks:
        page_id = c["page_id"]
        if page_id not in by_page:
            by_page[page_id] = []
        by_page[page_id].append(c)

    # 页面级评分聚合
    ranked: list[PageSearchResult] = []
    for page_id, chunks in by_page.items():
        # 按分数降序排列
        chunks.sort(key=lambda c: c["score"], reverse=True)
        top = chunks[0]["score"]
        tail = sum(c["score"] for c in chunks[1:])

        # 混合评分：主分 + 加权尾分（上限为 1 - 主分）
        blended = top + min(tail * 0.3, max(0, 1 - top))

        # 保留前 3 个匹配分块供 UI 展示
        matched = [
            {
                "text": c["chunk_text"],
                "headingPath": c["heading_path"],
                "score": c["score"],
            }
            for c in chunks[:3]
        ]

        ranked.append(PageSearchResult(
            id=page_id,
            score=blended,
            matched_chunks=matched,
        ))

    # 按分数降序排列
    ranked.sort(key=lambda r: r.score, reverse=True)

    elapsed = round((time.perf_counter() - t0) * 1000)
    logger.info(
        "[Embedding] 向量搜索: %d 分块 → %d 页面，耗时 %dms",
        len(raw_chunks),
        len(ranked),
        elapsed,
    )

    return ranked[:top_k]


async def remove_page_embedding(project_path: str, page_id: str, custom_path: str | None = None) -> None:
    """从向量索引中删除一个页面的嵌入

    在源文件删除流程中调用，防止孤立分块污染后续搜索。

    Args:
        project_path: 项目路径
        page_id: 页面 ID
        custom_path: 自定义向量索引路径（可选，来自 storage.vectorPath）
    """
    try:
        store = _get_vector_store(project_path, custom_path)
        store.delete_page(page_id)
        store.save()
    except Exception:
        # 非关键操作
        pass


def get_embedding_count(project_path: str, custom_path: str | None = None) -> int:
    """获取向量索引中的分块总数

    用于设置页面展示"N 个分块已索引"状态。

    Args:
        project_path: 项目路径
        custom_path: 自定义向量索引路径（可选，来自 storage.vectorPath）
    Returns:
        分块数量
    """
    try:
        store = _get_vector_store(project_path, custom_path)
        return store.count_chunks()
    except Exception:
        return 0
