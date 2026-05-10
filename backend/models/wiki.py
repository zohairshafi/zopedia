"""Wiki-related Pydantic models for Zopedia."""

from __future__ import annotations

import os
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, model_validator


def _env_int(name: str, default: int, *, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


_WIKI_MERGE_MAINTENANCE_MAX_MERGES_DEFAULT = _env_int(
    "ZOPEDIA_WIKI_MERGE_MAINTENANCE_MAX_MERGES", 512, minimum=1, maximum=512
)
_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES_DEFAULT = _env_int(
    "ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES", 48, minimum=1, maximum=256
)


# ── RAG Debug ─────────────────────────────────────────────────────

class RagContextDebugRequest(BaseModel):
    query: str = Field(..., min_length=1, description="User query to inspect")
    include_pending_raw: bool = Field(True, description="Ingest pending files from raw/ before retrieval")
    max_pages: Optional[int] = Field(None, ge=1, le=32, description="Optional override for max context pages")
    max_chars_per_page: Optional[int] = Field(None, ge=200, le=12000, description="Optional override for max chars per selected page")
    max_total_chars: Optional[int] = Field(None, ge=500, le=30000, description="Optional override for max total context characters")


class RagContextSnippet(BaseModel):
    page: str
    score: float
    snippet: str


class RagContextDebugResponse(BaseModel):
    query: str
    source: Literal["live-query", "last-request"]
    wants_history: bool
    context: str
    context_characters: int
    pages_considered: int
    selected: list[RagContextSnippet]
    applied_limits: Dict[str, int]
    generated_at: str


# ── Wiki Archive ───────────────────────────────────────────────────

class WikiArchiveRequest(BaseModel):
    dry_run: bool = Field(False)
    keep_recent_chat: int = Field(16, ge=0, le=500)
    keep_recent_per_source: int = Field(1, ge=1, le=10)
    move_raw_files: bool = Field(False)


class WikiArchiveResponse(BaseModel):
    dry_run: bool
    archive_dir: str
    moved_count: int
    moved_sources: list[str]
    moved_raw: list[str]
    errors: list[str]


# ── Wiki Delete ────────────────────────────────────────────────────

class WikiDeletePreviewRequest(BaseModel):
    entry_type: Literal["source", "analysis", "entity", "concept"] = Field(...)
    entries: list[str] = Field(..., min_length=1, max_length=256)
    cascade_orphan_knowledge: bool = Field(True)

    @model_validator(mode="before")
    @classmethod
    def _normalize_delete_payload(cls, raw: Any) -> Any:
        if not isinstance(raw, dict):
            return raw
        payload = dict(raw)
        entry_type = payload.get("entry_type")
        if isinstance(entry_type, str):
            payload["entry_type"] = entry_type.strip().lower()
        if "entries" not in payload and "entry" in payload:
            payload["entries"] = payload.get("entry")
        entries = payload.get("entries")
        if isinstance(entries, str):
            payload["entries"] = [entries]
        return payload


class WikiDeleteApplyRequest(WikiDeletePreviewRequest):
    hard_delete: bool = Field(False)


class WikiDeleteResponse(BaseModel):
    status: str
    dry_run: bool
    hard_delete: bool
    entry_type: str
    cascade_orphan_knowledge: bool
    requested_entries: list[str]
    resolved_entries: list[str]
    missing_entries: list[str]
    invalid_entries: list[str]
    planned_source_pages: list[str]
    planned_analysis_pages: list[str]
    planned_entity_pages: list[str]
    planned_concept_pages: list[str]
    planned_total_pages: int
    archived_pages: list[str]
    deleted_pages: list[str]
    errors: list[str]


# ── Wiki Data Graph ────────────────────────────────────────────────

class WikiDataGraphNode(BaseModel):
    id: str
    kind: Literal["source", "analysis", "entity", "concept"]
    label: str
    inbound_links: int
    outbound_links: int


class WikiDataGraphEdge(BaseModel):
    id: str
    source: str
    target: str


class WikiDataGraphResponse(BaseModel):
    status: str
    nodes: list[WikiDataGraphNode]
    edges: list[WikiDataGraphEdge]


# ── Wiki Ingest ────────────────────────────────────────────────────

class WikiIngestRequest(BaseModel):
    source_path: Optional[str] = Field(None)
    max_pending_raw_files: int = Field(8, ge=1, le=128)


class WikiIngestResponse(BaseModel):
    status: str
    processed_files: int
    results: list[Dict[str, Any]]


# ── Wiki Chat History ──────────────────────────────────────────────

class WikiChatHistoryMessage(BaseModel):
    role: str = Field(..., min_length=1, max_length=32)
    id: Optional[str] = Field(None, max_length=256)
    created_at: Optional[str] = Field(None, max_length=128)
    content: Optional[Union[str, list[Dict[str, Any]], Dict[str, Any]]] = Field(None)
    reasoning_content: Optional[str] = Field(None)
    attachments: Optional[list[Dict[str, Any]]] = Field(None)
    metadata: Optional[Dict[str, Any]] = Field(None)


class WikiChatHistorySaveRequest(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=256)
    thread_title: Optional[str] = Field(None, max_length=1024)
    messages: list[WikiChatHistoryMessage] = Field(..., min_length=1, max_length=40000)


class WikiChatHistorySaveResponse(BaseModel):
    status: Literal["ok"] = "ok"
    operation: Literal["created", "updated"]
    thread_id: str
    file_path: str
    relative_path: str
    message_count: int
    watcher_enabled: bool
    ingested_immediately: bool


# ── Wiki Enrich ────────────────────────────────────────────────────

class WikiEnrichRequest(BaseModel):
    dry_run: bool = Field(False)
    max_analysis_pages: int = Field(64, ge=1, le=1000)
    run_fallback_retry_first: Optional[bool] = Field(None)
    fill_gaps_from_web: Optional[bool] = Field(None)
    max_web_gap_queries: Optional[int] = Field(None, ge=1, le=100)
    refresh_non_fallback_oldest_pages: Optional[int] = Field(None, ge=0, le=1000)
    repair_answer_links: Optional[bool] = Field(None)
    compact_knowledge_pages: bool = Field(False)
    max_incremental_updates: int = Field(_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES_DEFAULT, ge=1, le=256)


class WikiEnrichResponse(BaseModel):
    status: str
    dry_run: bool
    scanned_pages: int
    updated_pages: int
    changes: list[Dict[str, Any]]
    web_gap_fill: Dict[str, Any]
    non_fallback_refresh: Dict[str, Any]
    analysis_link_repair: Dict[str, Any]
    knowledge_compaction: Dict[str, Any]


# ── Wiki Retry Fallback ────────────────────────────────────────────

class WikiRetryFallbackRequest(BaseModel):
    dry_run: bool = Field(False)
    max_analysis_pages: int = Field(24, ge=1, le=1000)


class WikiRetryFallbackResponse(BaseModel):
    status: str
    dry_run: bool
    scanned_pages: int
    fallback_pages_found: int
    retried_pages: int
    regenerated_pages: int
    fallback_still: int
    skipped_no_question: int
    errors: list[str]
    results: list[Dict[str, Any]]


# ── Wiki Analysis Backlinks ────────────────────────────────────────

class WikiAnalysisBacklinksRequest(BaseModel):
    dry_run: bool = Field(True)
    max_analysis_pages: Optional[int] = Field(None, ge=1, le=5000)
    max_links_per_page: int = Field(128, ge=1, le=2000)


class WikiAnalysisBacklinksResponse(BaseModel):
    status: str
    dry_run: bool
    scanned_analysis_pages: int
    target_pages: int
    linked_target_pages: int
    updated_pages: int
    removed_sections: int
    max_links_per_page: int
    changes: list[Dict[str, Any]]


# ── Wiki Merge Maintenance ─────────────────────────────────────────

class WikiMergeMaintenanceRequest(BaseModel):
    dry_run: bool = Field(True)
    include_entities: bool = Field(True)
    include_concepts: bool = Field(True)
    similarity_threshold: float = Field(0.75, ge=0.5, le=1.0)
    max_merges: int = Field(_WIKI_MERGE_MAINTENANCE_MAX_MERGES_DEFAULT, ge=1, le=512)
    semantic_concept_merge: bool = Field(True)
    semantic_merge_writeback: bool = Field(True)
    compact_knowledge_pages: bool = Field(False)
    max_incremental_updates: int = Field(_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES_DEFAULT, ge=1, le=256)


class WikiMergeMaintenanceResponse(BaseModel):
    status: str
    dry_run: bool
    entity_candidates: int
    concept_candidates: int
    semantic_concept_merge_enabled: bool
    semantic_merge_writeback_enabled: bool
    semantic_concept_candidates: int
    scanned_candidates: int
    planned_merges: int
    applied_merges: int
    rewritten_pages: int
    rewritten_links: int
    archived_pages: list[str]
    skipped: list[Dict[str, Any]]
    merges: list[Dict[str, Any]]
    errors: list[str]
    knowledge_compaction: Dict[str, Any]


# ── Wiki Query ─────────────────────────────────────────────────────

class WikiQueryRequest(BaseModel):
    question: str = Field(..., min_length=1)
    save_answer: bool = Field(True)


class WikiQueryResponse(BaseModel):
    status: str
    answer: str
    answer_page: Optional[str]
    context_pages: list[str]


# ── Wiki Lint ──────────────────────────────────────────────────────

class WikiLintResponse(BaseModel):
    status: str
    orphans: list[str]
    stale_pages: list[Dict[str, Any]]
    broken_links: list[Dict[str, str]]
    missing_concepts: list[str]
    low_coverage_sources: list[str]
    entity_merge_candidates: list[Dict[str, Any]] = Field(default_factory=list)
    concept_merge_candidates: list[Dict[str, Any]] = Field(default_factory=list)
    total_pages: int
    graphify_insights: Dict[str, Any]


# ── Wiki Env Config ────────────────────────────────────────────────

class WikiEnvVariable(BaseModel):
    name: str
    kind: Literal["bool", "int", "float", "string"]
    description: str
    default_value: str
    current_value: str
    source: Literal["environment", "default"]
    has_override: bool
    override_value: Optional[str] = None
    minimum: Optional[float] = None
    maximum: Optional[float] = None


class WikiEnvConfigResponse(BaseModel):
    status: str
    variables: list[WikiEnvVariable]
    overrides_file: str
    restart_supported: bool


class WikiEnvSetRequest(BaseModel):
    values: Dict[str, Optional[str]] = Field(default_factory=dict)
    restart_backend: bool = Field(True)


class WikiEnvSetResponse(BaseModel):
    status: str
    updated: list[str]
    cleared: list[str]
    invalid: Dict[str, str]
    overrides_file: str
    restart_supported: bool
    restart_scheduled: bool


# ── Wiki Graphify Export ───────────────────────────────────────────

class WikiGraphifyExportRequest(BaseModel):
    output_subdir: str = Field("graphify-wiki", min_length=1, max_length=120)


class WikiGraphifyExportResponse(BaseModel):
    status: str
    reason: Optional[str] = None
    output_dir: Optional[str] = None
    index_file: Optional[str] = None
    articles_written: int = 0
    communities: int = 0
    god_nodes: int = 0
