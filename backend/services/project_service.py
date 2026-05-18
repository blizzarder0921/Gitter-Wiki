import re
from backend.services.database import get_db


def _row_to_dict(row) -> dict | None:
    if row is None:
        return None
    return dict(row)


def normalize_github_url(url: str) -> str:
    normalized = url.strip().lower()
    normalized = re.sub(r"^https?://", "", normalized)
    normalized = re.sub(r"^git://", "", normalized)
    normalized = re.sub(r"^git@github\.com:", "github.com/", normalized)
    normalized = re.sub(r"\.git$", "", normalized)
    normalized = normalized.rstrip("/")
    return normalized


def get_all_projects() -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [_row_to_dict(r) for r in rows]


def get_project_by_id(project_id: int) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return _row_to_dict(row)


def get_project_by_github_url(github_url: str) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM projects WHERE github_url = ?", (github_url,)).fetchone()
    return _row_to_dict(row)


def get_project_by_normalized_github_url(github_url: str) -> dict | None:
    normalized = normalize_github_url(github_url)
    all_projects = get_all_projects()
    for p in all_projects:
        if p.get("github_url") and normalize_github_url(p["github_url"]) == normalized:
            return p
    return None


def create_project(input_data: dict) -> dict:
    db = get_db()
    cursor = db.execute(
        """INSERT INTO projects (name, description, readme, github_url, local_path, version_type,
           latest_version, current_version, download_url, commit_sha, commit_date, sync_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            input_data["name"],
            input_data.get("description"),
            input_data.get("readme"),
            input_data.get("github_url"),
            input_data.get("local_path"),
            input_data.get("version_type", "none"),
            input_data.get("latest_version"),
            input_data.get("current_version"),
            input_data.get("download_url"),
            input_data.get("commit_sha"),
            input_data.get("commit_date"),
            input_data.get("sync_status", "synced"),
        ),
    )
    db.commit()
    return get_project_by_id(cursor.lastrowid)


def update_project(project_id: int, input_data: dict) -> dict | None:
    db = get_db()
    fields = []
    values = []
    allowed = [
        "name", "description", "readme", "local_path", "version_type",
        "latest_version", "current_version", "download_url", "commit_sha",
        "commit_date", "sync_status", "workflow_status", "last_synced_at",
        "capability_report_path", "capability_generated_at",
    ]
    for key in allowed:
        if key in input_data and input_data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(input_data[key])
    if not fields:
        return get_project_by_id(project_id)
    fields.append("updated_at = datetime('now')")
    values.append(project_id)
    db.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    return get_project_by_id(project_id)


def delete_project(project_id: int) -> bool:
    """删除项目

    Args:
        project_id: 项目 ID

    Returns:
        删除成功返回 True，项目不存在返回 False
    """
    db = get_db()
    try:
        cursor = db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        db.commit()
        return cursor.rowcount > 0
    except Exception:
        db.rollback()
        return False


def get_setting(key: str) -> str | None:
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(key: str, value: str):
    db = get_db()
    db.execute(
        """INSERT INTO settings (key, value, updated_at) VALUES (?, ?, datetime('now'))
           ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = datetime('now')""",
        (key, value),
    )
    db.commit()


def get_all_settings() -> dict[str, str]:
    db = get_db()
    rows = db.execute("SELECT key, value FROM settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def create_wiki_chat(project_id: int, title: str = "New Chat") -> dict:
    db = get_db()
    cursor = db.execute(
        "INSERT INTO wiki_chats (project_id, title) VALUES (?, ?)",
        (project_id, title),
    )
    db.commit()
    row = db.execute("SELECT * FROM wiki_chats WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_dict(row)


def get_wiki_chats_by_project_id(project_id: int) -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM wiki_chats WHERE project_id = ? ORDER BY updated_at DESC", (project_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_wiki_chat_by_id(chat_id: int) -> dict | None:
    db = get_db()
    row = db.execute("SELECT * FROM wiki_chats WHERE id = ?", (chat_id,)).fetchone()
    return _row_to_dict(row)


def update_wiki_chat(chat_id: int, data: dict) -> dict | None:
    db = get_db()
    fields = []
    values = []
    for key in ["title"]:
        if key in data and data[key] is not None:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        return get_wiki_chat_by_id(chat_id)
    fields.append("updated_at = datetime('now')")
    values.append(chat_id)
    db.execute(f"UPDATE wiki_chats SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    return get_wiki_chat_by_id(chat_id)


def delete_wiki_chat(chat_id: int) -> bool:
    db = get_db()
    db.execute("DELETE FROM wiki_chat_messages WHERE chat_id = ?", (chat_id,))
    cursor = db.execute("DELETE FROM wiki_chats WHERE id = ?", (chat_id,))
    db.commit()
    return cursor.rowcount > 0


def add_wiki_chat_message(chat_id: int, role: str, content: str, references_json: str | None = None) -> dict:
    db = get_db()
    cursor = db.execute(
        "INSERT INTO wiki_chat_messages (chat_id, role, content, references_json) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, references_json),
    )
    db.commit()
    row = db.execute("SELECT * FROM wiki_chat_messages WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_dict(row)


def get_wiki_chat_messages(chat_id: int) -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM wiki_chat_messages WHERE chat_id = ? ORDER BY created_at ASC", (chat_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_research_task(project_id: int, topic: str) -> dict:
    db = get_db()
    cursor = db.execute(
        "INSERT INTO wiki_research_tasks (project_id, topic, status) VALUES (?, ?, 'queued')",
        (project_id, topic),
    )
    db.commit()
    row = db.execute("SELECT * FROM wiki_research_tasks WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_dict(row)


def get_research_tasks_by_project_id(project_id: int) -> list[dict]:
    db = get_db()
    rows = db.execute("SELECT * FROM wiki_research_tasks WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def update_research_task(task_id: int, data: dict) -> dict | None:
    db = get_db()
    fields = []
    values = []
    for key in ["status", "progress", "error"]:
        if key in data:
            fields.append(f"{key} = ?")
            values.append(data[key])
    if not fields:
        row = db.execute("SELECT * FROM wiki_research_tasks WHERE id = ?", (task_id,)).fetchone()
        return _row_to_dict(row)
    fields.append("updated_at = datetime('now')")
    values.append(task_id)
    db.execute(f"UPDATE wiki_research_tasks SET {', '.join(fields)} WHERE id = ?", values)
    db.commit()
    row = db.execute("SELECT * FROM wiki_research_tasks WHERE id = ?", (task_id,)).fetchone()
    return _row_to_dict(row)


def create_review_item(project_id: int, data: dict) -> dict:
    db = get_db()
    import json
    cursor = db.execute(
        "INSERT INTO wiki_review_items (project_id, item_type, title, description, source_path, affected_pages, search_queries, options_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            data["item_type"],
            data["title"],
            data.get("description"),
            data.get("source_path"),
            data.get("affected_pages"),
            data.get("search_queries"),
            json.dumps(data["options"]) if data.get("options") else None,
        ),
    )
    db.commit()
    row = db.execute("SELECT * FROM wiki_review_items WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _row_to_dict(row)


def get_review_items_by_project_id(project_id: int, resolved: bool | None = None) -> list[dict]:
    db = get_db()
    if resolved is None:
        rows = db.execute("SELECT * FROM wiki_review_items WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    elif resolved:
        rows = db.execute("SELECT * FROM wiki_review_items WHERE project_id = ? AND resolved = 1 ORDER BY created_at DESC", (project_id,)).fetchall()
    else:
        rows = db.execute("SELECT * FROM wiki_review_items WHERE project_id = ? AND resolved = 0 ORDER BY created_at DESC", (project_id,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def resolve_review_item(item_id: int, action: str) -> dict | None:
    db = get_db()
    db.execute(
        "UPDATE wiki_review_items SET resolved = 1, action = ? WHERE id = ?",
        (action, item_id),
    )
    db.commit()
    row = db.execute("SELECT * FROM wiki_review_items WHERE id = ?", (item_id,)).fetchone()
    return _row_to_dict(row)


# ============================================================
# GitHub 抓取状态与日志相关方法
# ============================================================


def get_github_fetch_status(project_id: int) -> dict | None:
    """获取项目的 GitHub 资源抓取状态

    Args:
        project_id: 项目 ID

    Returns:
        包含 github_fetch_status / github_issues_fetched_at / github_releases_fetched_at /
        github_prs_fetched_at / github_commits_fetched_at / github_community_fetched_at /
        github_docs_fetched_at 的字典，项目不存在时返回 None
    """
    db = get_db()
    row = db.execute(
        """SELECT github_fetch_status, github_issues_fetched_at, github_releases_fetched_at,
                  github_prs_fetched_at, github_commits_fetched_at, github_community_fetched_at,
                  github_docs_fetched_at, github_branches_fetched_at
           FROM projects WHERE id = ?""",
        (project_id,),
    ).fetchone()
    return _row_to_dict(row)


def update_github_fetch_status(project_id: int, status: str, **kwargs) -> bool:
    """更新项目的 GitHub 抓取状态

    Args:
        project_id: 项目 ID
        status: 抓取状态，可选值为 pending / fetching / completed / partial / failed
        **kwargs: 可选的时间戳字段，如 github_issues_fetched_at、github_releases_fetched_at 等

    Returns:
        更新成功返回 True，项目不存在返回 False
    """
    db = get_db()
    # 允许更新的时间戳字段白名单
    allowed_ts_fields = [
        "github_issues_fetched_at",
        "github_releases_fetched_at",
        "github_prs_fetched_at",
        "github_commits_fetched_at",
        "github_community_fetched_at",
        "github_docs_fetched_at",
        "github_branches_fetched_at",
    ]
    fields = ["github_fetch_status = ?"]
    values = [status]
    for key in allowed_ts_fields:
        if key in kwargs and kwargs[key] is not None:
            fields.append(f"{key} = ?")
            values.append(kwargs[key])
    fields.append("updated_at = datetime('now')")
    values.append(project_id)
    cursor = db.execute(
        f"UPDATE projects SET {', '.join(fields)} WHERE id = ?", values
    )
    db.commit()
    return cursor.rowcount > 0


def parse_github_url(github_url: str) -> tuple[str, str] | None:
    """从 GitHub URL 中解析出 owner 和 repo

    支持 https://github.com/owner/repo 格式，也兼容带 .git 后缀和尾部斜杠的情况。

    Args:
        github_url: GitHub 仓库 URL

    Returns:
        (owner, repo) 元组，解析失败返回 None
    """
    if not github_url:
        return None
    # 匹配 github.com/owner/repo 格式，忽略协议和尾部内容
    match = re.match(
        r"(?:https?://|git://|git@github\.com:)?github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$",
        github_url.strip(),
    )
    if match:
        return (match.group(1), match.group(2))
    return None
