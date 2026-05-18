"""
Wiki 质量检查模块

从 TypeScript 参考项目 llm_wiki-0.4.9/src/lib/lint.ts 移植，
适配 Python FastAPI 环境。

功能：
- 结构检查（run_structural_lint）：检测孤立页面、断链、无出链
- 语义检查（run_semantic_lint）：通过 LLM 分析页面摘要，发现矛盾、过时、缺失等问题

依赖：
- llm_client.py: LLM 流式调用
- frontmatter.py: Frontmatter 解析
"""

import os
import re
from typing import Optional

from backend.services.wiki.llm_client import stream_chat
from backend.services.wiki.frontmatter import parse_frontmatter


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class LintResult:
    """单条检查结果

    Attributes:
        type: 问题类型（orphan / broken-link / no-outlinks / semantic）
        severity: 严重程度（warning / info）
        page: 页面标识
        detail: 问题描述
        affectedPages: 受影响的页面列表（可选）
    """

    def __init__(
        self,
        type: str,
        severity: str,
        page: str,
        detail: str,
        affectedPages: Optional[list[str]] = None,
    ):
        self.type = type
        self.severity = severity
        self.page = page
        self.detail = detail
        self.affectedPages = affectedPages

    def to_dict(self) -> dict:
        """转换为字典格式

        Returns:
            包含所有字段的字典
        """
        result = {
            "type": self.type,
            "severity": self.severity,
            "page": self.page,
            "detail": self.detail,
        }
        if self.affectedPages is not None:
            result["affectedPages"] = self.affectedPages
        return result


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
        # 跳过隐藏目录
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for f in files:
            if f.endswith(".md"):
                md_files.append(os.path.join(root, f))

    return md_files


def _extract_wikilinks(content: str) -> list[str]:
    """从 Markdown 内容中提取所有 wikilink 目标

    支持格式：[[target]] 或 [[target|display text]]

    Args:
        content: Markdown 文本内容
    Returns:
        wikilink 目标列表（已去除首尾空格）
    """
    links = []
    # 匹配 [[target]] 或 [[target|display]]
    pattern = r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]"
    for match in re.finditer(pattern, content):
        links.append(match.group(1).strip())
    return links


def _relative_to_slug(relative_path: str) -> str:
    """将相对路径转换为 slug（去掉 .md 后缀）

    Args:
        relative_path: 相对于 wiki/ 目录的路径，如 "entities/foo-bar"
    Returns:
        slug 字符串，如 "entities/foo-bar"
    """
    return re.sub(r"\.md$", "", relative_path)


def _get_relative_path(full_path: str, base_path: str) -> str:
    """获取相对于 base_path 的相对路径，使用正斜杠

    Args:
        full_path: 完整路径
        base_path: 基准路径
    Returns:
        相对路径字符串
    """
    # 统一使用正斜杠
    full_norm = full_path.replace("\\", "/")
    base_norm = base_path.replace("\\", "/").rstrip("/")

    if full_norm.startswith(base_norm + "/"):
        return full_norm[len(base_norm) + 1:]
    return full_norm


def _get_file_name(path: str) -> str:
    """从路径中提取文件名

    Args:
        path: 文件路径
    Returns:
        文件名部分
    """
    return path.replace("\\", "/").split("/")[-1]


def _build_slug_map(wiki_files: list[str], wiki_root: str) -> dict[str, str]:
    """构建 slug -> 绝对路径 的映射表

    同时索引相对路径和 basename，key 全部小写以支持大小写不敏感匹配。
    例如 [[Transformer]] 可以匹配 transformer.md。

    额外索引 frontmatter 中的 title 字段（中文标题 → slug 映射），
    使 [[中文标题]] 形式的 wikilink 也能正确解析。

    Args:
        wiki_files: wiki 目录下的 .md 文件路径列表
        wiki_root: wiki 目录根路径
    Returns:
        小写 slug / 小写标题 到绝对路径的映射字典
    """
    slug_map = {}
    for file_path in wiki_files:
        # 例如 /path/to/project/wiki/entities/foo.md -> entities/foo
        rel = _relative_to_slug(_get_relative_path(file_path, wiki_root))
        slug_map[rel.lower()] = file_path
        # 同时索引 basename（不含扩展名）
        basename = re.sub(r"\.md$", "", _get_file_name(file_path))
        slug_map[basename.lower()] = file_path

        # 索引 frontmatter 中的 title 字段
        # 使 [[中文标题]] 也能匹配到对应页面
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            fm_result = parse_frontmatter(content)
            fm = fm_result.frontmatter or {}
            title = fm.get("title", "")
            if isinstance(title, str) and title and title.lower() not in slug_map:
                slug_map[title.lower()] = file_path
        except Exception:
            pass

    return slug_map


# ---------------------------------------------------------------------------
# 结构检查
# ---------------------------------------------------------------------------

async def run_structural_lint(project_path: str) -> list[dict]:
    """执行 Wiki 结构检查

    检查项：
    - 孤立页面：无入链（排除 index.md 和 log.md）
    - 断链：wikilink 目标在 slugMap 中找不到（大小写不敏感）
    - 无出链：页面无任何 wikilink

    Args:
        project_path: 项目根目录路径
    Returns:
        检查结果列表，每项为 {"type", "severity", "page", "detail", "affectedPages"}
    """
    wiki_root = os.path.join(project_path, "wiki")
    if not os.path.exists(wiki_root):
        return []

    wiki_files = _flatten_md_files(wiki_root)

    # 排除 index.md 和 log.md 的孤立检查
    content_files = [
        f for f in wiki_files
        if _get_file_name(f) not in ("index.md", "log.md")
    ]

    slug_map = _build_slug_map(content_files, wiki_root)

    # 读取所有内容文件
    pages = []
    for file_path in content_files:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            slug = _relative_to_slug(_get_relative_path(file_path, wiki_root))
            outlinks = _extract_wikilinks(content)
            pages.append({
                "path": file_path,
                "slug": slug,
                "content": content,
                "outlinks": outlinks,
            })
        except Exception:
            # 跳过无法读取的文件
            continue

    # 构建入链计数（大小写不敏感）
    inbound_counts: dict[str, int] = {}
    for p in pages:
        for link in p["outlinks"]:
            lookup = link.lower()
            if lookup in slug_map:
                target = _relative_to_slug(
                    _get_relative_path(slug_map[lookup], wiki_root)
                ).lower()
            else:
                target = lookup
            inbound_counts[target] = inbound_counts.get(target, 0) + 1

    results = []

    for p in pages:
        short_name = _get_relative_path(p["path"], wiki_root)

        # 孤立页面：无入链（小写 slug 进行大小写不敏感匹配）
        inbound = inbound_counts.get(p["slug"].lower(), 0)
        if inbound == 0:
            results.append(LintResult(
                type="orphan",
                severity="info",
                page=short_name,
                detail="No other pages link to this page.",
            ))

        # 无出链
        if len(p["outlinks"]) == 0:
            results.append(LintResult(
                type="no-outlinks",
                severity="info",
                page=short_name,
                detail="This page has no [[wikilink]] references to other pages.",
            ))

        # 断链检查（大小写不敏感匹配）
        for link in p["outlinks"]:
            lookup = link.lower()
            basename = re.sub(r"\.md$", "", _get_file_name(link)).lower()
            exists = lookup in slug_map or basename in slug_map
            if not exists:
                results.append(LintResult(
                    type="broken-link",
                    severity="warning",
                    page=short_name,
                    detail=f"Broken link: [[{link}]] — target page not found.",
                ))

    return [r.to_dict() for r in results]


# ---------------------------------------------------------------------------
# 语义检查
# ---------------------------------------------------------------------------

# 语义检查 LINT 块正则：匹配 ---LINT: type | severity | title--- ... ---END LINT---
LINT_BLOCK_REGEX = re.compile(
    r"---LINT:\s*([^\n|]+?)\s*\|\s*([^\n|]+?)\s*\|\s*([^\n-]+?)\s*---\n"
    r"([\s\S]*?)"
    r"---END LINT---"
)


async def run_semantic_lint(
    project_path: str,
    llm_config: dict,
) -> list[dict]:
    """执行 Wiki 语义检查

    将所有页面摘要（前500字）发给 LLM，要求输出 ---LINT--- 格式的问题块。
    LLM 可检测的语义问题包括：矛盾、过时信息、缺失页面、建议等。

    Args:
        project_path: 项目根目录路径
        llm_config: LLM 配置字典，包含 provider、apiKey、model 等字段
    Returns:
        语义检查结果列表，每项为 {"type", "severity", "page", "detail", "affectedPages"}
    """
    wiki_root = os.path.join(project_path, "wiki")
    if not os.path.exists(wiki_root):
        return []

    wiki_files = _flatten_md_files(wiki_root)
    # 排除 log.md
    wiki_files = [f for f in wiki_files if _get_file_name(f) != "log.md"]

    # 构建每个页面的紧凑摘要（frontmatter + 前500字符）
    summaries = []
    for file_path in wiki_files:
        try:
            with open(file_path, "r", encoding="utf-8") as fh:
                content = fh.read()
            preview = content[:500] + ("..." if len(content) > 500 else "")
            short_path = _get_relative_path(file_path, wiki_root)
            summaries.append(f"### {short_path}\n{preview}")
        except Exception:
            # 跳过无法读取的文件
            continue

    if not summaries:
        return []

    # 构建语言指令（根据摘要内容自动检测语言）
    summary_sample = "\n".join(summaries)[:2000]
    language_directive = _build_language_directive(summary_sample)

    # 构建 LLM 提示词
    prompt = "\n".join([
        "You are a wiki quality analyst. Review the following wiki page summaries and identify issues.",
        "",
        language_directive,
        "",
        "For each issue, output exactly this format:",
        "",
        "---LINT: type | severity | Short title---",
        "Description of the issue.",
        "PAGES: page1.md, page2.md",
        "---END LINT---",
        "",
        "Types:",
        "- contradiction: two or more pages make conflicting claims",
        "- stale: information that appears outdated or superseded",
        "- missing-page: an important concept is heavily referenced but has no dedicated page",
        "- suggestion: a question or source worth adding to the wiki",
        "",
        "Severities:",
        "- warning: should be addressed",
        "- info: nice to have",
        "",
        "Only report genuine issues. Do not invent problems. Output ONLY the ---LINT--- blocks, no other text.",
        "",
        "## Wiki Pages",
        "",
        "\n\n".join(summaries),
    ])

    # 调用 LLM 进行语义分析
    raw = ""
    had_error = False

    def on_token(token: str):
        """流式 token 回调：累积响应文本"""
        nonlocal raw
        raw += token

    def on_done():
        """流式完成回调"""
        pass

    def on_error(error: Exception):
        """流式错误回调"""
        nonlocal had_error
        had_error = True

    await stream_chat(
        llm_config,
        [{"role": "user", "content": prompt}],
        on_token=on_token,
        on_done=on_done,
        on_error=on_error,
    )

    if had_error:
        return []

    # 解析 LINT 块
    results = []
    for match in LINT_BLOCK_REGEX.finditer(raw):
        raw_type = match.group(1).strip().lower()
        severity = match.group(2).strip().lower()
        title = match.group(3).strip()
        body = match.group(4).strip()

        # 提取受影响的页面
        pages_match = re.search(r"^PAGES:\s*(.+)$", body, re.MULTILINE)
        affected_pages = None
        if pages_match:
            affected_pages = [p.strip() for p in pages_match.group(1).split(",")]

        # 提取描述（去掉 PAGES 行）
        detail = re.sub(r"^PAGES:.*$", "", body, flags=re.MULTILINE).strip()

        results.append(LintResult(
            type="semantic",
            severity="warning" if severity == "warning" else "info",
            page=title,
            detail=f"[{raw_type}] {detail}",
            affectedPages=affected_pages,
        ))

    return [r.to_dict() for r in results]


def _build_language_directive(fallback_text: str = "") -> str:
    """构建语言指令，注入到 LLM 系统提示词中

    根据配置的输出语言或自动检测的文本语言，生成强制输出语言指令。

    Args:
        fallback_text: 用于自动检测语言的回退文本
    Returns:
        语言指令字符串
    """
    # 简单的语言检测：检查是否包含中文字符
    has_cjk = bool(re.search(r"[\u4e00-\u9fff]", fallback_text))
    lang_name = "Chinese" if has_cjk else "English"

    return "\n".join([
        f"## MANDATORY OUTPUT LANGUAGE: {lang_name}",
        "",
        f"You MUST write your entire response (including wiki page titles, content, descriptions, "
        f"summaries, and any generated text) in **{lang_name}**.",
        f"The source material or wiki content may be in a different language, "
        f"but this is IRRELEVANT to your output language.",
        f"Ignore the language of any source content. Generate everything in {lang_name} only.",
        f"Proper nouns should use standard {lang_name} transliteration when appropriate.",
        f"DO NOT use any other language. This overrides all other instructions.",
    ])
