"""
Wiki 审核系统模块

从 TypeScript 参考项目 llm_wiki-0.4.9/src/lib/sweep-reviews.ts 移植，
适配 Python FastAPI 环境。

功能：
- 自动清理过期的审核项（sweep_resolved_reviews）
- 两阶段处理：
  1. 规则匹配：missing-page 检查候选名称是否已存在；duplicate 检查 affectedPages 是否仍全部存在
  2. LLM 判断：批量 40 条送 LLM，要求返回 {"resolved": ["id1", "id2"]}
- JSON 提取工具：extract_json_object

依赖：
- llm_client.py: LLM 流式调用
"""

import os
import re
import json
import asyncio
from typing import Optional

from backend.services.wiki.llm_client import stream_chat


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 每批 LLM 判断的最大审核项数
JUDGE_BATCH_SIZE = 40
# 最大 LLM 判断批次（避免无限调用）
MAX_JUDGE_BATCHES = 5
# 提示词中最大页面数
MAX_PAGES_IN_PROMPT = 300

# 审核标题前缀正则（英文和中文）
REVIEW_TITLE_PREFIX_RE = re.compile(
    r"^(missing[\s-]?page[:：]\s*|duplicate[\s-]?page[:：]\s*|"
    r"possible[\s-]?duplicate[:：]\s*|"
    r"缺失页面[:：]\s*|缺少页面[:：]\s*|"
    r"重复页面[:：]\s*|疑似重复[:：]\s*)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class WikiPageSummary:
    """Wiki 页面摘要

    Attributes:
        id: 文件名（不含 .md）
        title: frontmatter 中的标题（可选）
    """

    def __init__(self, id: str, title: Optional[str] = None):
        self.id = id
        self.title = title


class WikiIndex:
    """Wiki 索引

    Attributes:
        by_id: 按文件名（小写）索引的集合
        by_title: 按标题（小写）索引的集合
        pages: 页面摘要列表
    """

    def __init__(self):
        self.by_id: set[str] = set()
        self.by_title: set[str] = set()
        self.pages: list[WikiPageSummary] = []


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _flatten_md_files(directory: str) -> list[str]:
    """递归获取目录下所有 .md 文件的完整路径

    Args:
        directory: 要扫描的目录路径
    Returns:
        所有 .md 文件的完整路径列表
    """
    md_files = []
    if not os.path.exists(directory):
        return md_files

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))

    return md_files


def _build_wiki_index(project_path: str) -> WikiIndex:
    """构建 Wiki 页面索引

    索引包含文件名（id）和 frontmatter 中的标题，均小写归一化。

    Args:
        project_path: 项目根目录路径
    Returns:
        WikiIndex 索引对象
    """
    index = WikiIndex()
    wiki_root = os.path.join(project_path, "wiki")

    if not os.path.exists(wiki_root):
        return index

    files = _flatten_md_files(wiki_root)

    for file_path in files:
        file_name = os.path.basename(file_path)
        page_id = re.sub(r"\.md$", "", file_name).lower()
        index.by_id.add(page_id)

        # 尝试从 frontmatter 提取标题
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            # 匹配 frontmatter 中的 title 字段
            title_match = re.search(
                r"^---\n[\s\S]*?^title:\s*[\"']?(.+?)[\"']?\s*$",
                content,
                re.MULTILINE,
            )
            if title_match:
                title = title_match.group(1).strip()
                index.by_title.add(title.lower())
                index.pages.append(WikiPageSummary(id=page_id, title=title))
            else:
                index.pages.append(WikiPageSummary(id=page_id))
        except Exception:
            index.pages.append(WikiPageSummary(id=page_id))

    return index


def normalize_review_title(title: str) -> str:
    """归一化审核标题，用于等价比较

    操作：
    - 去除前缀（如 "Missing page:"、"缺失页面:" 等）
    - 合并空白
    - 转小写

    Args:
        title: 原始审核标题
    Returns:
        归一化后的标题字符串
    """
    cleaned = REVIEW_TITLE_PREFIX_RE.sub("", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def _extract_candidate_names(item: dict) -> list[str]:
    """从审核项的标题/描述中提取候选页面名称

    保守策略：仅提取可以确信为页面名称的候选项。

    Args:
        item: 审核项字典，包含 title、affectedPages 等字段
    Returns:
        候选名称列表
    """
    names = set()

    # 审核标题本身通常是缺失页面的名称
    cleaned = normalize_review_title(item.get("title", ""))
    if cleaned and len(cleaned) <= 100:
        names.add(cleaned)

    # 检查 affectedPages 中的文件名
    for page in item.get("affectedPages") or []:
        base = page.split("/")[-1]
        base = re.sub(r"\.md$", "", base)
        if base:
            names.add(base.lower())

    return list(names)


def _page_exists(name: str, index: WikiIndex) -> bool:
    """检查候选名称是否匹配已存在的 Wiki 页面

    匹配策略：
    - 精确文件名匹配（kebab-case 或现有 id）
    - 空格替换为连字符后匹配
    - 精确标题匹配（来自 frontmatter）

    Args:
        name: 候选页面名称
        index: Wiki 索引
    Returns:
        是否存在匹配的页面
    """
    normalized = name.strip().lower()
    if not normalized:
        return False

    # 精确文件名匹配
    if normalized in index.by_id:
        return True
    # 空格替换为连字符后匹配
    if normalized.replace(" ", "-") in index.by_id:
        return True
    # 精确标题匹配
    if normalized in index.by_title:
        return True

    return False


# ---------------------------------------------------------------------------
# JSON 提取工具
# ---------------------------------------------------------------------------

def extract_json_object(raw: str) -> str:
    """从 LLM 响应中提取 JSON 对象

    处理以下格式：
    - 裸 JSON：{...}
    - 代码围栏：```json\\n{...}\\n``` 或单行 ```{...}```
    - 散文中嵌入的 JSON：通过花括号深度遍历找到第一个完整对象

    Args:
        raw: LLM 原始响应文本
    Returns:
        提取到的 JSON 字符串，未找到则返回空字符串
    """
    text = raw.strip()

    # 去除开头的 ```json 或 ``` 围栏
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    # 去除结尾的 ``` 围栏
    text = re.sub(r"\s*```\s*$", "", text, flags=re.IGNORECASE)
    text = text.strip()

    # 通过花括号深度遍历找到第一个完整的 {...} 对象
    start = text.find("{")
    if start == -1:
        return ""

    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]

        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return ""


# ---------------------------------------------------------------------------
# LLM 批量判断
# ---------------------------------------------------------------------------

async def _judge_batch(
    batch: list[dict],
    index: WikiIndex,
    llm_config: dict,
    signal: Optional[asyncio.Event] = None,
) -> set[str]:
    """让 LLM 判断一批待审核项是否已解决

    保守策略：任何错误（网络、解析、配置缺失、中断）都返回空集合。

    Args:
        batch: 待判断的审核项列表
        index: Wiki 索引
        llm_config: LLM 配置
        signal: 取消信号（asyncio.Event，set 时表示取消）
    Returns:
        已解决的审核项 ID 集合
    """
    if not batch:
        return set()
    if signal and signal.is_set():
        return set()

    # 构建页面列表
    pages = index.pages[:MAX_PAGES_IN_PROMPT]
    page_list = "\n".join(
        f"- {p.id}  (title: {p.title})" if p.title else f"- {p.id}"
        for p in pages
    )

    # 构建审核项列表
    review_lines = []
    for r in batch:
        affected = r.get("affectedPages") or []
        affected_str = f" | affected: {', '.join(affected)}" if affected else ""
        desc = r.get("description") or ""
        desc_str = f" — {desc[:200]}" if desc else ""
        review_lines.append(
            f"- id={r['id']} [{r.get('type', '')}] \"{r.get('title', '')}\"{desc_str}{affected_str}"
        )
    review_list = "\n".join(review_lines)

    # 构建提示词
    prompt = "\n".join([
        "You are cleaning up a stale review queue for a personal wiki.",
        "After recent ingests, some review items may no longer be valid because "
        "the missing page now exists, the duplicate was resolved, or the referenced "
        "concept has been added.",
        "",
        "Current wiki pages (filename, optional title):",
        page_list or "(no pages yet)",
        "",
        "Pending review items to judge:",
        review_list,
        "",
        "For each review item, decide whether the underlying condition has been "
        "RESOLVED by the current wiki state.",
        "Be conservative: only mark as resolved if you are confident the concern "
        "no longer applies.",
        "For contradictions, confirmations, or human-judgment items, default to "
        "keeping them pending.",
        "",
        'Respond with ONLY a JSON object in this exact shape: {"resolved": ["id1", "id2"]}',
        'If none of the items are resolved, return exactly: {"resolved": []}',
        "Do not wrap in markdown fences. Do not add commentary.",
    ])

    # 调用 LLM
    raw = ""
    had_error = False

    def on_token(token: str):
        """流式 token 回调"""
        nonlocal raw
        raw += token

    def on_done():
        """流式完成回调"""
        pass

    def on_error(error: Exception):
        """流式错误回调"""
        nonlocal had_error
        had_error = True

    try:
        await stream_chat(
            llm_config,
            [{"role": "user", "content": prompt}],
            on_token=on_token,
            on_done=on_done,
            on_error=on_error,
        )
    except Exception as err:
        return set()

    if had_error or signal and signal.is_set() or not raw.strip():
        return set()

    # 解析 LLM 响应
    try:
        cleaned = extract_json_object(raw)
        if not cleaned:
            return set()

        parsed = json.loads(cleaned)
        if not parsed or not isinstance(parsed.get("resolved"), list):
            return set()

        valid_ids = {item["id"] for item in batch}
        resolved = set()
        for rid in parsed["resolved"]:
            if isinstance(rid, str) and rid in valid_ids:
                resolved.add(rid)

        return resolved
    except (json.JSONDecodeError, TypeError, AttributeError):
        return set()


async def _llm_judge_reviews(
    pending: list[dict],
    index: WikiIndex,
    llm_config: dict,
    signal: Optional[asyncio.Event] = None,
) -> set[str]:
    """通过 LLM 批量判断所有剩余待审核项

    - 限制最多 MAX_JUDGE_BATCHES 批次以避免无限 LLM 调用
    - 如果某批次没有解决任何项，提前终止
    - 中断信号时立即停止

    Args:
        pending: 待判断的审核项列表
        index: Wiki 索引
        llm_config: LLM 配置
        signal: 取消信号
    Returns:
        已解决的审核项 ID 集合
    """
    resolved = set()
    if not pending:
        return resolved

    remaining = list(pending)
    batches = 0

    while remaining and batches < MAX_JUDGE_BATCHES:
        if signal and signal.is_set():
            break

        batch = remaining[:JUDGE_BATCH_SIZE]
        remaining = remaining[JUDGE_BATCH_SIZE:]

        batch_resolved = await _judge_batch(batch, index, llm_config, signal)
        batches += 1

        if not batch_resolved:
            # 本批次没有解决任何项，后续批次大概率相同结果
            break

        resolved.update(batch_resolved)

    return resolved


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

async def sweep_resolved_reviews(
    project_path: str,
    reviews: list[dict],
    llm_config: dict,
    signal: Optional[asyncio.Event] = None,
) -> int:
    """自动清理过期的审核项

    两阶段处理：
    1. 规则匹配：
       - missing-page: 检查候选名称是否已存在于 wiki
       - duplicate: 检查 affectedPages 是否仍全部存在
    2. LLM 判断：批量 40 条送 LLM，要求返回 {"resolved": ["id1", "id2"]}

    保守策略：contradiction / suggestion / confirm 类型需要人工判断，不会自动解决。

    Args:
        project_path: 项目根目录路径
        reviews: 待审核项列表，每项包含 id、type、title、affectedPages 等字段
        llm_config: LLM 配置字典
        signal: 取消信号（asyncio.Event，set 时表示取消）
    Returns:
        自动解决的审核项数量
    """
    if signal and signal.is_set():
        return 0

    # 过滤出未解决的审核项
    pending = [r for r in reviews if not r.get("resolved")]
    if not pending:
        return 0

    # 构建 Wiki 索引
    index = _build_wiki_index(project_path)

    # 异步 I/O 后再次检查取消信号
    if signal and signal.is_set():
        return 0

    rule_resolved = 0
    still_pending = []

    # 阶段 1：规则匹配
    for item in pending:
        if signal and signal.is_set():
            return rule_resolved

        resolved_by_rule = False

        if item.get("type") == "missing-page":
            # 检查候选名称是否已存在
            names = _extract_candidate_names(item)
            if names and any(_page_exists(n, index) for n in names):
                item["resolved"] = True
                item["resolvedReason"] = "auto-resolved"
                rule_resolved += 1
                resolved_by_rule = True

        elif item.get("type") == "duplicate":
            # 如果任何受影响页面不再存在，说明重复情况已变化，自动解决
            affected = item.get("affectedPages") or []
            if affected:
                all_still_exist = all(
                    _page_exists(
                        re.sub(r"\.md$", "", p.split("/")[-1]).lower(),
                        index,
                    )
                    for p in affected
                    if re.sub(r"\.md$", "", p.split("/")[-1])
                )
                if not all_still_exist:
                    item["resolved"] = True
                    item["resolvedReason"] = "auto-resolved"
                    rule_resolved += 1
                    resolved_by_rule = True

        if not resolved_by_rule:
            still_pending.append(item)

    # 阶段 2：LLM 语义判断
    llm_resolved = 0

    if still_pending and not (signal and signal.is_set()):
        try:
            resolved_ids = await _llm_judge_reviews(
                still_pending, index, llm_config, signal
            )
            # 最终守卫：不要在信号取消后写入结果
            if not (signal and signal.is_set()):
                for rid in resolved_ids:
                    # 在 still_pending 中标记为已解决
                    for item in still_pending:
                        if item.get("id") == rid:
                            item["resolved"] = True
                            item["resolvedReason"] = "llm-judged"
                            llm_resolved += 1
                            break
        except Exception:
            pass

    total = rule_resolved + llm_resolved
    return total
