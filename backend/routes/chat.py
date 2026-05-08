"""OpenAI-compatible chat completions route. Uses upstream API exclusively.

Tool-calling architecture:
- During tool resolution: non-streaming API calls to resolve wiki tools.
  This is the "thinking" phase where the model decides which pages to read.
- After resolution: the final assistant message is popped and the API is called
  again with streaming for proper token-by-token output + CoT/reasoning visibility.
- A future revision will stream tool_call/tool_start/tool_end events during
  resolution for full visibility (following the original Unsloth pattern).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from core.llm import (
    _base_url,
    _headers,
    WIKI_TOOLS,
    chat_completions_non_streaming,
    chat_completions_stream,
    execute_web_search,
    execute_wiki_read,
    llm_available,
)
from routes.wiki import (
    _get_route_rag_context,
    _ingest_pending_raw_files,
    _LAST_RAG_DEBUG,
    _live_route_rag_limits,
    _loggable_rag_context,
    _optional_subject,
    _WIKI_LOG_INJECTED_CONTEXT,
    _WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT,
    get_wiki_components,
    _WIKI_VAULT,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_LLM_TIMEOUT_SECONDS = int(os.getenv("ZOPEDIA_LLM_TIMEOUT_SECONDS", "300"))
_LLM_MODEL = os.getenv("ZOPEDIA_LLM_MODEL", "").strip()
_WIKI_TOOL_RETRIEVAL = os.getenv("ZOPEDIA_WIKI_TOOL_RETRIEVAL", "true").strip().lower() in {"1", "true", "yes", "on"}
_WIKI_MAX_TOOL_TURNS = int(os.getenv("ZOPEDIA_WIKI_MAX_TOOL_TURNS", "8"))


def _resolve_model(requested: Optional[str]) -> str:
    r = (requested or "").strip()
    if r and r not in {"default", "current"}:
        return r
    return _LLM_MODEL or r or "default"


def _extract_last_user_query(messages: list[dict]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        parts.append(part.get("text", ""))
                return " ".join(parts)
    return ""


def _inject_rag_context(messages: list[dict], query: str) -> tuple[list[dict], Optional[str]]:
    """Inject wiki RAG context as a system message (legacy path)."""
    try:
        context = _get_route_rag_context(query)
    except Exception:
        return messages, None

    if not context or not context.strip():
        return messages, None

    global _LAST_RAG_DEBUG
    try:
        _, debug = _get_route_rag_context(query, return_debug=True)
        _LAST_RAG_DEBUG = debug
    except Exception:
        pass

    if _WIKI_LOG_INJECTED_CONTEXT:
        logger.info("Injected RAG context (%d chars):\n%s", len(context), _loggable_rag_context(context))

    system_block = (
        "You are Zopedia, an AI assistant with access to a personal wiki knowledge base.\n\n"
        "## Wiki Knowledge Base\n"
        "The following pages from the user's wiki are relevant to this conversation.\n"
        "Use this information to ground your answers. Cite specific pages when relevant.\n\n"
        f"{context}\n\n"
        "## Instructions\n"
        "- Answer questions using the wiki context above when available.\n"
        "- If the wiki doesn't cover something, use your general knowledge.\n"
        "- Be concise and specific."
    )
    new_messages = [{"role": "system", "content": system_block}] + list(messages)
    return new_messages, context


async def _resolve_tool_calls(messages: list[dict], tools: list[dict], resolved_model: str, max_turns: int | None = None) -> list[dict]:
    """Execute tool-calling loop. Returns messages array (non-streaming path)."""
    if max_turns is None:
        max_turns = _WIKI_MAX_TOOL_TURNS
    result = None
    async for _ in _resolve_tool_calls_stream(messages, tools, resolved_model, max_turns):
        pass
    # The generator mutates messages in place; return it
    return messages


async def _resolve_tool_calls_stream(
    messages: list[dict],
    tools: list[dict],
    resolved_model: str,
    max_turns: int | None = None,
):
    if max_turns is None:
        max_turns = _WIKI_MAX_TOOL_TURNS
    """Async generator that yields tool-calling progress events.

    Yields events following the original Unsloth protocol:
      {"type": "tool_status", "text": "..."}
      {"type": "tool_start", "tool_name": "...", "tool_call_id": "...", "arguments": {...}}
      {"type": "tool_end", "tool_name": "...", "tool_call_id": "...", "result": "..."}

    Does NOT yield content events — the final answer is streamed separately.
    Mutates messages in place with tool calls and results.
    """
    wiki_dir = str(_WIKI_VAULT / "wiki")
    turn = 0

    while turn < max_turns:
        turn += 1
        yield {"type": "tool_status", "text": f"Thinking... (turn {turn})"}

        result = await chat_completions_non_streaming(
            messages,
            model=resolved_model,
            temperature=0.7,
            max_tokens=4096,
            tools=tools,
        )

        if "error" in result:
            logger.warning("Tool-calling turn %d failed: %s", turn, result.get("error"))
            yield {"type": "tool_status", "text": f"Error: {result.get('error', 'unknown')}"}
            break

        choice = (result.get("choices") or [{}])[0]
        msg = choice.get("message") or {}

        # Forward reasoning_content from this turn
        reasoning = msg.get("reasoning_content", "")
        if reasoning:
            yield {"type": "tool_status", "text": reasoning}

        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            final_msg = {"role": "assistant", "content": msg.get("content", "")}
            if reasoning:
                final_msg["reasoning_content"] = reasoning
            messages.append(final_msg)
            yield {"type": "tool_status", "text": "Synthesizing answer..."}
            break

        logger.info("Tool-calling turn %d: %d tool calls", turn, len(tool_calls))

        assistant_msg: dict = {"role": "assistant", "content": msg.get("content") or None, "tool_calls": tool_calls}
        if reasoning:
            assistant_msg["reasoning_content"] = reasoning
        messages.append(assistant_msg)

        for tc in tool_calls:
            func = tc.get("function") or {}
            name = func.get("name", "")
            args_str = func.get("arguments", "{}")

            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except json.JSONDecodeError:
                args = {}

            tc_id = tc.get("id", f"call_{turn}")

            if name == "read_wiki_page":
                page_path = str(args.get("path", ""))
                yield {
                    "type": "tool_start",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "arguments": {"path": page_path},
                }
                yield {"type": "tool_status", "text": f"Reading {page_path}..."}
                tool_result = execute_wiki_read(wiki_dir, page_path)
                try:
                    result_data = json.loads(tool_result)
                    size = result_data.get("size_chars", 0)
                    preview = result_data.get("content", "")[:200]
                    yield {"type": "tool_status", "text": f"Read {page_path} ({size:,} chars)"}
                except Exception:
                    size = 0
                    preview = ""
                yield {
                    "type": "tool_end",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "result": json.dumps({"path": page_path, "size_chars": size, "preview": preview}),
                }
            elif name == "web_search":
                query_str = str(args.get("query", ""))
                yield {
                    "type": "tool_start",
                    "tool_name": "web_search",
                    "tool_call_id": tc_id,
                    "arguments": {"query": query_str},
                }
                yield {"type": "tool_status", "text": f"Searching web: {query_str}"}
                tool_result = await execute_web_search(query_str)
                try:
                    result_data = json.loads(tool_result)
                    count = len(result_data.get("results", []))
                    yield {"type": "tool_status", "text": f"Web search: {count} results"}
                except Exception:
                    pass
                yield {
                    "type": "tool_end",
                    "tool_name": "web_search",
                    "tool_call_id": tc_id,
                    "result": tool_result,
                }
            else:
                tool_result = json.dumps({"error": f"Unknown tool: {name}"})
                yield {
                    "type": "tool_end",
                    "tool_name": name,
                    "tool_call_id": tc_id,
                    "result": tool_result,
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc_id,
                "content": tool_result,
            })



# ── Standard chat/completions ──────────────────────────────────────


@router.post("/chat/completions")
async def openai_chat_completions(request: Request):
    """OpenAI-compatible chat completions via upstream API, with wiki RAG injection or tool retrieval."""
    if not llm_available():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No upstream LLM configured. Set ZOPEDIA_LLM_BASE_URL and ZOPEDIA_LLM_API_KEY.")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON body.")

    messages: list[dict] = body.get("messages", [])
    model = body.get("model")
    temperature = float(body.get("temperature", 0.7))
    max_tokens = int(body.get("max_tokens", 4096))
    stream = bool(body.get("stream", False))
    tools: list[dict] = body.get("tools") or []
    tool_choice = body.get("tool_choice")
    response_format = body.get("response_format")

    resolved_model = _resolve_model(model)

    if _WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT > 0:
        try:
            _ingest_pending_raw_files(max_files=_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT, respect_interval_gate=True)
        except Exception:
            pass

    query = _extract_last_user_query(messages)

    if _WIKI_TOOL_RETRIEVAL:
        wiki_tools = WIKI_TOOLS + [t for t in tools if t.get("function", {}).get("name") not in {"read_wiki_page", "web_search"}]

        index_path = _WIKI_VAULT / "wiki" / "index-concise.md"
        index_text = ""
        if index_path.exists():
            try:
                index_text = index_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                index_text = "(wiki index unavailable)"

        wiki_system = {
            "role": "system",
            "content": (
                "You have access to a personal wiki and web search.\n\n"
                "AVAILABLE TOOLS:\n"
                "- read_wiki_page(path): Read a wiki page. Use paths from the index below.\n"
                "- web_search(query): Search the web for external information. Use ONLY when the user explicitly asks for web search, or when the wiki doesn't have the answer.\n\n"
                "HOW TO USE THE WIKI:\n"
                "- The full index of entities and concepts is below. Pick relevant pages directly — no need to search.\n"
                "- Entity and concept pages are the most curated and up-to-date. They contain [[wikilinks]] to related analysis and source pages.\n"
                "- IMPORTANT: Entity/concept pages list analysis backlinks under '## Referenced by Analyses'. "
                "ALWAYS check this section and read the linked analysis/* pages — they contain detailed historical summaries.\n"
                "- Follow the chain: read entities/concepts first, then their linked analysis pages, then sources if needed.\n"
                "- Prefer analysis pages over source pages as sources can be large.\n\n"
                "CRITICAL RULES:\n"
                "- NEVER invent or shorten page paths. Only use EXACT paths you read via read_wiki_page.\n"
                "- Analysis page paths contain timestamps. Use the full path exactly as it appears.\n"
                "- When citing a page, use the exact path from the tool call result, not a made-up name.\n\n"
                "WIKI INDEX (Entities & Concepts):\n\n"
                f"{index_text}\n"
            ),
        }
        messages = [wiki_system] + list(messages)

        if stream:
            # ── Streaming with tool visibility ──────────────────────
            async def event_generator():
                chunk_id = f"chatcmpl-{int(time.time())}"
                created = int(time.time())

                # Phase 1: tool resolution with progress events
                try:
                    async for evt in _resolve_tool_calls_stream(messages, wiki_tools, resolved_model):
                        etype = evt["type"]
                        if etype == "tool_status":
                            yield f"data: {json.dumps({'type': 'tool_status', 'content': evt['text']})}\n\n"
                        elif etype == "tool_start":
                            yield f"data: {json.dumps({'type': 'tool_start', 'tool_name': evt['tool_name'], 'tool_call_id': evt['tool_call_id'], 'arguments': evt.get('arguments', {})})}\n\n"
                        elif etype == "tool_end":
                            yield f"data: {json.dumps({'type': 'tool_end', 'tool_name': evt['tool_name'], 'tool_call_id': evt['tool_call_id'], 'result': evt.get('result', '')})}\n\n"

                    # Pop any non-tool-call assistant message (narration/planning text).
                    if messages and messages[-1].get("role") == "assistant" and messages[-1].get("content") and not messages[-1].get("tool_calls"):
                        messages.pop()
                    # Add instruction to break the model out of tool-calling mode and force synthesis.
                    messages.append({"role": "user", "content": "Now synthesize a complete, thorough answer using all the wiki pages you just read. Provide the answer directly — do not output JSON or tool-call syntax."})
                except Exception as exc:
                    logger.warning("Tool-calling retrieval failed, falling back: %s", exc)
                    yield f"data: {json.dumps({'type': 'tool_status', 'content': f'Error: {exc}'})}\n\n"
                    if query:
                        fallback_msgs, _ = _inject_rag_context(messages, query)
                        messages.clear()
                        messages.extend(fallback_msgs)

                # Phase 2: always stream the final answer from the API.
                # This ensures proper token-by-token output with full CoT visibility
                # and prevents hallucinated/narration text from being treated as the answer.
                async for event in chat_completions_stream(messages, model=resolved_model, temperature=temperature, max_tokens=max_tokens, tools=None, tool_choice=None):
                    if event["type"] == "reasoning":
                        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': resolved_model, 'choices': [{'index': 0, 'delta': {'reasoning_content': event['content']}, 'finish_reason': None}]})}\n\n"
                    elif event["type"] == "text":
                        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': resolved_model, 'choices': [{'index': 0, 'delta': {'content': event['content']}, 'finish_reason': None}]})}\n\n"
                    elif event["type"] == "error":
                        yield f"data: {json.dumps({'error': event['message']})}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")
        else:
            # ── Non-streaming tool resolution ──────────────────────
            try:
                messages = await _resolve_tool_calls(list(messages), wiki_tools, resolved_model)
                if messages and messages[-1].get("role") == "assistant" and messages[-1].get("content") and not messages[-1].get("tool_calls"):
                    messages.pop()
                messages.append({"role": "user", "content": "Now synthesize a complete, thorough answer using all the wiki pages you just read. Provide the answer directly — do not output JSON or tool-call syntax."})
            except Exception as exc:
                logger.warning("Tool-calling retrieval failed, falling back: %s", exc)
                if query:
                    messages, _ = _inject_rag_context(messages, query)
    else:
        if query:
            messages, _ = _inject_rag_context(messages, query)

    # ── Non-streaming final response ───────────────────────────────

    if not stream:
        result = await chat_completions_non_streaming(messages, model=resolved_model, temperature=temperature, max_tokens=max_tokens, tools=tools, response_format=response_format)
        if "error" in result:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])
        result["model"] = resolved_model
        return result


# ── OpenAI-compatible /v1 passthrough ──────────────────────────────


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def openai_passthrough(request: Request, path: str):
    if not llm_available():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No upstream LLM configured.")

    base = _base_url()
    target_url = f"{base}/{path}"

    import httpx

    body = None
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()

    headers = dict(request.headers)
    headers.pop("host", None)
    headers["authorization"] = _headers().get("Authorization", "")

    async with httpx.AsyncClient(timeout=_LLM_TIMEOUT_SECONDS) as client:
        response = await client.request(request.method, target_url, content=body, headers=headers)
        return StreamingResponse(
            response.aiter_bytes(),
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.headers.get("content-type", "application/json"),
        )
