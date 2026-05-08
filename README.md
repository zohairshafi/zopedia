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
- **RAG chat**: Chat with your wiki using `read_wiki_page` tool-calling
- **Web search**: Model can search DuckDuckGo when wiki doesn't have the answer
- **Graph visualization**: Browse wiki knowledge graph (entities, concepts, analysis, sources)
- **Maintenance**: Lint, enrich, merge duplicate pages, archive stale content

## Environment Variables

### Required
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_LLM_BASE_URL` | — | Upstream OpenAI-compatible API base URL |
| `ZOPEDIA_LLM_API_KEY` | — | API key for upstream API |
| `ZOPEDIA_LLM_MODEL` | — | Upstream model name |

### Wiki
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_VAULT` | `./wiki_data` | Root wiki vault directory |
| `ZOPEDIA_WIKI_WATCHER` | `true` | Enable background raw-folder watcher |
| `ZOPEDIA_WIKI_AUTO_QUERY_ON_INGEST` | `true` | Auto-generate analysis after ingestion |
| `ZOPEDIA_WIKI_TOOL_RETRIEVAL` | `true` | Use tool-calling for wiki retrieval |
| `ZOPEDIA_WIKI_MAX_TOOL_TURNS` | `8` | Max tool calls per chat request |
| `ZOPEDIA_WIKI_LLM_MAX_TOKENS` | `6000` | Max tokens for wiki analysis/extraction |

### Ingestion
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_PENDING_INGEST_INTERVAL_SECONDS` | `45` | Min seconds between ingest sweeps |
| `ZOPEDIA_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT` | `1` | Max files ingested per chat request (0=off) |

### Maintenance
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_WIKI_AUTO_LINT_EVERY` | `10` | Maintenance cadence (every N ingests, 0=off) |
| `ZOPEDIA_WIKI_AUTO_RETRY_FALLBACK_ANALYSES_MAX_PAGES` | `24` | Fallback retry batch size (0=off) |
| `ZOPEDIA_WIKI_MERGE_MAINTENANCE_MAX_MERGES` | `512` | Max merges per maintenance run |
| `ZOPEDIA_WIKI_KNOWLEDGE_MAX_INCREMENTAL_UPDATES` | `10` | Max incremental updates per page before LLM summarization |

### Other
| Variable | Default | Description |
|---|---|---|
| `ZOPEDIA_LLM_TIMEOUT_SECONDS` | `300` | Timeout for upstream API calls |
| `ZOPEDIA_AUTH_DISABLED` | `true` | Disable authentication (single-user mode) |
| `ZOPEDIA_PORT` | `8000` | Server port |

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full prompt table, flow diagrams, and directory structure.
