"""
概念过时检测模块

扫描 wiki/concepts/ 目录下的概念页面，通过 LLM 判断概念是否可能过时，
并为过时概念生成审核项（review item），供用户确认后更新。

核心流程：
1. scan_concept_pages  — 扫描概念页面，提取 frontmatter 和内容预览
2. check_staleness     — 分批调用 LLM，判断每个概念是否过时
3. create_staleness_reviews — 为过时概念生成审核项
4. run_staleness_check — 主入口，串联上述三个步骤

依赖模块：
- llm_client.simple_chat  — 非流式 LLM 调用
- frontmatter.parse_frontmatter — 解析 YAML frontmatter
- project_service.create_review_item — 创建审核项
"""

import json
import logging
import os
from datetime import datetime, timezone

from backend.services.wiki.frontmatter import parse_frontmatter
from backend.services.wiki.llm_client import simple_chat

logger = logging.getLogger(__name__)

# 每批发送给 LLM 的概念数量上限
_BATCH_SIZE = 10

# 内容预览最大字符数，避免发送过多内容给 LLM
_PREVIEW_MAX_CHARS = 500


# ---------------------------------------------------------------------------
# 1. 扫描概念页面
# ---------------------------------------------------------------------------

def scan_concept_pages(project_path: str) -> list[dict]:
    """扫描 wiki/concepts/ 下所有概念页面，提取元信息和内容预览

    遍历项目 wiki/concepts/ 目录中的 .md 文件，
    解析每个文件的 frontmatter（标题、标签、更新时间等），
    并截取正文前 500 字符作为内容预览。

    Args:
        project_path: 项目本地路径（即 local_path），wiki/ 为其子目录
    Returns:
        概念页面信息列表，每项包含：
        - path: 相对于 wiki/ 的路径，如 "concepts/my-concept.md"
        - title: 概念标题，取自 frontmatter 的 title 字段，无则用文件名
        - tags: 标签列表，取自 frontmatter 的 tags 字段
        - content_preview: 正文前 500 字符
        - updated: 最后更新时间，取自 frontmatter 的 updated 字段或文件修改时间
    """
    concepts_dir = os.path.join(project_path, "wiki", "concepts")
    if not os.path.isdir(concepts_dir):
        logger.info("概念目录不存在: %s", concepts_dir)
        return []

    results: list[dict] = []

    # 遍历 concepts 目录下的 .md 文件（含子目录）
    for root, _dirs, files in os.walk(concepts_dir):
        for filename in sorted(files):
            if not filename.endswith(".md"):
                continue

            file_path = os.path.join(root, filename)
            # 相对于 wiki/ 的路径
            rel_path = os.path.relpath(file_path, os.path.join(project_path, "wiki"))
            # 统一使用正斜杠，兼容不同操作系统
            rel_path = rel_path.replace("\\", "/")

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except (OSError, UnicodeDecodeError) as exc:
                logger.warning("无法读取概念文件 %s: %s", file_path, exc)
                continue

            # 解析 frontmatter
            fm_result = parse_frontmatter(content)
            fm = fm_result.frontmatter or {}
            body = fm_result.body or ""

            # 提取标题：优先使用 frontmatter 中的 title，否则用文件名
            title = _extract_title(fm, filename)

            # 提取标签列表
            tags = _extract_tags(fm)

            # 提取更新时间：优先使用 frontmatter 中的 updated，否则用文件修改时间
            updated = _extract_updated(fm, file_path)

            # 截取正文前 N 字符作为预览
            content_preview = body.strip()[:_PREVIEW_MAX_CHARS]

            results.append({
                "path": rel_path,
                "title": title,
                "tags": tags,
                "content_preview": content_preview,
                "updated": updated,
            })

    logger.info("扫描到 %d 个概念页面", len(results))
    return results


def _extract_title(frontmatter: dict, filename: str) -> str:
    """从 frontmatter 中提取概念标题

    Args:
        frontmatter: 解析后的 frontmatter 字典
        filename: 文件名（含 .md 后缀），作为回退标题
    Returns:
        概念标题字符串
    """
    title = frontmatter.get("title", "")
    if isinstance(title, str) and title.strip():
        return title.strip()
    # 回退：用文件名（去掉 .md 后缀，将连字符替换为空格）
    return filename.replace(".md", "").replace("-", " ")


def _extract_tags(frontmatter: dict) -> list[str]:
    """从 frontmatter 中提取标签列表

    支持两种格式：
    - tags: ["tag1", "tag2"]  （列表形式）
    - tags: "tag1"            （标量形式，包装为单元素列表）

    Args:
        frontmatter: 解析后的 frontmatter 字典
    Returns:
        标签字符串列表
    """
    tags = frontmatter.get("tags", [])
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    if isinstance(tags, str) and tags.strip():
        return [tags.strip()]
    return []


def _extract_updated(frontmatter: dict, file_path: str) -> str:
    """从 frontmatter 或文件系统获取最后更新时间

    优先使用 frontmatter 中的 updated / date 字段，
    否则回退到文件的最后修改时间。

    Args:
        frontmatter: 解析后的 frontmatter 字典
        file_path: 文件绝对路径，用于获取 mtime
    Returns:
        ISO 8601 格式的时间字符串
    """
    # 尝试 frontmatter 中的 updated 字段
    updated = frontmatter.get("updated", "")
    if isinstance(updated, str) and updated.strip():
        return updated.strip()

    # 尝试 frontmatter 中的 date 字段
    date_val = frontmatter.get("date", "")
    if isinstance(date_val, str) and date_val.strip():
        return date_val.strip()

    # 回退到文件修改时间
    try:
        mtime = os.path.getmtime(file_path)
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# 2. LLM 过时检测
# ---------------------------------------------------------------------------

async def check_staleness(concept_pages: list[dict], llm_config: dict) -> list[dict]:
    """调用 LLM 判断概念是否过时

    将概念页面信息分批发送给 LLM（每批最多 _BATCH_SIZE 个），
    LLM 根据技术演进速度、最后更新时间等因素判断每个概念是否可能过时。

    Args:
        concept_pages: scan_concept_pages 返回的概念页面列表
        llm_config: LLM 配置字典，包含 provider, apiKey, baseUrl, model 等
    Returns:
        过时检测结果列表，每项包含：
        - path: 概念页面路径
        - title: 概念标题
        - is_stale: 是否过时
        - reason: 过时原因（未过时时为空字符串）
        - suggestion: 更新建议（未过时时为空字符串）
    """
    if not concept_pages:
        return []

    if not llm_config:
        logger.warning("LLM 配置为空，无法执行过时检测")
        return [_stale_unknown(page) for page in concept_pages]

    all_results: list[dict] = []

    # 分批处理
    for batch_start in range(0, len(concept_pages), _BATCH_SIZE):
        batch = concept_pages[batch_start:batch_start + _BATCH_SIZE]
        batch_results = await _check_batch(batch, llm_config)
        all_results.extend(batch_results)

    stale_count = sum(1 for r in all_results if r["is_stale"])
    logger.info("过时检测完成: %d/%d 个概念可能过时", stale_count, len(all_results))
    return all_results


def _stale_unknown(page: dict) -> dict:
    """为无法检测的概念生成默认结果

    当 LLM 配置不可用时，将概念标记为未知状态。

    Args:
        page: 概念页面信息
    Returns:
        默认检测结果（is_stale=False，reason 说明无法检测）
    """
    return {
        "path": page["path"],
        "title": page["title"],
        "is_stale": False,
        "reason": "LLM 配置不可用，无法检测",
        "suggestion": "",
    }


async def _check_batch(batch: list[dict], llm_config: dict) -> list[dict]:
    """对一批概念页面执行 LLM 过时检测

    构造提示词，将概念信息序列化后发送给 LLM，
    解析 LLM 返回的 JSON 结果。

    Args:
        batch: 一批概念页面信息（最多 _BATCH_SIZE 个）
        llm_config: LLM 配置字典
    Returns:
        本批次的过时检测结果列表
    """
    # 构造概念摘要列表
    concept_summaries = []
    for i, page in enumerate(batch, start=1):
        summary = (
            f"{i}. 概念: {page['title']}\n"
            f"   路径: {page['path']}\n"
            f"   标签: {', '.join(page['tags']) if page['tags'] else '无'}\n"
            f"   最后更新: {page['updated'] or '未知'}\n"
            f"   内容预览: {page['content_preview'] or '无内容'}"
        )
        concept_summaries.append(summary)

    concepts_text = "\n\n".join(concept_summaries)

    # 构造系统提示词
    system_prompt = (
        "你是一个技术知识管理专家，负责判断 Wiki 中的概念页面是否可能过时。\n"
        "请根据以下因素判断每个概念是否可能过时：\n"
        "1. 技术演进速度：该领域技术更新是否频繁\n"
        "2. 最后更新时间：距离上次更新过了多久\n"
        "3. 内容相关性：内容预览中是否包含可能已过时的技术、API 或框架引用\n"
        "4. 标签时效性：标签是否指向已废弃的技术\n\n"
        "请以 JSON 数组格式返回结果，每个概念一项，格式如下：\n"
        "[\n"
        '  {"index": 1, "is_stale": true/false, "reason": "过时原因", "suggestion": "更新建议"}\n'
        "]\n\n"
        "注意：\n"
        "- 仅返回 JSON 数组，不要包含其他文字\n"
        "- index 从 1 开始，对应输入中的概念编号\n"
        "- 未过时的概念 is_stale 设为 false，reason 简要说明即可\n"
        "- 过时概念的 reason 需具体说明哪些内容可能过时\n"
        "- suggestion 应给出具体的更新方向"
    )

    user_prompt = f"请判断以下概念是否可能过时：\n\n{concepts_text}"

    try:
        response = await simple_chat(
            llm_config,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
    except Exception as exc:
        logger.error("LLM 调用失败: %s", exc)
        # LLM 调用失败时，本批次全部标记为未知
        return [_stale_unknown(page) for page in batch]

    # 解析 LLM 返回的 JSON
    return _parse_llm_response(batch, response)


def _parse_llm_response(batch: list[dict], response: str) -> list[dict]:
    """解析 LLM 返回的过时检测结果 JSON

    尝试从 LLM 响应中提取 JSON 数组，并将结果与原始概念页面关联。
    解析失败时，本批次全部标记为未知状态。

    Args:
        batch: 本批次概念页面信息
        response: LLM 返回的原始文本
    Returns:
        本批次的过时检测结果列表
    """
    # 尝试提取 JSON 数组：优先直接解析，失败则尝试从 markdown 代码块中提取
    parsed = _extract_json_array(response)
    if parsed is None:
        logger.warning("无法解析 LLM 返回的 JSON，原始响应: %s", response[:300])
        return [_stale_unknown(page) for page in batch]

    # 构建 index -> parsed_item 的映射
    index_map: dict[int, dict] = {}
    for item in parsed:
        idx = item.get("index", 0)
        if isinstance(idx, (int, float)):
            index_map[int(idx)] = item

    # 将解析结果与原始概念页面关联
    results: list[dict] = []
    for i, page in enumerate(batch, start=1):
        item = index_map.get(i)
        if item is None:
            results.append(_stale_unknown(page))
            continue

        is_stale = bool(item.get("is_stale", False))
        results.append({
            "path": page["path"],
            "title": page["title"],
            "is_stale": is_stale,
            "reason": str(item.get("reason", "")) if is_stale else "",
            "suggestion": str(item.get("suggestion", "")) if is_stale else "",
        })

    return results


def _extract_json_array(text: str) -> list[dict] | None:
    """从文本中提取 JSON 数组

    支持以下格式：
    - 纯 JSON 数组
    - Markdown 代码块包裹的 JSON 数组

    Args:
        text: 可能包含 JSON 数组的文本
    Returns:
        解析后的字典列表，解析失败返回 None
    """
    # 尝试直接解析
    text = text.strip()
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试从 markdown 代码块中提取
    import re
    code_block_re = re.compile(r"```(?:json)?\s*\n?([\s\S]*?)\n?```")
    match = code_block_re.search(text)
    if match:
        try:
            result = json.loads(match.group(1).strip())
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    # 尝试查找第一个 [ 到最后一个 ] 之间的内容
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            result = json.loads(text[start:end + 1])
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, ValueError):
            pass

    return None


# ---------------------------------------------------------------------------
# 3. 生成审核项
# ---------------------------------------------------------------------------

def create_staleness_reviews(project_id: int, stale_concepts: list[dict]) -> int:
    """为过时概念生成审核项

    对每个被判定为过时的概念，调用 project_service.create_review_item
    创建一条类型为 "suggestion" 的审核项，标题包含"过时概念"。

    Args:
        project_id: 项目 ID
        stale_concepts: check_staleness 返回的结果中 is_stale=True 的子集
    Returns:
        成功创建的审核项数量
    """
    from backend.services.project_service import create_review_item

    created_count = 0
    for concept in stale_concepts:
        try:
            create_review_item(project_id, {
                "item_type": "suggestion",
                "title": f"过时概念: {concept['title']}",
                "description": (
                    f"原因: {concept.get('reason', '未知')}\n"
                    f"建议: {concept.get('suggestion', '无')}"
                ),
                "source_path": concept.get("path", ""),
                "options": [
                    {"label": "更新内容", "action": "update"},
                    {"label": "标记已审查", "action": "skip"},
                    {"label": "删除页面", "action": "delete"},
                ],
            })
            created_count += 1
        except Exception as exc:
            logger.error("创建审核项失败 (%s): %s", concept.get("title"), exc)

    logger.info("为项目 %d 创建了 %d 个过时概念审核项", project_id, created_count)
    return created_count


# ---------------------------------------------------------------------------
# 4. 主入口
# ---------------------------------------------------------------------------

async def run_staleness_check(
    project_path: str,
    llm_config: dict,
    project_id: int | None = None,
) -> dict:
    """概念过时检测主入口

    完整流程：扫描概念页面 -> 检测过时 -> 生成审核项

    Args:
        project_path: 项目本地路径
        llm_config: LLM 配置字典
        project_id: 项目 ID，提供时为过时概念生成审核项
    Returns:
        检测结果字典，包含：
        - scanned: 扫描到的概念页面数量
        - stale_count: 被判定为过时的概念数量
        - reviews_created: 创建的审核项数量（未提供 project_id 时为 0）
        - stale_concepts: 过时概念详情列表
    """
    # 第一步：扫描概念页面
    concept_pages = scan_concept_pages(project_path)
    scanned = len(concept_pages)

    if scanned == 0:
        logger.info("未扫描到概念页面，跳过过时检测")
        return {
            "scanned": 0,
            "stale_count": 0,
            "reviews_created": 0,
            "stale_concepts": [],
        }

    # 第二步：调用 LLM 检测过时
    staleness_results = await check_staleness(concept_pages, llm_config)

    # 筛选出过时的概念
    stale_concepts = [r for r in staleness_results if r["is_stale"]]
    stale_count = len(stale_concepts)

    # 第三步：为过时概念生成审核项
    reviews_created = 0
    if project_id is not None and stale_count > 0:
        reviews_created = create_staleness_reviews(project_id, stale_concepts)

    logger.info(
        "概念过时检测完成: 扫描 %d, 过时 %d, 审核项 %d",
        scanned, stale_count, reviews_created,
    )

    return {
        "scanned": scanned,
        "stale_count": stale_count,
        "reviews_created": reviews_created,
        "stale_concepts": stale_concepts,
    }
