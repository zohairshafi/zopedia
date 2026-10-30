"""Uploads must hand ingestion to the durable server-side queue."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import auth.storage  # noqa: E402
import ingest_queue  # noqa: E402
import main  # noqa: E402
import routes.wiki  # noqa: E402


class FakeUpload:
    filename = "note.txt"

    async def read(self) -> bytes:
        return b"hello"


class FakeForm:
    def __init__(self):
        self._files = {"files": [FakeUpload()]}

    def __iter__(self):
        return iter(self._files)

    def keys(self):
        return self._files.keys()

    def getlist(self, name):
        return self._files.get(name, [])


class FakeRequest:
    async def form(self):
        return FakeForm()


def test_upload_enqueues_raw_ingestion(tmp_path, monkeypatch):
    monkeypatch.setattr(routes.wiki, "_WIKI_VAULT", tmp_path)
    monkeypatch.setattr(main, "_require_valid_subject", _always_local_user)
    monkeypatch.setattr(auth.storage, "user_can_upload_files", lambda subject: True)

    queued = []
    monkeypatch.setattr(
        ingest_queue,
        "enqueue",
        lambda kind, source, dedup=True: queued.append((kind, source)),
    )

    response = asyncio.run(main.upload_file(FakeRequest()))

    assert response["uploaded"] == ["raw/note.txt"]
    assert (tmp_path / "raw" / "note.txt").read_bytes() == b"hello"
    assert queued == [("raw", str(tmp_path / "raw" / "note.txt"))]


async def _always_local_user(_request):
    return "local-user"
