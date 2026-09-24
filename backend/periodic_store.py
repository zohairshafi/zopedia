"""Periodic research configuration store — SQLite-backed persistence for
scheduled research jobs and ingested-URL deduplication.

Database lives at ~/.zopedia/periodic_research.db (same auth root as chat history).
"""

from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

from utils.auth_root import get_auth_root

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(get_auth_root(), "periodic_research.db")


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    # Pending trade approvals are written by a background research task while a
    # request handler reads/claims them, so this DB now has genuinely concurrent
    # writers — without a busy timeout that surfaces as "database is locked".
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_tables() -> None:
    conn = _get_conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS periodic_configs (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                topic TEXT NOT NULL,
                config_json TEXT NOT NULL,
                interval_type TEXT NOT NULL CHECK(interval_type IN ('hourly','daily','weekly','monthly')),
                enabled INTEGER DEFAULT 1,
                run_hour INTEGER DEFAULT NULL,
                run_dow INTEGER DEFAULT NULL,
                run_dom INTEGER DEFAULT NULL,
                created_at TEXT NOT NULL,
                last_run_at TEXT,
                next_run_at TEXT
            )
        """)
        # Migrations: add columns if missing from older schema
        for col, col_type in [
            ("run_hour", "INTEGER DEFAULT NULL"),
            ("run_dow", "INTEGER DEFAULT NULL"),
            ("run_dom", "INTEGER DEFAULT NULL"),
            ("thread_id", "TEXT DEFAULT NULL"),
        ]:
            try:
                conn.execute(f"ALTER TABLE periodic_configs ADD COLUMN {col} {col_type}")
                conn.commit()
            except sqlite3.OperationalError:
                pass  # column already exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingested_urls (
                config_id TEXT NOT NULL,
                url TEXT NOT NULL,
                ingested_at TEXT NOT NULL,
                PRIMARY KEY (config_id, url),
                FOREIGN KEY (config_id) REFERENCES periodic_configs(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingested_urls_global (
                url TEXT PRIMARY KEY,
                source_page TEXT NOT NULL DEFAULT '',
                ingested_at TEXT NOT NULL
            )
        """)
        # Orders proposed by a headless research run. These OUTLIVE the run: the
        # run only ever queues, and a human approves later from the app. Nothing
        # here is executed automatically.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_trade_approvals (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                source TEXT NOT NULL,
                config_id TEXT,
                thread_id TEXT,
                order_json TEXT NOT NULL,
                rationale TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                decided_at TEXT,
                result_json TEXT
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_pending_trade_approvals
            ON pending_trade_approvals(username, status, created_at)
        """)
        conn.commit()
    finally:
        conn.close()


def _normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    Handles arXiv /abs/ vs /pdf/ equivalence by extracting just the ID.
    """
    parsed = urlparse(url.strip().lower())
    # arXiv: normalize /abs/ID and /pdf/ID to just the ID
    arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", f"{parsed.netloc}{parsed.path}")
    if arxiv_match:
        return f"arxiv:{arxiv_match.group(1)}"
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"


# -- Config CRUD ---------------------------------------------------------


def create_config(
    username: str,
    topic: str,
    config: dict,
    interval_type: str,
    next_run_at: str,
    run_hour: int | None = None,
    run_dow: int | None = None,
    run_dom: int | None = None,
) -> str:
    """Create a periodic research config. Returns the new config ID."""
    _ensure_tables()
    config_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO periodic_configs (id, username, topic, config_json,
               interval_type, enabled, run_hour, run_dow, run_dom, created_at, next_run_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)""",
            (config_id, username, topic, json.dumps(config), interval_type,
             run_hour, run_dow, run_dom, now, next_run_at),
        )
        conn.commit()
        logger.info("Periodic config created: %s for user %s", config_id, username)
        return config_id
    finally:
        conn.close()


def get_config(config_id: str, username: str) -> dict | None:
    """Get a single periodic config by ID."""
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM periodic_configs WHERE id = ? AND username = ?",
            (config_id, username),
        ).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def list_configs(username: str) -> list[dict]:
    """List all periodic configs for a user."""
    _ensure_tables()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM periodic_configs WHERE username = ? ORDER BY created_at DESC",
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_enabled_configs() -> list[dict]:
    """List all enabled configs across all users (used by scheduler at startup)."""
    _ensure_tables()
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM periodic_configs WHERE enabled = 1"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def update_config(config_id: str, username: str, **fields) -> bool:
    """Update fields on a periodic config. Returns True if row was updated."""
    _ensure_tables()
    allowed = {
        "enabled", "interval_type", "next_run_at", "last_run_at",
        "config_json", "topic", "run_hour", "run_dow", "run_dom",
        "thread_id",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [config_id, username]
    conn = _get_conn()
    try:
        cursor = conn.execute(
            f"UPDATE periodic_configs SET {set_clause} WHERE id = ? AND username = ?",
            values,
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def delete_config(config_id: str, username: str) -> bool:
    """Delete a periodic config. Returns True if deleted."""
    _ensure_tables()
    conn = _get_conn()
    try:
        cursor = conn.execute(
            "DELETE FROM periodic_configs WHERE id = ? AND username = ?",
            (config_id, username),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def mark_run(config_id: str, last_run_at: str, next_run_at: str) -> None:
    """Update timing columns after a run completes."""
    _ensure_tables()
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE periodic_configs SET last_run_at = ?, next_run_at = ? WHERE id = ?",
            (last_run_at, next_run_at, config_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_thread_id(config_id: str) -> str | None:
    """Get the persistent thread ID for a periodic config, if one exists."""
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT thread_id FROM periodic_configs WHERE id = ?", (config_id,),
        ).fetchone()
        return row["thread_id"] if row and row["thread_id"] else None
    finally:
        conn.close()


def set_thread_id(config_id: str, thread_id: str) -> None:
    """Store the thread ID on a periodic config."""
    _ensure_tables()
    conn = _get_conn()
    try:
        conn.execute(
            "UPDATE periodic_configs SET thread_id = ? WHERE id = ?",
            (thread_id, config_id),
        )
        conn.commit()
    finally:
        conn.close()


# -- URL dedup -----------------------------------------------------------


def is_url_already_ingested(config_id: str, url: str) -> bool:
    """Check if a URL has already been ingested for this config."""
    _ensure_tables()
    normalized = _normalize_url(url)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT 1 FROM ingested_urls WHERE config_id = ? AND url = ?",
            (config_id, normalized),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def mark_url_ingested(config_id: str, url: str) -> None:
    """Record a URL as ingested for this config."""
    _ensure_tables()
    normalized = _normalize_url(url)
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO ingested_urls (config_id, url, ingested_at) VALUES (?, ?, ?)",
            (config_id, normalized, now),
        )
        conn.commit()
    finally:
        conn.close()


def mark_urls_ingested(config_id: str, urls: list[str]) -> None:
    """Record multiple URLs as ingested."""
    for url in urls:
        mark_url_ingested(config_id, url)


# -- Global URL dedup (across all ingest methods) ---------------------------


def is_url_globally_ingested(url: str) -> str | None:
    """Return the source_page if this URL was already ingested, or None."""
    _ensure_tables()
    normalized = _normalize_url(url)
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT source_page FROM ingested_urls_global WHERE url = ?",
            (normalized,),
        ).fetchone()
        return row["source_page"] if row else None
    finally:
        conn.close()


def mark_url_globally_ingested(url: str, source_page: str = "") -> None:
    """Record a URL as ingested globally (across all ingest methods).

    Uses UPSERT so later calls with a non-empty *source_page* can
    enrich a row that was first written without one.
    """
    _ensure_tables()
    normalized = _normalize_url(url)
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO ingested_urls_global (url, source_page, ingested_at)
               VALUES (?, ?, ?)
               ON CONFLICT(url) DO UPDATE SET
                   source_page = CASE
                       WHEN excluded.source_page != '' THEN excluded.source_page
                       ELSE source_page
                   END""",
            (normalized, source_page, now),
        )
        conn.commit()
    finally:
        conn.close()


# ── Pending trade approvals ──────────────────────────────────────────
# A headless research run cannot ask for approval (nobody is watching), so it
# queues the order here instead. The row's lifecycle is:
#
#   pending -> approved -> placed | failed     (a human approved it)
#   pending -> rejected                        (a human declined it)
#   pending -> expired                         (nobody decided in time)
#
# Only `place_order` after a successful claim moves money, and the claim is a
# single conditional UPDATE so two concurrent approvals cannot both win.


def create_pending_approval(
    username: str,
    order: dict,
    *,
    rationale: str | None = None,
    source: str = "research",
    config_id: str | None = None,
    thread_id: str | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Queue an order for later approval. Returns the approval id."""
    from core.alpaca_trading import approval_ttl_seconds

    _ensure_tables()
    approval_id = uuid.uuid4().hex[:16]
    now = datetime.now(timezone.utc)
    ttl = approval_ttl_seconds() if ttl_seconds is None else ttl_seconds
    expires_at = datetime.fromtimestamp(now.timestamp() + ttl, tz=timezone.utc)

    conn = _get_conn()
    try:
        conn.execute(
            """INSERT INTO pending_trade_approvals
               (id, username, source, config_id, thread_id, order_json,
                rationale, status, created_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
            (
                approval_id,
                username,
                source,
                config_id,
                thread_id,
                json.dumps(order, ensure_ascii=False, default=str),
                rationale,
                now.isoformat(),
                expires_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return approval_id


def expire_stale_approvals(username: str | None = None) -> int:
    """Mark overdue pending rows expired. Returns how many changed.

    Called lazily on read/claim rather than from a background job, so a row's
    stored status is always accurate by the time anyone looks at it.
    """
    _ensure_tables()
    now = datetime.now(timezone.utc).isoformat()
    conn = _get_conn()
    try:
        if username:
            cur = conn.execute(
                """UPDATE pending_trade_approvals SET status='expired'
                   WHERE status='pending' AND expires_at <= ? AND username = ?""",
                (now, username),
            )
        else:
            cur = conn.execute(
                """UPDATE pending_trade_approvals SET status='expired'
                   WHERE status='pending' AND expires_at <= ?""",
                (now,),
            )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _approval_row_to_dict(row: sqlite3.Row) -> dict:
    out = dict(row)
    try:
        out["order"] = json.loads(out.get("order_json") or "{}")
    except (json.JSONDecodeError, TypeError):
        out["order"] = {}
    if out.get("result_json"):
        try:
            out["result"] = json.loads(out["result_json"])
        except (json.JSONDecodeError, TypeError):
            out["result"] = None
    else:
        out["result"] = None
    return out


def list_pending_approvals(
    username: str, include_resolved: bool = False, limit: int = 100
) -> list[dict]:
    """Pending approvals for a user, newest first. Expires overdue rows first."""
    expire_stale_approvals(username)
    _ensure_tables()
    conn = _get_conn()
    try:
        if include_resolved:
            rows = conn.execute(
                """SELECT * FROM pending_trade_approvals WHERE username = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (username, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM pending_trade_approvals
                   WHERE username = ? AND status = 'pending'
                   ORDER BY created_at DESC LIMIT ?""",
                (username, limit),
            ).fetchall()
        return [_approval_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_approval(approval_id: str, username: str) -> dict | None:
    expire_stale_approvals(username)
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM pending_trade_approvals WHERE id = ? AND username = ?",
            (approval_id, username),
        ).fetchone()
        return _approval_row_to_dict(row) if row else None
    finally:
        conn.close()


def claim_pending_approval(approval_id: str, username: str) -> dict | None:
    """Atomically move a row pending -> approved and return it.

    Returns None when the row is missing, already decided, or expired — in which
    case the caller MUST NOT place an order. This single conditional UPDATE is
    what makes a double-click or a racing approval safe: only one caller can
    observe rowcount == 1.

    `expires_at > now` is re-checked inside the same statement rather than
    relying on the earlier expiry sweep, so a row cannot slip through in the
    window between the sweep and the claim.
    """
    _ensure_tables()
    now = datetime.now(timezone.utc)
    conn = _get_conn()
    try:
        cur = conn.execute(
            """UPDATE pending_trade_approvals
                  SET status = 'approved', decided_at = ?
                WHERE id = ? AND username = ? AND status = 'pending'
                  AND expires_at > ?""",
            (now.isoformat(), approval_id, username, now.isoformat()),
        )
        conn.commit()
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM pending_trade_approvals WHERE id = ? AND username = ?",
            (approval_id, username),
        ).fetchone()
        return _approval_row_to_dict(row) if row else None
    finally:
        conn.close()


# Statuses a row can still move out of. Anything else is terminal and must not
# be rewritten — a placed order must never be re-marked failed by a late call.
_NON_TERMINAL = ("pending", "approved")


def resolve_pending_approval(
    approval_id: str,
    username: str,
    status: str,
    result: dict | None = None,
) -> bool:
    """Record a final status (rejected / placed / failed) with optional result.

    Accepts rows in 'pending' (a rejection straight off the queue) or 'approved'
    (the outcome after a claim and an attempted placement), but never overwrites
    a terminal state.
    """
    _ensure_tables()
    conn = _get_conn()
    try:
        placeholders = ", ".join("?" for _ in _NON_TERMINAL)
        cur = conn.execute(
            f"""UPDATE pending_trade_approvals
                   SET status = ?, decided_at = ?, result_json = ?
                 WHERE id = ? AND username = ? AND status IN ({placeholders})""",
            (
                status,
                datetime.now(timezone.utc).isoformat(),
                json.dumps(result, ensure_ascii=False, default=str) if result else None,
                approval_id,
                username,
                *_NON_TERMINAL,
            ),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def count_pending_approvals(username: str) -> int:
    expire_stale_approvals(username)
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM pending_trade_approvals
               WHERE username = ? AND status = 'pending'""",
            (username,),
        ).fetchone()
        return int(row["c"]) if row else 0
    finally:
        conn.close()


def count_pending_for_run(config_id: str, username: str) -> int:
    """How many orders this run has already queued — used to cap a runaway loop."""
    _ensure_tables()
    conn = _get_conn()
    try:
        row = conn.execute(
            """SELECT COUNT(*) AS c FROM pending_trade_approvals
               WHERE config_id = ? AND username = ? AND created_at >= ?""",
            (
                config_id,
                username,
                datetime.now(timezone.utc).replace(
                    hour=0, minute=0, second=0, microsecond=0
                ).isoformat(),
            ),
        ).fetchone()
        return int(row["c"]) if row else 0
    finally:
        conn.close()
