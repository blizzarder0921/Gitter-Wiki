"""
持久化摄入队列模块

从 TypeScript 版 llm_wiki-0.4.9/src/lib/ingest-queue.ts 移植。
提供串行摄入任务队列，支持持久化到 JSON 文件、自动重试和取消。

核心功能：
- IngestTask: 摄入任务数据类
- save_queue / load_queue: 队列持久化（JSON 文件）
- enqueue / dequeue: 入队/出队操作
- cancel_task / retry_failed: 取消与重试
- process_next: 串行处理器，调用 auto_ingest
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Any

from backend.services.wiki.ingest import auto_ingest

logger = logging.getLogger(__name__)

# 最大重试次数，超过后标记为 failed
MAX_RETRIES = 3


# ── 数据类 ────────────────────────────────────────────────────────────────


@dataclass
class IngestTask:
    """摄入任务数据类

    Attributes:
        id: 任务唯一标识，格式 ingest-{timestamp}-{random}
        project_id: 项目唯一标识（UUID）
        source_path: 源文件相对路径，如 "raw/sources/folder/file.pdf"
        folder_context: 文件夹上下文提示，如 "AI-Research > papers"
        status: 任务状态 — pending / processing / done / failed
        added_at: 入队时间戳（毫秒）
        error: 错误信息，成功时为 None
        retry_count: 已重试次数
    """
    id: str
    project_id: str
    source_path: str
    folder_context: str = ""
    status: str = "pending"
    added_at: int = field(default_factory=lambda: int(time.time() * 1000))
    error: str | None = None
    retry_count: int = 0


# ── 内部状态 ──────────────────────────────────────────────────────────────


# 内存中的任务队列
_queue: list[IngestTask] = []
# 是否正在处理任务（串行锁）
_processing: bool = False
# 当前活跃项目 ID，用于防止跨项目操作
_current_project_id: str = ""
# 当前活跃项目路径
_current_project_path: str = ""
# 当前任务的异步取消事件
_current_cancel_event: asyncio.Event | None = None
# 当前摄入写入的文件列表（用于取消时清理）
_last_written_files: list[str] = []


# ── 持久化 ────────────────────────────────────────────────────────────────


def _queue_file_path(project_path: str) -> str:
    """获取队列持久化文件路径

    Args:
        project_path: 项目根目录绝对路径
    Returns:
        队列 JSON 文件路径
    """
    return os.path.join(project_path, ".llm-wiki", "ingest-queue.json")


def save_queue(project_path: str) -> None:
    """将队列持久化到磁盘

    仅保存 pending 和 failed 状态的任务，done 状态的任务不保存。
    写入失败时静默忽略（非关键操作）。

    Args:
        project_path: 项目根目录绝对路径
    """
    try:
        to_save = [t for t in _queue if t.status != "done"]
        path = _queue_file_path(project_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(t) for t in to_save], f, indent=2, ensure_ascii=False)
    except Exception:
        # 持久化失败非关键，静默忽略
        pass


def load_queue(project_path: str, project_id: str) -> list[IngestTask]:
    """从磁盘加载队列

    加载时自动回填 project_id（兼容旧格式文件），
    并将残留的 processing 状态重置为 pending（上次中断未完成）。

    Args:
        project_path: 项目根目录绝对路径
        project_id: 项目唯一标识
    Returns:
        加载的任务列表
    """
    try:
        path = _queue_file_path(project_path)
        with open(path, "r", encoding="utf-8") as f:
            raw_list = json.load(f)
        tasks: list[IngestTask] = []
        for item in raw_list:
            # 回填 project_id（兼容旧格式）
            item.setdefault("project_id", project_id)
            if not item.get("project_id"):
                item["project_id"] = project_id
            # 将残留的 processing 状态重置为 pending
            if item.get("status") == "processing":
                item["status"] = "pending"
            tasks.append(IngestTask(**item))
        # 过滤掉不属于当前项目的任务（防御性校验）
        tasks = [t for t in tasks if t.project_id == project_id]
        return tasks
    except Exception:
        return []


# ── 辅助函数 ──────────────────────────────────────────────────────────────


def _generate_id() -> str:
    """生成任务唯一标识

    格式：ingest-{timestamp}-{random6}

    Returns:
        任务 ID 字符串
    """
    import random
    import string
    rand_part = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"ingest-{int(time.time() * 1000)}-{rand_part}"


def _normalize_source_path(source_path: str) -> str:
    """规范化源文件路径为项目相对路径

    如果路径以当前项目路径开头，则截取相对部分。

    Args:
        source_path: 原始源文件路径
    Returns:
        规范化后的相对路径
    """
    normalized = os.path.normpath(source_path).replace("\\", "/")
    if _current_project_path:
        prefix = os.path.normpath(_current_project_path).replace("\\", "/")
        if normalized.startswith(prefix + "/"):
            return normalized[len(prefix) + 1:]
    return normalized


def _upsert_task(project_id: str, source_path: str, folder_context: str) -> str:
    """插入或更新队列中的摄入任务

    如果同项目同源文件已有 pending/failed 任务，则更新而非重复创建。
    如果同源文件正在 processing，则检查是否已有 pending 的重入任务，
    避免重复排队。

    Args:
        project_id: 项目 ID
        source_path: 源文件路径
        folder_context: 文件夹上下文
    Returns:
        任务 ID
    """
    normalized = _normalize_source_path(source_path)

    # 查找同项目同源文件的 pending 或 failed 任务
    for t in _queue:
        if (t.project_id == project_id
                and t.status in ("pending", "failed")
                and _normalize_source_path(t.source_path) == normalized):
            # 更新已有任务，重置状态
            t.source_path = normalized
            t.folder_context = folder_context or t.folder_context
            t.status = "pending"
            t.error = None
            t.retry_count = 0
            return t.id

    # 检查是否有正在 processing 的同源任务，避免重复排队
    has_processing = any(
        t.project_id == project_id
        and t.status == "processing"
        and _normalize_source_path(t.source_path) == normalized
        for t in _queue
    )
    if has_processing:
        has_pending_rerun = any(
            t.project_id == project_id
            and t.status == "pending"
            and _normalize_source_path(t.source_path) == normalized
            for t in _queue
        )
        if has_pending_rerun:
            # 已有重入任务，无需再创建
            for t in _queue:
                if (t.project_id == project_id
                        and t.status == "pending"
                        and _normalize_source_path(t.source_path) == normalized):
                    return t.id

    # 创建新任务
    task = IngestTask(
        id=_generate_id(),
        project_id=project_id,
        source_path=normalized,
        folder_context=folder_context,
    )
    _queue.append(task)
    return task.id


# ── 队列操作 ──────────────────────────────────────────────────────────────


async def enqueue(
    project_id: str,
    source_path: str,
    folder_context: str = "",
    llm_config: dict | None = None,
) -> str:
    """将文件加入摄入队列

    必须在当前活跃项目上操作。入队后自动触发串行处理。

    Args:
        project_id: 项目 ID（必须与当前活跃项目一致）
        source_path: 源文件路径
        folder_context: 文件夹上下文提示
        llm_config: LLM 配置字典（传入后缓存，供 process_next 使用）
    Returns:
        任务 ID
    Raises:
        ValueError: 项目 ID 与当前活跃项目不匹配
    """
    global _current_llm_config
    if not _current_project_id or _current_project_id != project_id:
        raise ValueError(
            f"enqueue: 项目 {project_id} 不是当前活跃项目"
            f"（当前: {_current_project_id or '<无>'}）"
        )

    task_id = _upsert_task(project_id, source_path, folder_context)
    save_queue(_current_project_path)

    # 缓存 LLM 配置供 process_next 使用
    if llm_config is not None:
        _current_llm_config = llm_config

    # 触发串行处理
    await process_next(project_id)

    return task_id


async def enqueue_batch(
    project_id: str,
    files: list[dict],
    llm_config: dict | None = None,
) -> list[str]:
    """批量入队

    一次性将多个文件加入队列，减少磁盘写入次数。

    Args:
        project_id: 项目 ID（必须与当前活跃项目一致）
        files: 文件列表，每项包含 source_path 和 folder_context
        llm_config: LLM 配置字典
    Returns:
        任务 ID 列表
    Raises:
        ValueError: 项目 ID 与当前活跃项目不匹配
    """
    global _current_llm_config
    if not _current_project_id or _current_project_id != project_id:
        raise ValueError(
            f"enqueue_batch: 项目 {project_id} 不是当前活跃项目"
            f"（当前: {_current_project_id or '<无>'}）"
        )

    ids: list[str] = []
    for f in files:
        ids.append(_upsert_task(project_id, f["source_path"], f.get("folder_context", "")))

    if llm_config is not None:
        _current_llm_config = llm_config

    save_queue(_current_project_path)
    logger.info("[IngestQueue] 批量入队 %d 个文件", len(files))
    await process_next(project_id)

    return ids


async def cancel_task(task_id: str) -> None:
    """取消指定任务

    如果任务正在处理中，则取消当前摄入操作。
    取消后从队列中移除该任务。

    Args:
        task_id: 要取消的任务 ID
    """
    global _processing

    task = next((t for t in _queue if t.id == task_id), None)
    if not task:
        return
    if task.project_id != _current_project_id:
        return

    if task.status == "processing":
        # 取消正在进行的 LLM 调用
        if _current_cancel_event is not None:
            _current_cancel_event.set()
        _processing = False

    # 从队列中移除
    _queue[:] = [t for t in _queue if t.id != task_id]
    save_queue(_current_project_path)
    logger.info("[IngestQueue] 已取消: %s", task.source_path)

    await process_next(_current_project_id)


async def retry_failed(task_id: str) -> None:
    """重试失败的任务

    将指定失败任务的状态重置为 pending，清空错误信息，
    然后触发串行处理。

    Args:
        task_id: 要重试的任务 ID
    """
    task = next((t for t in _queue if t.id == task_id), None)
    if not task:
        return
    if task.project_id != _current_project_id:
        return

    task.status = "pending"
    task.error = None
    save_queue(_current_project_path)
    await process_next(_current_project_id)


async def cancel_all_tasks() -> int:
    """取消所有未完成任务

    中止正在执行的任务，移除所有 pending 和 processing 任务，
    保留 failed 任务供用户查看/重试。

    Returns:
        被移除的任务数量
    """
    global _processing

    # 中止当前任务
    if _current_cancel_event is not None:
        _current_cancel_event.set()
    _processing = False

    before = len(_queue)
    # 仅保留 failed 任务
    _queue[:] = [t for t in _queue if t.status == "failed"]
    removed = before - len(_queue)

    save_queue(_current_project_path)
    logger.info("[IngestQueue] 取消全部: 移除 %d 个任务", removed)
    return removed


def clear_completed_tasks() -> None:
    """清除所有已完成和失败的任务

    仅保留 pending 和 processing 状态的任务。
    """
    _queue[:] = [t for t in _queue if t.status in ("pending", "processing")]
    save_queue(_current_project_path)


def get_queue() -> list[IngestTask]:
    """获取当前队列状态

    Returns:
        任务列表的副本
    """
    return list(_queue)


def get_queue_summary() -> dict[str, int]:
    """获取队列摘要统计

    Returns:
        包含 pending/processing/failed/total 的字典
    """
    return {
        "pending": sum(1 for t in _queue if t.status == "pending"),
        "processing": sum(1 for t in _queue if t.status == "processing"),
        "failed": sum(1 for t in _queue if t.status == "failed"),
        "total": len(_queue),
    }


# ── 项目切换 ──────────────────────────────────────────────────────────────


async def pause_queue() -> None:
    """暂停队列，保存当前项目状态到磁盘

    在切换项目前调用。将 processing 任务回退为 pending，
    持久化队列后清空内存状态。
    """
    global _processing, _current_project_id, _current_project_path

    if not _current_project_id or not _current_project_path:
        return

    paused_path = _current_project_path

    # 中止当前任务
    if _current_cancel_event is not None:
        _current_cancel_event.set()

    _processing = False

    # 将 processing 任务回退为 pending，以便下次恢复时重新执行
    for t in _queue:
        if t.status == "processing":
            t.status = "pending"

    # 持久化到当前项目的磁盘文件
    save_queue(paused_path)

    # 清空内存状态
    _queue.clear()
    _current_project_id = ""
    _current_project_path = ""


async def restore_queue(project_id: str, project_path: str) -> None:
    """恢复队列，从磁盘加载指定项目的任务

    在打开/切换项目时调用。必须先调用 pause_queue() 清空旧状态。

    Args:
        project_id: 项目唯一标识
        project_path: 项目根目录绝对路径
    """
    global _current_project_id, _current_project_path

    pp = os.path.normpath(project_path)

    # 防御性重置内存状态
    _queue.clear()
    _processing  # 仅读取，不修改
    _current_cancel_event  # 仅读取，不修改

    _current_project_id = project_id
    _current_project_path = pp

    saved = load_queue(pp, project_id)
    if not saved:
        return

    _queue.extend(saved)
    save_queue(pp)

    pending_count = sum(1 for t in _queue if t.status == "pending")
    failed_count = sum(1 for t in _queue if t.status == "failed")

    if pending_count > 0:
        logger.info(
            "[IngestQueue] 恢复队列: %d 个待处理, %d 个失败",
            pending_count, failed_count,
        )
        await process_next(project_id)


def clear_queue_state() -> None:
    """清空内存中的队列状态（不写磁盘）

    用于测试环境重置。生产代码应使用 pause_queue()。
    """
    global _processing, _current_project_id, _current_project_path

    if _current_cancel_event is not None:
        _current_cancel_event.set()

    _queue.clear()
    _processing = False
    _current_project_id = ""
    _current_project_path = ""


# ── 串行处理器 ────────────────────────────────────────────────────────────

# 缓存的 LLM 配置，由 enqueue/enqueue_batch 设置
_current_llm_config: dict | None = None


async def process_next(project_id: str) -> None:
    """串行处理下一个待处理任务

    从队列中取出下一个 pending 任务，调用 auto_ingest 执行摄入。
    处理完成后（成功或失败）自动递归处理下一个任务。

    串行保证：同一时刻只有一个任务在处理中。
    过期保护：如果 project_id 与当前活跃项目不一致则跳过。

    Args:
        project_id: 当前项目 ID（用于过期保护）
    """
    global _processing, _current_cancel_event, _last_written_files

    # 串行锁：已有任务在处理中则跳过
    if _processing:
        return

    # 过期保护：项目已切换则跳过
    if _current_project_id != project_id:
        return

    # 查找下一个 pending 任务
    next_task = next(
        (t for t in _queue if t.project_id == project_id and t.status == "pending"),
        None,
    )
    if next_task is None:
        # 队列已排空，无需额外操作
        return

    pp = _current_project_path
    if not pp:
        # 项目路径为空，标记失败
        next_task.status = "failed"
        next_task.error = "项目路径为空，无法执行摄入"
        save_queue(pp)
        return

    # 开始处理
    _processing = True
    next_task.status = "processing"
    save_queue(pp)

    # 再次检查过期
    if _current_project_id != project_id:
        return

    # 检查 LLM 配置
    llm_config = _current_llm_config
    if not llm_config:
        next_task.status = "failed"
        next_task.error = "LLM 未配置 — 请在设置中配置 API Key"
        _processing = False
        save_queue(pp)
        await process_next(project_id)
        return

    # 构建源文件完整路径
    if os.path.isabs(next_task.source_path):
        full_source_path = os.path.normpath(next_task.source_path)
    else:
        full_source_path = os.path.normpath(os.path.join(pp, next_task.source_path))

    pending_remaining = sum(
        1 for t in _queue
        if t.project_id == project_id and t.status == "pending"
    )
    logger.info(
        "[IngestQueue] 处理中: %s (剩余 %d 个待处理)",
        next_task.source_path, pending_remaining,
    )

    # 创建取消事件
    cancel_event = asyncio.Event()
    _current_cancel_event = cancel_event
    _last_written_files = []

    try:
        written_files = await auto_ingest(
            pp,
            full_source_path,
            llm_config,
            signal=cancel_event,
            folder_context=next_task.folder_context,
        )

        # 过期保护：LLM 调用期间项目可能已切换
        if _current_project_id != project_id:
            return

        _last_written_files = written_files

        # 安全检查：auto_ingest 返回空列表意味着未实际产出
        if not written_files:
            raise RuntimeError("摄入未产出任何输出文件")

        # 成功：从队列中移除
        _current_cancel_event = None
        _last_written_files = []
        _queue[:] = [t for t in _queue if t.id != next_task.id]
        save_queue(pp)

        logger.info("[IngestQueue] 完成: %s", next_task.source_path)

    except Exception as err:
        # 过期保护
        if _current_project_id != project_id:
            return

        _current_cancel_event = None
        message = str(err)
        next_task.retry_count += 1
        next_task.error = message

        if next_task.retry_count >= MAX_RETRIES:
            # 超过最大重试次数，标记为失败
            next_task.status = "failed"
            logger.info(
                "[IngestQueue] 失败 (%dx): %s — %s",
                next_task.retry_count, next_task.source_path, message,
            )
        else:
            # 重试：状态回退为 pending
            next_task.status = "pending"
            logger.info(
                "[IngestQueue] 错误 (重试 %d/%d): %s — %s",
                next_task.retry_count, MAX_RETRIES,
                next_task.source_path, message,
            )

        save_queue(pp)

    _processing = False
    await process_next(project_id)
