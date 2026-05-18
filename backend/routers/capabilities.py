"""
能力报告路由模块

提供项目能力报告的生成触发、状态查询和列表接口。
通过 LLM 分析项目材料，输出标准化的能力描述文档。

端点列表：
- POST /api/capabilities/{projectId}/generate — 手动触发生成能力报告
- GET  /api/capabilities/{projectId}/status    — 查询报告生成状态
- GET  /api/capabilities                        — 返回所有已生成报告的项目列表

GPLv3 License - Gitter Project
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from backend.services.project_service import get_project_by_id, get_all_projects
from backend.services.capability_generator import generate_capability_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/capabilities", tags=["capabilities"])

# 内存字典，跟踪正在生成报告的项目状态
# key: project_id (int), value: {"status": "generating" | "failed", "error": str | None}
_generating_status: dict[int, dict] = {}


async def _generate_and_track(project_id: int, github_url: str | None) -> None:
    """异步执行能力报告生成，并更新内存状态

    生成成功后清除内存中的 generating 状态（数据库中已有 capability_report_path 标记完成），
    生成失败时将状态设为 failed 并记录错误信息。

    Args:
        project_id: 项目 ID
        github_url: GitHub 仓库 URL，可选
    """
    try:
        _generating_status[project_id] = {"status": "generating", "error": None}
        result = await generate_capability_report(project_id, github_url)
        if result is None:
            _generating_status[project_id] = {
                "status": "failed",
                "error": "报告生成返回为空，可能缺少 LLM 配置或项目材料不足",
            }
            logger.warning("[capabilities] 项目 %d 报告生成返回 None", project_id)
        else:
            # 生成成功，清除内存状态（数据库字段已由 generate_capability_report 更新）
            _generating_status.pop(project_id, None)
            logger.info("[capabilities] 项目 %d 报告生成成功", project_id)
    except Exception as e:
        _generating_status[project_id] = {"status": "failed", "error": str(e)}
        logger.error(
            "[capabilities] 项目 %d 报告生成异常: %s", project_id, e, exc_info=True
        )


@router.post("/{projectId}/generate")
def trigger_generate(projectId: int):
    """手动触发能力报告生成

    根据项目 ID 查询数据库获取 github_url，然后异步调用
    generate_capability_report 生成报告。使用 asyncio.create_task
    在后台执行，接口立即返回 generating 状态。

    Args:
        projectId: 项目 ID（路径参数）

    Returns:
        {"status": "generating"} 表示已触发生成任务

    Raises:
        HTTPException 404: 项目不存在
        HTTPException 409: 项目正在生成中，避免重复触发
    """
    # 查询项目信息
    project = get_project_by_id(projectId)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 检查是否正在生成中，避免重复触发
    current = _generating_status.get(projectId)
    if current and current["status"] == "generating":
        raise HTTPException(status_code=409, detail="该项目正在生成能力报告，请稍后再试")

    github_url = project.get("github_url")

    # 异步执行生成任务
    asyncio.create_task(_generate_and_track(projectId, github_url))

    return {"status": "generating"}


@router.get("/{projectId}/status")
def get_status(projectId: int):
    """查询能力报告生成状态

    综合内存状态和数据库字段判断当前报告状态：
    - 内存中存在 generating 状态 → generating
    - 内存中存在 failed 状态 → failed（附带错误信息）
    - 数据库中 capability_report_path 非空 → done
    - 以上均不满足 → 无报告

    Args:
        projectId: 项目 ID（路径参数）

    Returns:
        {"status": "done" | "generating" | "failed" | "none",
         "generated_at": str | None,
         "error": str | None}

    Raises:
        HTTPException 404: 项目不存在
    """
    project = get_project_by_id(projectId)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 优先检查内存状态（generating / failed）
    mem_status = _generating_status.get(projectId)
    if mem_status:
        return {
            "status": mem_status["status"],
            "generated_at": project.get("capability_generated_at"),
            "error": mem_status.get("error"),
        }

    # 检查数据库中是否已有报告
    report_path = project.get("capability_report_path")
    if report_path:
        return {
            "status": "done",
            "generated_at": project.get("capability_generated_at"),
            "error": None,
        }

    # 无报告且不在生成中
    return {
        "status": "none",
        "generated_at": None,
        "error": None,
    }


@router.get("")
def list_capabilities():
    """返回所有已生成能力报告的项目列表

    查询 projects 表中 capability_report_path 不为空的记录，
    返回项目摘要信息供前端展示报告列表。

    Returns:
        项目列表，每项包含 id、name、capability_generated_at
    """
    try:
        all_projects = get_all_projects()
        result = []
        for p in all_projects:
            if p.get("capability_report_path"):
                result.append({
                    "id": p["id"],
                    "name": p.get("name"),
                    "capability_generated_at": p.get("capability_generated_at"),
                })
        return result
    except Exception as e:
        logger.error("[capabilities] 获取报告列表失败: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
