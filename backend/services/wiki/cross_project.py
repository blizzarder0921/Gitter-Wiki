"""
跨项目关联分析模块

扫描所有项目的 Wiki 页面，发现跨项目的知识关联，
包括共享概念、相似主题和潜在的知识交叉点。

核心函数：
- run_cross_project_analysis: 跨项目关联分析主入口
"""

import logging
import os
from typing import Any

from backend.config import PROJECTS_ROOT, GLOBAL_WIKI_DIR
from backend.services.wiki.frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)


def _scan_project_wiki_pages(project_path: str) -> list[dict]:
    """扫描项目 Wiki 目录下的所有页面，提取标题和标签

    Args:
        project_path: 项目本地路径
    Returns:
        页面信息列表，每项包含 path、title、tags 字段
    """
    wiki_dir = os.path.join(project_path, "wiki")
    if not os.path.isdir(wiki_dir):
        return []

    pages: list[dict] = []
    for root, _dirs, files in os.walk(wiki_dir):
        _dirs[:] = [d for d in _dirs if not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".md"):
                continue
            file_path = os.path.join(root, fname)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                fm_result = parse_frontmatter(content)
                fm = fm_result.frontmatter or {}
                title = fm.get("title", fname[:-3])
                tags = fm.get("tags", [])
                if isinstance(tags, str):
                    tags = [tags]
                rel_path = os.path.relpath(file_path, project_path).replace("\\", "/")
                pages.append({
                    "path": rel_path,
                    "title": str(title),
                    "tags": [str(t).strip() for t in tags if str(t).strip()],
                })
            except Exception:
                continue
    return pages


async def run_cross_project_analysis(
    current_wiki_path: str,
    llm_config: dict,
) -> dict:
    """跨项目关联分析主入口

    扫描全局 Wiki 和所有项目的 Wiki 页面，
    通过标签重叠和标题相似度发现跨项目知识关联。

    Args:
        current_wiki_path: 当前 Wiki 目录路径（全局 Wiki）
        llm_config: LLM 配置字典
    Returns:
        分析结果，包含 links（跨项目关联列表）
    """
    # 扫描全局 Wiki 页面
    global_pages = _scan_project_wiki_pages(current_wiki_path)
    if not global_pages:
        return {"links": []}

    # 扫描其他项目的 Wiki 页面
    other_project_pages: dict[str, list[dict]] = {}
    if os.path.isdir(PROJECTS_ROOT):
        for entry in os.listdir(PROJECTS_ROOT):
            proj_dir = os.path.join(PROJECTS_ROOT, entry)
            if not os.path.isdir(proj_dir):
                continue
            wiki_dir = os.path.join(proj_dir, "wiki")
            if not os.path.isdir(wiki_dir):
                continue
            pages = _scan_project_wiki_pages(proj_dir)
            if pages:
                other_project_pages[entry] = pages

    if not other_project_pages:
        return {"links": []}

    # 通过标签重叠发现关联
    links: list[dict[str, Any]] = []
    global_tag_map: dict[str, list[str]] = {}
    for page in global_pages:
        for tag in page.get("tags", []):
            tag_lower = tag.lower()
            if tag_lower not in global_tag_map:
                global_tag_map[tag_lower] = []
            global_tag_map[tag_lower].append(page["title"])

    # 构建全局标签集合，用于 Jaccard 计算
    global_tag_set: set[str] = set(global_tag_map.keys())

    for proj_name, pages in other_project_pages.items():
        for page in pages:
            page_tags = {t.lower() for t in page.get("tags", [])}
            common_tags_set = page_tags & global_tag_set
            common_tags = sorted(common_tags_set)

            if not common_tags:
                continue

            # Jaccard 相似度 = |交集| / |并集|
            union_tags = page_tags | global_tag_set
            jaccard = len(common_tags_set) / len(union_tags) if union_tags else 0.0

            links.append({
                "sourceProject": proj_name,
                "sourcePage": page["title"],
                "targetPages": global_tag_map.get(
                    common_tags[0], []
                )[:5],
                "commonTags": common_tags,
                "jaccardSimilarity": round(jaccard, 4),
                "type": "jaccard-similarity" if jaccard >= 0.1 else "tag-overlap",
            })

    # 按 Jaccard 相似度降序排列
    links.sort(key=lambda x: x.get("jaccardSimilarity", 0), reverse=True)

    logger.info(
        "[跨项目分析] 发现 %d 个跨项目关联（扫描 %d 个全局页面，%d 个项目）",
        len(links),
        len(global_pages),
        len(other_project_pages),
    )

    return {"links": links}
