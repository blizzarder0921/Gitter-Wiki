"""
wiki_page_resolver.py —— Wiki 页面路径解析器

将 Obsidian 风格的 [[wikilink]] 引用、related/sources 前置字段中的
各种格式（相对路径、裸文件名、裸 slug）解析为文件树中的绝对路径。

从 TypeScript 版本移植，移除了所有 Tauri API 依赖。
"""

from __future__ import annotations

import re
from typing import TypedDict


# ---------------------------------------------------------------------------
# 类型定义
# ---------------------------------------------------------------------------

class FileNode(TypedDict, total=False):
    """文件树节点格式，与项目其他模块保持一致。

    Attributes:
        name: 文件或目录的名称（含扩展名）
        path: 从项目根开始的绝对路径
        is_dir: 是否为目录
        children: 子节点列表（仅目录有）
    """
    name: str
    path: str
    is_dir: bool
    children: list["FileNode"]


# ---------------------------------------------------------------------------
# 核心函数
# ---------------------------------------------------------------------------

def unwrap_wikilink(s: str) -> tuple[str, str]:
    """剥离 Obsidian 风格的 [[target]] 或 [[target|alias]] 包裹。

    前置字段中的 related / sources 条目有时会写成 wikilink 格式，
    本函数将其拆分为 (slug, label)，方便后续查找和显示。

    非 wikilink 输入原样返回，即 slug == label == 输入字符串。

    Args:
        s: 待解析的字符串，可能是 wikilink 或普通文本。

    Returns:
        (slug, label) 二元组：
        - slug: 方括号内的目标部分，用于路径查找；
        - label: 别名部分（无别名时等于 slug），用于界面显示。
    """
    # 正则匹配 [[target]] 或 [[target|alias]] 两种形式
    m = re.match(r"^\[\[([^\]|]+)(?:\|([^\]]*))?\]\]$", s)
    if not m:
        return (s, s)

    target = m.group(1).strip()
    alias = m.group(2)
    # group(2) 可能是 None（无 | 分隔）或空字符串（| 后无内容）
    if alias is not None:
        alias = alias.strip()

    label = alias if alias and len(alias) > 0 else target
    return (target, label)


# ---------------------------------------------------------------------------
# 文件树查找辅助
# ---------------------------------------------------------------------------

def _walk_find_by_name(nodes: list[FileNode], target_name: str, path_contains: str) -> str | None:
    """递归遍历文件树，按名称和路径片段匹配查找文件。

    在子树中查找第一个 name 等于 target_name 且 path 包含
    path_contains 的文件节点，返回其绝对路径。

    Args:
        nodes: 当前层级的文件树节点列表。
        target_name: 目标文件名（含扩展名）。
        path_contains: 路径必须包含的片段，用于限定搜索范围。

    Returns:
        匹配节点的 path，未找到返回 None。
    """
    for node in nodes:
        if node.get("is_dir", False):
            children = node.get("children", [])
            if children:
                result = _walk_find_by_name(children, target_name, path_contains)
                if result is not None:
                    return result
            continue

        # 文件节点：名称匹配 且 路径包含指定片段
        if node.get("name") == target_name and path_contains in node.get("path", ""):
            return node.get("path")

    return None


def _walk_find_by_path(nodes: list[FileNode], target_path: str) -> str | None:
    """递归遍历文件树，按完整路径精确匹配查找节点。

    Args:
        nodes: 当前层级的文件树节点列表。
        target_path: 目标节点的完整路径。

    Returns:
        匹配节点的 path，未找到返回 None。
    """
    for node in nodes:
        if node.get("path") == target_path:
            return node.get("path")
        if node.get("is_dir", False):
            children = node.get("children", [])
            if children:
                result = _walk_find_by_path(children, target_path)
                if result is not None:
                    return result
    return None


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------

def find_in_tree_by_name(
    tree: list[FileNode],
    target_name: str,
    path_contains: str,
) -> str | None:
    """在文件树中按名称查找目标文件，限定路径范围。

    遍历 FileNode 树，返回第一个 name 匹配 target_name 且
    path 包含 pathContains 的文件节点的绝对路径。
    用于前置面板中将 related: [slug] 解析为 wiki/.../<slug>.md 路径，
    以及将 sources: [name.pdf] 解析为 raw/sources/.../name.pdf 路径。

    故意取首个匹配——不同子目录下的同名文件属于作者命名冲突，
    任意选择其一并不比纯文本展示更差。

    Args:
        tree: 文件树根节点列表。
        target_name: 目标文件名（含扩展名）。
        path_contains: 路径必须包含的片段，用于限定搜索范围。

    Returns:
        匹配文件的绝对路径，未找到返回 None。
    """
    return _walk_find_by_name(tree, target_name, path_contains)


def resolve_related_slug(
    tree: list[FileNode],
    ref: str,
    wiki_root: str,
) -> str | None:
    """解析 related 前置字段引用到绝对路径。

    支持三种历史格式：
      1. 项目相对路径：wiki/entities/dpao.md
      2. 带 .md 的裸文件名：dpao.md
      3. 裸 slug：dpao

    始终将查找范围限制在 wiki/ 目录内，避免误匹配
    raw/sources/ 下的同名文件。

    Args:
        tree: 文件树根节点列表。
        ref: related 字段中的引用字符串。
        wiki_root: wiki 目录的绝对路径（如 /project/wiki）。

    Returns:
        匹配文件的绝对路径，未找到返回 None。
    """
    # 路径形式 → 相对于项目根解析（wikiRoot 的上一级）
    if "/" in ref:
        project_root = re.sub(r"/wiki$", "", wiki_root)
        target = f"{project_root}/{ref}"
        found = _walk_find_by_path(tree, target)
        # 确保结果确实位于 wiki/ 目录下
        if found is not None and f"{wiki_root}/" in found:
            return found
        return None

    # 裸文件名或 slug → 补上 .md 后按名称查找
    filename = ref if ref.endswith(".md") else f"{ref}.md"
    return find_in_tree_by_name(tree, filename, f"{wiki_root}/")


def resolve_source_name(
    tree: list[FileNode],
    ref: str,
    sources_root: str,
) -> str | None:
    """解析 sources 前置字段引用到绝对路径。

    支持三种格式：
      1. 项目相对路径：wiki/sources/foo.md 或 raw/sources/year-2025/q1.pdf
      2. 带扩展名的裸文件名：q1.pdf
      3. wiki source-summary：foo.md（优先在 wiki/sources/ 中查找）

    对于裸 .md 文件名，优先在 wiki/sources/ 中查找
    （ingest 管道将摘要页写入该目录），找不到再回退到 raw/sources/。

    Args:
        tree: 文件树根节点列表。
        ref: sources 字段中的引用字符串。
        sources_root: raw/sources 目录的绝对路径（如 /project/raw/sources）。

    Returns:
        匹配文件的绝对路径，未找到返回 None。
    """
    # 从 sourcesRoot 推导项目根和 wiki/sources 路径
    project_root = re.sub(r"/raw/sources$", "", sources_root)
    wiki_sources = f"{project_root}/wiki/sources"

    # 路径形式 → 相对于项目根解析
    if "/" in ref:
        target = f"{project_root}/{ref}"
        return _walk_find_by_path(tree, target)

    # 裸 .md 文件名 → 优先在 wiki/sources/ 中查找（ingest 的摘要页）
    if ref.endswith(".md"):
        in_wiki = find_in_tree_by_name(tree, ref, f"{wiki_sources}/")
        if in_wiki is not None:
            return in_wiki

    # 其他情况 → 在 raw/sources/ 中查找
    return find_in_tree_by_name(tree, ref, f"{sources_root}/")
