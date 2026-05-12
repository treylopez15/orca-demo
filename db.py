import os
import sqlite3
import json
from typing import List, Dict, Any, Optional


DB_PATH = os.path.join(os.path.dirname(__file__), "messages.db")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def composite_thread_id(workspace: str, channel_id: str, thread_ts: str) -> str:
    """Primary key for threads: stable across channels."""
    return f"{workspace}:{channel_id}:{thread_ts}"


def _migrate_threads_composite_pk(conn: sqlite3.Connection) -> None:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='threads'")
    if not cur.fetchone():
        return
    cur = conn.execute("SELECT id FROM threads LIMIT 1")
    row = cur.fetchone()
    if not row:
        return
    if str(row["id"]).count(":") >= 2:
        return

    conn.execute("ALTER TABLE threads RENAME TO threads_legacy")
    conn.execute(
        """
        CREATE TABLE threads (
            id TEXT PRIMARY KEY,
            workspace TEXT,
            channel_id TEXT,
            channel_name TEXT,
            thread_ts TEXT,
            text TEXT,
            embedding TEXT,
            url TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO threads (id, workspace, channel_id, channel_name, thread_ts, text, embedding, url)
        SELECT
            COALESCE(workspace, '') || ':' || COALESCE(channel_id, '') || ':' || COALESCE(thread_ts, ''),
            workspace, channel_id, channel_name, thread_ts, text, embedding, url
        FROM threads_legacy
        """
    )
    conn.execute("DROP TABLE threads_legacy")
    conn.execute(
        "INSERT OR REPLACE INTO app_state (key, value) VALUES ('threads_pk_version', '2')"
    )


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS app_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS threads (
                id TEXT PRIMARY KEY,
                workspace TEXT,
                channel_id TEXT,
                channel_name TEXT,
                thread_ts TEXT,
                text TEXT,
                embedding TEXT,
                url TEXT
            )
            """
        )
        conn.commit()
        _migrate_threads_composite_pk(conn)
        conn.execute("DROP TABLE IF EXISTS thread_response_metrics")
        conn.commit()
    finally:
        conn.close()


def insert_thread(
    thread_id: str,
    workspace: str,
    channel_id: str,
    channel_name: str,
    thread_ts: str,
    text: str,
    embedding: Optional[List[float]] = None,
    url: Optional[str] = None,
) -> bool:
    """
    Insert a thread if it does not already exist.
    Returns True if inserted, False if skipped (duplicate).
    """
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO threads (id, workspace, channel_id, channel_name, thread_ts, text, embedding, url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                workspace,
                channel_id,
                channel_name,
                thread_ts,
                text,
                json.dumps(embedding) if embedding is not None else None,
                url,
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_all_threads_with_embeddings() -> List[Dict[str, Any]]:
    conn = get_connection()
    try:
        cur = conn.execute(
            "SELECT id, workspace, channel_id, channel_name, thread_ts, text, embedding, url "
            "FROM threads WHERE embedding IS NOT NULL"
        )
        rows = cur.fetchall()
        result: List[Dict[str, Any]] = []
        for row in rows:
            embedding = json.loads(row["embedding"]) if row["embedding"] else None
            result.append(
                {
                    "id": row["id"],
                    "workspace": row["workspace"],
                    "channel_id": row["channel_id"],
                    "channel_name": row["channel_name"],
                    "thread_ts": row["thread_ts"],
                    "text": row["text"],
                    "embedding": embedding,
                    "url": row["url"],
                }
            )
        return result
    finally:
        conn.close()


def get_latest_thread_ts(channel_id: Optional[str] = None) -> Optional[str]:
    """
    Return the latest thread_ts stored for a channel, or globally if channel_id is None.
    """
    conn = get_connection()
    try:
        if channel_id:
            cur = conn.execute(
                "SELECT MAX(thread_ts) as latest_ts FROM threads WHERE channel_id = ?",
                (channel_id,),
            )
        else:
            cur = conn.execute("SELECT MAX(thread_ts) as latest_ts FROM threads")
        row = cur.fetchone()
        if row and row["latest_ts"]:
            return row["latest_ts"]
        return None
    finally:
        conn.close()


def get_channel_name_map(channel_ids: List[str]) -> Dict[str, str]:
    """
    Best-effort channel_id -> channel_name map from stored threads.
    Uses the most recent non-empty channel_name seen for each channel.
    """
    ids = [c.strip() for c in channel_ids if c and c.strip()]
    if not ids:
        return {}

    placeholders = ",".join(["?"] * len(ids))
    conn = get_connection()
    try:
        cur = conn.execute(
            f"""
            SELECT channel_id, channel_name, MAX(CAST(thread_ts AS REAL)) AS latest_ts
            FROM threads
            WHERE channel_id IN ({placeholders})
              AND channel_name IS NOT NULL
              AND TRIM(channel_name) <> ''
            GROUP BY channel_id
            """,
            ids,
        )
        out: Dict[str, str] = {}
        for row in cur.fetchall():
            cid = str(row["channel_id"] or "").strip()
            name = str(row["channel_name"] or "").strip()
            if cid and name:
                out[cid] = name
        return out
    finally:
        conn.close()
