"""
Wiki 摄入管线模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/ingest.ts 移植。
两步思维链摄入管线：分析 → 生成 → 写入。

核心功能：
- parse_file_blocks: 解析 LLM 输出中的 FILE 块
- is_safe_ingest_path: 路径安全校验
- build_analysis_prompt / build_generation_prompt: 构建提示词
- auto_ingest: 自动摄入主函数
- parse_review_blocks: 解析 REVIEW 块
"""

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from backend.services.wiki.llm_client import stream_chat
from backend.services.wiki.frontmatter import parse_frontmatter
from backend.services.wiki.page_merge import merge_page_content, MergeFn, MergePageOptions
from backend.services.wiki.sources_merge import (
    parse_frontmatter_array,
    merge_array_fields_into_content,
)

logger = logging.getLogger(__name__)

OPENER_LINE = re.compile(r"^---\s*FILE:\s*(.+?)\s*---\s*$", re.IGNORECASE)
CLOSER_LINE = re.compile(r"^---\s*END\s+FILE\s*---\s*$", re.IGNORECASE)
FENCE_LINE = re.compile(r"^\s{0,3}(```+|~~~+)")
REVIEW_BLOCK_REGEX = re.compile(
    r"---REVIEW:\s*(\w[\w-]*)\s*\|\s*(.+?)\s*---\n([\s\S]*?)---END REVIEW---"
)


@dataclass
class ParsedFileBlock:
    path: str
    content: str


@dataclass
class ParseFileBlocksResult:
    blocks: list[ParsedFileBlock]
    warnings: list[str]


def parse_file_blocks(text: str) -> ParseFileBlocksResult:
    """解析 LLM 输出中的 FILE 块

    处理已知陷阱：
    - CRLF 行尾
    - 流截断（未闭合的块）
    - 标记空格/大小写变体
    - 代码围栏内的 ---END FILE---
    - 空路径

    Args:
        text: LLM 输出文本
    Returns:
        ParseFileBlocksResult 包含解析出的块和警告
    """
    normalized = text.replace("\r\n", "\n")
    lines = normalized.split("\n")

    blocks: list[ParsedFileBlock] = []
    warnings: list[str] = []

    i = 0
    while i < len(lines):
        opener_match = OPENER_LINE.match(lines[i])
        if not opener_match:
            i += 1
            continue
        path = opener_match.group(1).strip()
        i += 1

        content_lines: list[str] = []
        fence_marker: str | None = None
        fence_len = 0
        closed = False

        while i < len(lines):
            line = lines[i]

            fence_match = FENCE_LINE.match(line)
            if fence_match:
                run = fence_match.group(1)
                char = run[0]
                length = len(run)
                if fence_marker is None:
                    fence_marker = char
                    fence_len = length
                elif char == fence_marker and length >= fence_len:
                    fence_marker = None
                    fence_len = 0
                content_lines.append(line)
                i += 1
                continue

            if fence_marker is None and CLOSER_LINE.match(line):
                closed = True
                i += 1
                break

            content_lines.append(line)
            i += 1

        if not closed:
            path_label = path or "(unnamed)"
            msg = (
                f'FILE block "{path_label}" was not closed before end of stream '
                "— likely truncation (model hit max_tokens, timeout, or connection dropped). Block dropped."
            )
            logger.warning("[ingest] %s", msg)
            warnings.append(msg)
            continue

        if not path:
            msg = "FILE block with empty path skipped (LLM omitted the path after `---FILE:`)."
            logger.warning("[ingest] %s", msg)
            warnings.append(msg)
            continue

        if not is_safe_ingest_path(path):
            msg = (
                f'FILE block with unsafe path "{path}" rejected '
                "(must be under wiki/, no .., no absolute paths, and Windows-safe file names)."
            )
            logger.warning("[ingest] %s", msg)
            warnings.append(msg)
            continue

        blocks.append(ParsedFileBlock(path=path, content="\n".join(content_lines)))

    return ParseFileBlocksResult(blocks=blocks, warnings=warnings)


def is_safe_ingest_path(p: str) -> bool:
    """校验 FILE 块路径是否安全

    拒绝：
    - 非字符串或空白路径
    - 控制字符 / NUL 字节
    - 绝对路径（POSIX / Windows）
    - .. 段
    - Windows 非法文件名字符 / 保留设备名
    - 以空格或点结尾的段
    - 不以 wiki/ 开头

    Args:
        p: 待校验路径
    Returns:
        是否安全
    """
    if not isinstance(p, str) or not p.strip():
        return False
    if re.search(r"[\x00-\x1f]", p):
        return False
    if p.startswith("/") or p.startswith("\\"):
        return False
    if re.match(r"^[a-zA-Z]:", p):
        return False
    normalized = p.replace("\\", "/")
    segments = normalized.split("/")
    if any(seg == ".." for seg in segments):
        return False
    if any(not _is_windows_safe_path_segment(seg) for seg in segments):
        return False
    if not normalized.startswith("wiki/"):
        return False
    return True


def _is_windows_safe_path_segment(segment: str) -> bool:
    """检查路径段是否为 Windows 安全文件名

    Args:
        segment: 路径段
    Returns:
        是否安全
    """
    if not segment:
        return False
    if re.search(r'[<>:"|?*]', segment):
        return False
    if re.search(r"[ .]$", segment):
        return False
    stem = segment.split(".")[0].upper() if "." in segment else segment.upper()
    if not stem:
        return False
    reserved = {"CON", "PRN", "AUX", "NUL"}
    if stem in reserved:
        return False
    if re.match(r"^COM[1-9]$", stem):
        return False
    if re.match(r"^LPT[1-9]$", stem):
        return False
    return True


def build_analysis_prompt(
    purpose: str, index: str, source_content: str = "", language: str = "auto"
) -> str:
    """构建 Step1 分析提示词

    Args:
        purpose: Wiki 目的描述
        index: 当前 Wiki 索引内容
        source_content: 源文档内容（用于语言检测）
        language: 输出语言设置，"auto" 表示跟随源文档语言
    Returns:
        系统提示词文本
    """
    lines = [
        "You are an expert research analyst. Read the source document and produce a structured analysis.",
        "Do not output chain-of-thought, hidden reasoning, or a thinking transcript. Reason internally and write only the concise final analysis.",
        "",
        _language_rule(source_content, language=language),
        "",
        "Your analysis should cover:",
        "",
        "## Key Entities",
        "List people, organizations, products, datasets, tools mentioned. For each:",
        "- Name and type",
        "- Role in the source (central vs. peripheral)",
        "- Whether it likely already exists in the wiki (check the index)",
        "",
        "## Key Concepts",
        "List theories, methods, techniques, phenomena. For each:",
        "- Name and brief definition",
        "- Why it matters in this source",
        "- Whether it likely already exists in the wiki",
        "",
        "## Main Arguments & Findings",
        "- What are the core claims or results?",
        "- What evidence supports them?",
        "- How strong is the evidence?",
        "",
        "## Connections to Existing Wiki",
        "- What existing pages does this source relate to?",
        "- Does it strengthen, challenge, or extend existing knowledge?",
        "",
        "## Contradictions & Tensions",
        "- Does anything in this source conflict with existing wiki content?",
        "- Are there internal tensions or caveats?",
        "",
        "## Recommendations",
        "- What wiki pages should be created or updated?",
        "- What should be emphasized vs. de-emphasized?",
        "- Any open questions worth flagging for the user?",
        "",
        "Be thorough but concise. Focus on what's genuinely important.",
        "",
        "If a folder context is provided, use it as a hint for categorization — the folder structure often reflects the user's organizational intent (e.g., 'papers/energy' suggests the file is an energy-related paper).",
    ]
    if purpose:
        lines.append(f"## Wiki Purpose (for context)\n{purpose}")
    if index:
        lines.append(f"## Current Wiki Index (for checking existing content)\n{index}")
    return "\n".join(lines)


def build_generation_prompt(
    schema: str,
    purpose: str,
    index: str,
    source_file_name: str,
    overview: str = "",
    source_content: str = "",
    language: str = "auto",
) -> str:
    """构建 Step2 生成提示词

    Args:
        schema: Wiki 模式描述
        purpose: Wiki 目的描述
        index: 当前 Wiki 索引内容
        source_file_name: 源文件名
        overview: 当前 Wiki 概览内容
        source_content: 源文档内容（用于语言检测）
        language: 输出语言设置，"auto" 表示跟随源文档语言
    Returns:
        系统提示词文本
    """
    source_base_name = re.sub(r"\.[^.]+$", "", source_file_name)

    lines = [
        "You are a wiki maintainer. Based on the analysis provided, generate wiki files.",
        "Do not output chain-of-thought, hidden reasoning, or explanatory preamble. Reason internally and output only the requested FILE/REVIEW blocks.",
        "",
        _language_rule(source_content, language=language),
        "",
        "## IMPORTANT: Source File",
        f"The original source file is: **{source_file_name}**",
        f"All wiki pages generated from this source MUST include this filename in their frontmatter `sources` field.",
        "",
        "## What to generate",
        "",
        f"1. A source summary page at **wiki/sources/{source_base_name}.md** (MUST use this exact path)",
        "2. Entity pages in wiki/entities/ for key entities identified in the analysis",
        "3. Concept pages in wiki/concepts/ for key concepts identified in the analysis",
        "4. An updated wiki/index.md — add new entries to existing categories, preserve all existing entries",
        "5. A log entry for wiki/log.md (just the new entry to append, format: ## [YYYY-MM-DD] ingest | Title)",
        "6. An updated wiki/overview.md — a high-level summary of what the entire wiki covers, updated to reflect the newly ingested source. This should be a comprehensive 2-5 paragraph overview of ALL topics in the wiki, not just the new source.",
        "",
        "## Frontmatter Rules (CRITICAL — parser is strict)",
        "",
        "Every page begins with a YAML frontmatter block. Format rules, in order of importance:",
        "",
        "1. The VERY FIRST line of the file MUST be exactly `---` (three hyphens, nothing else).",
        "   Do NOT wrap the file in a ```yaml ... ``` code fence.",
        "   Do NOT prefix it with a `frontmatter:` key or any other line.",
        "2. Each frontmatter line is a `key: value` pair on its own line.",
        "3. The frontmatter ends with another `---` line on its own.",
        "4. The next line after the closing `---` is the start of the page body.",
        "5. Arrays use the standard YAML inline form `[a, b, c]` (no outer brackets around each item).",
        "   Wikilinks belong in the BODY only — never write `related: [[a]], [[b]]` (invalid YAML);",
        "   write `related: [a, b]` with bare slugs.",
        "",
        "Required fields and types:",
        "  - type     — one of: source | entity | concept | comparison | query | synthesis",
        '  - title    — string (quote it if it contains a colon, e.g. `title: "Foo: Bar"`)',
        "  - created  — date in YYYY-MM-DD form (no quotes)",
        "  - updated  — same as created",
        "  - tags     — array of bare strings: `tags: [microbiology, ai]`",
        "  - related  — array of bare wiki page slugs: `related: [foo, bar-baz]`. Do NOT include",
        "               `wiki/`, `.md`, or `[[...]]` here — slugs only.",
        f'  - sources  — array of source filenames; MUST include "{source_file_name}".',
        "",
        "Concrete example of a complete, parseable page (everything between the two `---` lines",
        "is the frontmatter; the heading and prose below are the body):",
        "",
        "    ---",
        "    type: entity",
        "    title: Example Entity",
        "    created: 2026-04-29",
        "    updated: 2026-04-29",
        "    tags: [example, demo]",
        "    related: [related-slug-1, related-slug-2]",
        f'    sources: ["{source_file_name}"]',
        "    ---",
        "",
        "    # Example Entity",
        "",
        "    Body content goes here. Use [[wikilink]] syntax in the body for cross-references.",
        "",
        "Other rules:",
        "- Use [[wikilink]] syntax in the BODY for cross-references between pages",
        "- CRITICAL: [[wikilink]] targets MUST match the page's filename slug (kebab-case, "
        "no .md extension). For example, if a page is wiki/entities/aitoearn.md, link to it as "
        "[[aitoearn]] or [[entities/aitoearn]], NOT as [[AiToEarn]] or [[中文标题]]. "
        "Using titles or display names as link targets will cause broken links.",
        "- Use kebab-case filenames",
        "- Follow the analysis recommendations on what to emphasize",
        "- If the analysis found connections to existing pages, add cross-references",
        "",
        "## Review block types",
        "",
        "After all FILE blocks, optionally emit REVIEW blocks for anything that needs human judgment:",
        "",
        "- contradiction: the analysis found conflicts with existing wiki content",
        "- duplicate: an entity/concept might already exist under a different name in the index",
        "- missing-page: an important concept is referenced but has no dedicated page",
        "- suggestion: ideas for further research, related sources to look for, or connections worth exploring",
        "",
        "Only create reviews for things that genuinely need human input. Don't create trivial reviews.",
        "",
        "## OPTIONS allowed values (only these predefined labels):",
        "",
        "- contradiction: OPTIONS: Create Page | Skip",
        "- duplicate: OPTIONS: Create Page | Skip",
        "- missing-page: OPTIONS: Create Page | Skip",
        "- suggestion: OPTIONS: Create Page | Skip",
        "",
        "The user also has a 'Deep Research' button (auto-added by the system) that triggers web search.",
        "Do NOT invent custom option labels. Only use 'Create Page' and 'Skip'.",
        "",
        "For suggestion and missing-page reviews, the SEARCH field must contain 2-3 web search queries",
        "(keyword-rich, specific, suitable for a search engine — NOT titles or sentences). Example:",
        "  SEARCH: automated technical debt detection AI generated code | software quality metrics LLM code generation | static analysis tools agentic software development",
    ]
    if purpose:
        lines.append(f"## Wiki Purpose\n{purpose}")
    if schema:
        lines.append(f"## Wiki Schema\n{schema}")
    if index:
        lines.append(f"## Current Wiki Index (preserve all existing entries, add new ones)\n{index}")
    if overview:
        lines.append(f"## Current Overview (update this to reflect the new source)\n{overview}")
    lines.extend([
        "",
        "## Output Format (MUST FOLLOW EXACTLY — this is how the parser reads your response)",
        "",
        "Your ENTIRE response consists of FILE blocks followed by optional REVIEW blocks. Nothing else.",
        "",
        "FILE block template:",
        "```",
        "---FILE: wiki/path/to/page.md---",
        "(complete file content with YAML frontmatter)",
        "---END FILE---",
        "```",
        "",
        "REVIEW block template (optional, after all FILE blocks):",
        "```",
        "---REVIEW: type | Title---",
        "Description of what needs the user's attention.",
        "OPTIONS: Create Page | Skip",
        "PAGES: wiki/page1.md, wiki/page2.md",
        "SEARCH: query 1 | query 2 | query 3",
        "---END REVIEW---",
        "```",
        "",
        "## Output Requirements (STRICT — deviations will cause parse failure)",
        "",
        "1. The FIRST character of your response MUST be `-` (the opening of `---FILE:`).",
        '2. DO NOT output any preamble such as "Here are the files:", "Based on the analysis...", or any introductory prose.',
        "3. DO NOT echo or restate the analysis — that was stage 1's job. Your job is to emit FILE blocks.",
        "4. DO NOT output markdown tables, bullet lists, or headings outside of FILE/REVIEW blocks.",
        "5. DO NOT output any trailing commentary after the last `---END FILE---` or `---END REVIEW---`.",
        "6. Between blocks, use only blank lines — no prose.",
        "7. EVERY FILE block's content (titles, body, descriptions) MUST be in the mandatory output language specified below. No exceptions — not even for page names or section headings.",
        "",
        "If you start with anything other than `---FILE:`, the entire response will be discarded.",
        "",
        "---",
        "",
        _language_rule(source_content, language=language),
    ])
    return "\n".join(lines)


def _language_rule(source_content: str = "", language: str = "auto") -> str:
    """构建语言规则指令

    Args:
        source_content: 源文档内容（预留参数）
        language: 输出语言设置，"auto" 表示跟随源文档语言，否则使用指定语言
    Returns:
        语言规则文本
    """
    if language and language != "auto":
        return f"Output language: {language}. All content MUST be written in {language}."
    return "Output language: Match the language of the source document. If the source is in Chinese, output in Chinese. If in English, output in English. Follow the source document's language for all generated content."


def _try_read_file(path: str) -> str:
    """尝试读取文件，失败返回空字符串

    Args:
        path: 文件路径
    Returns:
        文件内容或空字符串
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _try_read_file_async(path: str) -> str:
    """同步读取文件的别名，用于统一调用风格

    Args:
        path: 文件路径
    Returns:
        文件内容或空字符串
    """
    return _try_read_file(path)


def _build_page_merger(llm_config: dict) -> MergeFn:
    """构建页面合并用的 MergeFn

    返回的函数调用 LLM 合并两个版本的 Wiki 页面。

    Args:
        llm_config: LLM 配置字典
    Returns:
        MergeFn 异步函数
    """
    async def _merger(
        existing_content: str,
        incoming_content: str,
        source_file_name: str,
        signal: Any = None,
    ) -> str:
        system_prompt = "\n".join([
            "You are merging two versions of the same wiki page into one coherent document.",
            "Both versions describe the same entity / concept; one is already on disk,",
            "the other was just generated from a different source document.",
            "",
            "Output ONE merged version that:",
            "- Preserves every factual claim from both versions (do not drop content)",
            "- Eliminates redundancy when both versions state the same fact",
            "- Reorganizes sections so the structure is logical for the merged topic,",
            "  not just a concatenation of the two inputs",
            "- Uses consistent markdown structure (headings, tables, lists, callouts)",
            "- Keeps `[[wikilink]]` references intact",
            "",
            "Output requirements:",
            "- The FIRST character of your response MUST be `-` (the opening of `---`)",
            "- Output the COMPLETE file: YAML frontmatter + body",
            '- No preamble (no "Here is the merged version:"), no analysis prose',
            "- The caller will overwrite `sources`/`tags`/`related`/`updated` with",
            "  deterministic values — your job is the body and any other fields",
        ])

        user_message = "\n".join([
            "## Existing version on disk",
            "",
            existing_content,
            "",
            "---",
            "",
            f"## Newly generated version (from {source_file_name})",
            "",
            incoming_content,
            "",
            "---",
            "",
            "Now output the merged file. Start with `---` on the first line.",
        ])

        result = ""
        tokens: list[str] = []

        async def _on_token(token: str) -> None:
            tokens.append(token)

        full_text = await stream_chat(
            llm_config,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            on_token=_on_token,
            signal=signal,
        )
        return full_text

    return _merger


async def _backup_existing_page(
    project_path: str,
    relative_path: str,
    existing_content: str,
) -> None:
    """备份已有页面到 .llm-wiki/page-history/

    Args:
        project_path: 项目路径
        relative_path: 相对路径
        existing_content: 已有内容
    """
    from datetime import datetime
    stamp = datetime.now().isoformat().replace(":", "-").replace(".", "-")
    sanitized = relative_path.replace("/", "_").replace("\\", "_")
    backup_dir = os.path.join(project_path, ".llm-wiki", "page-history")
    os.makedirs(backup_dir, exist_ok=True)
    backup_path = os.path.join(backup_dir, f"{sanitized}-{stamp}")
    with open(backup_path, "w", encoding="utf-8") as f:
        f.write(existing_content)


def _merge_existing_array_fields(
    new_content: str, existing_content: str
) -> str:
    """合并已有文件中的 sources/tags/related 数组字段到新内容

    作为 page_merge 之后的额外安全层，确保即使 LLM 合并过程
    中丢失了某些数组字段值，也能从已有文件中恢复。

    从已有内容中提取 sources/tags/related 的旧值，
    调用 sources_merge 模块进行集合并集合并。

    Args:
        new_content: 经过 page_merge 后的新内容
        existing_content: 磁盘上已有的文件内容
    Returns:
        合并后的内容；无实际变化时原样返回 new_content
    """
    merge_fields = ["sources", "tags", "related"]
    new_values: dict[str, list[str]] = {}

    for field in merge_fields:
        old_vals = parse_frontmatter_array(existing_content, field)
        if old_vals:
            new_values[field] = old_vals

    if not new_values:
        return new_content

    return merge_array_fields_into_content(new_content, new_values)


async def _write_file_blocks(
    project_path: str,
    text: str,
    llm_config: dict,
    source_file_name: str,
    signal: Any = None,
) -> tuple[list[str], list[str], list[str]]:
    """解析并写入 FILE 块

    对已有页面调用 page_merge 合并，对新页面直接写入。
    log.md 追加写入，index.md/overview.md 整体覆写。

    Args:
        project_path: 项目路径
        text: LLM 生成文本
        llm_config: LLM 配置
        source_file_name: 源文件名
        signal: 取消信号
    Returns:
        (written_paths, warnings, hard_failures) 三元组
    """
    result = parse_file_blocks(text)
    warnings = list(result.warnings)
    written_paths: list[str] = []
    hard_failures: list[str] = []

    merger = _build_page_merger(llm_config)

    for block in result.blocks:
        relative_path = block.path
        content = block.content

        full_path = os.path.join(project_path, relative_path)
        try:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)

            if relative_path.endswith("/log.md") or relative_path == "wiki/log.md":
                existing = _try_read_file(full_path)
                appended = f"{existing}\n\n{content.strip()}" if existing else content.strip()
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(appended)
            elif (
                relative_path.endswith("/index.md")
                or relative_path == "wiki/index.md"
                or relative_path.endswith("/overview.md")
                or relative_path == "wiki/overview.md"
            ):
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
            else:
                existing = _try_read_file(full_path)
                to_write = await merge_page_content(
                    content,
                    existing or None,
                    merger,
                    MergePageOptions(
                        source_file_name=source_file_name,
                        page_path=relative_path,
                        signal=signal,
                        backup=lambda old_content, rp=relative_path: _backup_existing_page(
                            project_path, rp, old_content
                        ),
                    ),
                )
                # 额外安全层：如果目标文件已存在，合并 sources/tags/related 字段
                # 防止 LLM 合并过程中丢失已有的数组字段值
                if existing:
                    to_write = _merge_existing_array_fields(to_write, existing)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(to_write)

            written_paths.append(relative_path)
        except Exception as err:
            msg = f'Failed to write "{relative_path}": {err}'
            logger.error("[ingest] %s", msg)
            warnings.append(msg)
            hard_failures.append(relative_path)

    return written_paths, warnings, hard_failures


def parse_review_blocks(text: str, source_path: str) -> list[dict]:
    """解析 LLM 输出中的 REVIEW 块

    Args:
        text: LLM 生成文本
        source_path: 源文件路径
    Returns:
        审查项字典列表
    """
    items: list[dict] = []

    for match in REVIEW_BLOCK_REGEX.finditer(text):
        raw_type = match.group(1).strip().lower()
        title = match.group(2).strip()
        body = match.group(3).strip()

        valid_types = {"contradiction", "duplicate", "missing-page", "suggestion"}
        review_type = raw_type if raw_type in valid_types else "confirm"

        options_match = re.match(r"^OPTIONS:\s*(.+)$", body, re.MULTILINE)
        if options_match:
            options = [
                {"label": o.strip(), "action": o.strip()}
                for o in options_match.group(1).split("|")
            ]
        else:
            options = [
                {"label": "Approve", "action": "Approve"},
                {"label": "Skip", "action": "Skip"},
            ]

        pages_match = re.match(r"^PAGES:\s*(.+)$", body, re.MULTILINE)
        affected_pages = (
            [p.strip() for p in pages_match.group(1).split(",")]
            if pages_match
            else None
        )

        search_match = re.match(r"^SEARCH:\s*(.+)$", body, re.MULTILINE)
        search_queries = (
            [q.strip() for q in search_match.group(1).split("|") if q.strip()]
            if search_match
            else None
        )

        description = body
        description = re.sub(r"^OPTIONS:.*$", "", description, flags=re.MULTILINE)
        description = re.sub(r"^PAGES:.*$", "", description, flags=re.MULTILINE)
        description = re.sub(r"^SEARCH:.*$", "", description, flags=re.MULTILINE)
        description = description.strip()

        items.append({
            "type": review_type,
            "title": title,
            "description": description,
            "sourcePath": source_path,
            "affectedPages": affected_pages,
            "searchQueries": search_queries,
            "options": options,
        })

    return items


async def auto_ingest(
    project_path: str,
    source_path: str,
    llm_config: dict,
    signal: Any = None,
    folder_context: str = "",
    wiki_config: dict | None = None,
) -> list[str]:
    """自动摄入主函数：读取源文件 → LLM 分析 → LLM 生成 → 写入

    Args:
        project_path: 项目路径
        source_path: 源文件路径
        llm_config: LLM 配置字典
        signal: 取消信号
        folder_context: 文件夹上下文提示
        wiki_config: Wiki 设置字典（可选），包含 vector/language/contextWindow
    Returns:
        写入的文件路径列表
    """
    pp = os.path.normpath(project_path)
    sp = os.path.normpath(source_path)
    file_name = os.path.basename(sp)

    logger.info('[ingest:diag] auto_ingest ENTRY for "%s" (project="%s", source="%s")', file_name, pp, sp)

    source_content = _try_read_file(sp)
    schema = _try_read_file(os.path.join(pp, "schema.md"))
    purpose = _try_read_file(os.path.join(pp, "purpose.md"))
    index = _try_read_file(os.path.join(pp, "wiki", "index.md"))
    overview = _try_read_file(os.path.join(pp, "wiki", "overview.md"))

    # 摄入缓存检查
    cached_files: list[str] | None = None
    try:
        from backend.services.wiki.ingest_cache import check_ingest_cache
        cached_files = check_ingest_cache(pp, file_name, source_content)
    except ImportError:
        logger.info("[ingest:diag] ingest_cache module not available, skipping cache check")
    except Exception as err:
        logger.warning("[ingest:diag] cache check failed: %s", err)

    logger.info(
        "[ingest:diag] cache check for %s: %s",
        file_name,
        "MISS (full pipeline)" if cached_files is None else f"HIT ({len(cached_files)} cached files)",
    )

    if cached_files is not None:
        logger.info("[ingest:diag] cache-hit, returning %d cached files", len(cached_files))
        return cached_files

    # 截断过长内容
    enriched_source_content = source_content
    if len(enriched_source_content) > 50000:
        enriched_source_content = enriched_source_content[:50000] + "\n\n[...truncated...]"

    # 从 wiki_config 提取语言和上下文窗口设置
    _lang = (wiki_config or {}).get("language", "auto")
    _ctx_window = (wiki_config or {}).get("contextWindow", None)

    # 计算上下文预算
    if _ctx_window is not None:
        from backend.services.wiki.context_budget import compute_context_budget
        _budget = compute_context_budget(_ctx_window)
        logger.info(
            "[ingest:diag] context budget: max_ctx=%d, max_page_size=%d",
            _budget.max_ctx, _budget.max_page_size,
        )

    # Step 1: 分析
    logger.info("[ingest:diag] Step 1/2: Analyzing source...")

    analysis = ""

    async def _on_analysis_token(token: str) -> None:
        nonlocal analysis
        analysis += token

    await stream_chat(
        llm_config,
        [
            {"role": "system", "content": build_analysis_prompt(purpose, index, enriched_source_content, language=_lang)},
            {
                "role": "user",
                "content": (
                    f"Analyze this source document:\n\n**File:** {file_name}"
                    + (f"\n**Folder context:** {folder_context}" if folder_context else "")
                    + f"\n\n---\n\n{enriched_source_content}"
                ),
            },
        ],
        on_token=_on_analysis_token,
        signal=signal,
    )

    if not analysis.strip():
        raise RuntimeError("Analysis stream produced no output")

    # Step 2: 生成
    logger.info("[ingest:diag] Step 2/2: Generating wiki pages...")

    generation = ""

    async def _on_generation_token(token: str) -> None:
        nonlocal generation
        generation += token

    user_content = "\n".join([
        f"Source document to process: **{file_name}**",
        "",
        "The Stage 1 analysis below is CONTEXT to inform your output. Do NOT echo",
        "its tables, bullet points, or prose. Your output must be FILE/REVIEW",
        "blocks as specified in the system prompt — nothing else.",
        "",
        "## Stage 1 Analysis (context only — do not repeat)",
        "",
        analysis,
        "",
        "## Original Source Content",
        "",
        enriched_source_content,
        "",
        "---",
        "",
        f"Now emit the FILE blocks for the wiki files derived from **{file_name}**.",
        "Your response MUST begin with `---FILE:` as the very first characters.",
        "No preamble. No analysis prose. Start immediately.",
    ])

    await stream_chat(
        llm_config,
        [
            {
                "role": "system",
                "content": build_generation_prompt(schema, purpose, index, file_name, overview, enriched_source_content, language=_lang),
            },
            {"role": "user", "content": user_content},
        ],
        on_token=_on_generation_token,
        signal=signal,
    )

    if not generation.strip():
        raise RuntimeError("Generation stream produced no output")

    # Step 3: 写入文件
    logger.info("[ingest:diag] Writing files...")
    written_paths, write_warnings, hard_failures = await _write_file_blocks(
        pp, generation, llm_config, file_name, signal
    )

    if write_warnings:
        for w in write_warnings:
            logger.warning("[ingest] %s", w)

    # 确保源文件摘要页面存在
    source_base_name = re.sub(r"\.[^.]+$", "", file_name)
    source_summary_path = f"wiki{os.sep}sources{os.sep}{source_base_name}.md"
    source_summary_full_path = os.path.join(pp, source_summary_path)
    has_source_summary = any(
        p.replace("/", os.sep).replace("\\", os.sep).startswith(
            f"wiki{os.sep}sources{os.sep}"
        )
        for p in written_paths
    )

    if not has_source_summary and not (signal and isinstance(signal, asyncio.Event) and signal.is_set()):
        today_str = date.today().isoformat()
        fallback_content = "\n".join([
            "---",
            "type: source",
            f'title: "Source: {file_name}"',
            f"created: {today_str}",
            f"updated: {today_str}",
            f'sources: ["{file_name}"]',
            "tags: []",
            "related: []",
            "---",
            "",
            f"# Source: {file_name}",
            "",
            analysis[:3000] if analysis else "(Analysis not available)",
            "",
        ])
        try:
            os.makedirs(os.path.dirname(source_summary_full_path), exist_ok=True)
            with open(source_summary_full_path, "w", encoding="utf-8") as f:
                f.write(fallback_content)
            written_paths.append(source_summary_path)
        except Exception:
            pass

    # Step 4: 解析 REVIEW 块
    review_items = parse_review_blocks(generation, sp)
    if review_items:
        logger.info("[ingest:diag] Found %d review items", len(review_items))

    # Step 5: 保存缓存
    if written_paths and not hard_failures:
        try:
            from backend.services.wiki.ingest_cache import save_ingest_cache
            save_ingest_cache(pp, file_name, source_content, written_paths)
        except ImportError:
            pass
        except Exception as err:
            logger.warning("[ingest] cache save failed: %s", err)
    elif hard_failures:
        logger.warning(
            '[ingest] Skipping cache save for "%s" — %d block(s) failed to write: %s',
            file_name,
            len(hard_failures),
            ", ".join(hard_failures),
        )

    # Step 6: 生成嵌入向量（如果启用）
    # 从 wiki_config 提取向量配置，传递给 embed_page
    _vector_cfg = (wiki_config or {}).get("vector", {})
    try:
        from backend.services.wiki.embedding import embed_page
        for wpath in written_paths:
            page_id = os.path.splitext(os.path.basename(wpath))[0]
            if not page_id or page_id in ("index", "log", "overview"):
                continue
            try:
                page_full_path = os.path.join(pp, wpath)
                page_content = _try_read_file(page_full_path)
                if page_content:
                    title_match = re.search(
                        r"^---\n[\s\S]*?^title:\s*[\"']?(.+?)[\"']?\s*$",
                        page_content,
                        re.MULTILINE,
                    )
                    title = title_match.group(1).strip() if title_match else page_id
                    await embed_page(pp, page_id, title, page_content, _vector_cfg)
            except Exception:
                pass
    except ImportError:
        pass
    except Exception:
        pass

    detail = (
        f"{len(written_paths)} files written"
        + (f", {len(review_items)} review item(s)" if review_items else "")
        if written_paths
        else "No files generated"
    )
    logger.info("[ingest:diag] auto_ingest complete: %s", detail)

    return written_paths
