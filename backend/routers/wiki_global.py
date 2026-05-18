"""
全局 Wiki 路由模块

提供跨项目的全局 Wiki 信息查询功能。

端点列表：
- GET /api/wiki/global/health — 全局 Wiki 健康概览
- GET /api/wiki/global/concepts — 全局概念列表
- GET /api/wiki/global/graph — 全局图谱概览
- GET /api/wiki/global/cross-project — 跨项目关联分析
"""

import os
import re

from fastapi import APIRouter, HTTPException, Query

from backend.services.project_service import get_all_projects
from backend.config import PROJECTS_ROOT, GLOBAL_WIKI_DIR

router = APIRouter(prefix="/api/wiki/global", tags=["wiki-global"])


def _get_wiki_projects() -> list[dict]:
    """获取所有拥有 wiki 目录的项目列表

    扫描所有项目，筛选出本地路径存在且包含 wiki 子目录的项目。

    Returns:
        包含 project_id / project_name / local_path 的字典列表
    """
    projects = get_all_projects()
    result = []
    for project in projects:
        local_path = project.get("local_path")
        if not local_path:
            continue
        wiki_dir = os.path.join(local_path, "wiki")
        if not os.path.isdir(wiki_dir):
            continue
        result.append({
            "project_id": project["id"],
            "project_name": project.get("name", ""),
            "local_path": local_path,
        })
    return result


def _count_md_files(directory: str) -> int:
    """递归统计目录下的 .md 文件数量

    Args:
        directory: 目标目录路径

    Returns:
        .md 文件数量
    """
    count = 0
    for root, _dirs, files in os.walk(directory):
        for f in files:
            if f.endswith(".md"):
                count += 1
    return count


@router.get("/health")
def global_health():
    """全局 Wiki 健康概览

    扫描所有项目的 wiki 目录，统计页面数量和基本信息。

    Returns:
        全局健康概览，包含 overall 汇总和各项目详情列表
    """
    try:
        projects = get_all_projects()
        project_list = []
        total_pages = 0

        for project in projects:
            local_path = project.get("local_path")
            if not local_path:
                continue
            wiki_dir = os.path.join(local_path, "wiki")
            if not os.path.isdir(wiki_dir):
                continue

            page_count = _count_md_files(wiki_dir)
            total_pages += page_count

            project_list.append({
                "projectId": project["id"],
                "projectName": project.get("name", ""),
                "pageCount": page_count,
            })

        wiki_project_count = len(project_list)

        return {
            "overall": {
                "totalProjects": wiki_project_count,
                "totalPages": total_pages,
            },
            "projects": project_list,
        }
    except Exception as err:
        return {
            "overall": {
                "totalProjects": 0,
                "totalPages": 0,
            },
            "projects": [],
            "error": str(err),
        }


@router.get("/concepts")
def global_concepts(limit: int = Query(50, description="概念数量限制")):
    """全局概念列表

    扫描所有项目 wiki 目录下的 concepts 子目录，提取概念页面信息。

    Args:
        limit: 返回概念数量上限，默认 50

    Returns:
        概念列表和总数
    """
    try:
        wiki_projects = _get_wiki_projects()
        all_concepts = []
        fm_title_re = re.compile(r'^---\n[\s\S]*?^title:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)
        fm_type_re = re.compile(r'^---\n[\s\S]*?^type:\s*["\']?(.+?)["\']?\s*$', re.MULTILINE)

        for wp in wiki_projects:
            project_id = wp["project_id"]
            project_name = wp["project_name"]
            local_path = wp["local_path"]
            concepts_dir = os.path.join(local_path, "wiki", "concepts")
            if not os.path.isdir(concepts_dir):
                continue

            for entry in sorted(os.listdir(concepts_dir)):
                if not entry.endswith(".md"):
                    continue
                file_path = os.path.join(concepts_dir, entry)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        content = f.read()
                except (OSError, UnicodeDecodeError):
                    continue

                title_match = fm_title_re.search(content)
                title = title_match.group(1).strip() if title_match else entry.replace(".md", "").replace("-", " ")

                type_match = fm_type_re.search(content)
                concept_type = type_match.group(1).strip().lower() if type_match else "concept"

                all_concepts.append({
                    "name": title,
                    "type": concept_type,
                    "projectId": project_id,
                    "projectName": project_name,
                    "path": f"wiki/concepts/{entry}",
                })

        return {
            "concepts": all_concepts[:limit],
            "total": len(all_concepts),
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/graph")
def global_graph():
    """全局图谱概览

    扫描所有项目的 wiki 目录，统计页面数量作为节点数的近似值。

    Returns:
        全局图谱概览，包含总节点数和各项目详情
    """
    try:
        projects = get_all_projects()
        project_list = []
        total_pages = 0

        for project in projects:
            local_path = project.get("local_path")
            if not local_path:
                continue
            wiki_dir = os.path.join(local_path, "wiki")
            if not os.path.isdir(wiki_dir):
                continue

            page_count = _count_md_files(wiki_dir)
            total_pages += page_count

            project_list.append({
                "projectId": project["id"],
                "projectName": project.get("name", ""),
                "pageCount": page_count,
            })

        return {
            "totalPages": total_pages,
            "projects": project_list,
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/cross-project")
async def cross_project_analysis():
    """跨项目关联分析

    扫描全局 Wiki 和所有项目的 Wiki 页面，
    通过标签重叠和 Jaccard 相似度发现跨项目知识关联。

    Returns:
        跨项目关联列表，包含源项目、目标页面、共同标签等信息
    """
    try:
        from backend.services.wiki.cross_project import run_cross_project_analysis
        from backend.services.wiki.llm_client import simple_chat

        result = await run_cross_project_analysis(GLOBAL_WIKI_DIR, {})
        return result
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))
