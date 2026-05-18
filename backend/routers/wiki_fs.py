"""
Wiki 文件系统路由模块

提供全局 Wiki 知识库的文件读写和删除操作。
所有操作基于全局 Wiki 目录（data/global-wiki/wiki/），无项目级隔离。

端点列表：
- GET    /api/wiki-fs — 读取文件内容
- POST   /api/wiki-fs — 保存文件内容
- DELETE /api/wiki-fs — 删除文件
"""

import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from backend.services.wiki.wiki_page_delete import cascade_delete_wiki_page
from backend.config import GLOBAL_WIKI_DIR, GLOBAL_WIKI_WIKI_DIR

router = APIRouter(prefix="/api/wiki-fs", tags=["wiki-fs"])


def _resolve_wiki_path(relative_path: str) -> str:
    """解析全局 Wiki 文件的完整路径

    基于 GLOBAL_WIKI_WIKI_DIR 解析文件路径，
    与 /api/wiki/filetree 返回的路径对齐。

    Args:
        relative_path: 相对于 Wiki 目录的文件路径
    Returns:
        文件的完整路径
    Raises:
        HTTPException: 路径不合法时抛出
    """
    wiki_dir = GLOBAL_WIKI_WIKI_DIR

    # 安全检查：确保路径不会逃逸出 wiki 目录
    full_path = os.path.normpath(os.path.join(wiki_dir, relative_path))
    if not full_path.startswith(os.path.normpath(wiki_dir)):
        raise HTTPException(status_code=403, detail="路径不合法")

    return full_path


@router.get("")
def read_file(path: str = Query(..., description="文件相对路径")):
    """读取全局 Wiki 文件内容

    Args:
        path: 相对于 Wiki 目录的文件路径
    Returns:
        文件内容
    """
    try:
        full_path = _resolve_wiki_path(path)

        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        if os.path.isdir(full_path):
            raise HTTPException(status_code=400, detail="路径是目录，不是文件")

        try:
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
        except UnicodeDecodeError:
            # 二进制文件返回 base64 编码
            import base64
            with open(full_path, "rb") as f:
                content = base64.b64encode(f.read()).decode("ascii")
            return {"content": content, "encoding": "base64", "path": path}

        return {"content": content, "encoding": "utf-8", "path": path}

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"读取文件失败：{str(err)}")


class SaveFileInput(BaseModel):
    """保存文件请求体"""
    path: str
    content: str
    encoding: Optional[str] = "utf-8"


@router.post("")
async def save_file(body: SaveFileInput):
    """保存全局 Wiki 文件内容

    Args:
        body: 包含路径和内容的请求体
    Returns:
        保存结果
    """
    try:
        full_path = _resolve_wiki_path(body.path)

        # 确保父目录存在
        parent_dir = os.path.dirname(full_path)
        os.makedirs(parent_dir, exist_ok=True)

        if body.encoding == "base64":
            import base64
            with open(full_path, "wb") as f:
                f.write(base64.b64decode(body.content))
        else:
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(body.content)

        return {"success": True, "path": body.path}

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"保存文件失败：{str(err)}")


class DeleteFileInput(BaseModel):
    """删除文件请求体"""
    path: str


@router.delete("")
async def delete_file(body: DeleteFileInput):
    """删除全局 Wiki 文件

    对于 wiki 目录下的 .md 文件，执行级联删除：
    删除文件本身、移除向量索引、清理 index.md 引用、
    清理其他页面中的 wikilink 和 related 字段、
    如果是 source 页面则额外清理媒体目录。

    对于非 .md 文件或目录，执行普通删除。

    Args:
        body: 包含路径的请求体
    Returns:
        删除结果
    """
    try:
        full_path = _resolve_wiki_path(body.path)

        if not os.path.exists(full_path):
            raise HTTPException(status_code=404, detail="文件不存在")

        # 判断是否为 wiki 目录下的 .md 文件，需要级联删除
        if full_path.lower().endswith(".md") and os.path.isfile(full_path):
            # 级联清理使用全局 Wiki 根目录
            cascade_delete_wiki_page(GLOBAL_WIKI_DIR, full_path)
        elif os.path.isdir(full_path):
            import shutil
            shutil.rmtree(full_path)
        else:
            os.unlink(full_path)

        return {"success": True, "path": body.path}

    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"删除文件失败：{str(err)}")
