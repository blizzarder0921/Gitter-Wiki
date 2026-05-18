"""
Wiki 页面合并模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/page-merge.ts 移植。
合并 LLM 新生成的 Wiki 页面与磁盘上已有页面，防止静默数据丢失。

三层保护：
1. Frontmatter 数组字段（sources/tags/related）— 集合并集合并
2. Body — 新旧不同时调用 LLM 合并，带健全性检查
3. 锁定字段（type/title/created）— 强制恢复为已有值
"""

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Awaitable, Callable

from backend.services.wiki.frontmatter import parse_frontmatter
from backend.services.wiki.frontmatter import merge_array_fields_into_content
from backend.services.wiki.frontmatter import set_frontmatter_scalar

logger = logging.getLogger(__name__)

UNION_FIELDS = ["sources", "tags", "related"]

LOCKED_FIELDS = ["type", "title", "created"]

BODY_SHRINK_THRESHOLD = 0.7

MergeFn = Callable[[str, str, str, Any], Awaitable[str]]


@dataclass
class MergePageOptions:
    source_file_name: str
    page_path: str
    signal: Any = None
    backup: Callable[[str], Awaitable[None]] | None = None
    today: Callable[[], str] | None = None


async def merge_page_content(
    new_content: str,
    existing_content: str | None,
    merger: MergeFn,
    opts: MergePageOptions,
) -> str:
    """合并新页面内容与已有页面内容

    快速路径：
    1. 已有内容为空 → 直接返回新内容
    2. 字节级相同 → 返回已有内容
    3. body 相同（仅 frontmatter 数组字段不同）→ 返回数组合并结果

    正常路径：
    1. 集合并集合并数组字段
    2. LLM 合并 body
    3. 健全性检查（frontmatter 存在性 + body 长度阈值）
    4. 锁定字段回写 + 数组字段重合并 + updated 时间戳

    Args:
        new_content: LLM 新生成的页面内容
        existing_content: 磁盘上已有的页面内容，可为 None
        merger: LLM 合并函数
        opts: 合并选项
    Returns:
        合并后的页面内容
    """
    if not existing_content:
        return new_content

    if new_content == existing_content:
        return existing_content

    array_merged = merge_array_fields_into_content(
        new_content, existing_content, list(UNION_FIELDS)
    )

    old_parsed = parse_frontmatter(existing_content)
    array_merged_parsed = parse_frontmatter(array_merged)
    if old_parsed.body.strip() == array_merged_parsed.body.strip():
        return array_merged

    try:
        llm_output = await merger(
            existing_content, array_merged, opts.source_file_name, opts.signal
        )
    except Exception as err:
        logger.warning(
            "[page-merge] LLM merge failed for %s, falling back to incoming + array-field union: %s",
            opts.page_path,
            err,
        )
        await _try_backup(opts, existing_content)
        return array_merged

    llm_parsed = parse_frontmatter(llm_output)
    if llm_parsed.frontmatter is None:
        logger.warning(
            "[page-merge] LLM output for %s has no frontmatter — rejecting, falling back",
            opts.page_path,
        )
        await _try_backup(opts, existing_content)
        return array_merged

    old_body_len = len(old_parsed.body)
    new_body_len = len(array_merged_parsed.body)
    llm_body_len = len(llm_parsed.body)
    min_threshold = max(old_body_len, new_body_len) * BODY_SHRINK_THRESHOLD
    if llm_body_len < min_threshold:
        logger.warning(
            "[page-merge] LLM merge for %s produced body %d chars, below threshold %.0f (max input was %d) — rejecting, falling back",
            opts.page_path,
            llm_body_len,
            min_threshold,
            max(old_body_len, new_body_len),
        )
        await _try_backup(opts, existing_content)
        return array_merged

    final = llm_output
    for field_name in LOCKED_FIELDS:
        existing_value = old_parsed.frontmatter.get(field_name) if old_parsed.frontmatter else None
        if isinstance(existing_value, str) and existing_value != "":
            final = set_frontmatter_scalar(final, field_name, existing_value)

    final = merge_array_fields_into_content(final, array_merged, list(UNION_FIELDS))

    today_fn = opts.today or _default_today
    final = set_frontmatter_scalar(final, "updated", today_fn())

    return final


async def _try_backup(opts: MergePageOptions, existing_content: str) -> None:
    """尝试备份已有内容，错误不传播

    Args:
        opts: 合并选项
        existing_content: 已有内容
    """
    if not opts.backup:
        return
    try:
        await opts.backup(existing_content)
    except Exception as err:
        logger.warning(
            "[page-merge] backup failed for %s: %s",
            opts.page_path,
            err,
        )


def _default_today() -> str:
    """返回当前 UTC 日期字符串

    Returns:
        YYYY-MM-DD 格式的日期字符串
    """
    return date.today().isoformat()
