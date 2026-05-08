# Zopedia Architecture

## Flow Overview

```
User → Frontend (React + Vite) → /v1/chat/completions → Chat Route
                                                                │
                                                    ┌───────────┴───────────┐
                                                    │  Tool Retrieval Path   │
                                                    │  (ZOPEDIA_WIKI_TOOL_  │
                                                    │   RETRIEVAL=true)      │
                                                    └───────────┬───────────┘
                                                                │
                                    ┌───────────────────────────┴───────────────────────────┐
                                    │  Phase 1: Tool Resolution (non-streaming)              │
                                    │  Model calls read_wiki_page / web_search as needed     │
                                    │  Events: tool_status, tool_start, tool_end → SSE       │
                                    └───────────────────────────┬───────────────────────────┘
                                                                │
                                    ┌───────────────────────────┴───────────────────────────┐
                                    │  Phase 2: Final Answer (streaming)                    │
                                    │  API called with tools=None, full CoT visibility       │
                                    │  Token-by-token output via SSE                         │
                                    └───────────────────────────────────────────────────────┘

Files → raw/ → Watcher → Ingestor → Engine (extract entities/concepts)
                    │                              │
                    ▼                              ▼
            wiki_data/raw/                  wiki_data/wiki/
                                           ├── entities/
                                           ├── concepts/
                                           ├── analysis/
                                           ├── sources/
                                           ├── index.md
                                           └── index-concise.md
```

## Directory Structure

```
zopedia/
├── backend/
│   ├── main.py              # FastAPI app, lifespan, health, shutdown
│   ├── requirements.txt     # Python deps
│   ├── core/
│   │   ├── llm.py           # Upstream API client, wiki tools, web search
│   │   └── wiki/
│   │       ├── engine.py    # Wiki engine (10k lines, zero ML deps)
│   │       ├── manager.py   # Thin facade over engine
│   │       ├── ingestor.py  # File ingestion (PDF, text)
│   │       ├── watcher.py   # File system watcher for raw/
│   │       ├── runtime_env.py  # Env var definitions (17 vars)
│   │       └── bridge.py    # ZOPEDIA_* → UNSLOTH_* env mapping
│   ├── routes/
│   │   ├── chat.py          # /v1/chat/completions with tool-calling
│   │   └── wiki.py          # Wiki management endpoints
│   ├── models/wiki.py       # Pydantic models
│   └── auth/                # Stub auth (disabled by default)
├── frontend/                # React + Vite + TypeScript
├── graphify/                # Standalone graph analysis library
└── scripts/setup.sh
```

## All LLM Prompt Locations

| File | Line | Method | Purpose |
|---|---|---|---|
| `routes/chat.py` | 308 | Chat system prompt | Wiki index, tools, analysis backlinks, path rules |
| `routes/chat.py` | 112 | Legacy RAG prompt | Pre-injected wiki context (fallback) |
| `core/wiki/engine.py` | 4756 | `_extract_from_source` | Extract entities/concepts/summary from ingested text |
| `core/wiki/engine.py` | 4847 | `_try_json_repair` | Repair malformed extraction JSON |
| `core/wiki/engine.py` | 6018 | `_llm_summarize_updates` | Condense old incremental update blocks |
| `core/wiki/engine.py` | 7338 | `_llm_rerank_candidates` | LLM re-ranks wiki pages (legacy) |
| `core/wiki/engine.py` | 7664 | `_planner_index_text` | Build index for rerank planner (legacy) |
| `core/wiki/engine.py` | 8383 | `_entity_query_focus` | Entity intent parsing |
| `core/wiki/engine.py` | 8650 | `_llm_select_link_expansion_targets` | Select wikilinks to follow (legacy) |
| `core/wiki/engine.py` | 9179 | `query` | Main wiki Q&A with context |
| `core/wiki/engine.py` | 1595 | `_extractive_query_answer` | Extractive fallback from cited context |
| `core/wiki/engine.py` | 3871 | `_semantic_filter_missing_or_related_concepts` | Missing concept detection |
| `core/wiki/engine.py` | 3971 | `_semantic_concept_merge_candidates` | Merge candidate planning |
| `core/wiki/engine.py` | 4210 | `_semantic_concept_merge_writeback` | Merge writeback |
| `core/wiki/engine.py` | 5559 | `_index_title_with_llm` | Index title generation |
| `core/wiki/engine.py` | 5719 | `_enrichment_llm_selector` | Enrichment link selection |
| `core/wiki/engine.py` | 5864 | `_web_gap_fill_query_planner` | Web gap-fill planning |
| `core/llm.py` | 125 | `wiki_llm_fn` | Routes ALL wiki engine calls to upstream API |

## Tool-Calling Protocol (SSE Events)

Following the original Unsloth pattern:

| Event Type | Direction | Purpose |
|---|---|---|
| `tool_status` | Server → Client | Status text (appears in thinking box) |
| `tool_start` | Server → Client | Tool call initiated (name, id, args) |
| `tool_end` | Server → Client | Tool call completed (name, id, result) |
| `reasoning` | Server → Client | CoT/thinking content (DeepSeek) |
| Standard OpenAI chunks | Server → Client | Token-by-token text streaming |

## Ingestion Flow

1. File placed in `raw/` → Watcher detects → `Ingestor.ingest_file()`
2. Content read (PDF via PyMuPDF or text)
3. `Engine.ingest_source()`:
   - `_extract_from_source()` → LLM extracts entities, concepts, summary
   - Source page written to `sources/`
   - Entity pages upserted to `entities/`
   - Concept pages upserted to `concepts/`
   - `_rebuild_index()` → `index.md` + `index-concise.md`
4. Optional auto-analysis: watcher calls `query_rag()` to generate `analysis/` page
