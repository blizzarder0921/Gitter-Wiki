"""
全局 Wiki 对话历史管理路由

提供对话的创建、列表、详情、删除以及消息发送等 API。
适配全局 Wiki 架构，所有接口无需 projectId 参数，
数据库中 project_id 固定为 0（全局 Wiki 标识）。
"""

import json
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.services.project_service import (
    create_wiki_chat,
    get_wiki_chats_by_project_id,
    get_wiki_chat_by_id,
    update_wiki_chat,
    delete_wiki_chat,
    add_wiki_chat_message,
    get_wiki_chat_messages,
)

router = APIRouter(prefix="/api/wiki", tags=["wiki-chats"])

# 全局 Wiki 的固定 project_id
_GLOBAL_PROJECT_ID = 0


def _iso_to_ms(iso_str: str | None) -> int | None:
    """将 ISO 时间字符串转换为 Unix 毫秒时间戳

    Args:
        iso_str: ISO 8601 格式时间字符串
    Returns:
        Unix 毫秒时间戳，解析失败返回 None
    """
    if not iso_str:
        return None
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


# ── 对话管理接口 ──


@router.get("/chats")
def list_chats():
    """获取全局 Wiki 的所有对话列表

    Returns:
        conversations: 对话列表，包含 id/title/createdAt/updatedAt
    """
    try:
        chats = get_wiki_chats_by_project_id(_GLOBAL_PROJECT_ID)
        conversations = []
        for chat in chats:
            conversations.append({
                "id": str(chat["id"]),
                "title": chat["title"],
                "createdAt": _iso_to_ms(chat["created_at"]),
                "updatedAt": _iso_to_ms(chat["updated_at"]),
            })
        return {"conversations": conversations}
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


class CreateChatInput(BaseModel):
    """创建对话请求体"""
    title: Optional[str] = None


@router.post("/chats", status_code=201)
def create_chat(body: CreateChatInput = None):
    """创建新对话

    Args:
        body: 可选的请求体，包含 title
    Returns:
        新创建的对话信息
    """
    try:
        body = body or CreateChatInput()
        title = body.title or "新对话"

        chat = create_wiki_chat(_GLOBAL_PROJECT_ID, title)
        chat = get_wiki_chat_by_id(chat["id"])

        return {
            "id": str(chat["id"]),
            "title": chat["title"],
            "createdAt": _iso_to_ms(chat["created_at"]),
            "updatedAt": _iso_to_ms(chat["updated_at"]),
        }
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.get("/chats/{chatId}")
def get_chat(chatId: int):
    """获取指定对话的消息列表

    Args:
        chatId: 对话 ID
    Returns:
        messages: 该对话下的所有消息
    """
    try:
        chat = get_wiki_chat_by_id(chatId)
        if not chat:
            raise HTTPException(status_code=404, detail="对话不存在")

        messages = get_wiki_chat_messages(chatId)
        display_messages = []
        for msg in messages:
            display_messages.append({
                "id": str(msg["id"]),
                "role": msg["role"],
                "content": msg["content"],
                "timestamp": _iso_to_ms(msg["created_at"]),
                "conversationId": str(chatId),
                "references": json.loads(msg["references_json"]) if msg.get("references_json") else None,
            })

        return {
            "id": str(chat["id"]),
            "title": chat["title"],
            "createdAt": _iso_to_ms(chat["created_at"]),
            "updatedAt": _iso_to_ms(chat["updated_at"]),
            "messages": display_messages,
        }
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


@router.delete("/chats/{chatId}")
def delete_chat(chatId: int):
    """删除指定对话及其所有消息

    Args:
        chatId: 对话 ID
    Returns:
        success: 是否删除成功
    """
    try:
        chat = get_wiki_chat_by_id(chatId)
        if not chat:
            raise HTTPException(status_code=404, detail="对话不存在")

        delete_wiki_chat(chatId)
        return {"success": True}
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


class RenameChatInput(BaseModel):
    """重命名对话请求体"""
    title: str


@router.patch("/chats/{chatId}")
def rename_chat(chatId: int, body: RenameChatInput):
    """重命名对话标题

    Args:
        chatId: 对话 ID
        body: 包含新标题的请求体
    Returns:
        更新后的对话信息
    """
    try:
        chat = get_wiki_chat_by_id(chatId)
        if not chat:
            raise HTTPException(status_code=404, detail="对话不存在")

        updated = update_wiki_chat(chatId, {"title": body.title})
        return {
            "id": str(updated["id"]),
            "title": updated["title"],
            "createdAt": _iso_to_ms(updated["created_at"]),
            "updatedAt": _iso_to_ms(updated["updated_at"]),
        }
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))


# ── 消息保存接口 ──


class SaveMessageInput(BaseModel):
    """保存消息请求体"""
    role: str
    content: str
    references: Optional[list] = None
    answerSources: Optional[list[str]] = None
    sourceFiles: Optional[list[str]] = None


@router.post("/chats/{chatId}/messages", status_code=201)
def save_message(chatId: int, body: SaveMessageInput):
    """保存一条消息到指定对话

    用于前端在流式回复完成后持久化用户/助手消息。

    Args:
        chatId: 对话 ID
        body: 消息内容
    Returns:
        保存后的消息信息
    """
    try:
        chat = get_wiki_chat_by_id(chatId)
        if not chat:
            raise HTTPException(status_code=404, detail="对话不存在")

        # 构建 references_json：合并 answerSources 和 sourceFiles
        refs = {}
        if body.answerSources:
            refs["answerSources"] = body.answerSources
        if body.sourceFiles:
            refs["sourceFiles"] = body.sourceFiles
        if body.references:
            refs["references"] = body.references

        references_json = json.dumps(refs, ensure_ascii=False) if refs else None

        msg = add_wiki_chat_message(chatId, body.role, body.content, references_json)

        return {
            "id": str(msg["id"]),
            "role": msg["role"],
            "content": msg["content"],
            "timestamp": _iso_to_ms(msg["created_at"]),
            "conversationId": str(chatId),
        }
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err))
