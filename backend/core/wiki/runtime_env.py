"""Runtime wiki environment metadata and override persistence helpers.

Simplified for Zopedia: ~10 critical env vars instead of 68.
All other engine config fields use sensible hardcoded defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Optional

WikiEnvKind = Literal["bool", "int", "float", "string"]


@dataclass(frozen=True)
class WikiEnvSpec:
    name: str
    kind: WikiEnvKind
    default: str
    description: str
    minimum: Optional[float] = None
    maximum: Optional[float] = None


WIKI_ENV_SPECS: tuple[WikiEnvSpec, ...] = (
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_VAULT",
        kind="string",
        default="./wiki_data",
        description="Root wiki vault directory.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_WATCHER",
        kind="bool",
        default="true",
        description="Enable background wiki raw-folder watcher.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_AUTO_QUERY_ON_INGEST",
        kind="bool",
        default="true",
        description="Run automatic wiki analysis after ingestion.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_RAG_PREFETCH_ENABLED",
        kind="bool",
        default="false",
        description="Pre-inject top-ranked wiki pages into the system prompt before each chat message. When disabled, the LLM relies entirely on tool-calling (read_wiki_page) for retrieval.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_TOOL_RETRIEVAL",
        kind="bool",
        default="true",
        description="Use tool-calling for wiki retrieval (model calls search_wiki/read_wiki_page tools). Disable for legacy pre-injected RAG context.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_LLM_BASE_URL",
        kind="string",
        default="",
        description="Upstream OpenAI-compatible API base URL.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_LLM_API_KEY",
        kind="string",
        default="",
        description="API key for upstream API.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_LLM_MODEL",
        kind="string",
        default="",
        description="Upstream model name.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_AUTH_DISABLED",
        kind="bool",
        default="false",
        description="Disable authentication for single-user mode.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_LLM_MAX_TOKENS",
        kind="int",
        default="200000",
        description="Max tokens for wiki-generated responses (analysis, extraction, etc.).",
        minimum=200,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_LLM_TIMEOUT_SECONDS",
        kind="int",
        default="300",
        description="Timeout in seconds for upstream LLM API calls.",
        minimum=10,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_MAX_ANALYSIS_PAGES",
        kind="int",
        default="128",
        description="Max analysis pages processed per enrich/retry/backlinks operation. Most-recent pages are prioritized.",
        minimum=1,
        maximum=1024,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_AUTO_LINT_EVERY",
        kind="int",
        default="10",
        description="Maintenance cadence for lint/retry/enrichment (every N ingests). 0 disables.",
        minimum=0,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_AUTO_RETRY_FALLBACK_ANALYSES_MAX_PAGES",
        kind="int",
        default="24",
        description="Max fallback analysis pages scanned per maintenance run. 0 disables.",
        minimum=0,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_PENDING_INGEST_INTERVAL_SECONDS",
        kind="int",
        default="45",
        description="Min seconds between automatic pending-ingest sweeps during chat.",
        minimum=0,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT",
        kind="int",
        default="1",
        description="Max pending raw files ingested per chat request. 0 disables chat-triggered ingest.",
        minimum=0,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_MERGE_MAINTENANCE_MAX_MERGES",
        kind="int",
        default="512",
        description="Max concept/entity merges per maintenance run.",
        minimum=1,
        maximum=512,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES",
        kind="int",
        default="5",
        description="Max Incremental Updates blocks retained per entity/concept page.",
        minimum=1,
        maximum=256,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_COMPACTION_MAX_PAGES",
        kind="int",
        default="128",
        description="Max entity/concept pages compacted per maintenance run. Pages with most overflow are prioritized.",
        minimum=0,
        maximum=2048,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_MAX_TOOL_TURNS",
        kind="int",
        default="10",
        description="Max tool-calling turns per chat request. Each turn can batch multiple reads (see MAX_READS_PER_TURN).",
        minimum=1,
        maximum=50,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_MAX_READS_PER_TURN",
        kind="int",
        default="5",
        description="Max wiki page reads per tool-calling turn. Caps batched reads to prevent context overload.",
        minimum=1,
        maximum=100,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_MAX_CHARS_PER_READ",
        kind="int",
        default="12000",
        description="Max chars returned per read_wiki_page call. Pages are truncated to this length. 12000 chars ≈ 3000 tokens.",
        minimum=1000,
        maximum=100000,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS",
        kind="int",
        default="500000",
        description="Hard cap on cumulative chars from all read_wiki_page calls in a single chat request. When exceeded, tool loop stops. 500000 chars ≈ 125000 tokens.",
        minimum=10000,
        maximum=5000000,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_COMMUNITY_CUTOFF",
        kind="int",
        default="40",
        description="Max number of communities detected by graph-based clustering. Higher values produce more fine-grained clusters. Controls granularity of the god-nodes index.",
        minimum=5,
        maximum=100,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_COMMUNITY_MIN_SIZE",
        kind="int",
        default="10",
        description="Communities smaller than this are merged into Other Pages in the god-nodes index.",
        minimum=2,
        maximum=50,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_COMMUNITY_MAX_SIZE",
        kind="int",
        default="150",
        description="Communities larger than this are recursively split into sub-communities. 0 disables splitting.",
        minimum=0,
        maximum=10000,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_GODNODES_REBUILD_THRESHOLD",
        kind="int",
        default="100",
        description="Rebuild god-nodes index after this many new pages are added (delta threshold).",
        minimum=10,
        maximum=10000,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_WIKI_PARALLEL_WORKERS",
        kind="int",
        default="8",
        description="Max worker threads for parallel wiki operations (ingestion, enrichment, lint, maintenance). Set to 1 to disable parallelism.",
        minimum=1,
        maximum=64,
    ),
    # ── Database ───────────────────────────────────────────────────
    WikiEnvSpec(
        name="ZOPEDIA_DATABASE_URL",
        kind="string",
        default="",
        description="PostgreSQL connection string for the database query tool (e.g. postgresql://user:pass@host:5432/dbname). Leave empty to disable database features.",
    ),
    WikiEnvSpec(
        name="ZOPEDIA_DB_MAX_ROWS",
        kind="int",
        default="100",
        description="Maximum rows returned per SQL query. A LIMIT is auto-appended to queries that don't already have one.",
        minimum=1,
        maximum=10000,
    ),
    WikiEnvSpec(
        name="ZOPEDIA_DB_TIMEOUT_SECONDS",
        kind="int",
        default="10",
        description="Per-query statement timeout in seconds. Queries exceeding this are cancelled.",
        minimum=1,
        maximum=300,
    ),
)

_WIKI_ENV_SPECS_BY_NAME = {spec.name: spec for spec in WIKI_ENV_SPECS}
WIKI_ENV_NAMES = frozenset(_WIKI_ENV_SPECS_BY_NAME.keys())


def wiki_env_overrides_file() -> Path:
    configured = os.getenv("ZOPEDIA_WIKI_ENV_OVERRIDES_FILE")
    if configured and configured.strip():
        return Path(configured).expanduser()
    zopedia_home = os.getenv("ZOPEDIA_HOME", str(Path.home()))
    return Path(zopedia_home) / ".zopedia" / "wiki_env_overrides.json"


def _validate_numeric_bounds(spec: WikiEnvSpec, value: float) -> None:
    if spec.minimum is not None and value < spec.minimum:
        raise ValueError(f"Value must be >= {spec.minimum}.")
    if spec.maximum is not None and value > spec.maximum:
        raise ValueError(f"Value must be <= {spec.maximum}.")


def _normalize_bool(raw: str) -> str:
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return "true"
    if value in {"0", "false", "no", "off"}:
        return "false"
    raise ValueError("Expected a boolean value (true/false).")


def _validate_value(spec: WikiEnvSpec, raw_value: str) -> str:
    value = raw_value.strip()
    if not value:
        raise ValueError("Value cannot be empty.")
    if spec.kind == "string":
        return value
    if spec.kind == "bool":
        return _normalize_bool(value)
    if spec.kind == "int":
        try:
            numeric = int(value)
        except ValueError as exc:
            raise ValueError("Expected an integer value.") from exc
        _validate_numeric_bounds(spec, float(numeric))
        return str(numeric)
    if spec.kind == "float":
        try:
            numeric = float(value)
        except ValueError as exc:
            raise ValueError("Expected a numeric value.") from exc
        _validate_numeric_bounds(spec, numeric)
        return str(numeric)
    raise ValueError(f"Unsupported variable type: {spec.kind}")


def load_wiki_env_overrides() -> dict[str, str]:
    path = wiki_env_overrides_file()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    cleaned: dict[str, str] = {}
    for raw_name, raw_value in payload.items():
        if not isinstance(raw_name, str):
            continue
        spec = _WIKI_ENV_SPECS_BY_NAME.get(raw_name)
        if spec is None:
            continue
        normalized_input = str(raw_value)
        try:
            cleaned[raw_name] = _validate_value(spec, normalized_input)
        except ValueError:
            continue
    return cleaned


def persist_wiki_env_overrides(overrides: dict[str, str]) -> Path:
    path = wiki_env_overrides_file()
    if not overrides:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overrides, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def apply_wiki_env_overrides(overrides: dict[str, str], override_existing: bool = True) -> dict[str, str]:
    applied: dict[str, str] = {}
    for name, value in overrides.items():
        if name not in WIKI_ENV_NAMES:
            continue
        if override_existing:
            os.environ[name] = value
            applied[name] = value
        elif name not in os.environ:
            os.environ[name] = value
            applied[name] = value
    return applied


def apply_stored_wiki_env_overrides(override_existing: bool = False) -> dict[str, str]:
    overrides = load_wiki_env_overrides()
    return apply_wiki_env_overrides(overrides, override_existing=override_existing)


def collect_wiki_env_state() -> list[dict[str, Any]]:
    overrides = load_wiki_env_overrides()
    state: list[dict[str, Any]] = []
    for spec in WIKI_ENV_SPECS:
        current = os.getenv(spec.name)
        current_value = current if current is not None else spec.default
        state.append({
            "name": spec.name,
            "kind": spec.kind,
            "description": spec.description,
            "default_value": spec.default,
            "current_value": current_value,
            "source": "environment" if current is not None else "default",
            "has_override": spec.name in overrides,
            "override_value": overrides.get(spec.name),
            "minimum": spec.minimum,
            "maximum": spec.maximum,
        })
    return state


def update_wiki_env_values(values: dict[str, Optional[str]]) -> dict[str, Any]:
    from core.wiki.bridge import ZOPEDIA_TO_UNSLOTH_MAP, apply_defaults

    overrides = load_wiki_env_overrides()
    updated: list[str] = []
    cleared: list[str] = []
    invalid: dict[str, str] = {}

    for name, incoming in values.items():
        spec = _WIKI_ENV_SPECS_BY_NAME.get(name)
        if spec is None:
            invalid[name] = "Unknown wiki environment variable."
            continue
        if incoming is None or incoming.strip() == "":
            had_value = name in os.environ or name in overrides
            overrides.pop(name, None)
            os.environ.pop(name, None)
            # Also clear the UNSLOTH_* equivalent so apply_defaults can reset its default
            if name in ZOPEDIA_TO_UNSLOTH_MAP:
                os.environ.pop(ZOPEDIA_TO_UNSLOTH_MAP[name], None)
            if had_value:
                cleared.append(name)
            continue
        try:
            normalized = _validate_value(spec, incoming)
        except ValueError as exc:
            invalid[name] = str(exc)
            continue
        overrides[name] = normalized
        os.environ[name] = normalized
        # Propagate to UNSLOTH_* equivalent so the engine sees the change at runtime
        if name in ZOPEDIA_TO_UNSLOTH_MAP:
            os.environ[ZOPEDIA_TO_UNSLOTH_MAP[name]] = normalized
        updated.append(name)

    # Re-apply all defaults so cleared vars get their UNSLOTH_* defaults back
    apply_defaults()
    overrides_path = persist_wiki_env_overrides(overrides)
    return {
        "updated": sorted(set(updated)),
        "cleared": sorted(set(cleared)),
        "invalid": invalid,
        "overrides_file": str(overrides_path),
        "overrides_count": len(overrides),
    }
