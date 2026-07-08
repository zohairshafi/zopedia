"""Scheduled maintenance config store — SQLite-backed persistence for
wiki maintenance schedules.

Shares the periodic_research.db database (adding a scheduled_maintenance table).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone

from utils.auth_root import get_auth_root

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(get_auth_root(), "periodic_research.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _ensure_tables() -> None:
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scheduled_maintenance (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                interval_type TEXT NOT NULL
                    CHECK(interval_type IN ('hourly','daily','weekly','monthly')),
                run_hour INTEGER DEFAULT NULL,
                run_dow INTEGER DEFAULT NULL,
                run_dom INTEGER DEFAULT NULL,
                with_web_fill INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_run_at TEXT,
                next_run_at TEXT
            )
        """)
        conn.commit()
    finally:
        conn.close()


# ── CRUD ────────────────────────────────────────────────────────────────


def create_schedule(
    username: str,
    interval_type: str,
    with_web_fill: bool,
    next_run_at: str,
    run_hour: int | None = None,
    run_dow: int | None = None,
    run_dom: int | None = None,
) -> str:
    _ensure_tables()
    sid = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO scheduled_maintenance
               (id, username, enabled, interval_type, with_web_fill,
                run_hour, run_dow, run_dom, created_at, next_run_at)
               VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)""",
            (sid, username, interval_type, int(with_web_fill),
             run_hour, run_dow, run_dom, now, next_run_at),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def list_schedules(username: str) -> list[dict]:
    _ensure_tables()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM scheduled_maintenance WHERE username = ? ORDER BY created_at DESC",
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_schedule(sid: str, username: str) -> dict | None:
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM scheduled_maintenance WHERE id = ? AND username = ?",
            (sid, username),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def update_schedule(sid: str, username: str, **kwargs) -> bool:
    _ensure_tables()
    allowed = {
        "enabled", "interval_type", "with_web_fill",
        "run_hour", "run_dow", "run_dom",
        "next_run_at", "last_run_at",
    }
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [sid, username]
    conn = _get_conn()
    try:
        cur = conn.execute(
            f"UPDATE scheduled_maintenance SET {set_clause} WHERE id = ? AND username = ?",
            values,
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def delete_schedule(sid: str, username: str) -> bool:
    _ensure_tables()
    conn = _get_conn()
    try:
        cur = conn.execute(
            "DELETE FROM scheduled_maintenance WHERE id = ? AND username = ?",
            (sid, username),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_due() -> list[dict]:
    """All enabled schedules whose next_run_at is <= now."""
    _ensure_tables()
    conn = _get_conn()
    try:
        now = datetime.now(timezone.utc).isoformat()
        rows = conn.execute(
            "SELECT * FROM scheduled_maintenance WHERE enabled = 1 AND next_run_at <= ?",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
