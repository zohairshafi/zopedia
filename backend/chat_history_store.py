"""SQLite-backed server-side chat history store, scoped by username."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

from utils.auth_root import get_auth_root


def _auth_root() -> Path:
    return get_auth_root()


def _ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


DB_PATH = _auth_root() / "chat_history.db"

MESSAGE_CONTENT_MAX_CHARS = 100_000


def _get_connection() -> sqlite3.Connection:
    _ensure_dir(DB_PATH.parent)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_threads (
            id TEXT NOT NULL,
            username TEXT NOT NULL,
            title TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (id, username)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            reasoning_content TEXT,
            parent_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (id, username),
            FOREIGN KEY (thread_id, username) REFERENCES chat_threads(id, username) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_threads_username ON chat_threads(username)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id ON chat_messages(thread_id, username)"
    )
    conn.commit()
    return conn


def _truncate_content(content: str | None) -> str | None:
    if content is None:
        return None
    if len(content) <= MESSAGE_CONTENT_MAX_CHARS:
        return content
    return (
        content[:MESSAGE_CONTENT_MAX_CHARS]
        + f"\n\n...(truncated at {MESSAGE_CONTENT_MAX_CHARS} chars, original: {len(content)} chars)"
    )


def _serialize_content(content: Any) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return _truncate_content(content)
    return _truncate_content(json.dumps(content, ensure_ascii=False))


# ── Threads ──────────────────────────────────────────────────────────


def list_threads(username: str) -> list[dict]:
    conn = _get_connection()
    try:
        cur = conn.execute(
            """
            SELECT t.id, t.title, t.created_at, t.updated_at,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.thread_id = t.id AND m.username = t.username) AS message_count
            FROM chat_threads t
            WHERE t.username = ?
            ORDER BY t.updated_at DESC
            """,
            (username,),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def get_thread(thread_id: str, username: str) -> dict | None:
    conn = _get_connection()
    try:
        cur = conn.execute(
            "SELECT id, title, created_at, updated_at FROM chat_threads WHERE id = ? AND username = ?",
            (thread_id, username),
        )
        row = cur.fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_thread_messages(thread_id: str, username: str) -> list[dict]:
    conn = _get_connection()
    try:
        cur = conn.execute(
            "SELECT id, thread_id, role, content, reasoning_content, parent_id, created_at FROM chat_messages WHERE thread_id = ? AND username = ? ORDER BY created_at ASC",
            (thread_id, username),
        )
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def upsert_thread(
    thread_id: str,
    username: str,
    title: str | None,
    created_at: str,
    updated_at: str,
    messages: list[dict],
) -> None:
    conn = _get_connection()
    try:
        conn.execute(
            """
            INSERT INTO chat_threads (id, username, title, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id, username) DO UPDATE SET
                title = excluded.title,
                created_at = CASE WHEN excluded.created_at < chat_threads.created_at THEN excluded.created_at ELSE chat_threads.created_at END,
                updated_at = excluded.updated_at
            """,
            (thread_id, username, title, created_at, updated_at),
        )
        # Replace all messages for this thread (simpler than diff-based sync)
        conn.execute(
            "DELETE FROM chat_messages WHERE thread_id = ? AND username = ?",
            (thread_id, username),
        )
        for msg in messages:
            conn.execute(
                """
                INSERT INTO chat_messages (id, thread_id, username, role, content, reasoning_content, parent_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.get("id", ""),
                    thread_id,
                    username,
                    msg.get("role", ""),
                    _serialize_content(msg.get("content")),
                    msg.get("reasoning_content"),
                    msg.get("parent_id"),
                    msg.get("created_at", ""),
                ),
            )
        conn.commit()
    finally:
        conn.close()


def delete_thread(thread_id: str, username: str) -> bool:
    conn = _get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM chat_threads WHERE id = ? AND username = ?",
            (thread_id, username),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_all_threads(username: str) -> int:
    conn = _get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM chat_threads WHERE username = ?",
            (username,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()
