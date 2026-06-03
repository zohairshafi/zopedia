"""Upstream LLM client for Zopedia. All LLM calls go through an OpenAI-compatible API."""

from __future__ import annotations

import json
import logging
import os
import re
from urllib.parse import quote
import time
from typing import Any, Callable, Optional

import httpx

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


def refresh_llm_config():
    """Re-read LLM config from os.environ (for soft reload after Apply and Restart)."""
    global _LLM_BASE_URL, _LLM_API_KEY, _LLM_MODEL, _LLM_TIMEOUT_SECONDS, _WIKI_LLM_MAX_TOKENS
    _LLM_BASE_URL = _env_str("ZOPEDIA_LLM_BASE_URL")
    _LLM_API_KEY = _env_str("ZOPEDIA_LLM_API_KEY")
    _LLM_MODEL = _env_str("ZOPEDIA_LLM_MODEL", "default")
    _LLM_TIMEOUT_SECONDS = _env_int("ZOPEDIA_LLM_TIMEOUT_SECONDS", 300)
    _WIKI_LLM_MAX_TOKENS = _env_int("ZOPEDIA_WIKI_LLM_MAX_TOKENS", 6000)


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
            {"role": "system", "content": "Return only a valid JSON object matching the requested schema. Do not include markdown fences, reasoning text, or any other prose."},
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
        "description": (
            "Read the full content of a wiki page by its exact path. "
            "Use paths from the wiki index provided in the system message. "
            "Page paths look like 'entities/person.md', 'concepts/topic.md', 'analysis/2024-01-01-query-topic.md', or 'sources/my-doc.md'. "
            "Entity and concept pages often contain [[wikilinks]] to related analysis and source pages — follow those links for deeper detail."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The wiki page path to read (e.g. 'entities/person.md', 'concepts/topic.md'). Use exact paths from the index.",
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
        "description": (
            "Search the web for information not in the wiki. "
            "Use this ONLY when the user explicitly asks you to search the web, "
            "or when the wiki doesn't have the answer. "
            "Returns search result snippets with URLs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for the web.",
                },
            },
            "required": ["query"],
        },
    },
}

WIKI_TOOLS = [WIKI_READ_PAGE_TOOL, WIKI_WEB_SEARCH_TOOL]


async def execute_web_search(query: str, max_results: int = 5, timelimit: str = "m") -> str:
    """Search the web using DuckDuckGo and return JSON results.
    timelimit: 'd' (day), 'w' (week), 'm' (month), 'y' (year), or '' (no limit)."""
    try:
        from ddgs import DDGS

        # Normalize "all" (frontend "Any time" selection) to empty string
        if timelimit == "all":
            timelimit = ""

        results = []
        kwargs: dict = {"max_results": max_results, "backend": "duckduckgo,google,brave"}
        if timelimit:
            kwargs["timelimit"] = timelimit
        with DDGS() as ddgs:
            for r in ddgs.text(query, **kwargs):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": (r.get("body", "") or "")[:300],
                })

        if not results:
            return json.dumps({"results": [], "query": query, "hint": "No results found."})

        return json.dumps({"results": results, "query": query}, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "duckduckgo_search package not installed. Run: pip install duckduckgo_search"})
    except Exception as exc:
        return json.dumps({"error": f"Web search failed: {exc}"})


async def execute_video_search(query: str, max_results: int = 5, timelimit: str = "m") -> str:
    """Search for videos using ddgs videos() endpoint. Returns JSON results.
    Use for YouTube source type — much better than text search with site:youtube.com."""
    try:
        from ddgs import DDGS

        # Normalize "all" (frontend "Any time" selection) to empty string
        if timelimit == "all":
            timelimit = ""

        results = []
        kwargs: dict = {"max_results": max_results}
        if timelimit:
            kwargs["timelimit"] = timelimit
            kwargs["backend"] = "duckduckgo,google,brave"
        with DDGS() as ddgs:
            for r in ddgs.videos(query, **kwargs):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("content", ""),  # ddgs videos use 'content' for URL
                    "snippet": (r.get("description", "") or "")[:300],
                })

        if not results:
            return json.dumps({"results": [], "query": query, "hint": "No video results found."})

        return json.dumps({"results": results, "query": query}, ensure_ascii=False)
    except ImportError:
        return json.dumps({"error": "duckduckgo_search package not installed."})
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
