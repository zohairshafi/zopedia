"""Bridge ZOPEDIA_* env vars to UNSLOTH_* equivalents for engine compatibility.

The wiki engine reads UNSLOTH_* env vars directly in WikiConfig and watcher.
We set sensible defaults for all of them so the engine works unchanged.
Only a few are exposed as ZOPEDIA_* user-configurable vars.
"""

import os


def _setdefault(name: str, value: str) -> None:
    if name not in os.environ:
        os.environ[name] = value


def apply_defaults() -> None:
    """Apply all UNSLOTH_* defaults expected by the wiki engine/watcher/ingestor."""
    # Map ZOPEDIA_* vars to UNSLOTH_* equivalents first
    _map = {
        "ZOPEDIA_WIKI_VAULT": "UNSLOTH_WIKI_VAULT",
        "ZOPEDIA_WIKI_WATCHER": "UNSLOTH_WIKI_WATCHER",
        "ZOPEDIA_WIKI_AUTO_QUERY_ON_INGEST": "UNSLOTH_WIKI_AUTO_QUERY_ON_INGEST",
        "ZOPEDIA_WIKI_COMMUNITY_MIN_SIZE": "UNSLOTH_WIKI_COMMUNITY_MIN_SIZE",
        "ZOPEDIA_WIKI_COMMUNITY_CUTOFF": "UNSLOTH_WIKI_COMMUNITY_CUTOFF",
        "ZOPEDIA_WIKI_GODNODES_REBUILD_THRESHOLD": "UNSLOTH_WIKI_GODNODES_REBUILD_THRESHOLD",
    }
    for z_name, u_name in _map.items():
        if z_name in os.environ:
            os.environ[u_name] = os.environ[z_name]

    # Vault path defaults
    _setdefault("UNSLOTH_WIKI_VAULT", os.getenv("ZOPEDIA_WIKI_VAULT", "./wiki_data"))

    # Watcher defaults
    _setdefault("UNSLOTH_WIKI_WATCHER", "true")
    _setdefault("UNSLOTH_WIKI_AUTO_QUERY_ON_INGEST", "true")
    _setdefault("UNSLOTH_WIKI_AUTO_QUERY_CHAT_HISTORY", "false")
    _setdefault("UNSLOTH_WIKI_MAX_ANALYSIS_PAGES", "64")
    _setdefault("UNSLOTH_WIKI_AUTO_LINT_EVERY", "10")
    _setdefault("UNSLOTH_WIKI_AUTO_RETRY_FALLBACK_ANALYSES_MAX_PAGES", "24")
    _setdefault("UNSLOTH_WIKI_CHAT_HISTORY_FLUSH_SECONDS", "600")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_CONTEXT_FRACTION", "0.70")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_CHARS_PER_TOKEN", "4")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_RETRY_ON_FALLBACK", "true")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_MAX_RETRIES", "3")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_RETRY_REDUCTION", "0.5")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_MIN_CONTEXT_CHARS", "8000")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_SOURCE_ONLY", "false")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_SOURCE_ONLY_FINAL_RETRY", "true")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_FORCE_CHUNK_ON_FALLBACK", "true")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_FORCE_CHUNK_MIN_SOURCE_CHARS", "50000")
    _setdefault("UNSLOTH_WIKI_AUTO_ANALYSIS_FORCE_CHUNK_MAX_PAGES", "2")

    # Pending ingest defaults
    _setdefault("UNSLOTH_WIKI_PENDING_INGEST_INTERVAL_SECONDS", "45")
    _setdefault("UNSLOTH_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT", "1")

    # RAG defaults
    _setdefault("UNSLOTH_WIKI_RAG_MAX_PAGES", "8")
    _setdefault("UNSLOTH_WIKI_RAG_MAX_CHARS_PER_PAGE", "1800")
    _setdefault("UNSLOTH_WIKI_RAG_MAX_TOTAL_CHARS", "12000")
    _setdefault("UNSLOTH_WIKI_RAG_INCLUDE_SOURCE_PAGES", "true")
    _setdefault("UNSLOTH_WIKI_INDEX_INCLUDE_SOURCE_PAGES", "true")
    _setdefault("UNSLOTH_WIKI_LOG_INJECTED_CONTEXT", "true")
    _setdefault("UNSLOTH_WIKI_LOG_INJECTED_CONTEXT_MAX_CHARS", "12000")
    _setdefault("UNSLOTH_WIKI_LLM_MAX_TOKENS", "2000")

    # Wiki LLM upstream defaults
    _setdefault("UNSLOTH_WIKI_LLM_PREFER_UPSTREAM", "true")
    _setdefault("UNSLOTH_WIKI_LLM_THINKING_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_LLM_REASONING_STYLE", "reasoning_effort")
    _setdefault("UNSLOTH_WIKI_LLM_REASONING_EFFORT", "high")
    _setdefault("UNSLOTH_WIKI_LLM_PRESERVE_THINKING", "false")

    # Upstream API defaults (mapped from ZOPEDIA)
    _setdefault("UNSLOTH_LLM_UPSTREAM_BASE_URL", os.getenv("ZOPEDIA_LLM_BASE_URL", ""))
    _setdefault("UNSLOTH_LLM_UPSTREAM_API_KEY", os.getenv("ZOPEDIA_LLM_API_KEY", ""))
    _setdefault("UNSLOTH_LLM_UPSTREAM_MODEL", os.getenv("ZOPEDIA_LLM_MODEL", ""))

    # Engine model defaults
    _setdefault("UNSLOTH_WIKI_ENGINE_MODEL_TOKEN_CAPACITY", "125000")
    _setdefault("UNSLOTH_WIKI_ENGINE_MODEL_SAFE_TOKEN_RATIO", "0.50")
    _setdefault("UNSLOTH_WIKI_ENGINE_MODEL_CHARS_PER_TOKEN", "4.0")

    # Engine extraction defaults
    _setdefault("UNSLOTH_WIKI_ENGINE_EXTRACT_SOURCE_MAX_CHARS", "20000")
    _setdefault("UNSLOTH_WIKI_ENGINE_SOURCE_EXCERPT_MAX_CHARS", "8000")

    # Engine chunk defaults
    _setdefault("UNSLOTH_WIKI_ENGINE_CHUNK_ANALYSIS_CONTEXT_WINDOW_CHARS", "125000")
    _setdefault("UNSLOTH_WIKI_ENGINE_CHUNK_ANALYSIS_TARGET_RATIO", "0.70")
    _setdefault("UNSLOTH_WIKI_ENGINE_CHUNK_ANALYSIS_OVERLAP_RATIO", "0.08")
    _setdefault("UNSLOTH_WIKI_ENGINE_CHUNK_ANALYSIS_MIN_CHARS", "1200")
    _setdefault("UNSLOTH_WIKI_ENGINE_CHUNK_ANALYSIS_MAX_CHARS", "125000")

    # Engine ranking defaults
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_MAX_CHARS", "24000")
    _setdefault("UNSLOTH_WIKI_ENGINE_MAX_CONTEXT_PAGES", "16")
    _setdefault("UNSLOTH_WIKI_ENGINE_MAX_CHARS_PER_PAGE", "3500")
    _setdefault("UNSLOTH_WIKI_ENGINE_QUERY_CONTEXT_MAX_CHARS", "24000")
    _setdefault("UNSLOTH_WIKI_ENGINE_INCLUDE_ANALYSIS_IN_QUERY", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_ANALYSIS_FIRST", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_TYPE_MIX_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_TYPE_MIX_WINDOW_PAGES", "24")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_TYPE_MIX_ANALYSIS_RATIO", "0.60")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_TYPE_MIX_ENTITY_RATIO", "0.20")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_TYPE_MIX_CONCEPT_RATIO", "0.20")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_LINK_DEPTH", "2")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_LINK_FANOUT", "8")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_LINK_LLM_SELECTOR_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_RANKING_LINK_LLM_SELECTOR_MAX_CANDIDATES", "24")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_INCLUDE_ANALYSIS_PAGES", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_MIN_CANDIDATES", "3")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_CANDIDATES", "32")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_TOP_N", "12")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_PREVIEW_CHARS", "420")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_LOG_OUTPUT", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_LLM_RERANK_LOG_MAX_CHARS", "4000")

    # Engine index defaults
    _setdefault("UNSLOTH_WIKI_INDEX_INCLUDE_ANALYSIS_PAGES", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_INDEX_LLM_TITLE_ON_REBUILD", "false")

    # Quality defaults
    _setdefault("UNSLOTH_WIKI_LOW_UNIQUE_RATIO_MIN_TOKENS", "40")
    _setdefault("UNSLOTH_WIKI_LOW_UNIQUE_RATIO_THRESHOLD", "0.25")

    # Enrich defaults
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_FILL_GAPS_FROM_WEB", "false")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_WEB_GAP_MAX_QUERIES", "4")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_WEB_GAP_MAX_RESULTS", "3")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_WEB_GAP_MAX_SNIPPET_CHARS", "280")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_WEB_GAP_LLM_PLANNER_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_WEB_GAP_LLM_SELECTOR_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_LLM_SELECTOR_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_LLM_SELECTOR_MAX_CANDIDATES", "48")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_REFRESH_OLDEST_NON_FALLBACK_PAGES", "0")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENRICH_REPAIR_ANSWER_LINKS", "false")

    # Community detection defaults for god-nodes index pagination
    _setdefault("UNSLOTH_WIKI_COMMUNITY_CUTOFF", "20")
    _setdefault("UNSLOTH_WIKI_COMMUNITY_MIN_SIZE", "4")
    _setdefault("UNSLOTH_WIKI_GODNODES_REBUILD_THRESHOLD", "50")

    # Merge/compaction defaults
    _setdefault("UNSLOTH_WIKI_ENGINE_MERGE_LLM_CANDIDATE_PLANNER_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_ENGINE_ENTITY_QUERY_FOCUS_LLM_ENABLED", "true")
    _setdefault("UNSLOTH_WIKI_MERGE_MAINTENANCE_MAX_MERGES", "512")
    _setdefault("UNSLOTH_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES", "10")
    _setdefault("UNSLOTH_WIKI_COMPACTION_MAX_PAGES", "64")


# Apply defaults on import
apply_defaults()
