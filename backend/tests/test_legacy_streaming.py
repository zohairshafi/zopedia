"""Streaming must work when tool retrieval is disabled.

`POST /v1/chat/completions` with `stream: true` used to fall through the
legacy (no-tool-retrieval) branch and return None, which FastAPI serialized as
a literal `null` body. Clients saw an empty stream. These tests pin the SSE
response for that branch without touching the network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routes import chat  # noqa: E402


class FakeRequest:
    def __init__(self, payload: dict):
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


async def _collect(response) -> str:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
    return "".join(chunks)


def _run(payload: dict) -> str:
    response = asyncio.run(chat.openai_chat_completions(FakeRequest(payload)))
    assert response is not None, "streaming returned None (the original bug)"
    return asyncio.run(_collect(response))


def test_legacy_stream_emits_reasoning_text_usage_and_done(monkeypatch):
    monkeypatch.setattr(chat, "_WIKI_TOOL_RETRIEVAL", False)
    monkeypatch.setattr(chat, "llm_available", lambda: True)
    monkeypatch.setattr(chat, "_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT", 0)

    async def fake_stream(messages, **kwargs):
        yield {"type": "reasoning", "content": "think"}
        yield {"type": "text", "content": "hello"}
        yield {"type": "usage", "usage": {"total_tokens": 3}}

    monkeypatch.setattr(chat, "chat_completions_stream", fake_stream)

    body = _run({
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })

    assert '"reasoning_content": "think"' in body
    assert '"content": "hello"' in body
    assert '"total_tokens": 3' in body
    assert body.rstrip().endswith("data: [DONE]")


def test_legacy_stream_emits_error_frame(monkeypatch):
    monkeypatch.setattr(chat, "_WIKI_TOOL_RETRIEVAL", False)
    monkeypatch.setattr(chat, "llm_available", lambda: True)
    monkeypatch.setattr(chat, "_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT", 0)

    async def fake_stream(messages, **kwargs):
        yield {"type": "error", "message": "boom"}

    monkeypatch.setattr(chat, "chat_completions_stream", fake_stream)

    body = _run({
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })

    assert '"error": "boom"' in body
    assert body.rstrip().endswith("data: [DONE]")
