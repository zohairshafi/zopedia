# Zopedia

Lightweight personal wiki + RAG chat application. Drop files into `raw/`, chat with your knowledge base.

## Quick Start

```bash
# Install
cd backend && pip install -r requirements.txt
cd ../frontend && npm install && npm run build

# Configure
export ZOPEDIA_LLM_BASE_URL=https://api.deepseek.com/v1
export ZOPEDIA_LLM_API_KEY=sk-...
export ZOPEDIA_LLM_MODEL=deepseek-chat

# Run
cd ../backend && python main.py
# Open http://localhost:8000
```

## Features

- **Wiki ingestion**: Drop PDFs or text files into `wiki_data/raw/` — entities, concepts, and summaries are extracted automatically
- **Tool-calling RAG**: Model uses `read_wiki_page` and `web_search` tools to find information
- **Community-based index pagination**: Wiki pages are clustered into named communities via bipartite graph projection + community detection. The `index-godnodes.md` TOC stays compact regardless of wiki size
- **Web search**: Model can search DuckDuckGo when wiki doesn't have the answer
- **Graph visualization**: Browse wiki knowledge graph (entities, concepts, analysis, sources)
- **Maintenance**: Auto lint, enrich, merge duplicates, archive stale content, compact knowledge pages
- **God-nodes index lifecycle**: New pages land in "Other" section instantly; community detection redistributes them during maintenance cycles

## Environment Variables

### Required
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_LLM_BASE_URL` | — | Upstream OpenAI-compatible API base URL |
| `ZOPEDIA_LLM_API_KEY` | — | API key for upstream API |
| `ZOPEDIA_LLM_MODEL` | — | Upstream model name |

### Wiki & Chat
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_VAULT` | `./wiki_data` | Root wiki vault directory |
| `ZOPEDIA_WIKI_WATCHER` | `true` | Enable background raw-folder watcher |
| `ZOPEDIA_WIKI_AUTO_QUERY_ON_INGEST` | `true` | Auto-generate analysis after ingestion |
| `ZOPEDIA_WIKI_TOOL_RETRIEVAL` | `true` | Use tool-calling for wiki retrieval (disable for legacy RAG) |
| `ZOPEDIA_WIKI_MAX_TOOL_TURNS` | `8` | Max tool-calling turns per chat request |
| `ZOPEDIA_WIKI_MAX_READS_PER_TURN` | `20` | Max wiki reads per tool-calling turn |
| `ZOPEDIA_WIKI_LLM_MAX_TOKENS` | `6000` | Max tokens for wiki analysis/extraction |

### Ingestion
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_PENDING_INGEST_INTERVAL_SECONDS` | `45` | Min seconds between ingest sweeps |
| `ZOPEDIA_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT` | `1` | Max files ingested per chat request (0=off) |

### God-Nodes Index Pagination
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_COMMUNITY_CUTOFF` | `20` | Max nodes per community (controls cluster granularity) |
| `ZOPEDIA_WIKI_COMMUNITY_MIN_SIZE` | `4` | Communities smaller than this merge into Other Pages |

### Maintenance
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_MAX_ANALYSIS_PAGES` | `64` | Max analysis pages per enrich/retry/backlinks operation |
| `ZOPEDIA_WIKI_AUTO_LINT_EVERY` | `10` | Maintenance cadence (every N ingests, 0=off) |
| `ZOPEDIA_WIKI_AUTO_RETRY_FALLBACK_ANALYSES_MAX_PAGES` | `24` | Fallback retry batch size (0=off) |
| `ZOPEDIA_WIKI_MERGE_MAINTENANCE_MAX_MERGES` | `512` | Max merges per maintenance run |
| `ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES` | `10` | Max incremental updates per page before LLM rewrite |
| `ZOPEDIA_WIKI_COMPACTION_MAX_PAGES` | `64` | Max pages LLM-rewritten per maintenance cycle (0=off) |

### Other
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_LLM_TIMEOUT_SECONDS` | `300` | Timeout for upstream API calls |
| `ZOPEDIA_AUTH_DISABLED` | `true` | Disable authentication (single-user mode) |
| `ZOPEDIA_PORT` | `8000` | Server port |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for full prompt table, flow diagrams, maintenance lifecycle, and god-nodes index pagination design.
