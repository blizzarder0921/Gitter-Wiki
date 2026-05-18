import sqlite3
import os
from backend.config import DB_PATH, DATA_DIR

_connection: sqlite3.Connection | None = None


def get_db() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        _connection = sqlite3.connect(DB_PATH, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        _connection.execute("PRAGMA journal_mode=WAL")
        _init_db(_connection)
        _migrate_db(_connection)
    return _connection


def _init_db(db: sqlite3.Connection):
    db.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            description     TEXT,
            readme          TEXT,
            github_url      TEXT,
            local_path      TEXT,
            version_type    TEXT DEFAULT 'none',
            latest_version  TEXT,
            current_version TEXT,
            download_url    TEXT,
            commit_sha      TEXT,
            commit_date     TEXT,
            sync_status     TEXT DEFAULT 'synced',
            workflow_status TEXT DEFAULT 'idle',
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now')),
            last_synced_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS settings (
            key             TEXT PRIMARY KEY,
            value           TEXT NOT NULL,
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS wiki_chats (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id        INTEGER NOT NULL,
            title             TEXT DEFAULT 'New Chat',
            created_at        TEXT DEFAULT (datetime('now')),
            updated_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS wiki_chat_messages (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id           INTEGER NOT NULL REFERENCES wiki_chats(id) ON DELETE CASCADE,
            role              TEXT NOT NULL,
            content           TEXT,
            references_json   TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS wiki_research_tasks (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id        INTEGER NOT NULL,
            topic             TEXT NOT NULL,
            status            TEXT DEFAULT 'queued',
            progress          TEXT,
            error             TEXT,
            created_at        TEXT DEFAULT (datetime('now')),
            updated_at        TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS wiki_review_items (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id        INTEGER NOT NULL,
            item_type         TEXT NOT NULL,
            title             TEXT NOT NULL,
            description       TEXT,
            source_path       TEXT,
            affected_pages    TEXT,
            search_queries    TEXT,
            options_json      TEXT,
            action            TEXT,
            resolved          BOOLEAN DEFAULT 0,
            created_at        TEXT DEFAULT (datetime('now'))
        );

    """)


def _migrate_db(db: sqlite3.Connection):
    cursor = db.execute("PRAGMA table_info(projects)")
    columns = {row[1] for row in cursor.fetchall()}

    if "current_version" not in columns:
        db.execute("ALTER TABLE projects ADD COLUMN current_version TEXT")
    if "sync_status" not in columns:
        db.execute("ALTER TABLE projects ADD COLUMN sync_status TEXT DEFAULT 'synced'")

    col_info = db.execute("PRAGMA table_info(projects)").fetchall()
    github_col = next((c for c in col_info if c[1] == "github_url"), None)
    if github_col and github_col[3] == 1:
        db.executescript("""
            CREATE TABLE projects_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                description     TEXT,
                readme          TEXT,
                github_url      TEXT,
                local_path      TEXT,
                version_type    TEXT DEFAULT 'none',
                latest_version  TEXT,
                current_version TEXT,
                download_url    TEXT,
                commit_sha      TEXT,
                commit_date     TEXT,
                sync_status     TEXT DEFAULT 'synced',
                workflow_status TEXT DEFAULT 'idle',
                created_at      TEXT DEFAULT (datetime('now')),
                updated_at      TEXT DEFAULT (datetime('now')),
                last_synced_at  TEXT
            );
            INSERT INTO projects_new (id, name, description, readme, github_url, local_path, version_type, latest_version, current_version, download_url, commit_sha, commit_date, sync_status, workflow_status, created_at, updated_at, last_synced_at)
            SELECT id, name, description, readme, NULLIF(github_url, ''), local_path, version_type, latest_version, current_version, download_url, commit_sha, commit_date, sync_status, workflow_status, created_at, updated_at, last_synced_at
            FROM projects;
            DROP TABLE projects;
            ALTER TABLE projects_new RENAME TO projects;
        """)

    wiki_tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'wiki_%'").fetchall()}
    if "wiki_chats" not in wiki_tables:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS wiki_chats (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id        INTEGER NOT NULL,
                title             TEXT DEFAULT 'New Chat',
                created_at        TEXT DEFAULT (datetime('now')),
                updated_at        TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS wiki_chat_messages (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id           INTEGER NOT NULL REFERENCES wiki_chats(id) ON DELETE CASCADE,
                role              TEXT NOT NULL,
                content           TEXT,
                references_json   TEXT,
                created_at        TEXT DEFAULT (datetime('now'))
            );
        """)
    if "wiki_research_tasks" not in wiki_tables:
        db.execute("""
            CREATE TABLE IF NOT EXISTS wiki_research_tasks (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id        INTEGER NOT NULL,
                topic             TEXT NOT NULL,
                status            TEXT DEFAULT 'queued',
                progress          TEXT,
                error             TEXT,
                created_at        TEXT DEFAULT (datetime('now')),
                updated_at        TEXT DEFAULT (datetime('now'))
            );
        """)
    if "wiki_review_items" not in wiki_tables:
        db.execute("""
            CREATE TABLE IF NOT EXISTS wiki_review_items (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id        INTEGER NOT NULL,
                item_type         TEXT NOT NULL,
                title             TEXT NOT NULL,
                description       TEXT,
                source_path       TEXT,
                affected_pages    TEXT,
                search_queries    TEXT,
                options_json      TEXT,
                action            TEXT,
                resolved          BOOLEAN DEFAULT 0,
                created_at        TEXT DEFAULT (datetime('now'))
            );
        """)

    chat_indexes = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_wiki_chat%'").fetchall()}
    if "idx_wiki_chats_project_id" not in chat_indexes:
        db.execute("CREATE INDEX IF NOT EXISTS idx_wiki_chats_project_id ON wiki_chats(project_id)")
    if "idx_wiki_chat_messages_chat_id" not in chat_indexes:
        db.execute("CREATE INDEX IF NOT EXISTS idx_wiki_chat_messages_chat_id ON wiki_chat_messages(chat_id)")
    if "idx_wiki_research_tasks_project_id" not in chat_indexes:
        db.execute("CREATE INDEX IF NOT EXISTS idx_wiki_research_tasks_project_id ON wiki_research_tasks(project_id)")
    if "idx_wiki_review_items_project_id" not in chat_indexes:
        db.execute("CREATE INDEX IF NOT EXISTS idx_wiki_review_items_project_id ON wiki_review_items(project_id)")

    # ---- projects 表新增 GitHub 抓取相关字段 ----
    proj_cols = {row[1] for row in db.execute("PRAGMA table_info(projects)").fetchall()}
    if "github_issues_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_issues_fetched_at TEXT")
    if "github_releases_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_releases_fetched_at TEXT")
    if "github_prs_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_prs_fetched_at TEXT")
    if "github_commits_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_commits_fetched_at TEXT")
    if "github_community_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_community_fetched_at TEXT")
    if "github_docs_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_docs_fetched_at TEXT")
    if "github_branches_fetched_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_branches_fetched_at TEXT")
    if "github_fetch_status" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN github_fetch_status TEXT DEFAULT 'pending'")
    if "workflow_status" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN workflow_status TEXT DEFAULT 'idle'")

    # ---- 全局 Wiki 架构升级：新增能力报告字段 ----
    if "capability_report_path" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN capability_report_path TEXT")
    if "capability_generated_at" not in proj_cols:
        db.execute("ALTER TABLE projects ADD COLUMN capability_generated_at TEXT")

    # ---- 全局 Wiki 架构升级：删除旧的项目级 Wiki 表 ----
    db.executescript("""
        DROP TABLE IF EXISTS wiki_projects;
        DROP TABLE IF EXISTS wiki_ingest_logs;
        DROP TABLE IF EXISTS wiki_health_snapshots;
        DROP TABLE IF EXISTS github_fetch_logs;
    """)
