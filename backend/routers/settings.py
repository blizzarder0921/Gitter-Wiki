"""
设置路由模块

对应原 Next.js 的 app/api/settings/ 目录，提供设置读写和项目路径迁移功能。

端点列表：
- GET  /api/settings                — 获取设置
- POST /api/settings                — 保存设置
- POST /api/settings/migrate-projects — 迁移项目路径
"""

import json

from fastapi import APIRouter, HTTPException, Request

from backend.services.project_service import get_setting, set_setting, get_all_settings, get_all_projects, update_project

router = APIRouter(prefix="/api/settings", tags=["settings"])

# 设置存储的键名，与原 Next.js 版本一致
SETTINGS_KEY = "settings-storage"


@router.get("")
def get_settings():
    """获取设置

    返回格式：{"settings": {key: value, ...}}，其中 value 为原始字符串值（不解析 JSON）。
    前端 settings-preloader.tsx 使用 data.settings?.[SETTINGS_KEY] 访问，
    SETTINGS_KEY = "settings-storage"，value 是 JSON 字符串，由前端自行 JSON.parse。

    Returns:
        {"settings": {"settings-storage": "json_string", ...}} 格式
    """
    try:
        all_settings = get_all_settings()
        return {"settings": all_settings}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("")
async def save_settings(request: Request):
    """保存设置到 SQLite

    请求体为 JSON 字符串（Content-Type: text/plain 或 application/json）

    Returns:
        保存结果
    """
    try:
        body = await request.body()
        text = body.decode("utf-8")

        if not text or text in ("[object Object]", "undefined", "null"):
            raise HTTPException(status_code=400, detail="Invalid settings data")

        try:
            json.loads(text)
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid JSON")

        set_setting(SETTINGS_KEY, text)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.post("/migrate-projects")
async def migrate_projects(request: Request):
    """项目存储路径迁移

    执行项目存储路径变更后的全量迁移，更新所有项目的 local_path。

    Args:
        request: 请求体包含 oldPath 和 newPath
    Returns:
        迁移结果统计
    """
    try:
        body = await request.json()
        old_path = body.get("oldPath")
        new_path = body.get("newPath")

        if not old_path or not new_path:
            raise HTTPException(status_code=400, detail="缺少必要参数：oldPath 和 newPath")

        if old_path == new_path:
            return {"success": True, "migrated": 0, "failed": 0, "skipped": 0}

        # 遍历所有项目，更新 local_path 中的旧路径前缀
        projects = get_all_projects()
        migrated = 0
        failed = 0
        skipped = 0

        for project in projects:
            local_path = project.get("local_path")
            if not local_path:
                skipped += 1
                continue

            # 替换路径前缀
            if local_path.startswith(old_path):
                new_local_path = new_path + local_path[len(old_path):]
                try:
                    update_project(project["id"], {"local_path": new_local_path})
                    migrated += 1
                except Exception:
                    failed += 1
            else:
                skipped += 1

        return {
            "success": True,
            "migrated": migrated,
            "failed": failed,
            "skipped": skipped,
        }
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"迁移失败：{str(err)}")
