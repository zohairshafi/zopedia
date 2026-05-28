"""Research Mode API routes — SSE streaming for multi-round research."""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from core.llm import wiki_llm_fn
from core.research import (
    ResearchConfig,
    ResearchOrchestrator,
    _research_approvals,
    _research_cancelled,
    _research_sessions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_wiki_dirs():
    """Resolve wiki and raw directories from environment."""
    import os
    wiki_vault = Path(os.getenv("ZOPEDIA_WIKI_VAULT", "./wiki_data")).expanduser()
    return wiki_vault, wiki_vault / "raw"


@router.post("/api/research/stream")
async def research_stream(request: Request):
    """SSE streaming endpoint for Research Mode."""
    body = await request.json()
    topic = body.get("topic", "").strip()
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")

    config = ResearchConfig(
        topic=topic,
        rounds=int(body.get("rounds", 3)),
        sources_per_round=int(body.get("sources_per_round", 10)),
        auto_mode=bool(body.get("auto_mode", False)),
        trusted_sources=list(body.get("trusted_sources", [])),
        blocked_sources=list(body.get("blocked_sources", [])),
        research_depth=str(body.get("research_depth", "standard")),
        source_types=list(body.get("source_types", [])),
    )

    session_id = body.get("session_id", uuid.uuid4().hex[:16])

    wiki_dir, raw_dir = _get_wiki_dirs()
    orchestrator = ResearchOrchestrator(wiki_dir, raw_dir, wiki_llm_fn)

    async def event_generator():
        try:
            async for event in orchestrator.run_research_stream(config, session_id):
                if await request.is_disconnected():
                    _research_cancelled[session_id] = True
                    # Wake up a waiting approval so it doesn't hang forever
                    evt = _research_sessions.get(session_id)
                    if evt:
                        evt.set()
                    break
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("Research stream error")
            yield f"data: {json.dumps({'type': 'research_error', 'message': str(exc)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/api/research/approve")
async def research_approve(request: Request):
    """Submit approved/rejected sources and resume the research stream."""
    body = await request.json()
    session_id = body.get("session_id", "")
    approved_urls = body.get("approved_urls", [])
    rejected_urls = body.get("rejected_urls", [])

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    _research_approvals[session_id] = {
        "approved_urls": approved_urls,
        "rejected_urls": rejected_urls,
    }

    event = _research_sessions.get(session_id)
    if event:
        event.set()

    return {"status": "ok"}


@router.post("/api/research/cancel")
async def research_cancel(request: Request):
    """Cancel a running research session."""
    body = await request.json()
    session_id = body.get("session_id", "")

    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    _research_cancelled[session_id] = True
    event = _research_sessions.get(session_id)
    if event:
        event.set()

    return {"status": "ok"}
