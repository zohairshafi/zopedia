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
                                           ├── godnodes/         ← community pages
                                           ├── index.md
                                           ├── index-concise.md
                                           └── index-godnodes.md  ← community TOC
```

## Directory Structure

```
zopedia/
├── backend/
│   ├── main.py              # FastAPI app, lifespan, health, shutdown
│   ├── prompts.py           # Centralized LLM prompt registry (50+ definitions)
│   ├── requirements.txt     # Python deps (fastapi, uvicorn, httpx, networkx, ddgs, watchdog)
│   ├── core/
│   │   ├── llm.py           # Upstream API client, wiki tools, web search, execute_wiki_read
│   │   └── wiki/
│   │       ├── engine.py    # Wiki engine (~10k lines, community detection, enrichment, merge)
│   │       ├── manager.py   # Thin facade over engine
│   │       ├── ingestor.py  # File ingestion (PDF, text)
│   │       ├── watcher.py   # File system watcher + maintenance lifecycle
│   │       ├── runtime_env.py  # Env var definitions (20 vars)
│   │       └── bridge.py    # ZOPEDIA_* → UNSLOTH_* env mapping
│   ├── routes/
│   │   ├── chat.py          # /v1/chat/completions with tool-calling + dynamic system prompt
│   │   └── wiki.py          # Wiki management endpoints (17 endpoints)
│   ├── models/wiki.py       # Pydantic models
│   ├── auth/                # JWT auth (router, storage, authentication, hashing)
│   └── chat_history_store.py  # Server-side chat history (SQLite, per-user)
├── frontend/                # React + Vite + TypeScript
├── graphify/                # Standalone graph analysis library (copied as-is)
└── notebooks/               # Jupyter notebooks for graph exploration
```

## Maintenance Lifecycle

The watcher triggers maintenance every N ingests (`ZOPEDIA_WIKI_AUTO_LINT_EVERY`, default 10):

```
File ingested → analysis run count % 10 == 0 →
  1. lint()                       — Health scan: orphans, stale, broken links, merge candidates
  2. retry_fallback_analysis()    — Re-query analyses that used extractive fallback
  3. enrich_analysis_pages()      — Web gap fill, refresh oldest, enrichment links, link repair
     └─ _rebuild_index_godnodes() — Full community detection (backlinks exist at this point)
  4. refresh_analysis_backlinks() — Update "Referenced by Analyses" sections
  5. _rebuild_index_godnodes()    — Redundant safety net (also triggered from enrich)
```

On every ingest (lightweight):
```
_rebuild_index() → _rebuild_index_concise() → _sync_godnodes_other()
```
`_sync_godnodes_other` appends new entity/concept pages inline to `index-godnodes.md` without running community detection.

## Knowledge Compaction

Entity and concept pages accumulate incremental updates over time. When the number
of update blocks exceeds `ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES` (default 10),
the page is rewritten:

1. **LLM rewrites the entire page**: Consolidates all incremental updates into
   Summary, Facts, and Contradictions. Preserves all [[wikilinks]], dates, timestamps,
   Sources, and Referenced by Analyses sections.
2. **Prioritization**: Pages with the most overflow are compacted first.
3. **Per-cycle cap**: `ZOPEDIA_WIKI_COMPACTION_MAX_PAGES` (default 64) limits how
   many pages are LLM-rewritten per maintenance cycle. 0 disables.
4. **Recent changes**: The last 3 updates are preserved verbatim in a `### Recent Changes` section.

Compaction runs during maintenance cycles (via `enrich_analysis_pages` with
`compact_knowledge_pages=True`) and via the API.

## God-Nodes Index Pagination

### Problem
As the wiki grows, the flat `index-concise.md` (all entity/concept pages) exceeds the LLM's context window.

### Solution
Community-based hierarchical index:

1. **Full link graph** built from ALL pages (entities, concepts, analysis, sources)
2. **Bipartite graph**: entity nodes ↔ (analysis ∪ source) nodes, concept nodes ↔ (analysis ∪ source) nodes
3. **Unipartite projection**: entities connected if they co-occur on the same analysis/source pages
4. **Community detection**: `greedy_modularity_communities` on each projection (cutoff from env var)
5. **Community naming**: LLM names each community (e.g., "ML Infrastructure"), falls back to most-central page title
6. **Output**:
   - `godnodes/{slug}.md` — one file per community listing all member pages
   - `index-godnodes.md` — compact TOC pointing to community files, with "Other" pages listed inline

### Index Format

```markdown
# Wiki Index (Community View)

## Entity Communities
- [[godnodes/ml-infrastructure]] - ML Infrastructure (12 pages)
- [[godnodes/product-team]] - Product Team (8 pages)

## Other Entities
- [[entities/Zeke]] - Intern
- [[entities/new-hire]] - New Hire

## Concept Communities
- [[godnodes/q4-planning]] - Q4 Planning (6 pages)

## Other Concepts
- [[concepts/misc-topic]] - Misc Topic
---
Total: 27 pages in 3 communities. Use read_wiki_page to expand community pages.
```

### How the Model Uses It

1. Scans the compact `index-godnodes.md` TOC
2. Picks a relevant community → calls `read_wiki_page("godnodes/ml-infrastructure")`
3. Gets full member list with summaries → reads individual entity/concept pages
4. Follows `[[wikilinks]]` from entity/concept pages to analysis and source pages

### Config

| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_COMMUNITY_CUTOFF` | 20 | Max number of communities (higher = more granular) |
| `ZOPEDIA_WIKI_COMMUNITY_MIN_SIZE` | 4 | Communities below this → "Other" (listed inline) |
| `ZOPEDIA_WIKI_COMPACTION_MAX_PAGES` | 64 | Max pages LLM-rewritten per maintenance cycle. 0=off. Pages with most overflow prioritized |

## Tool-Calling Protocol (SSE Events)

Following the original Zopedia pattern:

| Event Type | Direction | Purpose |
|---|---|---|
| `tool_status` | Server → Client | Status text (appears in thinking box) |
| `tool_start` | Server → Client | Tool call initiated (name, id, args) |
| `tool_end` | Server → Client | Tool call completed (name, id, result) |
| `reasoning` | Server → Client | CoT/thinking content (DeepSeek) |
| Standard OpenAI chunks | Server → Client | Token-by-token text streaming |

### Available Tools

- **`read_wiki_page(path)`** — Reads any wiki page by path. Full content goes to model; only metadata (`path`, `size_chars`, `preview`) goes to UI.
- **`web_search(query)`** — Searches DuckDuckGo via `ddgs` library. Returns titles, URLs, snippets.

### Tool-Calling Budget

To prevent context window exhaustion from unbounded wiki reads, two caps limit how much page content is loaded:

| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_MAX_CHARS_PER_READ` | 12000 | Max chars per `read_wiki_page` result. Pages truncated to this. 12K chars ≈ 3K tokens. |
| `ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS` | 500000 | Hard stop after cumulative read chars exceed this. 500K chars ≈ 125K tokens. |
| `ZOPEDIA_WIKI_MAX_TOOL_TURNS` | 8 | Max tool-calling turns per request. Each turn can batch multiple reads. |
| `ZOPEDIA_WIKI_MAX_READS_PER_TURN` | 20 | Max wiki reads per tool-calling turn. |

The budget is surfaced in the system prompt so the model can plan its reads. When the cumulative cap is hit mid-turn, remaining tool calls are skipped and the model is forced to synthesize.

For a 1M-token context window targeting ~250-300K usable tokens, recommended values:
```bash
ZOPEDIA_WIKI_MAX_CHARS_PER_READ=16000       # ~4K tokens per page
ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS=800000  # ~200K tokens for tool results
```

### Frontend Tool Toggle

The Search button in the chat composer controls only `web_search`. Wiki (`read_wiki_page`) is always available. The frontend sends:

```json
{
  "enable_tools": true,
  "enabled_tools": ["read_wiki_page", "web_search"]  // or ["read_wiki_page"] when Search off
}
```

## Ingestion Flow

1. File placed in `raw/` → Watcher detects → `Ingestor.ingest_file()`
2. Content read via **MarkItDown** (PDF, DOCX, PPTX, XLSX, HTML, CSV, EPUB, images, audio, ZIP, etc.)
   with plain-text fallback for unsupported formats.
3. `Engine.ingest_source()`:
   - `_extract_from_source()` → LLM extracts entities, concepts, summary
   - Source page written to `sources/`
   - Entity pages upserted to `entities/`
   - Concept pages upserted to `concepts/`
   - `_rebuild_index()` → `index.md` + `index-concise.md` + `_sync_godnodes_other()`
4. Optional auto-analysis: watcher calls `query_rag()` to generate `analysis/` page

## Authentication & Multi-User

### Single-User Mode (default)

`ZOPEDIA_AUTH_DISABLED=true` — the current default. All requests are treated as `"local-user"`. Auth endpoints return hardcoded tokens. Chat history lives entirely in the browser's IndexedDB. No server-side persistence.

### Multi-User Mode

Set `ZOPEDIA_AUTH_DISABLED=false` to enable real authentication:

```
First startup → bootstrap creates "zopedia" admin with diceware passphrase
              → passphrase printed to server logs
User visits   → login form with username + password fields
              → JWT access token (60 min) + refresh token (7 days) returned
              → all API calls include Authorization: Bearer <token>
              → current_subject extracted from JWT, used to scope data
```

**Auth backend** (`backend/auth/`):
- `router.py` — Login, refresh, change-password, register (admin-only) endpoints
- `storage.py` — SQLite-backed user store (`auth_user`, `refresh_tokens`, `api_keys` tables)
- `authentication.py` — JWT creation/validation (HS256), API key support, refresh token flow
- `hashing.py` — PBKDF2-HMAC-SHA256 (100k iterations)

**Chat history store** (`backend/chat_history_store.py`):
- SQLite database alongside `auth.db` at `~/.unsloth/studio/auth/chat_history.db`
- Tables: `chat_threads` (id, username, title, timestamps) and `chat_messages` (id, thread_id, username, role, content, reasoning_content, parent_id)
- All queries scoped by `username` — each user sees only their own threads
- Message content capped at 100KB to prevent SQLite bloat from tool call results

**Frontend sync** (`frontend/src/features/chat/chat-server-sync.ts`):
- Thread list: fire-and-forget merge from server on `list()` (server wins on `updated_at`)
- Thread load: if local IndexedDB is empty, fetch messages from server
- Message append: debounced 2s POST to server after each local write
- Migration: on first sync, if server is empty but IndexedDB has data, auto-import all local threads
- `isAuthDisabled()` guard: all sync operations are no-ops when auth is disabled (token === `"zopedia-local"`)

**Wiki chat history export**: Files saved to `raw/users/{username}/` when auth enabled, `raw/` when disabled. The watcher (`recursive=True`) picks up files from both paths automatically.

### Auth API Endpoints

| Method | Path | Auth Required | Purpose |
|---|---|---|---|
| `GET` | `/api/auth/status` | No | Returns initialized, requires_password_change, auth_disabled |
| `POST` | `/api/auth/login` | No | Validates username/password, returns JWT pair |
| `POST` | `/api/auth/refresh` | No | Validates refresh token, returns new JWT pair |
| `POST` | `/api/auth/change-password` | Yes (allow-pw-change) | Changes password, rotates JWT secret |
| `POST` | `/api/auth/register` | Yes (admin only) | Creates new user (only `"zopedia"` admin) |

### Chat History API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/api/chat/threads` | List threads for current user |
| `GET` | `/v1/api/chat/threads/{id}` | Load thread + messages |
| `POST` | `/v1/api/chat/threads` | Upsert thread + replace all messages |
| `DELETE` | `/v1/api/chat/threads/{id}` | Delete thread |

## All LLM Prompt Locations

All LLM prompts are centralized in [`backend/prompts.py`](backend/prompts.py) — a single registry organized by domain:

| Section | Count | Used by |
|---|---|---|
| **Chat** | 11 | `routes/chat.py` — system prompt fragments, tool usage guides, synthesis, title generation |
| **LLM Helpers** | 11 | `core/llm.py` — JSON mode prompt, tool descriptions, tool parameter descriptions |
| **Research** | 13 | `core/research.py` — survey, query generation, ranking, final summary, title generation |
| **Wiki Engine** | 19 | `core/wiki/engine.py` — extraction, JSON repair, merge planning/writing, compaction, community naming, enrichment, entity intent, chunk merging, index titles, source-first summaries |

**Design**: Prompts are defined as either static constants (no dynamic parameters) or functions (when they need to interpolate variables like `topic`, `today`, `max_rows`, etc.). Each prompt file imports only what it needs. To modify any LLM behaviour, edit `prompts.py` — all call sites pick up the change automatically.

The previous inline prompt locations (pre-centralization) were spread across:

| File | Method | Purpose |
|---|---|---|
| `routes/chat.py` | `openai_chat_completions` | Dynamic system prompt: wiki index, tools, analysis backlinks |
| `routes/chat.py` | `_inject_rag_context` | Legacy pre-injected wiki context (fallback) |
| `core/wiki/engine.py` | `_extract_from_source` | Extract entities/concepts/summary from ingested text |
| `core/wiki/engine.py` | `_try_json_repair` | Repair malformed extraction JSON |
| `core/wiki/engine.py` | `_llm_summarize_updates` | Condense old incremental update blocks |
| `core/wiki/engine.py` | `_llm_rerank_candidates` | LLM re-ranks wiki pages (legacy ranking) |
| `core/wiki/engine.py` | `_llm_select_enrichment_links` | Select enrichment links for analysis pages |
| `core/wiki/engine.py` | `_name_community` (inline in `_rebuild_index_godnodes`) | Name wiki communities |
| `core/wiki/engine.py` | `_llm_plan_web_gap_queries` | Plan web search queries for gap fill |
| `core/wiki/engine.py` | `_llm_select_web_gap_results` | Select best web results for gap fill |
| `core/wiki/engine.py` | `_semantic_filter_missing_or_related_concepts` | Missing concept detection |
| `core/wiki/engine.py` | `_semantic_concept_merge_writeback` | Merge duplicate concepts via LLM |
| `core/wiki/engine.py` | `_entity_query_focus` | Entity intent parsing |
| `core/wiki/engine.py` | `query` | Main wiki Q&A with context |
| `core/llm.py` | `wiki_llm_fn` | Routes ALL wiki engine LLM calls to upstream API |

## Key Design Decisions

1. **Index-based retrieval, not lexical search**: The index (preferably `index-godnodes.md`) is passed as system context. Model picks community pages → expands them → follows wikilinks. No `search_wiki` tool.

2. **Tool results: full content to model, metadata to UI**: `tool_end` SSE events send only `{path, size_chars, preview}`, preventing UI bloat. The model gets full content via `role: "tool"` messages.

3. **Always stream final answer from API**: After tool resolution, the streaming API is always called with `tools=None`. Prevents narration text from being treated as the final answer.

4. **Wiki always available**: The backend always includes `read_wiki_page` in the enabled tool set. The Search toggle controls `web_search` only.

5. **God-nodes on maintenance, not ingest**: Expensive community detection runs during maintenance cycles (after backlinks exist). New pages land in "Other" inline, instantly visible.

6. **Community detection uses full graph**: Bipartite projection preserves multi-hop connections through analysis/source pages. The EC-only graph would miss bridges.

7. **DeepSeek reasoning_content**: All assistant messages preserve `reasoning_content` for DeepSeek compatibility.

8. **Auth disabled by default**: `ZOPEDIA_AUTH_DISABLED=true`. Stub endpoints return fake tokens, all requests treated as `"local-user"`. Chat history stays in browser IndexedDB. When enabled, real JWT auth with SQLite-backed users kicks in, chat history syncs to the server, and data is scoped per-user.

9. **Server-side chat history sync**: When auth is enabled, chat threads and messages are persisted to `chat_history.db` (SQLite, stored alongside `auth.db`). The frontend syncs on thread list load (fire-and-forget merge from server), on thread open (if local is empty), and on message append (debounced 2s POST). Local IndexedDB remains the primary store for responsiveness; the server is the durable copy. Migration from local-only to server is automatic on first sync.
