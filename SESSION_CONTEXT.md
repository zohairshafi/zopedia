# Zopedia — Session Context

## What This Is

Zopedia is a lightweight personal wiki + RAG chat application extracted from Unsloth Studio. It drops all local model training/fine-tuning/serving — only the wiki engine, graphify, and frontend chat UI remain. All LLM calls go through an upstream OpenAI-compatible API (tested with DeepSeek).

**Repo:** `/Users/zohairshafi/Local Workspace/zopedia`  
**Git:** Initialized on `main`, 17 commits.  
**Original source:** `/Users/zohairshafi/Local Workspace/unsloth/studio/`

## Quick Start

```bash
cd zopedia/backend
export ZOPEDIA_LLM_BASE_URL=https://api.deepseek.com/v1
export ZOPEDIA_LLM_API_KEY=sk-...
export ZOPEDIA_LLM_MODEL=deepseek-chat
python main.py
# Open http://localhost:8000
```

Frontend is served from `frontend/dist/` — build with `cd frontend && npm run build`.

## Directory Structure

```
zopedia/
├── backend/
│   ├── main.py              # FastAPI app (lifespan, health, shutdown, auth stubs, model stubs)
│   ├── requirements.txt     # fastapi, uvicorn, pydantic, httpx, watchdog, ddgs
│   ├── core/
│   │   ├── llm.py           # Upstream API client, wiki_llm_fn, tool definitions, web search
│   │   └── wiki/
│   │       ├── engine.py    # Wiki engine (10k lines, copied as-is, zero ML deps)
│   │       ├── manager.py   # Thin facade over engine
│   │       ├── ingestor.py  # File ingestion (PDF, text, graphify integration)
│   │       ├── watcher.py   # File system watcher for raw/ folder
│   │       ├── runtime_env.py  # Env var definitions and UI persistence (18 vars)
│   │       └── bridge.py    # Maps ZOPEDIA_* → UNSLOTH_* env vars with defaults
│   ├── routes/
│   │   ├── chat.py          # /v1/chat/completions — tool-calling + streaming
│   │   └── wiki.py          # Wiki management endpoints (17 endpoints)
│   ├── models/wiki.py       # Pydantic models for all wiki endpoints
│   └── auth/                # Auth system (disabled by default, stubs in main.py)
├── frontend/                # React + Vite + TypeScript (trimmed from original)
├── graphify/                # Standalone graph analysis library (copied as-is)
├── ARCHITECTURE.md          # Flow diagrams, prompt table, SSE protocol
├── README.md                # Features, all env vars documented
└── SESSION_CONTEXT.md       # This file
```

## Environment Variables (18 total)

### Required (for LLM)
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_LLM_BASE_URL` | — | Upstream API endpoint (e.g. `https://api.deepseek.com/v1`) |
| `ZOPEDIA_LLM_API_KEY` | — | API key |
| `ZOPEDIA_LLM_MODEL` | — | Model name (e.g. `deepseek-chat`) |

### Wiki & Ingestion
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_VAULT` | `./wiki_data` | Root wiki vault directory |
| `ZOPEDIA_WIKI_WATCHER` | `true` | Background file watcher for raw/ |
| `ZOPEDIA_WIKI_AUTO_QUERY_ON_INGEST` | `true` | Auto-generate analysis pages after ingestion |
| `ZOPEDIA_WIKI_TOOL_RETRIEVAL` | `true` | Use tool-calling for wiki retrieval (disable for legacy RAG) |
| `ZOPEDIA_WIKI_MAX_TOOL_TURNS` | `8` | Max tool-calling turns (API round-trips) per chat |
| `ZOPEDIA_WIKI_MAX_READS_PER_TURN` | `20` | Max wiki reads per turn (caps batched reads) |
| `ZOPEDIA_WIKI_LLM_MAX_TOKENS` | `6000` | Max tokens for wiki analysis/extraction LLM calls |
| `ZOPEDIA_WIKI_PENDING_INGEST_INTERVAL_SECONDS` | `45` | Min seconds between ingest sweeps during chat |
| `ZOPEDIA_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT` | `1` | Max files ingested per chat request (0=off) |

### Maintenance
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_AUTO_LINT_EVERY` | `10` | Maintenance cadence — every N ingests (0=off) |
| `ZOPEDIA_WIKI_AUTO_RETRY_FALLBACK_ANALYSES_MAX_PAGES` | `24` | Fallback retry batch size (0=off) |
| `ZOPEDIA_WIKI_MERGE_MAINTENANCE_MAX_MERGES` | `512` | Max merges per maintenance run |
| `ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES` | `10` | Max incremental updates before LLM summarization |

### Other
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_LLM_TIMEOUT_SECONDS` | `300` | Timeout for upstream API calls |
| `ZOPEDIA_AUTH_DISABLED` | `true` | Skip authentication (single-user mode) |
| `ZOPEDIA_PORT` | `8000` | Server port |

## Chat Flow (Tool-Calling)

The core chat flow in `routes/chat.py` works in two phases:

### Phase 1: Tool Resolution (non-streaming)
1. System prompt is injected with the wiki index (`index-concise.md`) and tool budget info
2. Model calls `read_wiki_page(path)` or `web_search(query)` as needed
3. Each tool call emits SSE events: `tool_status`, `tool_start`, `tool_end`
4. Tool results (full page content) are appended to messages
5. Loop continues until model returns text without tool calls, or hits max_turns
6. If budget exhausted, a nudge message is added to force synthesis

### Phase 2: Final Answer (streaming)
1. Any non-tool-call assistant message is popped (narration text)
2. A synthesis instruction is appended: "Now synthesize a complete answer..."
3. API is called with `tools=None` for token-by-token streaming
4. Reasoning/CoT content is forwarded as `delta.reasoning_content`

### SSE Event Protocol (matches original Unsloth pattern)
| Event | Direction | Purpose |
|---|---|---|
| `tool_status` | Server→Client | Status text, CoT thinking, read progress |
| `tool_start` | Server→Client | Tool call initiated (name, id, args) |
| `tool_end` | Server→Client | Tool call completed (name, id, result metadata only) |
| Standard OpenAI chunks | Server→Client | Token-by-token text + reasoning_content |

### Available Tools
- **`read_wiki_page(path)`** — reads any wiki page by path. Full content goes to model; only metadata (`path`, `size_chars`, `preview`) goes to UI.
- **`web_search(query)`** — searches DuckDuckGo via `ddgs` library. Returns titles, URLs, snippets.

## Key Design Decisions

1. **Index-based retrieval, not lexical search**: The `index-concise.md` (entities + concepts only) is passed as system context. Model picks pages directly — no `search_wiki` tool, no lexical scoring. Eliminates `_rank_pages` complexity for the primary path. Legacy `_rank_pages` still exists as fallback.

2. **Analysis backlinks in entity/concept pages**: Entity and concept pages have `## Referenced by Analyses` sections with wikilinks. System prompt tells model to follow these. Model discovers analysis pages recursively through entity→analysis links.

3. **Tool results: full content to model, metadata to UI**: `tool_end` SSE events send only `{path, size_chars, preview}` — not full page content. This prevents UI bloat and keeps saved chat history manageable. The model gets full content via the `role: "tool"` message in the conversation.

4. **Always stream final answer from API**: After tool resolution, the streaming API is always called (with `tools=None`). We never directly stream the non-streaming answer, because the model's "narration" text (e.g., "Let me check...") was being treated as the final answer, causing hallucinations.

5. **No `list(messages)` copy bug**: A critical bug was fixed where `list(messages)` created a copy — tool results were appended to the copy but the streaming API call used the original. Changed to pass `messages` directly. Commit `145d731`.

6. **DeepSeek reasoning_content**: All assistant messages preserve `reasoning_content` for DeepSeek compatibility. The streaming path forwards `delta.reasoning_content`.

7. **Incremental updates summarization**: When `ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES` (default 10) is reached, older updates are summarized by the LLM into a single `### Summarised Updates` block. New updates continue being added individually. Old updates are NOT merged — the LLM creates a fresh summary.

8. **16 env vars → 18 env vars**: Reduced from original 68 Unsloth env vars. Added `ZOPEDIA_WIKI_MAX_TOOL_TURNS` and `ZOPEDIA_WIKI_MAX_READS_PER_TURN`.

9. **Auth disabled by default**: `ZOPEDIA_AUTH_DISABLED=true`. Stub endpoints return fake tokens. Chat endpoint works without any `Authorization` header.

10. **Model selector replaced with config button**: `UpstreamConfigButton` shows current provider/model and lets user edit Base URL, API Key, Model via popover. Posts to `/api/inference/wiki/env` to update and triggers restart.

## Frontend Changes from Original

- **Removed**: Training, export, data recipes, recipe studio, onboarding features/routes
- **Removed**: Model selector dropdown (replaced with UpstreamConfigButton)
- **Removed**: Sampling section, Tools section, Upstream Backend toggle from settings
- **Removed**: HF token, Start onboarding from Settings > General
- **Removed**: Learn More, What's New, Feedback, Guided Tour from sidebar footer
- **Removed**: Auto-title button from thread toolbar (kept in chat page top bar)
- **Removed**: Compare nav item from sidebar
- **Removed**: Train, Recipes, Export nav items from sidebar
- **Changed**: All "Unsloth" → "Zopedia" in user-facing text
- **Changed**: `initialUseUpstream = true` in chat-runtime-store (always upstream)
- **Changed**: Wiki behaviour dialog expected env count set to 0 (disables mismatch warning)
- **Changed**: `sk-unsloth-` → `sk-zopedia-` in usage examples
- **Added**: `UpstreamConfigButton` component (env var editor popover)
- **Added**: Green status dot on upstream config button
- **Added**: `/api/shutdown` endpoint

## Files Copied As-Is (Zero Modifications)

- `backend/core/wiki/engine.py` (10k lines — only 2 path fixes: `parents[4]` → `parents[3]` for graphify import)
- `backend/core/wiki/manager.py`
- `backend/core/wiki/ingestor.py` (only parents path fix)
- `backend/core/wiki/watcher.py`
- `backend/auth/` (all 4 files — not actively used, auth is stubbed)
- `graphify/` (entire directory)

## Key Files That Were Heavily Modified

- `backend/routes/chat.py` — Complete rewrite: tool-calling loop, SSE events, streaming, web search, system prompt
- `backend/core/llm.py` — Tool definitions, wiki_llm_fn, web search, execute_wiki_read
- `backend/main.py` — Auth stubs, model stubs, health endpoint, shutdown, restart support
- `backend/core/wiki/runtime_env.py` — Reduced from 68 to 18 env specs
- `backend/core/wiki/bridge.py` — New file: ZOPEDIA_* → UNSLOTH_* mapping
- `backend/routes/wiki.py` — Chat history save, archive, wiki management endpoints
- `backend/models/wiki.py` — New file: extracted wiki Pydantic models
- `frontend/src/components/app-sidebar.tsx` — Removed training nav, Compare, footer links
- `frontend/src/components/upstream-config-button.tsx` — New file: env editor popover
- `frontend/src/features/chat/chat-page.tsx` — Replaced ModelSelector with UpstreamConfigButton
- `frontend/src/features/chat/stores/chat-runtime-store.ts` — `initialUseUpstream = true`
- `frontend/src/features/chat/chat-settings-sheet.tsx` — Removed Upstream toggle, Sampling, Tools
- `frontend/src/features/settings/tabs/about-tab.tsx` — Rewritten: removed Unsloth links
- `frontend/src/features/settings/tabs/general-tab.tsx` — Removed HF token, onboarding
- `frontend/src/features/profile/hooks/use-effective-profile.ts` — Null guard on displayName
- `frontend/src/features/profile/utils/avatar-initials.ts` — Null guard on name parameter
- `frontend/src/components/assistant-ui/thread.tsx` — Removed AutoTitleToggle, null guard on models

## Pending / Known Issues

1. **API Keys section in Settings** — Frontend calls `/api/auth/api-keys` endpoints which don't exist (auth router not mounted). Currently cosmetic since auth is disabled.

2. **Web search reliability** — Uses `ddgs` library (DuckDuckGo). May occasionally return 0 results or rate-limit errors (HTTP 202). Works well most of the time.

3. **Tool-calling visibility** — The tool resolution progress events work, but the frontend's `chat-adapter.ts` expects `_toolEvent` and `_toolStatus` properties on chunks. The current SSE events (`tool_status`, `tool_start`, `tool_end`) may not be fully rendered by the frontend's tool UI components.

4. **No `python` or `wiki_search` tools** — Only `read_wiki_page` and `web_search` are implemented. The `enable_tools` / `enabled_tools` request parameters are silently ignored.

5. **Analysis file truncation** — If `ZOPEDIA_WIKI_LLM_MAX_TOKENS` is too low, analysis output gets cut off mid-word. Default 6000 should be sufficient for most cases.

## Git History

```
33879f9 Clean up UI, add shutdown endpoint, create docs
ad7955d Add web_search tool alongside read_wiki_page
2aee1a7 Switch web search to ddgs library
1a4ba53 Fix urllib.parse.quote import in web_search
72b2f4b Add tool budget to system prompt
a2c61c5 Add ZOPEDIA_WIKI_MAX_READS_PER_TURN env var (default 20)
f4d6295 Remove HF token and onboarding from General tab
145d731 Fix tool results not reaching final streaming call (list() copy bug)
8efcbf8 Add max tool turns env var, tool info in thinking box
fe4df93 Add budget-exhausted nudge when tool-calling hits max turns
e8810f7 Fix UnboundLocalError in tool-calling stream closure
5b67b9c Initial commit
```

## Running Notes

- Frontend build: `cd frontend && npm run build` (outputs to `dist/`)
- Backend serves frontend from `ZOPEDIA_FRONTEND_DIR` (default `../frontend/dist`)
- Python version: 3.10 (uses `from __future__ import annotations`)
- Wiki data excluded from git via `.gitignore` (`backend/wiki_data/`)
- `node_modules/`, `dist/`, `__pycache__/`, `.DS_Store` all in `.gitignore`
