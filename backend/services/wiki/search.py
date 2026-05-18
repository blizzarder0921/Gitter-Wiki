"""
搜索服务模块

混合检索系统：BM25 关键词搜索 + 向量语义搜索，通过 RRF 融合。
移植自 TypeScript 项目 llm_wiki-0.4.9/src/lib/search.ts。

核心功能：
- CJK 分词：对中文文本生成 bigram + 单字 + 原始 token
- 多级评分权重：文件名精确匹配 +200，标题短语匹配 +50，内容短语 +20/次 等
- RRF 融合（K=60）：fused(p) = 1/(K + token_rank) + 1/(K + vector_rank)
- 向量搜索后补：向量搜索命中的页面如果不在 token 结果中，从磁盘物化补充

依赖：embedding.py, text_chunker.py
"""

import os
import re
import math
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 最大返回结果数
MAX_RESULTS = 20

# 摘要上下文字符数
SNIPPET_CONTEXT = 80

# RRF 融合常数（Cormack et al. SIGIR 2009）
RRF_K = 60

# ── 评分权重 ──────────────────────────────────────────────────────
# 文件名精确匹配（如查询 "attention" 匹配 attention.md）
FILENAME_EXACT_BONUS = 200
# 标题短语匹配
PHRASE_IN_TITLE_BONUS = 50
# 内容短语出现（每次）
PHRASE_IN_CONTENT_PER_OCC = 20
# 内容短语出现次数上限（避免大文件跑分）
MAX_PHRASE_OCC_COUNTED = 10
# 标题 token 匹配（每 token）
TITLE_TOKEN_WEIGHT = 5
# 内容 token 匹配（每 token）
CONTENT_TOKEN_WEIGHT = 1

# 停用词集合
STOP_WORDS = frozenset([
    # 中文停用词
    "的", "是", "了", "什么", "在", "有", "和", "与", "对", "从",
    # 英文停用词
    "the", "is", "a", "an", "what", "how", "are", "was", "were",
    "do", "does", "did", "be", "been", "being", "have", "has", "had",
    "it", "its", "in", "on", "at", "to", "for", "of", "with", "by",
    "this", "that", "these", "those",
])

# CJK 字符范围正则
CJK_REGEX = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf]')

# 标点分隔正则（用于 token 切分）
TOKEN_SPLIT_REGEX = re.compile(r'[\s,，。！？、；：""''（）()\-_/\\·~～…]+')

# 首尾标点清理正则（用于短语匹配前的归一化）
TRIM_PUNCT_RE = re.compile(
    r'^[\s,，。！？、；：""''（）()\-_/\\·~～…]+'
    r'|[\s,，。！？、；：""''（）()\-_/\\·~～…]+$'
)

# Markdown 图片引用正则
IMAGE_REF_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)\)')

# Wikilink 正则（用于 frontmatter 解析中的 sources 字段）
WIKILINK_REGEX = re.compile(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]')


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class ImageRef:
    """图片引用

    Attributes:
        url: 图片 URL（Markdown 中的原始路径）
        alt: 替代文本
    """
    def __init__(self, url: str, alt: str):
        self.url = url
        self.alt = alt

    def to_dict(self) -> dict:
        return {"url": self.url, "alt": self.alt}


class SearchResult:
    """搜索结果

    Attributes:
        path: 文件相对路径
        title: 页面标题
        snippet: 内容摘要
        titleMatch: 标题是否匹配
        score: RRF 融合分数
        images: 页面中的图片引用列表
    """
    def __init__(self, path: str, title: str, snippet: str,
                 title_match: bool, score: float, images: list[ImageRef]):
        self.path = path
        self.title = title
        self.snippet = snippet
        self.titleMatch = title_match
        self.score = score
        self.images = images

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "snippet": self.snippet,
            "titleMatch": self.titleMatch,
            "score": self.score,
            "images": [img.to_dict() for img in self.images],
        }


# ---------------------------------------------------------------------------
# CJK 分词
# ---------------------------------------------------------------------------

def tokenize_query(query: str) -> list[str]:
    """对查询文本进行分词，支持 CJK bigram

    对中文文本生成 bigram + 单字 + 原始 token：
    "默会知识" → ["默会", "会知", "知识", "默", "会", "知", "识", "默会知识"]

    Args:
        query: 查询字符串
    Returns:
        去重后的 token 列表
    """
    # 按标点和空白切分
    raw_tokens = [
        t for t in TOKEN_SPLIT_REGEX.split(query.lower())
        if len(t) > 1 and t not in STOP_WORDS
    ]

    tokens: list[str] = []

    for token in raw_tokens:
        # 检查是否包含 CJK 字符
        if CJK_REGEX.search(token) and len(token) > 2:
            chars = list(token)
            # 添加 bigram（对中文最有用）
            for i in range(len(chars) - 1):
                tokens.append(chars[i] + chars[i + 1])
            # 添加单字（排除停用词）
            for ch in chars:
                if ch not in STOP_WORDS:
                    tokens.append(ch)
            # 保留原始 token（用于精确短语匹配）
            tokens.append(token)
        else:
            tokens.append(token)

    # 去重并保持顺序
    seen: set[str] = set()
    result: list[str] = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            result.append(t)

    return result


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _token_match_score(text: str, tokens: list[str]) -> int:
    """计算文本与 token 列表的匹配分数

    Args:
        text: 待匹配文本
        tokens: token 列表
    Returns:
        匹配的 token 数量
    """
    lower = text.lower()
    return sum(1 for token in tokens if token in lower)


def _count_occurrences(haystack_lower: str, needle_lower: str) -> int:
    """统计子串出现次数

    Args:
        haystack_lower: 被搜索文本（已小写）
        needle_lower: 搜索词（已小写）
    Returns:
        出现次数
    """
    if not needle_lower:
        return 0
    count = 0
    pos = 0
    while True:
        idx = haystack_lower.find(needle_lower, pos)
        if idx == -1:
            break
        count += 1
        pos = idx + len(needle_lower)
    return count


def _flatten_md_files(directory: str, prefix: str = "") -> list[dict]:
    """递归扫描目录，收集所有 .md 文件信息

    Args:
        directory: 目录绝对路径
        prefix: 路径前缀
    Returns:
        文件信息列表
    """
    files: list[dict] = []
    if not os.path.exists(directory):
        return files

    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return files

    for entry in entries:
        if entry.startswith("."):
            continue
        full_path = os.path.join(directory, entry)
        rel_path = f"{prefix}/{entry}" if prefix else entry

        if os.path.isdir(full_path):
            files.extend(_flatten_md_files(full_path, rel_path))
        elif entry.endswith(".md"):
            files.append({
                "name": entry,
                "path": full_path,
                "rel_path": rel_path,
            })

    return files


def _extract_title(content: str, file_name: str) -> str:
    """从 Markdown 内容提取页面标题

    Args:
        content: Markdown 文件内容
        file_name: 文件名
    Returns:
        页面标题
    """
    fm_match = re.search(r'^---\n[\s\S]*?^title:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    if fm_match:
        return fm_match.group(1).strip()

    heading_match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if heading_match:
        return heading_match.group(1).strip()

    return file_name.replace(".md", "").replace("-", " ")


def _extract_image_refs(content: str) -> list[ImageRef]:
    """从 Markdown 内容提取图片引用

    Args:
        content: Markdown 文件内容
    Returns:
        去重后的图片引用列表
    """
    seen: set[str] = set()
    out: list[ImageRef] = []
    for m in IMAGE_REF_RE.finditer(content):
        url = m.group(2)
        if url in seen:
            continue
        seen.add(url)
        out.append(ImageRef(url=url, alt=m.group(1)))
    return out


def _build_snippet(content: str, query: str) -> str:
    """构建搜索结果摘要

    在内容中定位查询词位置，截取前后上下文。

    Args:
        content: Markdown 文件内容
        query: 查询锚点文本
    Returns:
        摘要文本
    """
    lower = content.lower()
    lower_query = query.lower()
    idx = lower.find(lower_query)

    if idx == -1:
        # 未找到锚点，截取内容开头
        snippet = content[:SNIPPET_CONTEXT * 2].replace("\n", " ")
        return snippet

    start = max(0, idx - SNIPPET_CONTEXT)
    end = min(len(content), idx + len(query) + SNIPPET_CONTEXT)
    snippet = content[start:end].replace("\n", " ")

    if start > 0:
        snippet = "..." + snippet
    if end < len(content):
        snippet = snippet + "..."

    return snippet


def _score_file(
    file_info: dict,
    content: str,
    tokens: list[str],
    query_phrase: str,
    query: str,
) -> Optional[SearchResult]:
    """对单个文件进行评分

    纯评分逻辑，无 IO 操作。

    Args:
        file_info: 文件信息（name, path, rel_path）
        content: 文件内容
        tokens: 分词后的 token 列表
        query_phrase: 归一化后的查询短语（用于短语匹配）
        query: 原始查询文本
    Returns:
        搜索结果（无匹配返回 None）
    """
    title = _extract_title(content, file_info["name"])
    title_text = f"{title} {file_info['name']}"
    title_lower = title_text.lower()
    content_lower = content.lower()
    file_stem = file_info["name"].replace(".md", "").lower()

    # 精确匹配信号（最强）
    filename_exact = (file_stem == query_phrase)
    title_has_phrase = (
        len(query_phrase) > 0 and query_phrase in title_lower
    )
    content_phrase_occ = min(
        _count_occurrences(content_lower, query_phrase),
        MAX_PHRASE_OCC_COUNTED,
    )

    # Token 级别信号
    title_token_score = _token_match_score(title_text, tokens)
    content_token_score = _token_match_score(content, tokens)

    # 无任何匹配则跳过
    if (not filename_exact and not title_has_phrase
            and content_phrase_occ == 0
            and title_token_score == 0
            and content_token_score == 0):
        return None

    # 计算总分
    score = (
        (FILENAME_EXACT_BONUS if filename_exact else 0)
        + (PHRASE_IN_TITLE_BONUS if title_has_phrase else 0)
        + content_phrase_occ * PHRASE_IN_CONTENT_PER_OCC
        + title_token_score * TITLE_TOKEN_WEIGHT
        + content_token_score * CONTENT_TOKEN_WEIGHT
    )

    is_title_match = title_token_score > 0 or title_has_phrase

    # 选择摘要锚点
    if content_phrase_occ > 0:
        snippet_anchor = query_phrase
    else:
        # 找到第一个在内容中出现的 token
        snippet_anchor = query
        for t in tokens:
            if t in content_lower:
                snippet_anchor = t
                break

    return SearchResult(
        path=file_info["rel_path"],
        title=title,
        snippet=_build_snippet(content, snippet_anchor),
        title_match=is_title_match,
        score=score,
        images=_extract_image_refs(content),
    )


def _normalize_path(p: str) -> str:
    """归一化路径：统一使用正斜杠

    Args:
        p: 文件路径
    Returns:
        归一化后的路径
    """
    return p.replace("\\", "/")


def _get_file_stem(path: str) -> str:
    """从路径中提取文件名（去掉目录和 .md 后缀）

    Args:
        path: 文件路径
    Returns:
        文件 stem
    """
    basename = os.path.basename(path)
    return basename.replace(".md", "") if basename.endswith(".md") else basename


# ---------------------------------------------------------------------------
# 核心接口
# ---------------------------------------------------------------------------

async def search_wiki(
    project_path: str,
    query: str,
    config: dict = None,
) -> list[dict]:
    """混合检索 Wiki 知识库

    BM25 关键词搜索 + 向量语义搜索，通过 RRF 融合。

    Args:
        project_path: 项目根目录的绝对路径
        query: 搜索查询字符串
        config: 搜索配置（可选），包含向量搜索相关参数：
            - vector_enabled: 是否启用向量搜索
            - embedding_model: 向量模型名称
            - embedding_endpoint: 向量搜索端点
            - embedding_api_key: 向量搜索 API Key
    Returns:
        搜索结果列表，每项包含 path/title/snippet/titleMatch/score/images
    """
    if not query.strip():
        return []

    tokens = tokenize_query(query)
    # 如果所有 token 都被过滤掉，使用原始查询作为单个 token
    effective_tokens = tokens if tokens else [query.strip().lower()]
    results: list[SearchResult] = []

    # ── Token 搜索：扫描 Wiki 页面 ──────────────────────────────
    wiki_root = os.path.join(project_path, "wiki")
    try:
        wiki_files = _flatten_md_files(wiki_root)
        # 归一化查询短语（去除首尾标点）
        query_phrase = TRIM_PUNCT_RE.sub("", query.strip().lower())

        for file_info in wiki_files:
            try:
                with open(file_info["path"], "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError):
                continue

            result = _score_file(file_info, content, effective_tokens,
                                 query_phrase, query)
            if result:
                results.append(result)
    except Exception as e:
        logger.warning(f"[search] Wiki 目录扫描失败: {e}")

    # ── 构建 token 侧排名 ────────────────────────────────────────
    token_sorted = sorted(results, key=lambda r: r.score, reverse=True)
    token_rank: dict[str, int] = {}
    for i, r in enumerate(token_sorted):
        token_rank[_normalize_path(r.path)] = i + 1  # 1-indexed

    # ── 向量搜索 ─────────────────────────────────────────────────
    vector_rank: dict[str, int] = {}
    vector_count = 0

    if config and config.get("vector_enabled") and config.get("embedding_model"):
        try:
            from backend.services.wiki.embedding import search_by_embedding
            vector_results = await search_by_embedding(
                project_path, query, config, top_k=10
            )
            vector_count = len(vector_results)

            # 构建向量排名映射
            for i, vr in enumerate(vector_results):
                vector_rank[vr["id"]] = i + 1  # 1-indexed

            # 物化向量搜索命中但 token 搜索未包含的页面
            known_ids: set[str] = {_get_file_stem(r.path) for r in results}
            added = 0

            # Wiki 子目录列表
            wiki_dirs = ["entities", "concepts", "sources",
                         "synthesis", "comparison", "queries"]

            for vr in vector_results:
                vr_id = vr["id"]
                if vr_id in known_ids:
                    continue

                # 在各子目录中尝试查找对应 .md 文件
                for dir_name in wiki_dirs:
                    try_path = os.path.join(
                        project_path, "wiki", dir_name, f"{vr_id}.md"
                    )
                    try:
                        with open(try_path, "r", encoding="utf-8") as f:
                            content = f.read()
                        title = _extract_title(content, f"{vr_id}.md")
                        rel_path = f"wiki/{dir_name}/{vr_id}.md"
                        results.append(SearchResult(
                            path=rel_path,
                            title=title,
                            snippet=_build_snippet(content, query),
                            title_match=False,
                            score=0,  # RRF 覆盖
                            images=_extract_image_refs(content),
                        ))
                        known_ids.add(vr_id)
                        added += 1
                        break
                    except (OSError, UnicodeDecodeError):
                        continue

            if added > 0:
                logger.debug(f"[search] 向量搜索补充了 {added} 个页面")

        except ImportError:
            logger.debug("[search] embedding 模块不可用，跳过向量搜索")
        except Exception as e:
            logger.warning(f"[search] 向量搜索失败: {e}")

    # ── RRF 融合 ─────────────────────────────────────────────────
    # fused(p) = 1/(K + token_rank) + 1/(K + vector_rank)
    # 不在任何一侧的列表中，该侧贡献为 0
    for r in results:
        rrf = 0.0
        t_rank = token_rank.get(_normalize_path(r.path))
        v_rank = vector_rank.get(_get_file_stem(r.path))
        if t_rank is not None:
            rrf += 1.0 / (RRF_K + t_rank)
        if v_rank is not None:
            rrf += 1.0 / (RRF_K + v_rank)
        r.score = rrf

    # 按 RRF 分数降序排列，同分按路径字母序排列（确保确定性）
    results.sort(key=lambda r: (-r.score, r.path))

    logger.debug(
        f"[search] query=\"{query}\" | "
        f"RRF fused: {len(token_rank)} token + {vector_count} vector "
        f"→ {len(results)} unique"
    )

    return [r.to_dict() for r in results[:MAX_RESULTS]]
