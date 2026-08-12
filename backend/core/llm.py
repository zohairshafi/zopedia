"""Upstream LLM client for Zopedia. All LLM calls go through an OpenAI-compatible API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from urllib.parse import quote
import time
from typing import Any, Callable, Optional

import httpx

from prompts import (
    LLM_JSON_MODE_PROMPT,
    TOOL_DESC_ALPACA_MARKET_DATA,
    TOOL_DESC_ALPACA_NEWS,
    TOOL_DESC_DESCRIBE_DATABASE_SCHEMA,
    TOOL_DESC_EXECUTE_SQL as _tool_desc_execute_sql,
    TOOL_DESC_READ_WIKI_PAGE,
    TOOL_DESC_SEARCH_WIKI,
    TOOL_DESC_WEB_SEARCH,
    TOOL_PARAM_ALPACA_END_DESC,
    TOOL_PARAM_ALPACA_EXPIRATION_DESC,
    TOOL_PARAM_ALPACA_LIMIT_DESC,
    TOOL_PARAM_ALPACA_NEWS_INCLUDE_CONTENT_DESC,
    TOOL_PARAM_ALPACA_NEWS_LIMIT_DESC,
    TOOL_PARAM_ALPACA_NEWS_SYMBOLS_DESC,
    TOOL_PARAM_ALPACA_OPTION_TYPE_DESC,
    TOOL_PARAM_ALPACA_PAGE_TOKEN_DESC,
    TOOL_PARAM_ALPACA_START_DESC,
    TOOL_PARAM_ALPACA_STRIKE_GTE_DESC,
    TOOL_PARAM_ALPACA_STRIKE_LTE_DESC,
    TOOL_PARAM_ALPACA_SYMBOL_DESC,
    TOOL_PARAM_ALPACA_TIMEFRAME_DESC,
    TOOL_PARAM_ALPACA_TYPE_DESC,
    TOOL_PARAM_PATH_DESC,
    TOOL_PARAM_SQL_QUERY_DESC,
    TOOL_PARAM_TABLE_NAME_DESC,
    TOOL_PARAM_WEB_QUERY_DESC,
    TOOL_PARAM_WIKI_QUERY_DESC,
)

logger = logging.getLogger(__name__)

# ── Config from environment ────────────────────────────────────────


def _env_str(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    val = os.getenv(name, "").strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


_LLM_BASE_URL = _env_str("ZOPEDIA_LLM_BASE_URL")
_LLM_API_KEY = _env_str("ZOPEDIA_LLM_API_KEY")
_LLM_MODEL = _env_str("ZOPEDIA_LLM_MODEL", "default")
_LLM_TIMEOUT_SECONDS = _env_int("ZOPEDIA_LLM_TIMEOUT_SECONDS", 300)
_WIKI_LLM_MAX_TOKENS = _env_int("ZOPEDIA_WIKI_LLM_MAX_TOKENS", 6000)
_BRAVE_API_KEY = _env_str("ZOPEDIA_BRAVE_API_KEY")
_ALPACA_API_KEY = _env_str("ZOPEDIA_ALPACA_API_KEY")
_ALPACA_API_SECRET = _env_str("ZOPEDIA_ALPACA_API_SECRET")
_DATABASE_URL = _env_str("ZOPEDIA_DATABASE_URL")
_DB_MAX_ROWS = _env_int("ZOPEDIA_DB_MAX_ROWS", 100)
_DB_TIMEOUT_SECONDS = _env_int("ZOPEDIA_DB_TIMEOUT_SECONDS", 10)


def refresh_llm_config():
    """Re-read LLM config from os.environ (for soft reload after Apply and Restart)."""
    global _LLM_BASE_URL, _LLM_API_KEY, _LLM_MODEL, _LLM_TIMEOUT_SECONDS, _WIKI_LLM_MAX_TOKENS
    global _BRAVE_API_KEY, _ALPACA_API_KEY, _ALPACA_API_SECRET, _DATABASE_URL, _DB_MAX_ROWS, _DB_TIMEOUT_SECONDS
    _LLM_BASE_URL = _env_str("ZOPEDIA_LLM_BASE_URL")
    _LLM_API_KEY = _env_str("ZOPEDIA_LLM_API_KEY")
    _LLM_MODEL = _env_str("ZOPEDIA_LLM_MODEL", "default")
    _LLM_TIMEOUT_SECONDS = _env_int("ZOPEDIA_LLM_TIMEOUT_SECONDS", 300)
    _WIKI_LLM_MAX_TOKENS = _env_int("ZOPEDIA_WIKI_LLM_MAX_TOKENS", 6000)
    _BRAVE_API_KEY = _env_str("ZOPEDIA_BRAVE_API_KEY")
    _ALPACA_API_KEY = _env_str("ZOPEDIA_ALPACA_API_KEY")
    _ALPACA_API_SECRET = _env_str("ZOPEDIA_ALPACA_API_SECRET")
    _DATABASE_URL = _env_str("ZOPEDIA_DATABASE_URL")
    _DB_MAX_ROWS = _env_int("ZOPEDIA_DB_MAX_ROWS", 100)
    _DB_TIMEOUT_SECONDS = _env_int("ZOPEDIA_DB_TIMEOUT_SECONDS", 10)


def _normalize_base_url(url: str) -> str:
    normalized = url.rstrip("/")
    if not normalized:
        return ""
    if normalized.lower().endswith("/v1"):
        return normalized
    return f"{normalized}/v1"


def _base_url() -> str:
    return _normalize_base_url(_LLM_BASE_URL)


def llm_available() -> bool:
    return bool(_base_url() and _LLM_API_KEY)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {_LLM_API_KEY}"}


# ── Wiki LLM function ──────────────────────────────────────────────


def _wants_structured_json(prompt: str) -> bool:
    normalized = re.sub(r"\s+", " ", (prompt or "").strip().lower())
    if not normalized:
        return False
    if "json repair assistant" in normalized:
        return True
    strict_patterns = (
        "return strict json with keys",
        "return strict json only with this schema",
        "return strict json only with schema",
        "return strict json only",
        "return strict json",
        "return exactly one json object",
    )
    if any(pattern in normalized for pattern in strict_patterns):
        return True
    if "strict json" in normalized and ("schema" in normalized or "keys" in normalized):
        return True
    if "json object" in normalized and "schema" in normalized and "return" in normalized:
        return True
    return False


def _normalize_structured_json_text(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return raw
    except Exception:
        pass
    fenced = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.IGNORECASE)
    if fenced:
        candidate = fenced.group(1).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return candidate
        except Exception:
            pass
    candidate_match = re.search(r"\{[\s\S]*\}", raw, flags=re.S)
    if candidate_match:
        candidate = candidate_match.group(0).strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return candidate
        except Exception:
            pass
    return raw


def wiki_llm_fn(prompt: str) -> str:
    """Call the upstream LLM for wiki operations. Falls back to returning the prompt if unavailable."""
    if not llm_available():
        logger.warning("Wiki LLM called but no upstream API configured. Returning prompt as-is.")
        return prompt

    wants_json = _wants_structured_json(prompt)
    max_tokens = max(_WIKI_LLM_MAX_TOKENS, 2000) if wants_json else _WIKI_LLM_MAX_TOKENS
    temperature = 0.0 if wants_json else 0.2

    target_url = f"{_base_url()}/chat/completions"

    bodies: list[dict[str, Any]] = []
    base_body: dict[str, Any] = {
        "model": _LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }

    if wants_json:
        strict_body = dict(base_body)
        strict_body["messages"] = [
            {"role": "system", "content": LLM_JSON_MODE_PROMPT},
            {"role": "user", "content": prompt},
        ]
        strict_body["response_format"] = {"type": "json_object"}
        bodies = [strict_body, base_body]
    else:
        bodies = [base_body]

    for attempt_idx, body in enumerate(bodies, start=1):
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=_LLM_TIMEOUT_SECONDS) as client:
                response = client.post(target_url, json=body, headers=_headers())
        except Exception as exc:
            logger.warning("Upstream wiki LLM call failed (attempt=%d): %s", attempt_idx, exc)
            continue

        if response.status_code != 200:
            logger.warning("Upstream wiki LLM returned status %s (attempt=%d): %s", response.status_code, attempt_idx, response.text[:240])
            continue

        try:
            data = response.json()
        except Exception as exc:
            logger.warning("Upstream wiki LLM returned invalid JSON envelope (attempt=%d): %s", attempt_idx, exc)
            continue

        choices = data.get("choices") or [{}]
        content = ""
        if choices and isinstance(choices[0], dict):
            msg = choices[0].get("message") or {}
            if isinstance(msg, dict):
                content = msg.get("content", "")
        if not content:
            content = data.get("output_text", data.get("text", ""))

        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            content = "".join(parts)

        content = str(content or "").strip()

        if wants_json and content:
            content = _normalize_structured_json_text(content)

        if content:
            elapsed = time.perf_counter() - started
            logger.info("Upstream wiki LLM call succeeded (attempt=%d, %.1fs, %d chars)", attempt_idx, elapsed, len(content))
            return content

    logger.warning("All upstream wiki LLM attempts failed. Returning prompt as fallback.")
    return prompt


# ── Chat completions (streaming) ────────────────────────────────────


def _openai_choice_text(choice: dict) -> str:
    msg = choice.get("message") or choice.get("delta") or {}
    if isinstance(msg, dict):
        content = msg.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(part.get("text", ""))
            return "".join(parts)
    return ""


async def chat_completions_stream(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    thinking: dict[str, Any] | None = None,
) -> Any:
    """Stream chat completions from upstream API. Yields SSE text chunks and tool call events."""
    if not llm_available():
        yield {"type": "error", "message": "No upstream LLM configured. Set ZOPEDIA_LLM_BASE_URL and ZOPEDIA_LLM_API_KEY."}
        return

    target_url = f"{_base_url()}/chat/completions"
    resolved_model = model or _LLM_MODEL

    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if tools:
        body["tools"] = tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
    if thinking:
        body["thinking"] = thinking

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
        async with client.stream("POST", target_url, json=body, headers=_headers()) as response:
            if response.status_code != 200:
                text = await response.aread()
                yield {"type": "error", "message": f"Upstream API error {response.status_code}: {text.decode()[:500]}"}
                return

            tool_calls_acc: dict[int, dict[str, Any]] = {}
            last_usage: dict[str, Any] | None = None
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data_str = line[6:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if data.get("usage"):
                    last_usage = data["usage"]

                choices = data.get("choices") or []
                for choice in choices:
                    delta = choice.get("delta") or {}

                    # Reasoning / thinking content (DeepSeek, Claude, etc.)
                    reasoning = delta.get("reasoning_content", "")
                    if reasoning:
                        yield {"type": "reasoning", "content": reasoning}

                    # Text content
                    content = delta.get("content", "")
                    if content:
                        yield {"type": "text", "content": content}

                    # Tool calls
                    tc_list = delta.get("tool_calls") or []
                    for tc in tc_list:
                        idx = tc.get("index", 0)
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.get("id", ""),
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            }
                        if tc.get("id"):
                            tool_calls_acc[idx]["id"] = tc["id"]
                        func = tc.get("function") or {}
                        if func.get("name"):
                            tool_calls_acc[idx]["function"]["name"] += func["name"]
                        if func.get("arguments"):
                            tool_calls_acc[idx]["function"]["arguments"] += func["arguments"]

                    finish_reason = choice.get("finish_reason", "")
                    if finish_reason == "tool_calls" and tool_calls_acc:
                        for tc_entry in sorted(tool_calls_acc.values(), key=lambda x: x.get("id", "")):
                            yield {"type": "tool_call", "tool_call": tc_entry}
                        tool_calls_acc.clear()

            # Emit any remaining tool calls
            if tool_calls_acc:
                for tc_entry in sorted(tool_calls_acc.values(), key=lambda x: x.get("id", "")):
                    yield {"type": "tool_call", "tool_call": tc_entry}

            if last_usage:
                yield {"type": "usage", "usage": last_usage}


async def chat_completions_non_streaming(
    messages: list[dict[str, Any]],
    *,
    model: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    tools: list[dict[str, Any]] | None = None,
    response_format: dict[str, Any] | None = None,
    thinking: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Non-streaming chat completion from upstream API."""
    if not llm_available():
        return {"error": "No upstream LLM configured."}

    target_url = f"{_base_url()}/chat/completions"
    resolved_model = model or _LLM_MODEL

    body: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
    if response_format:
        body["response_format"] = response_format
    if thinking:
        body["thinking"] = thinking

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
        response = await client.post(target_url, json=body, headers=_headers())
        if response.status_code != 200:
            return {"error": f"Upstream API error {response.status_code}: {response.text[:500]}"}
        try:
            return response.json()
        except Exception as exc:
            return {"error": f"Failed to parse response: {exc}"}


def extract_content(response: dict[str, Any]) -> str:
    """Extract the assistant's text content from an OpenAI-compatible response.

    Handles both the raw API format (choices[0].message.content) and
    simplified formats that already have 'content' at the top level.
    """
    # Already extracted (our simplified format)
    if "content" in response and "choices" not in response:
        return str(response.get("content", "") or "")

    # OpenAI-compatible format
    choices = response.get("choices") or [{}]
    content = ""
    if choices and isinstance(choices[0], dict):
        choice = choices[0]
        msg = choice.get("message") or {}
        if isinstance(msg, dict):
            content = msg.get("content", "")
        # DeepSeek sometimes puts content at choice level or uses reasoning_content
        if not content:
            content = choice.get("text", choice.get("content", ""))
        # Check finish_reason for clues
        finish = choice.get("finish_reason", "")
        if not content and finish:
            logger = logging.getLogger(__name__)
            logger.warning(
                "LLM response: empty content, finish_reason=%r, choice keys=%s",
                finish, list(choice.keys()),
            )
    if not content:
        content = response.get("output_text", response.get("text", ""))

    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(part.get("text", ""))
        content = "".join(parts)

    return str(content or "").strip()


# ── Wiki Tool Definitions ──────────────────────────────────────────

WIKI_READ_PAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_wiki_page",
        "description": TOOL_DESC_READ_WIKI_PAGE,
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": TOOL_PARAM_PATH_DESC,
                },
            },
            "required": ["path"],
        },
    },
}

WIKI_WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": TOOL_DESC_WEB_SEARCH,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": TOOL_PARAM_WEB_QUERY_DESC,
                },
            },
            "required": ["query"],
        },
    },
}

WIKI_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_wiki",
        "description": TOOL_DESC_SEARCH_WIKI,
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": TOOL_PARAM_WIKI_QUERY_DESC,
                },
            },
            "required": ["query"],
        },
    },
}

WIKI_TOOLS = [WIKI_READ_PAGE_TOOL, WIKI_WEB_SEARCH_TOOL, WIKI_SEARCH_TOOL]

# ── Database tools (PostgreSQL) ────────────────────────────────────

DESCRIBE_DATABASE_SCHEMA_TOOL = {
    "type": "function",
    "function": {
        "name": "describe_database_schema",
        "description": TOOL_DESC_DESCRIBE_DATABASE_SCHEMA,
        "parameters": {
            "type": "object",
            "properties": {
                "table_name": {
                    "type": "string",
                    "description": TOOL_PARAM_TABLE_NAME_DESC,
                },
            },
            "required": [],
        },
    },
}

EXECUTE_SQL_TOOL = {
    "type": "function",
    "function": {
        "name": "execute_sql_query",
        "description": _tool_desc_execute_sql(_DB_MAX_ROWS),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": TOOL_PARAM_SQL_QUERY_DESC,
                },
            },
            "required": ["query"],
        },
    },
}

DB_TOOLS = [DESCRIBE_DATABASE_SCHEMA_TOOL, EXECUTE_SQL_TOOL]

# ── Alpaca Market Data tool ─────────────────────────────────────────

ALPACA_MARKET_DATA_TOOL = {
    "type": "function",
    "function": {
        "name": "alpaca_market_data",
        "description": TOOL_DESC_ALPACA_MARKET_DATA,
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_SYMBOL_DESC,
                },
                "type": {
                    "type": "string",
                    "enum": ["quote", "bars", "snapshot", "options_chain"],
                    "description": TOOL_PARAM_ALPACA_TYPE_DESC,
                },
                "timeframe": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_TIMEFRAME_DESC,
                },
                "limit": {
                    "type": "integer",
                    "description": TOOL_PARAM_ALPACA_LIMIT_DESC,
                },
                "start": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_START_DESC,
                },
                "end": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_END_DESC,
                },
                "expiration_date": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_EXPIRATION_DESC,
                },
                "strike_gte": {
                    "type": "number",
                    "description": TOOL_PARAM_ALPACA_STRIKE_GTE_DESC,
                },
                "strike_lte": {
                    "type": "number",
                    "description": TOOL_PARAM_ALPACA_STRIKE_LTE_DESC,
                },
                "option_type": {
                    "type": "string",
                    "enum": ["call", "put"],
                    "description": TOOL_PARAM_ALPACA_OPTION_TYPE_DESC,
                },
                "page_token": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_PAGE_TOKEN_DESC,
                },
            },
            "required": ["symbol", "type"],
        },
    },
}

ALPACA_NEWS_TOOL = {
    "type": "function",
    "function": {
        "name": "alpaca_news",
        "description": TOOL_DESC_ALPACA_NEWS,
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_NEWS_SYMBOLS_DESC,
                },
                "start": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_START_DESC,
                },
                "end": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_END_DESC,
                },
                "limit": {
                    "type": "integer",
                    "description": TOOL_PARAM_ALPACA_NEWS_LIMIT_DESC,
                },
                "include_content": {
                    "type": "boolean",
                    "description": TOOL_PARAM_ALPACA_NEWS_INCLUDE_CONTENT_DESC,
                },
                "page_token": {
                    "type": "string",
                    "description": TOOL_PARAM_ALPACA_PAGE_TOKEN_DESC,
                },
            },
            "required": [],
        },
    },
}

ALPACA_TOOLS = [ALPACA_MARKET_DATA_TOOL, ALPACA_NEWS_TOOL]


async def execute_web_search(query: str, max_results: int = 5, timelimit: str = "m") -> str:
    """Search the web using the Brave Search API and return JSON results.

    Requires ZOPEDIA_BRAVE_API_KEY env var (free tier: 2,000 queries/month).
    Sign up at https://brave.com/search/api/

    timelimit: 'd' (day), 'w' (week), 'm' (month), 'y' (year), or '' (no limit)."""
    if not _BRAVE_API_KEY:
        return json.dumps({"error": "Brave Search API key not configured. Set ZOPEDIA_BRAVE_API_KEY."})

    import httpx

    # Normalize "all" (frontend "Any time" selection) to empty string
    if timelimit == "all":
        timelimit = ""

    # Map timelimit to Brave's freshness parameter
    _FRESHNESS_MAP = {"d": "pd", "w": "pw", "m": "pm", "y": "py"}

    try:
        params: dict = {
            "q": query,
            "count": min(max_results, 20),
            "search_lang": "en",
        }
        freshness = _FRESHNESS_MAP.get(timelimit, "")
        if freshness:
            params["freshness"] = freshness

        def _search():
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip",
                        "X-Subscription-Token": _BRAVE_API_KEY,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("Brave Search API returned %d: %.300s", resp.status_code, resp.text)
                    return []
                data = resp.json()
                web = data.get("web", {})
                return web.get("results", [])

        raw_results = await asyncio.to_thread(_search)

        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": (r.get("description", "") or "")[:300],
            })

        if not results:
            return json.dumps({"results": [], "query": query, "hint": "No results found."})

        return json.dumps({"results": results, "query": query}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"Web search failed: {exc}"})


_ALPACA_DATA_BASE_URL = "https://data.alpaca.markets"


def _alpaca_headers() -> dict[str, str]:
    return {
        "APCA-API-KEY-ID": _ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": _ALPACA_API_SECRET,
    }


def _alpaca_request(url: str, params: dict) -> dict | None:
    """Sync helper (run via asyncio.to_thread) — returns parsed JSON or None."""
    import httpx

    with httpx.Client(timeout=10) as client:
        resp = client.get(url, params=params, headers=_alpaca_headers())
        if resp.status_code != 200:
            logger.warning("Alpaca API returned %d: %.300s", resp.status_code, resp.text)
            return None
        return resp.json()


async def execute_alpaca_market_data(
    symbol: str,
    data_type: str,
    timeframe: str = "1Day",
    limit: int = 10,
    expiration_date: str | None = None,
    strike_gte: float | None = None,
    strike_lte: float | None = None,
    option_type: str | None = None,
    page_token: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> str:
    """Query live market data from the Alpaca Markets API.

    Requires ZOPEDIA_ALPACA_API_KEY and ZOPEDIA_ALPACA_API_SECRET env vars.
    data_type: 'quote' | 'bars' | 'snapshot' | 'options_chain'.
    Returns a JSON string (never raises).
    """
    if not _ALPACA_API_KEY or not _ALPACA_API_SECRET:
        return json.dumps({"error": "Alpaca API key not configured. Set ZOPEDIA_ALPACA_API_KEY and ZOPEDIA_ALPACA_API_SECRET."})

    symbol = str(symbol or "").strip().upper()
    if not symbol:
        return json.dumps({"error": "Alpaca: symbol is required."})

    try:
        limit = max(1, min(int(limit or 10), 1000))
    except (TypeError, ValueError):
        limit = 10

    try:
        if data_type == "quote":
            # GET /v2/stocks/{symbol}/quotes/latest — latest quote.
            # Fields: t (timestamp), ap/asp (ask price/size), bp/bs (bid price/size).
            url = f"{_ALPACA_DATA_BASE_URL}/v2/stocks/{symbol}/quotes/latest"
            data = await asyncio.to_thread(_alpaca_request, url, {})
            if data is None:
                return json.dumps({"error": f"Alpaca: no quote returned for {symbol} (invalid symbol or market data unavailable)."})
            quote = data.get("quote") or data
            return json.dumps({
                "symbol": symbol,
                "type": "quote",
                "bid": quote.get("bp"),
                "bid_size": quote.get("bs"),
                "ask": quote.get("ap"),
                "ask_size": quote.get("as"),
                "timestamp": quote.get("t"),
            }, default=str)

        if data_type == "bars":
            # GET /v2/stocks/{symbol}/bars — historical OHLCV bars.
            url = f"{_ALPACA_DATA_BASE_URL}/v2/stocks/{symbol}/bars"
            params = {"timeframe": str(timeframe or "1Day"), "limit": limit}
            if start:
                params["start"] = str(start)
            if end:
                params["end"] = str(end)
            data = await asyncio.to_thread(_alpaca_request, url, params)
            if data is None:
                return json.dumps({"error": f"Alpaca: no bars returned for {symbol}."})
            bars = data.get("bars", [])
            return json.dumps({
                "symbol": symbol,
                "type": "bars",
                "timeframe": params["timeframe"],
                "bars": bars,  # each bar: t, o, h, l, c, v, n (OHLCV + trades + timestamp)
                "count": len(bars),
            }, default=str)

        if data_type == "snapshot":
            # GET /v2/stocks/{symbol}/snapshot — latest trade + quote + daily/prev bars.
            url = f"{_ALPACA_DATA_BASE_URL}/v2/stocks/{symbol}/snapshot"
            data = await asyncio.to_thread(_alpaca_request, url, {})
            if data is None:
                return json.dumps({"error": f"Alpaca: no snapshot returned for {symbol}."})
            latest_trade = data.get("latestTrade") or {}
            latest_quote = data.get("latestQuote") or {}
            daily_bar = data.get("dailyBar") or {}
            prev = data.get("prevDailyBar") or {}
            return json.dumps({
                "symbol": symbol,
                "type": "snapshot",
                "last_price": latest_trade.get("p"),
                "last_trade_time": latest_trade.get("t"),
                "bid": latest_quote.get("bp"),
                "ask": latest_quote.get("ap"),
                "open": daily_bar.get("o"),
                "high": daily_bar.get("h"),
                "low": daily_bar.get("l"),
                "close": daily_bar.get("c"),
                "volume": daily_bar.get("v"),
                "prev_close": prev.get("c"),
                "change": round((daily_bar.get("c", 0) or 0) - (prev.get("c", 0) or 0), 4) if prev.get("c") is not None else None,
            }, default=str)

        if data_type == "options_chain":
            # GET /v1beta1/options/snapshots/{underlying_symbol} — options snapshots.
            # underlying_symbol is a PATH param (e.g. AAPL). Default feed is
            # 'opra' if subscribed, else 'indicative' — don't force it.
            url = f"{_ALPACA_DATA_BASE_URL}/v1beta1/options/snapshots/{symbol}"
            # Options snapshots are large — keep the default cap low so the
            # model gets a focused slice; surface next_page_token for more.
            chain_limit = min(limit, 25)
            params = {"limit": chain_limit}
            if expiration_date:
                params["expiration_date"] = str(expiration_date)
            if strike_gte is not None:
                params["strike_price_gte"] = strike_gte
            if strike_lte is not None:
                params["strike_price_lte"] = strike_lte
            if option_type in ("call", "put"):
                params["type"] = option_type
            if page_token:
                params["page_token"] = str(page_token)
            data = await asyncio.to_thread(_alpaca_request, url, params)
            if data is None:
                return json.dumps({"error": f"Alpaca: no options snapshots returned for {symbol}."})
            snapshots = data.get("snapshots") or {}
            # snapshots is {option_symbol: {latestTrade, latestQuote, greeks,
            # impliedVolatility, ...}}. openInterest is not in the documented
            # schema — read defensively if the feed includes it.
            items = []
            for opt_symbol, snap in snapshots.items():
                quote = snap.get("latestQuote") or {}
                trade = snap.get("latestTrade") or {}
                greeks = snap.get("greeks") or {}
                items.append({
                    "option_symbol": opt_symbol,
                    "bid": quote.get("bp"),
                    "ask": quote.get("ap"),
                    "last": trade.get("p"),
                    "implied_volatility": snap.get("impliedVolatility"),
                    "open_interest": snap.get("openInterest") if snap.get("openInterest") is not None else snap.get("open_interest"),
                    "delta": greeks.get("delta"),
                    "gamma": greeks.get("gamma"),
                    "theta": greeks.get("theta"),
                    "vega": greeks.get("vega"),
                })
            return json.dumps({
                "underlying": symbol,
                "type": "options_chain",
                "count": len(items),
                "next_page_token": data.get("next_page_token"),
                "options": items,
            }, default=str)

        return json.dumps({"error": f"Alpaca: unknown type '{data_type}'. Use quote, bars, snapshot, or options_chain."})
    except Exception as exc:
        return json.dumps({"error": f"Alpaca market data failed: {exc}"})


async def execute_alpaca_news(
    symbols: str | None = None,
    start: str | None = None,
    end: str | None = None,
    limit: int = 10,
    include_content: bool = False,
    page_token: str | None = None,
) -> str:
    """Query financial news from the Alpaca Markets news API.

    Requires ZOPEDIA_ALPACA_API_KEY and ZOPEDIA_ALPACA_API_SECRET env vars.
    Returns a JSON string (never raises).
    """
    if not _ALPACA_API_KEY or not _ALPACA_API_SECRET:
        return json.dumps({"error": "Alpaca API key not configured. Set ZOPEDIA_ALPACA_API_KEY and ZOPEDIA_ALPACA_API_SECRET."})

    try:
        limit = max(1, min(int(limit or 10), 50))
    except (TypeError, ValueError):
        limit = 10

    try:
        # GET /v1beta1/news — news articles (fields: id, headline, author,
        # created_at, updated_at, summary, content, symbols, source, url).
        url = f"{_ALPACA_DATA_BASE_URL}/v1beta1/news"
        params: dict = {"limit": limit, "sort": "desc"}
        if symbols:
            params["symbols"] = str(symbols)
        if start:
            params["start"] = str(start)
        if end:
            params["end"] = str(end)
        if include_content:
            params["include_content"] = True
        if page_token:
            params["page_token"] = str(page_token)
        data = await asyncio.to_thread(_alpaca_request, url, params)
        if data is None:
            return json.dumps({"error": "Alpaca: no news returned (check symbols / API access)."})
        news = data.get("news") or []
        items = []
        for a in news:
            item = {
                "headline": a.get("headline"),
                "summary": a.get("summary"),
                "source": a.get("source"),
                "url": a.get("url"),
                "author": a.get("author"),
                "created_at": a.get("created_at"),
                "updated_at": a.get("updated_at"),
                "symbols": a.get("symbols") or [],
            }
            if include_content:
                item["content"] = a.get("content")
            items.append(item)
        return json.dumps({
            "type": "news",
            "count": len(items),
            "next_page_token": data.get("next_page_token"),
            "articles": items,
        }, default=str)
    except Exception as exc:
        return json.dumps({"error": f"Alpaca news failed: {exc}"})


async def execute_video_search(query: str, max_results: int = 5, timelimit: str = "m") -> str:
    """Search for videos using the Brave Search API. Returns JSON results.

    Requires ZOPEDIA_BRAVE_API_KEY env var.
    timelimit: 'd' (day), 'w' (week), 'm' (month), 'y' (year), or '' (no limit)."""
    if not _BRAVE_API_KEY:
        return json.dumps({"error": "Brave Search API key not configured. Set ZOPEDIA_BRAVE_API_KEY."})

    import httpx

    # Normalize "all" (frontend "Any time" selection) to empty string
    if timelimit == "all":
        timelimit = ""

    _FRESHNESS_MAP = {"d": "pd", "w": "pw", "m": "pm", "y": "py"}

    try:
        params: dict = {
            "q": query,
            "count": min(max_results, 20),
            "search_lang": "en",
        }
        freshness = _FRESHNESS_MAP.get(timelimit, "")
        if freshness:
            params["freshness"] = freshness

        def _search():
            with httpx.Client(timeout=10) as client:
                resp = client.get(
                    "https://api.search.brave.com/res/v1/videos/search",
                    params=params,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "gzip",
                        "X-Subscription-Token": _BRAVE_API_KEY,
                    },
                )
                if resp.status_code != 200:
                    logger.warning("Brave Video API returned %d: %.300s", resp.status_code, resp.text)
                    return []
                data = resp.json()
                return data.get("results", [])

        raw_results = await asyncio.to_thread(_search)

        results = []
        for r in raw_results:
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": (r.get("description", "") or "")[:300],
            })

        if not results:
            return json.dumps({"results": [], "query": query, "hint": "No video results found."})

        return json.dumps({"results": results, "query": query}, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"Video search failed: {exc}"})


def execute_wiki_search(wiki_dir: str, query: str, max_results: int = 10) -> str:
    """Search wiki pages and return JSON with matching pages and previews."""
    from pathlib import Path
    import re

    wiki_path = Path(wiki_dir)
    if not wiki_path.exists():
        return json.dumps({"results": [], "total": 0, "hint": "Wiki directory is empty. Add files to raw/ to populate it."})

    all_pages = sorted(
        [p for p in wiki_path.rglob("*.md") if ".archive" not in str(p)],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    query_lower = query.lower()
    query_terms = [t for t in re.findall(r"[a-zA-Z0-9]{2,}", query_lower) if t not in {
        "the", "a", "an", "and", "or", "for", "with", "that", "this", "what",
        "when", "where", "who", "why", "how", "from", "into", "about", "tell",
        "please", "using", "wiki", "context", "only",
    }]

    results = []
    for rel_path in all_pages:
        try:
            text = wiki_path / rel_path.relative_to(wiki_path)
            content = text.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        rel_str = str(rel_path.relative_to(wiki_path))
        if rel_str in {"index.md", "log.md"}:
            continue

        # Score by term matches
        content_lower = content.lower()
        title = ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                title = stripped[2:].strip()
                break

        score = 0
        if query_terms:
            for term in query_terms:
                score += content_lower[:5000].count(term)
                if term in rel_str.lower():
                    score += 3
                if term in title.lower():
                    score += 5

        # Also check for exact phrase match
        if query_lower in content_lower[:5000]:
            score += 10
        if query_lower in title.lower():
            score += 20

        if score > 0 or not query_terms:
            # Generate preview
            preview = content[:400].replace("\n", " ").strip()
            if len(content) > 400:
                preview += "..."

            # Determine kind from path
            kind = "other"
            if rel_str.startswith("sources/"):
                kind = "source"
            elif rel_str.startswith("entities/"):
                kind = "entity"
            elif rel_str.startswith("concepts/"):
                kind = "concept"
            elif rel_str.startswith("analysis/"):
                kind = "analysis"

            # Boost entity and concept pages — they are the most curated and up-to-date
            if kind == "entity" or kind == "concept":
                score = score * 1.3
            elif kind == "source":
                score = score * 0.8
            # analysis and other: no adjustment

            results.append({
                "path": rel_str,
                "kind": kind,
                "title": title or rel_str.replace(".md", "").replace("-", " ").replace("_", " "),
                "score": score,
                "preview": preview,
                "size_chars": len(content),
            })

    # Sort by score descending, then by recency
    results.sort(key=lambda r: (r["score"], r["path"]), reverse=True)
    results = results[:max_results]

    return json.dumps({"results": results, "total": len(results)}, ensure_ascii=False)


def execute_wiki_read(wiki_dir: str, page_path: str, max_chars: int = 50000) -> str:
    """Read a wiki page and return its content."""
    from pathlib import Path

    wiki_path = Path(wiki_dir)
    # Security: prevent path traversal
    safe_path = page_path.replace("\\", "/").strip("/")
    if ".." in safe_path:
        return json.dumps({"error": "Invalid page path."})

    full_path = wiki_path / safe_path
    if not full_path.exists() or not full_path.is_file():
        # Try common variations
        candidates = [
            wiki_path / safe_path,
            wiki_path / f"{safe_path}.md",
            wiki_path / safe_path.replace(".md", "") / ".md",
        ]
        found = None
        for c in candidates:
            if c.exists() and c.is_file():
                found = c
                break
        if not found:
            return json.dumps({"error": f"Page not found: {safe_path}. Use search_wiki to find available pages."})
        full_path = found

    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        return json.dumps({"error": f"Failed to read page: {exc}"})

    if len(content) > max_chars:
        content = content[:max_chars] + f"\n\n...(truncated at {max_chars} chars, page total: {len(content)} chars)"

    rel_path = str(full_path.relative_to(wiki_path)) if wiki_path in full_path.parents else str(full_path)
    return json.dumps({"path": rel_path, "content": content, "size_chars": len(content)}, ensure_ascii=False)
