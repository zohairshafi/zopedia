"""OpenAI-compatible chat completions route. Uses upstream API exclusively.

Tool-calling architecture:
- During tool resolution: non-streaming API calls to resolve wiki tools.
  This is the "thinking" phase where the model decides which pages to read.
- After resolution: the final assistant message is popped and the API is called
  again with streaming for proper token-by-token output + CoT/reasoning visibility.
- A future revision will stream tool_call/tool_start/tool_end events during
  resolution for full visibility (following the original Zopedia pattern).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from core.llm import (
    _base_url,
    _headers,
    WIKI_TOOLS,
    chat_completions_non_streaming,
    chat_completions_stream,
    execute_web_search,
    execute_wiki_read,
    execute_wiki_search,
    llm_available,
)
from routes.wiki import (
    _get_route_rag_context,
    _ingest_pending_raw_files,
    _LAST_RAG_DEBUG,
    _live_route_rag_limits,
    _loggable_rag_context,
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


def _wiki_max_tool_turns() -> int:
    return int(os.getenv("ZOPEDIA_WIKI_MAX_TOOL_TURNS", "8"))


def _wiki_max_reads_per_turn() -> int:
    return int(os.getenv("ZOPEDIA_WIKI_MAX_READS_PER_TURN", "20"))


def _wiki_max_chars_per_read() -> int:
    return int(os.getenv("ZOPEDIA_WIKI_MAX_CHARS_PER_READ", "12000"))


def _wiki_max_cumulative_read_chars() -> int:
    return int(os.getenv("ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS", "500000"))


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
    """Inject wiki RAG context as a system message (legacy path).

    Controlled by ZOPEDIA_RAG_PREFETCH_ENABLED env var. Defaults to disabled.
    When disabled, the LLM relies entirely on tool calling (read_wiki_page)."""
    if not os.getenv("ZOPEDIA_RAG_PREFETCH_ENABLED", "").strip().lower() in ("1", "true", "yes", "on"):
        return messages, None

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
        max_turns = _wiki_max_tool_turns()
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
        max_turns = _wiki_max_tool_turns()
    """Async generator that yields tool-calling progress events.

    Yields events following the original Zopedia protocol:
      {"type": "tool_status", "text": "..."}
      {"type": "tool_start", "tool_name": "...", "tool_call_id": "...", "arguments": {...}}
      {"type": "tool_end", "tool_name": "...", "tool_call_id": "...", "result": "..."}

    Does NOT yield content events — the final answer is streamed separately.
    Mutates messages in place with tool calls and results.
    """
    wiki_dir = str(_WIKI_VAULT / "wiki")
    turn = 0
    cumulative_read_chars = 0
    max_chars_per_read = _wiki_max_chars_per_read()
    max_cumulative = _wiki_max_cumulative_read_chars()

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

        # Cap reads per turn
        read_count = 0
        for tc in tool_calls:
            func = tc.get("function") or {}
            name = func.get("name", "")
            args_str = func.get("arguments", "{}")

            if name == "read_wiki_page":
                read_count += 1
                if read_count > _wiki_max_reads_per_turn():
                    break

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
                tool_result = execute_wiki_read(wiki_dir, page_path, max_chars=max_chars_per_read)
                try:
                    result_data = json.loads(tool_result)
                    size = result_data.get("size_chars", 0)
                    preview = result_data.get("content", "")[:200]
                    yield {"type": "tool_status", "text": f"Read {page_path} ({size:,} chars)"}
                except Exception:
                    size = 0
                    preview = ""
                cumulative_read_chars += size
                yield {
                    "type": "tool_end",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "result": json.dumps({"path": page_path, "size_chars": size, "preview": preview}),
                }
                if cumulative_read_chars >= max_cumulative:
                    yield {"type": "tool_status", "text": f"Read budget reached ({cumulative_read_chars:,} chars). Synthesizing answer..."}
                    break
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
                # Small delay between successive web_search calls to avoid
                # hammering upstream search engines when the LLM issues
                # multiple searches in a single tool-calling turn.
                await asyncio.sleep(0.15)
            elif name == "search_wiki":
                query_str = str(args.get("query", ""))
                yield {
                    "type": "tool_start",
                    "tool_name": "search_wiki",
                    "tool_call_id": tc_id,
                    "arguments": {"query": query_str},
                }
                yield {"type": "tool_status", "text": f"Searching wiki: {query_str}"}
                tool_result = await asyncio.to_thread(execute_wiki_search, wiki_dir, query_str)
                try:
                    result_data = json.loads(tool_result)
                    count = result_data.get("total", 0)
                    yield {"type": "tool_status", "text": f"Wiki search: {count} results"}
                except Exception:
                    pass
                yield {
                    "type": "tool_end",
                    "tool_name": "search_wiki",
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

        # Stop further tool turns if cumulative read budget is exhausted
        if cumulative_read_chars >= max_cumulative:
            yield {"type": "tool_status", "text": "Synthesizing answer..."}
            break


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
    enable_tools = bool(body.get("enable_tools", False))
    enabled_tools: list[str] = body.get("enabled_tools") or []

    resolved_model = _resolve_model(model)

    if _WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT > 0:
        # Fire-and-forget: don't delay the chat response for background ingest.
        # The ingest runs in a thread pool and may complete after streaming begins.
        async def _background_ingest():
            try:
                await asyncio.to_thread(
                    _ingest_pending_raw_files,
                    max_files=_WIKI_PENDING_INGEST_MAX_FILES_PER_CHAT,
                    respect_interval_gate=True,
                )
            except Exception:
                logger.debug("Background wiki ingest during chat request failed", exc_info=True)

        asyncio.create_task(_background_ingest())

    query = _extract_last_user_query(messages)

    if _WIKI_TOOL_RETRIEVAL:
        # Determine which tools are enabled. If enable_tools is set, use enabled_tools list.
        # Otherwise default to both wiki + web search.
        # Wiki is always available when tool retrieval is enabled — the frontend toggle
        # controls web_search only.
        if enable_tools:
            enabled_set = set(enabled_tools)
            enabled_set.add("read_wiki_page")
            enabled_set.add("search_wiki")
        else:
            enabled_set = {"read_wiki_page", "web_search", "search_wiki"}

        wiki_tools = [t for t in WIKI_TOOLS if t["function"]["name"] in enabled_set]
        # Add any custom tools from the request (only those not already in WIKI_TOOLS)
        _wiki_tool_names = {t["function"]["name"] for t in WIKI_TOOLS}
        wiki_tools += [t for t in tools if t.get("function", {}).get("name") not in _wiki_tool_names]

        has_wiki = "read_wiki_page" in enabled_set
        has_web = "web_search" in enabled_set

        # Prefer the hierarchical god-nodes index; fall back to flat concise index
        index_path = _WIKI_VAULT / "wiki" / "index-godnodes.md"
        if not index_path.exists():
            index_path = _WIKI_VAULT / "wiki" / "index-concise.md"
        index_text = ""
        if has_wiki and index_path.exists():
            try:
                index_text = index_path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                index_text = "(wiki index unavailable)"

        # Build system prompt dynamically based on enabled tools
        prompt_parts = []

        # Intro line
        today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        if has_wiki and has_web:
            prompt_parts.append(f"Today's date is {today}. You have access to a personal wiki and web search.\n")
        elif has_wiki:
            prompt_parts.append(f"Today's date is {today}. You have access to a personal wiki.\n")
        elif has_web:
            prompt_parts.append(f"Today's date is {today}. You have access to web search.\n")

        # Budget info (only relevant when wiki is enabled)
        if has_wiki:
            prompt_parts.append(
                f"BUDGET: You have {_wiki_max_tool_turns()} turns (up to {_wiki_max_reads_per_turn()} wiki reads per turn, "
                f"max {_wiki_max_tool_turns() * _wiki_max_reads_per_turn()} total reads). "
                f"Each page is capped at {_wiki_max_chars_per_read():,} chars. "
                f"Total read budget: {_wiki_max_cumulative_read_chars():,} chars cumulative. "
                "Plan carefully: start with the most relevant entities/concepts, then follow their analysis backlinks. "
                "Prioritize quality over quantity — you cannot read everything.\n\n"
            )

        # Available tools
        if wiki_tools:
            prompt_parts.append("AVAILABLE TOOLS:\n")
            for tool in wiki_tools:
                name = tool["function"]["name"]
                desc = tool["function"]["description"]
                prompt_parts.append(f"- {name}: {desc}\n")
            prompt_parts.append("\n")

        # Wiki usage instructions
        if has_wiki:
            prompt_parts.append(
                "HOW TO USE THE WIKI:\n"
                "- The wiki index below is a table of contents. Each line is a community page (godnodes/*.md).\n"
                "- Use read_wiki_page to expand a community — the page lists all entity/concept members.\n"
                "- If you don't know which pages to read, use search_wiki to search all wiki content by keywords.\n"
                "- Start with the community name that best matches the user's question, "
                "read it, then read individual member pages and follow their [[wikilinks]].\n"
                "- Entity and concept pages are the most curated and up-to-date. They contain [[wikilinks]] to related analysis and source pages.\n"
                "- IMPORTANT: Entity/concept pages list analysis backlinks under '## Referenced by Analyses'. "
                "ALWAYS check this section and read the linked analysis/* pages if the query needs a deeper answer - they contain detailed historical summaries.\n"
                "- Follow the chain: read entities/concepts first, then their linked analysis pages, then sources if needed.\n"
                "- Prefer analysis pages over source pages as sources can be large.\n\n"
                "CRITICAL RULES:\n"
                "- NEVER invent or shorten page paths. Only use EXACT paths you read via read_wiki_page.\n"
                "- Analysis page paths contain timestamps. Use the full path exactly as it appears.\n"
                "- When citing a page, use the exact path from the tool call result, not a made-up name.\n\n"
            )

        # Web search guideline
        if has_web and not has_wiki:
            prompt_parts.append(
                "Use web_search when the user asks for information that requires external or up-to-date sources.\n\n"
            )

        # Wiki index
        if has_wiki and index_text:
            prompt_parts.append(f"WIKI INDEX (Entities & Concepts):\n\n{index_text}\n")

        if prompt_parts:
            wiki_system = {
                "role": "system",
                "content": "".join(prompt_parts),
            }
            messages = [wiki_system] + list(messages)

        # Inject current date into the last user message so the model always
        # knows what "today" is — even when continuing a conversation from days ago.
        _today = datetime.now(timezone.utc).strftime("%A, %B %d, %Y")
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].get("role") == "user":
                content = messages[i].get("content", "")
                if isinstance(content, str):
                    messages[i]["content"] = f"Today's date is {_today}.\n\n{content}"
                break

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
                    # Marked so we can remove it after streaming — it should not persist into the next turn.
                    messages.append({"role": "user", "content": (
                        "Now synthesize a complete, thorough answer using all the wiki pages and web results you "
                        "just accessed. DO NOT use any more tools. Provide the answer directly as plain markdown. CRITICAL: Do NOT output "
                        "XML tags, tool invocations (like <invoke> or <function_call>), JSON structures, or any "
                        "other machine-readable format. The user will see your raw output — write only the final answer."
                        "If you need more information, admit you don't know and provide the best answer you can with what you have. Do not make up information or use the wiki/web tools anymore."
                    ), "_ephemeral": True})
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
                    elif event["type"] == "usage":
                        yield f"data: {json.dumps({'id': chunk_id, 'object': 'chat.completion.chunk', 'created': created, 'model': resolved_model, 'choices': [], 'usage': event['usage']})}\n\n"
                # Remove ephemeral synthesis instruction so it doesn't leak into next turn
                if messages and messages[-1].get("_ephemeral"):
                    messages.pop()

                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream")
        else:
            # ── Non-streaming tool resolution ──────────────────────
            try:
                messages = await _resolve_tool_calls(list(messages), wiki_tools, resolved_model)
                if messages and messages[-1].get("role") == "assistant" and messages[-1].get("content") and not messages[-1].get("tool_calls"):
                    messages.pop()
                messages.append({"role": "user", "content": (
                    "Now synthesize a complete, thorough answer using all the wiki pages and web results you "
                    "just accessed. DO NOT use any more tools. Provide the answer directly as plain markdown. CRITICAL: Do NOT output "
                    "XML tags, tool invocations (like <invoke> or <function_call>), JSON structures, or any "
                    "other machine-readable format. The user will see your raw output — write only the final answer."
                    "If you need more information, admit you don't know and provide the best answer you can with what you have. Do not make up information or use the wiki/web tools anymore."

                ), "_ephemeral": True})
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
        # Remove ephemeral synthesis instruction so it doesn't leak into the response
        if messages and messages[-1].get("_ephemeral"):
            messages.pop()
        if "error" in result:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])
        result["model"] = resolved_model
        return result


# ── Title generation ────────────────────────────────────────────────


@router.post("/api/chat/generate-title")
async def generate_title(body: dict):
    """Generate a concise chat title from the first user message.

    Calls the upstream LLM directly — no wiki injection, no tools.
    """
    if not llm_available():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="No upstream LLM configured.")

    user_text = (body.get("userText") or "").strip()
    if not user_text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="userText is required")

    assistant_text = (body.get("assistantText") or "").strip()

    context = f"User: {user_text[:400]}"
    if assistant_text:
        context += f"\nAssistant response begins: {assistant_text[:300]}"

    messages = [
        {
            "role": "system",
            "content": (
                "Write a concise chat title (3-8 words) summarizing what the user is asking about. "
                "Be specific — use topic names, proper nouns, and technical terms. "
                "Output only the title, no quotes, no prefixes, no punctuation at the end."
            ),
        },
        {"role": "user", "content": context},
    ]

    result = await chat_completions_non_streaming(
        messages,
        temperature=0.2,
        max_tokens=32,
        thinking={"type": "disabled"},
    )

    if "error" in result:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=result["error"])

    raw = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    title = (raw or "").split("\n", 1)[0].strip()
    # Strip common prefixes the model might emit
    title = title.replace("Title:", "").replace("title:", "").strip()
    title = title.strip("\"'`")
    if not title:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Model returned empty title")

    return {"title": title}


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
