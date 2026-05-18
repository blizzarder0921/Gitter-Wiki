"""
FastAPI 应用入口模块

功能：
- 创建 FastAPI 应用实例
- 配置 CORS 中间件（允许 localhost:3000 前端访问）
- 挂载所有路由模块
- 启动时初始化数据库
- 启动后台定时任务（Lint 调度、对话清理、归档清理）
- 提供健康检查端点
"""

import asyncio
import logging
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.services.database import get_db
from backend.config import GLOBAL_WIKI_SOURCES_DIR, GLOBAL_WIKI_WIKI_DIR, GLOBAL_WIKI_META_DIR, PROJECTS_ROOT
from backend.routers import (
    projects,
    settings,
    system,
    extract,
    github,
    translate,
    graphify,
    wiki,
    wiki_chats,
    wiki_global,
    wiki_fs,
    capabilities,
    share,
)

_logger = logging.getLogger("backend.main")


# ---------------------------------------------------------------------------
# 后台定时任务
# ---------------------------------------------------------------------------


def _start_background_tasks() -> None:
    """启动所有后台定时任务

    读取 Wiki 配置，根据设置启动：
    - Lint 定时调度（lintSchedule 不为 off 时）
    - 对话历史自动清理（chatRetention 不为 forever 时）
    - 旧版本归档自动清理（autoCleanup 为 True 时）
    """
    try:
        from backend.routers.wiki import _get_wiki_settings, _run_scheduled_lint
        wiki_cfg = _get_wiki_settings()
    except Exception as err:
        _logger.warning("读取 Wiki 设置失败，跳过后台任务启动: %s", err)
        return

    # Lint 定时调度
    schedule = wiki_cfg.get("evolution", {}).get("lintSchedule", "off")
    if schedule != "off":
        asyncio.create_task(_run_scheduled_lint(schedule))
        _logger.info("已启动 Lint 定时调度，频率: %s", schedule)

    # 对话历史自动清理
    chat_retention = wiki_cfg.get("storage", {}).get("chatRetention", "90d")
    if chat_retention != "forever":
        asyncio.create_task(_run_chat_cleanup(chat_retention))
        _logger.info("已启动对话历史自动清理，保留期限: %s", chat_retention)

    # 旧版本归档自动清理
    auto_cleanup = wiki_cfg.get("storage", {}).get("autoCleanup", False)
    if auto_cleanup:
        asyncio.create_task(_run_archive_cleanup())
        _logger.info("已启动旧版本归档自动清理")


async def _run_chat_cleanup(retention: str) -> None:
    """后台定时清理过期对话历史

    每天执行一次，根据 retention 设置删除过期记录。
    每次执行前重新读取设置，响应用户配置变更。

    Args:
        retention: 保留期限，如 "30d"、"90d"、"forever"
    """
    while True:
        await asyncio.sleep(24 * 3600)

        # 重新读取设置
        try:
            from backend.routers.wiki import _get_wiki_settings
            wiki_cfg = _get_wiki_settings()
            current_retention = wiki_cfg.get("storage", {}).get("chatRetention", "90d")

            if current_retention == "forever":
                _logger.info("[对话清理] chatRetention 已设为 forever，退出清理任务")
                break

            retention = current_retention
        except Exception as err:
            _logger.warning("[对话清理] 读取设置失败: %s，继续使用当前配置", err)

        # 解析保留天数
        days = _parse_retention_days(retention)
        if days <= 0:
            continue

        # 执行清理
        try:
            db = get_db()
            # 先删除过期对话的消息
            db.execute(
                "DELETE FROM wiki_chat_messages WHERE chat_id IN "
                "(SELECT id FROM wiki_chats WHERE created_at < datetime('now', ?))",
                (f"-{days} days",),
            )
            # 再删除过期对话
            cursor = db.execute(
                "DELETE FROM wiki_chats WHERE created_at < datetime('now', ?)",
                (f"-{days} days",),
            )
            db.commit()
            deleted = cursor.rowcount
            if deleted > 0:
                _logger.info("[对话清理] 已删除 %d 条过期对话（保留 %d 天）", deleted, days)
        except Exception as err:
            _logger.error("[对话清理] 清理失败: %s", err)


async def _run_archive_cleanup() -> None:
    """后台定时清理过期归档文件

    每天执行一次，扫描 data/projects/ 下的压缩包文件，
    删除超过 90 天的归档。每次执行前重新读取设置。
    """
    _ARCHIVE_EXTENSIONS = {".zip", ".7z", ".rar", ".tar.gz", ".tgz"}
    _ARCHIVE_RETENTION_DAYS = 90

    while True:
        await asyncio.sleep(24 * 3600)

        # 重新读取设置
        try:
            from backend.routers.wiki import _get_wiki_settings
            wiki_cfg = _get_wiki_settings()
            if not wiki_cfg.get("storage", {}).get("autoCleanup", False):
                _logger.info("[归档清理] autoCleanup 已关闭，退出清理任务")
                break
        except Exception as err:
            _logger.warning("[归档清理] 读取设置失败: %s，继续执行", err)

        # 执行清理
        try:
            if not os.path.isdir(PROJECTS_ROOT):
                continue

            now = time.time()
            cutoff = now - _ARCHIVE_RETENTION_DAYS * 86400
            deleted_count = 0

            for root, _dirs, files in os.walk(PROJECTS_ROOT):
                for fname in files:
                    # 检查是否为归档文件
                    is_archive = any(
                        fname.lower().endswith(ext) for ext in _ARCHIVE_EXTENSIONS
                    )
                    if not is_archive:
                        continue

                    file_path = os.path.join(root, fname)
                    try:
                        mtime = os.path.getmtime(file_path)
                        if mtime < cutoff:
                            os.remove(file_path)
                            deleted_count += 1
                    except OSError:
                        continue

            if deleted_count > 0:
                _logger.info(
                    "[归档清理] 已删除 %d 个过期归档（保留 %d 天）",
                    deleted_count, _ARCHIVE_RETENTION_DAYS,
                )
        except Exception as err:
            _logger.error("[归档清理] 清理失败: %s", err)


def _parse_retention_days(retention: str) -> int:
    """解析保留期限字符串为天数

    Args:
        retention: 保留期限字符串，如 "30d"、"90d"、"forever"
    Returns:
        保留天数，无法解析时返回 0
    """
    if not retention or retention == "forever":
        return 0
    try:
        # 提取数字部分
        num_str = retention.rstrip("dD")
        return int(num_str)
    except (ValueError, AttributeError):
        return 0


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例"""
    app = FastAPI(
        title="Gitter API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
    )

    # 配置 CORS 中间件，允许前端开发服务器访问
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册所有路由模块
    app.include_router(projects.router)
    app.include_router(settings.router)
    app.include_router(system.router)
    app.include_router(extract.router)
    app.include_router(github.router)
    app.include_router(translate.router)
    app.include_router(graphify.router)
    app.include_router(wiki_global.router)
    app.include_router(wiki.router)
    app.include_router(wiki_chats.router)
    app.include_router(wiki_fs.router)
    app.include_router(capabilities.router)
    app.include_router(share.router)

    # 应用启动事件：初始化数据库
    @app.on_event("startup")
    def on_startup():
        """应用启动时初始化数据库连接和表结构，并重置中断的状态，启动后台定时任务"""
        db = get_db()

        # 确保全局 Wiki 目录结构存在
        os.makedirs(GLOBAL_WIKI_SOURCES_DIR, exist_ok=True)
        os.makedirs(GLOBAL_WIKI_WIKI_DIR, exist_ok=True)
        os.makedirs(GLOBAL_WIKI_META_DIR, exist_ok=True)

        # 重置卡在 fetching 的 github_fetch_status（后台任务中断后状态无法恢复）
        db.execute(
            "UPDATE projects SET github_fetch_status = 'pending' WHERE github_fetch_status = 'fetching'"
        )
        # 重置卡在非终态的 workflow_status
        db.execute(
            "UPDATE projects SET workflow_status = 'idle' WHERE workflow_status NOT IN ('idle', 'done', 'failed')"
        )
        # 重置卡在 cloning/pulling 的 sync_status
        db.execute(
            "UPDATE projects SET sync_status = 'pending' WHERE sync_status IN ('cloning', 'pulling')"
        )
        db.commit()

        # 启动后台定时任务
        _start_background_tasks()

    return app


app = create_app()


@app.get("/api/health")
def health_check():
    """健康检查端点，返回服务状态和版本信息"""
    return {"status": "ok", "version": "0.1.0"}
