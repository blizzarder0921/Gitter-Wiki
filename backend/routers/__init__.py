"""
路由模块包

导出所有路由模块供 main.py 挂载使用。
"""

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
)

__all__ = [
    "projects",
    "settings",
    "system",
    "extract",
    "github",
    "translate",
    "graphify",
    "wiki",
    "wiki_chats",
    "wiki_global",
    "wiki_fs",
]
