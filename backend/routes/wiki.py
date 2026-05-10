"""Wiki management routes for Zopedia."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.wiki.engine import LLMWikiEngine, WikiConfig
from core.wiki.manager import WikiManager
from core.wiki.ingestor import WikiIngestor
from core.wiki.watcher import WikiIngestionWatcher
from core.wiki.runtime_env import (
    WIKI_ENV_SPECS,
    collect_wiki_env_state,
    update_wiki_env_values,
    wiki_env_overrides_file,
)
from core.llm import wiki_llm_fn, llm_available
from models.wiki import (
    RagContextDebugRequest,
    RagContextDebugResponse,
    RagContextSnippet,
    WikiAnalysisBacklinksRequest,
    WikiAnalysisBacklinksResponse,
    WikiArchiveRequest,
    WikiArchiveResponse,
    WikiChatHistorySaveRequest,
    WikiChatHistorySaveResponse,
    WikiDataGraphEdge,
    WikiDataGraphNode,
    WikiDataGraphResponse,
    WikiDeleteApplyRequest,
    WikiDeletePreviewRequest,
    WikiDeleteResponse,
    WikiEnrichRequest,
    WikiEnrichResponse,
    WikiEnvConfigResponse,
    WikiEnvSetRequest,
    WikiEnvSetResponse,
    WikiGraphifyExportRequest,
    WikiGraphifyExportResponse,
    WikiIngestRequest,
    WikiIngestResponse,
    WikiLintResponse,
    WikiMergeMaintenanceRequest,
    WikiMergeMaintenanceResponse,
    WikiQueryRequest,
    WikiQueryResponse,
    WikiRetryFallbackRequest,
    WikiRetryFallbackResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Environment config ─────────────────────────────────────────────

_RE = re

def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()

def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    return val in {"1", "true", "yes", "on"} if val else default

def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default

_WIKI_VAULT = Path(_env_str("ZOPEDIA_WIKI_VAULT", "./wiki_data")).expanduser()
_WIKI_WATCHER_ENABLED = _env_bool("ZOPEDIA_WIKI_WATCHER", True)
_WIKI_AUTO_QUERY_ON_INGEST = _env_bool("ZOPEDIA_WIKI_AUTO_QUERY_ON_INGEST", True)
_WIKI_AUTO_QUERY_CHAT_HISTORY = _env_bool("ZOPEDIA_WIKI_AUTO_QUERY_CHAT_HISTORY", False)
_WIKI_AUTO_LINT_EVERY = _env_int("ZOPEDIA_WIKI_AUTO_LINT_EVERY", 10)
_WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES = _env_int("ZOPEDIA_WIKI_AUTO_RETRY_FALLBACK_ANALYSES_MAX_PAGES", 24)
_WIKI_RAG_MAX_PAGES = _env_int("ZOPEDIA_WIKI_RAG_MAX_PAGES", 8)
_WIKI_RAG_MAX_CHARS_PER_PAGE = _env_int("ZOPEDIA_WIKI_RAG_MAX_CHARS_PER_PAGE", 1800)
_WIKI_RAG_MAX_TOTAL_CHARS = _env_int("ZOPEDIA_WIKI_RAG_MAX_TOTAL_CHARS", 12000)
_WIKI_RAG_INCLUDE_SOURCE_PAGES = _env_bool("ZOPEDIA_WIKI_RAG_INCLUDE_SOURCE_PAGES", True)
_WIKI_LOG_INJECTED_CONTEXT = _env_bool("ZOPEDIA_WIKI_LOG_INJECTED_CONTEXT", True)
_WIKI_LOG_INJECTED_CONTEXT_MAX_CHARS = _env_int("ZOPEDIA_WIKI_LOG_INJECTED_CONTEXT_MAX_CHARS", 12000)
_WIKI_PENDING_INGEST_INTERVAL_SECONDS = _env_int("ZOPEDIA_WIKI_PENDING_INGEST_INTERVAL_SECONDS", 45)
_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT = _env_int("ZOPEDIA_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT", 1)

# ── Global state ───────────────────────────────────────────────────

_ROUTE_WIKI_MANAGER: Optional[WikiManager] = None
_ROUTE_WIKI_INGESTOR: Optional[WikiIngestor] = None
_ROUTE_WIKI_WATCHER: Optional[WikiIngestionWatcher] = None
_WIKI_QUERY_RUN_COUNT: int = 0
_LAST_PENDING_RAW_INGEST_AT: Optional[float] = None
_LAST_RAG_DEBUG: Optional[dict[str, Any]] = None


def get_wiki_components() -> tuple[WikiManager, WikiIngestor]:
    global _ROUTE_WIKI_MANAGER, _ROUTE_WIKI_INGESTOR
    if _ROUTE_WIKI_MANAGER is None or _ROUTE_WIKI_INGESTOR is None:
        _ROUTE_WIKI_MANAGER = WikiManager.create(_WIKI_VAULT, wiki_llm_fn)
        _ROUTE_WIKI_INGESTOR = WikiIngestor(_ROUTE_WIKI_MANAGER, _WIKI_VAULT / "raw")
    return _ROUTE_WIKI_MANAGER, _ROUTE_WIKI_INGESTOR


# ── Auth dependency (override in main.py for optional auth) ────────

async def _optional_subject(request: Request) -> str:
    get_current = getattr(request.app.state, "get_current_subject", None)
    if get_current is not None:
        return await get_current(request)
    return "local-user"


# ── Helpers ────────────────────────────────────────────────────────

def _live_route_rag_limits() -> tuple[int, int, int, bool]:
    return (_WIKI_RAG_MAX_PAGES, _WIKI_RAG_MAX_CHARS_PER_PAGE, _WIKI_RAG_MAX_TOTAL_CHARS, _WIKI_RAG_INCLUDE_SOURCE_PAGES)


def _looks_like_history_intent(query: str) -> bool:
    q = query.lower().strip()
    patterns = [
        r"\bwhat (?:have|did) (?:i|we|you) ", r"\brecall\b", r"\bprevious\b",
        r"\bhistory\b", r"\b(?:earlier|before|prior|last)\s+(?:chat|conversation|message)",
        r"\b(?:my|our) (?:previous|last|earlier) (?:chat|conversation|message)",
        r"\b(?:do you|you) remember\b", r"\bwhat did (?:we|i) (?:just|say|talk|discuss)",
        r"\b(?:previous|prior|past|earlier) (?:discussion|conversation|topic)",
    ]
    return any(_RE.search(p, q) for p in patterns)


def _ingest_pending_raw_files(max_files: int = 8, respect_interval_gate: bool = True) -> list[dict[str, Any]]:
    global _LAST_PENDING_RAW_INGEST_AT
    if respect_interval_gate and _WIKI_PENDING_INGEST_INTERVAL_SECONDS > 0 and _LAST_PENDING_RAW_INGEST_AT:
        elapsed = time.time() - _LAST_PENDING_RAW_INGEST_AT
        if elapsed < _WIKI_PENDING_INGEST_INTERVAL_SECONDS:
            return []
    _, ingestor = get_wiki_components()
    results = ingestor.ingest_pending_raw_files(max_files=max_files, contributor="Zopedia")
    _LAST_PENDING_RAW_INGEST_AT = time.time()
    return results


def _loggable_rag_context(context: str) -> str:
    if _WIKI_LOG_INJECTED_CONTEXT_MAX_CHARS <= 0:
        return context
    if len(context) <= _WIKI_LOG_INJECTED_CONTEXT_MAX_CHARS:
        return context
    return context[:_WIKI_LOG_INJECTED_CONTEXT_MAX_CHARS].rstrip() + "\n...[truncated]"


def _to_rag_debug_response(payload: dict[str, Any]) -> RagContextDebugResponse:
    source = str(payload.get("source", "live-query"))
    if source not in {"live-query", "last-request"}:
        source = "live-query"
    selected = [
        RagContextSnippet(page=str(item.get("page", "unknown")), score=float(item.get("score", 0.0)), snippet=str(item.get("snippet", "")))
        for item in payload.get("selected", [])
    ]
    applied_limits = payload.get("applied_limits", {})
    if not isinstance(applied_limits, dict):
        applied_limits = {}
    return RagContextDebugResponse(
        query=str(payload.get("query", "")),
        source=source,
        wants_history=bool(payload.get("wants_history", False)),
        context=str(payload.get("context", "")),
        context_characters=int(payload.get("context_characters", 0)),
        pages_considered=int(payload.get("pages_considered", 0)),
        selected=selected,
        applied_limits=applied_limits,
        generated_at=str(payload.get("generated_at", "")),
    )


def _get_route_rag_context(
    query: str,
    *,
    return_debug: bool = False,
    max_pages_override: Optional[int] = None,
    max_chars_per_page_override: Optional[int] = None,
    max_total_chars_override: Optional[int] = None,
    debug_source: str = "live-query",
) -> str | tuple[str, dict[str, Any]]:
    manager, _ = get_wiki_components()
    query_lower = query.lower()
    live_max_pages, live_max_chars_per_page, live_max_total_chars, include_source_pages = _live_route_rag_limits()

    max_pages = live_max_pages if max_pages_override is None else int(max_pages_override)
    max_chars_per_page = live_max_chars_per_page if max_chars_per_page_override is None else int(max_chars_per_page_override)
    max_total_chars = live_max_total_chars if max_total_chars_override is None else int(max_total_chars_override)
    max_pages = max(1, min(max_pages, 64))
    max_chars_per_page = max(200, min(max_chars_per_page, 120000))
    max_total_chars = max(500, min(max_total_chars, 500000))

    wants_history = _looks_like_history_intent(query)
    result = manager.retrieve_context(query, max_pages=max(max_pages * 4, 12), max_chars_per_page=max(max_chars_per_page * 6, 6000), include_source_pages=include_source_pages)
    ranking_mode = str(result.get("ranking_mode", "unknown") or "unknown")
    blocks: list[dict] = result.get("context_blocks", [])

    if not include_source_pages:
        blocks = [b for b in blocks if not str(b.get("page", "")).lower().startswith("sources/")]

    query_terms = [t for t in _RE.findall(r"[a-zA-Z0-9]{3,}", query_lower) if t not in {
        "the", "and", "for", "with", "that", "this", "what", "when", "where", "who",
        "why", "how", "from", "into", "about", "tell", "please", "using", "wiki", "context", "only",
    }]

    def _block_hit_score(block: dict) -> int:
        page = str(block.get("page", "")).lower()
        content = str(block.get("content", "")).lower()
        sample = content[:4000]
        if not query_terms:
            return 0
        return sum(sample.count(t) + page.count(t) * 3 for t in query_terms)

    if wants_history:
        chat_blocks = [b for b in blocks if "chat-history" in str(b.get("page", "")).lower()]
        non_chat = [b for b in blocks if "chat-history" not in str(b.get("page", "")).lower()]
        blocks = (chat_blocks + non_chat)[:max_pages]

        sources_dir = _WIKI_VAULT / "wiki" / "sources"
        if include_source_pages and sources_dir.exists():
            history_files = sorted([p for p in sources_dir.glob("chat-history-*.md")], key=lambda p: p.stat().st_mtime, reverse=True)
            hint_terms = [t for t in _RE.findall(r"[A-Za-z]{2,}-[A-Za-z0-9]{2,}", query) if len(t) >= 5]
            selected: list[dict] = []
            for p in history_files:
                text = p.read_text(encoding="utf-8", errors="ignore")
                if hint_terms and not any(h.lower() in text.lower() for h in hint_terms):
                    continue
                selected.append({"page": f"sources/{p.stem}.md", "score": 1.0, "content": text})
                if len(selected) >= max_pages:
                    break
            if not selected:
                for p in history_files[:max_pages]:
                    selected.append({"page": f"sources/{p.stem}.md", "score": 1.0, "content": p.read_text(encoding="utf-8", errors="ignore")})
            if selected:
                blocks = selected
    else:
        rerank_enabled = bool(manager.engine.cfg.ranking_llm_rerank_enabled)
        if rerank_enabled:
            blocks = blocks[:max_pages]
        else:
            chat_blocks = [b for b in blocks if "chat-history" in str(b.get("page", "")).lower()]
            non_chat_blocks = [b for b in blocks if "chat-history" not in str(b.get("page", "")).lower()]
            blocks = list(non_chat_blocks)
            best_hit = max((_block_hit_score(b) for b in non_chat_blocks), default=0)
            if best_hit <= 0:
                candidate = sorted([b for b in chat_blocks if _block_hit_score(b) > 0], key=_block_hit_score, reverse=True)
                blocks = candidate + blocks
            blocks = blocks[:max_pages]

    if not blocks and not wants_history and include_source_pages:
        sources_dir = _WIKI_VAULT / "wiki" / "sources"
        if sources_dir.exists() and any(x in query_lower for x in ("resume", ".pdf", "document")):
            candidates = sorted([p for p in sources_dir.glob("*.md") if "chat-history" not in p.name.lower()], key=lambda p: p.stat().st_mtime, reverse=True)
            for p in candidates[:max_pages]:
                blocks.append({"page": f"sources/{p.stem}.md", "score": 1.0, "content": p.read_text(encoding="utf-8", errors="ignore")})

    if not include_source_pages:
        blocks = [b for b in blocks if not str(b.get("page", "")).lower().startswith("sources/")]

    def _select_snippet(page: str, content: str) -> str:
        content = str(content)
        if str(page).lower().startswith("analysis/"):
            answer_match = _RE.search(r"(?ms)^## Answer\n(.+?)(?=\n## |\Z)", content)
            if answer_match:
                answer_text = answer_match.group(1).strip()
                if answer_text:
                    content = answer_text
        if len(content) <= max_chars_per_page:
            return content
        terms = [t for t in _RE.findall(r"[a-zA-Z0-9]{2,}", query_lower) if t not in {
            "a", "an", "and", "as", "at", "by", "for", "from", "how", "in", "is", "it",
            "of", "on", "or", "that", "the", "this", "to", "what", "which", "who", "why",
            "wiki", "context", "only", "with",
        }]
        lowered = content.lower()
        for term in terms:
            idx = lowered.find(term)
            if idx >= 0:
                half = max_chars_per_page // 2
                start = max(0, idx - half)
                end = min(len(content), start + max_chars_per_page)
                start = max(0, end - max_chars_per_page)
                return content[start:end]
        return content[:max_chars_per_page]

    context_parts = []
    for block in blocks:
        page = block.get("page", "unknown")
        score = float(block.get("score", 0.0))
        content = _select_snippet(page, block.get("content", ""))
        context_parts.append(f"PAGE: {page}\nSCORE: {score:.4f}\nCONTENT:\n{content}")
    context = "\n\n---\n\n".join(context_parts)
    if len(context) > max_total_chars:
        context = context[:max_total_chars].rstrip() + "\n..."

    debug_payload: dict[str, Any] = {
        "query": query,
        "source": debug_source,
        "wants_history": wants_history,
        "include_source_pages": bool(include_source_pages),
        "ranking_mode": ranking_mode,
        "context": context,
        "context_characters": len(context),
        "pages_considered": len(blocks),
        "selected": [{"page": str(b.get("page", "unknown")), "score": float(b.get("score", 0.0)), "snippet": _select_snippet(str(b.get("page", "unknown")), b.get("content", ""))} for b in blocks],
        "applied_limits": {"max_pages": max_pages, "max_chars_per_page": max_chars_per_page, "max_total_chars": max_total_chars},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    if return_debug:
        return context, debug_payload
    return context


# ── RAG Debug Endpoints ────────────────────────────────────────────

@router.post("/rag/debug/context", response_model=RagContextDebugResponse)
async def debug_rag_context(payload: RagContextDebugRequest, current_subject: str = Depends(_optional_subject)):
    if payload.include_pending_raw:
        _ingest_pending_raw_files(respect_interval_gate=False)
    _, debug_payload = _get_route_rag_context(payload.query, return_debug=True, max_pages_override=payload.max_pages, max_chars_per_page_override=payload.max_chars_per_page, max_total_chars_override=payload.max_total_chars, debug_source="live-query")
    return _to_rag_debug_response(debug_payload)


@router.get("/rag/debug/last", response_model=RagContextDebugResponse)
async def debug_rag_last_request(current_subject: str = Depends(_optional_subject)):
    if not _LAST_RAG_DEBUG:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No RAG debug record available yet.")
    return _to_rag_debug_response(_LAST_RAG_DEBUG)


# ── Wiki Archive ───────────────────────────────────────────────────

def _extract_source_ref(source_page: Path) -> Optional[str]:
    text = source_page.read_text(encoding="utf-8", errors="ignore")
    match = _RE.search(r"(?mi)^source_ref:\s*(.+?)\s*$", text)
    return match.group(1).strip() if match else None


def _source_identity_key(source_page: Path, source_ref: Optional[str], raw_dir: Path) -> str:
    if not source_ref:
        return source_page.stem
    normalized_ref = source_ref.strip().replace("\\", "/")
    if not normalized_ref:
        return source_page.stem
    try:
        raw_root = raw_dir.resolve()
        ref_path = Path(source_ref).expanduser()
        if ref_path.exists():
            resolved_ref = ref_path.resolve()
            if resolved_ref == raw_root or raw_root in resolved_ref.parents:
                return str(resolved_ref.relative_to(raw_root)).replace("\\", "/")
            return str(resolved_ref).replace("\\", "/")
    except Exception:
        pass
    return normalized_ref


def _archive_stale_wiki_pages(*, dry_run: bool, keep_recent_chat: int, keep_recent_per_source: int, move_raw_files: bool = False) -> dict[str, Any]:
    sources_dir = _WIKI_VAULT / "wiki" / "sources"
    archive_sources_dir = _WIKI_VAULT / "wiki" / ".archive" / "sources"
    raw_dir = _WIKI_VAULT / "raw"
    archive_raw_dir = raw_dir / ".archive"

    report: dict[str, Any] = {"dry_run": dry_run, "archive_dir": str(archive_sources_dir), "moved_count": 0, "moved_sources": [], "moved_raw": [], "errors": []}
    if not sources_dir.exists():
        return report

    source_pages = sorted([p for p in sources_dir.glob("*.md") if p.is_file()], key=lambda p: p.stat().st_mtime, reverse=True)
    to_archive: dict[Path, Optional[str]] = {}

    chat_pages = [p for p in source_pages if p.name.lower().startswith("chat-history-")]
    for p in chat_pages[keep_recent_chat:]:
        to_archive[p] = _extract_source_ref(p)

    grouped: dict[str, list[tuple[Path, Optional[str]]]] = {}
    non_chat_pages = [p for p in source_pages if p not in to_archive]
    for p in non_chat_pages:
        source_ref = _extract_source_ref(p)
        grouped.setdefault(_source_identity_key(p, source_ref, raw_dir), []).append((p, source_ref))

    for entries in grouped.values():
        entries.sort(key=lambda x: x[0].stat().st_mtime, reverse=True)
        for stale_page, source_ref in entries[keep_recent_per_source:]:
            to_archive[stale_page] = source_ref

    for stale_page, source_ref in sorted(to_archive.items(), key=lambda x: x[0].stat().st_mtime):
        try:
            target_name = stale_page.name
            target = archive_sources_dir / target_name
            if target.exists():
                stamp = int(stale_page.stat().st_mtime)
                target = archive_sources_dir / f"{stale_page.stem}--{stamp}{stale_page.suffix}"
            if not dry_run:
                archive_sources_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(stale_page), str(target))
            report["moved_sources"].append(str(target))
            if move_raw_files and source_ref:
                raw_path = Path(source_ref)
                if raw_path.exists() and raw_dir in raw_path.parents:
                    raw_target = archive_raw_dir / raw_path.name
                    if raw_target.exists():
                        stamp = int(raw_path.stat().st_mtime)
                        raw_target = archive_raw_dir / f"{raw_path.stem}--{stamp}{raw_path.suffix}"
                    if not dry_run:
                        archive_raw_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(raw_path), str(raw_target))
                    report["moved_raw"].append(str(raw_target))
        except Exception as exc:
            report["errors"].append(f"{stale_page}: {exc}")

    report["moved_count"] = len(report["moved_sources"])
    return report


@router.post("/wiki/archive/stale", response_model=WikiArchiveResponse)
async def archive_stale_wiki_sources(payload: WikiArchiveRequest, current_subject: str = Depends(_optional_subject)):
    report = _archive_stale_wiki_pages(dry_run=payload.dry_run, keep_recent_chat=payload.keep_recent_chat, keep_recent_per_source=payload.keep_recent_per_source, move_raw_files=payload.move_raw_files)
    if report["moved_count"] and not payload.dry_run:
        manager, _ = get_wiki_components()
        manager.engine._rebuild_index()
    return WikiArchiveResponse(dry_run=bool(report["dry_run"]), archive_dir=str(report["archive_dir"]), moved_count=int(report["moved_count"]), moved_sources=[str(x) for x in report["moved_sources"]], moved_raw=[str(x) for x in report["moved_raw"]], errors=[str(x) for x in report["errors"]])


# ── Wiki Delete ────────────────────────────────────────────────────

def _to_wiki_delete_response(report: dict[str, Any]) -> WikiDeleteResponse:
    return WikiDeleteResponse(
        status=str(report.get("status", "ok")), dry_run=bool(report.get("dry_run", True)), hard_delete=bool(report.get("hard_delete", False)),
        entry_type=str(report.get("entry_type", "")), cascade_orphan_knowledge=bool(report.get("cascade_orphan_knowledge", True)),
        requested_entries=[str(i) for i in report.get("requested_entries", [])], resolved_entries=[str(i) for i in report.get("resolved_entries", [])],
        missing_entries=[str(i) for i in report.get("missing_entries", [])], invalid_entries=[str(i) for i in report.get("invalid_entries", [])],
        planned_source_pages=[str(i) for i in report.get("planned_source_pages", [])], planned_analysis_pages=[str(i) for i in report.get("planned_analysis_pages", [])],
        planned_entity_pages=[str(i) for i in report.get("planned_entity_pages", [])], planned_concept_pages=[str(i) for i in report.get("planned_concept_pages", [])],
        planned_total_pages=int(report.get("planned_total_pages", 0)), archived_pages=[str(i) for i in report.get("archived_pages", [])],
        deleted_pages=[str(i) for i in report.get("deleted_pages", [])], errors=[str(i) for i in report.get("errors", [])],
    )


def _to_wiki_data_graph_response(report: dict[str, Any]) -> WikiDataGraphResponse:
    valid_kinds = {"source", "analysis", "entity", "concept"}
    nodes = [WikiDataGraphNode(id=str(item["id"]), kind=str(item["kind"]).strip().lower(), label=str(item["label"]), inbound_links=int(item.get("inbound_links", 0)), outbound_links=int(item.get("outbound_links", 0))) for item in report.get("nodes", []) if isinstance(item, dict) and str(item.get("kind", "")).strip().lower() in valid_kinds]
    edges = [WikiDataGraphEdge(id=str(item["id"]), source=str(item["source"]), target=str(item["target"])) for item in report.get("edges", []) if isinstance(item, dict)]
    return WikiDataGraphResponse(status=str(report.get("status", "ok")), nodes=nodes, edges=edges)


@router.get("/wiki/data/graph", response_model=WikiDataGraphResponse)
async def wiki_data_graph(include_analysis: bool = True, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    try:
        report = manager.get_wiki_data_graph(include_analysis=include_analysis)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki data graph failed: {exc}")
    return _to_wiki_data_graph_response(report)


@router.post("/wiki/delete/preview", response_model=WikiDeleteResponse)
async def wiki_delete_preview(payload: WikiDeletePreviewRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    try:
        report = manager.delete_wiki_entries(entry_type=payload.entry_type, entries=payload.entries, dry_run=True, cascade_orphan_knowledge=payload.cascade_orphan_knowledge, hard_delete=False)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki delete preview failed: {exc}")
    return _to_wiki_delete_response(report)


@router.post("/wiki/delete/apply", response_model=WikiDeleteResponse)
async def wiki_delete_apply(payload: WikiDeleteApplyRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    try:
        report = manager.delete_wiki_entries(entry_type=payload.entry_type, entries=payload.entries, dry_run=False, cascade_orphan_knowledge=payload.cascade_orphan_knowledge, hard_delete=payload.hard_delete)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki delete apply failed: {exc}")
    return _to_wiki_delete_response(report)


# ── Wiki Ingest ────────────────────────────────────────────────────

@router.post("/wiki/ingest", response_model=WikiIngestResponse)
async def wiki_ingest(payload: WikiIngestRequest, current_subject: str = Depends(_optional_subject)):
    _, ingestor = get_wiki_components()
    if payload.source_path:
        source_path = Path(payload.source_path).expanduser()
        if not source_path.exists() or not source_path.is_file():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File not found: {source_path}")
        result = ingestor.ingest_file(source_path, contributor="Zopedia")
        if not result:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to ingest file: {source_path}")
        return WikiIngestResponse(status="ok", processed_files=1, results=[{"source_path": str(source_path), "result": result}])
    results = _ingest_pending_raw_files(max_files=payload.max_pending_raw_files, respect_interval_gate=False)
    return WikiIngestResponse(status="ok", processed_files=len(results), results=results)


# ── Wiki Enrich ────────────────────────────────────────────────────

@router.post("/wiki/enrich", response_model=WikiEnrichResponse)
async def wiki_enrich(payload: WikiEnrichRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    run_retry = (_WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES > 0) if payload.run_fallback_retry_first is None else bool(payload.run_fallback_retry_first)
    if run_retry:
        try:
            retry_report = manager.retry_fallback_analysis_pages(dry_run=payload.dry_run, max_analysis_pages=payload.max_analysis_pages)
            logger.info("Fallback-retry before /wiki/enrich: scanned=%d fallback_found=%d regenerated=%d still_fallback=%d", int(retry_report.get("scanned_pages", 0)), int(retry_report.get("fallback_pages_found", 0)), int(retry_report.get("regenerated_pages", 0)), int(retry_report.get("fallback_still", 0)))
        except Exception as exc:
            logger.warning("Fallback-retry before /wiki/enrich failed: %s", exc)
    try:
        report = manager.enrich_analysis_pages(dry_run=payload.dry_run, max_analysis_pages=payload.max_analysis_pages, fill_gaps_from_web=payload.fill_gaps_from_web, max_web_gap_queries=payload.max_web_gap_queries, refresh_non_fallback_oldest_pages=payload.refresh_non_fallback_oldest_pages, repair_answer_links=payload.repair_answer_links, compact_knowledge_pages=payload.compact_knowledge_pages, max_incremental_updates=payload.max_incremental_updates)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki enrichment failed: {exc}")
    return WikiEnrichResponse(status=str(report.get("status", "ok")), dry_run=bool(report.get("dry_run", payload.dry_run)), scanned_pages=int(report.get("scanned_pages", 0)), updated_pages=int(report.get("updated_pages", 0)), changes=[dict(item) for item in report.get("changes", [])], web_gap_fill=dict(report.get("web_gap_fill", {})), non_fallback_refresh=dict(report.get("non_fallback_refresh", {})), analysis_link_repair=dict(report.get("analysis_link_repair", {})), knowledge_compaction=dict(report.get("knowledge_compaction", {})))


# ── Wiki Retry Fallback ────────────────────────────────────────────

@router.post("/wiki/retry-fallback", response_model=WikiRetryFallbackResponse)
async def wiki_retry_fallback(payload: WikiRetryFallbackRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    try:
        report = manager.retry_fallback_analysis_pages(dry_run=payload.dry_run, max_analysis_pages=payload.max_analysis_pages)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki fallback retry failed: {exc}")
    return WikiRetryFallbackResponse(status=str(report.get("status", "ok")), dry_run=bool(report.get("dry_run", payload.dry_run)), scanned_pages=int(report.get("scanned_pages", 0)), fallback_pages_found=int(report.get("fallback_pages_found", 0)), retried_pages=int(report.get("retried_pages", 0)), regenerated_pages=int(report.get("regenerated_pages", 0)), fallback_still=int(report.get("fallback_still", 0)), skipped_no_question=int(report.get("skipped_no_question", 0)), errors=[str(i) for i in report.get("errors", [])], results=[dict(i) for i in report.get("results", [])])


# ── Wiki Analysis Backlinks ────────────────────────────────────────

@router.post("/wiki/analysis-backlinks", response_model=WikiAnalysisBacklinksResponse)
async def wiki_analysis_backlinks(payload: WikiAnalysisBacklinksRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    try:
        report = manager.refresh_analysis_backlinks(dry_run=payload.dry_run, max_analysis_pages=payload.max_analysis_pages, max_links_per_page=payload.max_links_per_page)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki analysis backlink maintenance failed: {exc}")
    return WikiAnalysisBacklinksResponse(status=str(report.get("status", "ok")), dry_run=bool(report.get("dry_run", payload.dry_run)), scanned_analysis_pages=int(report.get("scanned_analysis_pages", 0)), target_pages=int(report.get("target_pages", 0)), linked_target_pages=int(report.get("linked_target_pages", 0)), updated_pages=int(report.get("updated_pages", 0)), removed_sections=int(report.get("removed_sections", 0)), max_links_per_page=int(report.get("max_links_per_page", payload.max_links_per_page)), changes=[dict(i) for i in report.get("changes", [])])


# ── Wiki Rebuild Index (backlinks + godnodes) ────────────────────────


@router.post("/wiki/rebuild-index", response_model=WikiAnalysisBacklinksResponse)
async def wiki_rebuild_index(payload: WikiAnalysisBacklinksRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    # Step 1: refresh analysis backlinks (zero LLM calls, pure lexical)
    try:
        backlinks_report = manager.refresh_analysis_backlinks(
            dry_run=payload.dry_run,
            max_analysis_pages=payload.max_analysis_pages,
            max_links_per_page=payload.max_links_per_page,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analysis backlink refresh failed: {exc}",
        )
    # Step 2: rebuild god-nodes community index
    try:
        manager.engine._rebuild_index_godnodes()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"God-nodes index rebuild failed: {exc}",
        )
    return WikiAnalysisBacklinksResponse(
        status="ok",
        dry_run=bool(backlinks_report.get("dry_run", payload.dry_run)),
        scanned_analysis_pages=int(backlinks_report.get("scanned_analysis_pages", 0)),
        target_pages=int(backlinks_report.get("target_pages", 0)),
        linked_target_pages=int(backlinks_report.get("linked_target_pages", 0)),
        updated_pages=int(backlinks_report.get("updated_pages", 0)),
        removed_sections=int(backlinks_report.get("removed_sections", 0)),
        max_links_per_page=int(backlinks_report.get("max_links_per_page", payload.max_links_per_page)),
        changes=[dict(i) for i in backlinks_report.get("changes", [])],
    )


# ── Wiki Merge Maintenance ─────────────────────────────────────────

@router.post("/wiki/merge-maintenance", response_model=WikiMergeMaintenanceResponse)
async def wiki_merge_maintenance(payload: WikiMergeMaintenanceRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    try:
        report = manager.merge_duplicate_knowledge_pages(dry_run=payload.dry_run, include_entities=payload.include_entities, include_concepts=payload.include_concepts, similarity_threshold=payload.similarity_threshold, max_merges=payload.max_merges, semantic_concept_merge=payload.semantic_concept_merge, semantic_merge_writeback=payload.semantic_merge_writeback, compact_knowledge_pages=payload.compact_knowledge_pages, max_incremental_updates=payload.max_incremental_updates)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki merge maintenance failed: {exc}")
    return WikiMergeMaintenanceResponse(status=str(report.get("status", "ok")), dry_run=bool(report.get("dry_run", payload.dry_run)), entity_candidates=int(report.get("entity_candidates", 0)), concept_candidates=int(report.get("concept_candidates", 0)), semantic_concept_merge_enabled=bool(report.get("semantic_concept_merge_enabled", payload.semantic_concept_merge)), semantic_merge_writeback_enabled=bool(report.get("semantic_merge_writeback_enabled", payload.semantic_merge_writeback)), semantic_concept_candidates=int(report.get("semantic_concept_candidates", 0)), scanned_candidates=int(report.get("scanned_candidates", 0)), planned_merges=int(report.get("planned_merges", 0)), applied_merges=int(report.get("applied_merges", 0)), rewritten_pages=int(report.get("rewritten_pages", 0)), rewritten_links=int(report.get("rewritten_links", 0)), archived_pages=[str(i) for i in report.get("archived_pages", [])], skipped=[dict(i) for i in report.get("skipped", [])], merges=[dict(i) for i in report.get("merges", [])], errors=[str(i) for i in report.get("errors", [])], knowledge_compaction=dict(report.get("knowledge_compaction", {})))


# ── Wiki Query ─────────────────────────────────────────────────────

@router.post("/wiki/query", response_model=WikiQueryResponse)
async def wiki_query(payload: WikiQueryRequest, current_subject: str = Depends(_optional_subject)):
    if not llm_available():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No upstream LLM configured. Set ZOPEDIA_LLM_BASE_URL and ZOPEDIA_LLM_API_KEY.")
    manager, _ = get_wiki_components()
    try:
        result = manager.engine.query(payload.question, save_answer=payload.save_answer)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Wiki query failed: {exc}")

    global _WIKI_QUERY_RUN_COUNT
    _WIKI_QUERY_RUN_COUNT += 1
    if _WIKI_AUTO_LINT_EVERY > 0 and _WIKI_QUERY_RUN_COUNT % _WIKI_AUTO_LINT_EVERY == 0:
        try:
            lint_report = manager.engine.lint()
            logger.info("Auto lint after wiki query #%d: orphans=%d stale=%d broken=%d", _WIKI_QUERY_RUN_COUNT, len(lint_report.get("orphans", [])), len(lint_report.get("stale_pages", [])), len(lint_report.get("broken_links", [])))
        except Exception as exc:
            logger.warning("Auto lint after query #%d failed: %s", _WIKI_QUERY_RUN_COUNT, exc)
        if _WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES > 0:
            try:
                manager.retry_fallback_analysis_pages(dry_run=False, max_analysis_pages=_WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES)
            except Exception as exc:
                logger.warning("Auto fallback-retry after query #%d failed: %s", _WIKI_QUERY_RUN_COUNT, exc)
        try:
            manager.enrich_analysis_pages(dry_run=False)
        except Exception as exc:
            logger.warning("Auto enrichment after query #%d failed: %s", _WIKI_QUERY_RUN_COUNT, exc)

    return WikiQueryResponse(status=str(result.get("status", "ok")), answer=str(result.get("answer", "")), answer_page=result.get("answer_page"), context_pages=[str(p) for p in result.get("context_pages", [])])


# ── Wiki Lint ──────────────────────────────────────────────────────

@router.get("/wiki/lint", response_model=WikiLintResponse)
async def wiki_lint(current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    if _WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES > 0:
        try:
            retry_report = manager.retry_fallback_analysis_pages(dry_run=False, max_analysis_pages=_WIKI_AUTO_RETRY_FALLBACK_MAX_PAGES)
            logger.info("Fallback-retry before /wiki/lint: scanned=%d fallback_found=%d regenerated=%d still_fallback=%d", int(retry_report.get("scanned_pages", 0)), int(retry_report.get("fallback_pages_found", 0)), int(retry_report.get("regenerated_pages", 0)), int(retry_report.get("fallback_still", 0)))
        except Exception as exc:
            logger.warning("Fallback-retry before /wiki/lint failed: %s", exc)
    report = manager.engine.lint()
    return WikiLintResponse(status=str(report.get("status", "ok")), orphans=[str(x) for x in report.get("orphans", [])], stale_pages=[dict(x) for x in report.get("stale_pages", [])], broken_links=[dict(x) for x in report.get("broken_links", [])], missing_concepts=[str(x) for x in report.get("missing_concepts", [])], low_coverage_sources=[str(x) for x in report.get("low_coverage_sources", [])], entity_merge_candidates=[dict(x) for x in report.get("entity_merge_candidates", [])], concept_merge_candidates=[dict(x) for x in report.get("concept_merge_candidates", [])], total_pages=int(report.get("total_pages", 0)), graphify_insights=dict(report.get("graphify_insights", {})))


# ── Wiki Env Config ────────────────────────────────────────────────

@router.get("/wiki/env", response_model=WikiEnvConfigResponse)
async def wiki_env_config(request: Request, current_subject: str = Depends(_optional_subject)):
    restart_supported = callable(getattr(request.app.state, "trigger_restart", None))
    return WikiEnvConfigResponse(status="ok", variables=collect_wiki_env_state(), overrides_file=str(wiki_env_overrides_file()), restart_supported=restart_supported)


@router.post("/wiki/env", response_model=WikiEnvSetResponse)
async def wiki_env_set(payload: WikiEnvSetRequest, request: Request, current_subject: str = Depends(_optional_subject)):
    result = update_wiki_env_values(payload.values)
    changed = bool(result.get("updated") or result.get("cleared"))
    restart_supported = callable(getattr(request.app.state, "trigger_restart", None))
    restart_scheduled = False
    if payload.restart_backend and changed and restart_supported:
        trigger_restart = getattr(request.app.state, "trigger_restart", None)
        if callable(trigger_restart):

            async def _delayed_restart():
                await asyncio.sleep(0.2)
                try:
                    trigger_restart()
                except Exception as exc:
                    logger.warning("Failed to trigger backend restart: %s", exc)

            request.app.state._restart_task = asyncio.create_task(_delayed_restart())
            restart_scheduled = True
    status_value = "partial" if result.get("invalid") else "ok"
    return WikiEnvSetResponse(status=status_value, updated=[str(i) for i in result.get("updated", [])], cleared=[str(i) for i in result.get("cleared", [])], invalid=dict(result.get("invalid", {})), overrides_file=str(result.get("overrides_file", wiki_env_overrides_file())), restart_supported=restart_supported, restart_scheduled=restart_scheduled)


# ── Wiki Graphify Export ───────────────────────────────────────────

@router.post("/wiki/export/graphify-wiki", response_model=WikiGraphifyExportResponse)
async def wiki_export_graphify_wiki(payload: WikiGraphifyExportRequest, current_subject: str = Depends(_optional_subject)):
    manager, _ = get_wiki_components()
    report = manager.engine.export_graphify_wiki(output_subdir=payload.output_subdir)
    return WikiGraphifyExportResponse(status=str(report.get("status", "error")), reason=report.get("reason"), output_dir=str(report.get("output_dir", "")), index_file=str(report.get("index_file", "")), articles_written=int(report.get("articles_written", 0)), communities=int(report.get("communities", 0)), god_nodes=int(report.get("god_nodes", 0)))


# ── Chat History Save ─────────────────────────────────────────────

@router.post("/wiki/chat-history/save", response_model=WikiChatHistorySaveResponse)
async def wiki_save_chat_history(payload: WikiChatHistorySaveRequest, current_subject: str = Depends(_optional_subject)):
    """Save chat history markdown to the wiki raw/ folder for ingestion."""
    raw_dir = _WIKI_VAULT / "raw"
    try:
        raw_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Cannot create raw dir: {exc}")

    # Build markdown from messages
    thread_id = payload.thread_id.strip() or "unknown"
    title = (payload.thread_title or "Chat History").strip()
    safe_id = _RE.sub(r"[^a-zA-Z0-9._-]+", "_", thread_id).strip("._-") or "chat"
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
    filename = f"chat-history-{safe_id}-{timestamp}.md"
    file_path = raw_dir / filename

    lines = [
        f"# {title}",
        "",
        "> This file is an exported Zopedia chat history. It was saved from a conversation "
        "with the wiki and will be ingested as a new source. When analyzing this file, "
        "treat it as a dialogue between a user and an AI assistant. Extract entities, "
        "concepts, and facts as you would from any other source.",
        "",
        f"thread_id: {thread_id}",
        f"saved_at: {datetime.now().isoformat()}",
        "",
    ]
    for msg in payload.messages:
        role = (msg.role or "unknown").capitalize()
        content = msg.content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
            content = "\n".join(parts) if parts else "(non-text content)"
        elif isinstance(content, dict):
            content = json.dumps(content)
        elif content is None:
            content = "(empty)"
        content_str = str(content)
        if msg.reasoning_content:
            content_str = f"<think>\n{msg.reasoning_content}\n</think>\n\n{content_str}"
        lines.append(f"## {role}")
        lines.append(content_str)
        lines.append("")

    try:
        file_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to write chat history: {exc}")

    relative_path = f"raw/{filename}"
    watcher_enabled = _WIKI_WATCHER_ENABLED
    ingested = False

    # Trigger immediate ingestion if watcher is enabled
    if watcher_enabled:
        try:
            _, ingestor = get_wiki_components()
            result = ingestor.ingest_file(file_path, contributor="Zopedia Chat")
            ingested = bool(result)
        except Exception as exc:
            logger.warning("Failed to auto-ingest chat history: %s", exc)

    return WikiChatHistorySaveResponse(
        status="ok",
        operation="created",
        thread_id=thread_id,
        file_path=str(file_path),
        relative_path=relative_path,
        message_count=len(payload.messages),
        watcher_enabled=watcher_enabled,
        ingested_immediately=ingested,
    )
