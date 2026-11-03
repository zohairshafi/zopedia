"""Compaction boundaries must survive a server round-trip."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chat_history_store as store  # noqa: E402

NOW = "2026-11-02T00:00:00+00:00"


def boundary(message_id: str = "compact-1") -> dict:
    return {
        "id": message_id,
        "role": "system",
        "content": "Earlier conversation summary.",
        "subtype": "compact",
        "created_at": NOW,
    }


def test_append_round_trips_subtype(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "chat.db")

    store.append_thread_messages("t1", "zohair", None, NOW, [boundary()])

    messages = store.get_thread_messages("t1", "zohair")
    assert messages[0]["subtype"] == "compact"


def test_upsert_round_trips_subtype(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "chat.db")

    store.upsert_thread("t1", "zohair", None, NOW, NOW, [boundary()])

    messages = store.get_thread_messages("t1", "zohair")
    assert messages[0]["subtype"] == "compact"


def test_migration_adds_subtype_to_existing_table(tmp_path, monkeypatch):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE chat_messages (
            id TEXT NOT NULL,
            thread_id TEXT NOT NULL,
            username TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT,
            reasoning_content TEXT,
            parent_id TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (id, username)
        )
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(store, "DB_PATH", db_path)
    connection = store._get_connection()
    try:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(chat_messages)")
        }
    finally:
        connection.close()

    assert "subtype" in columns
