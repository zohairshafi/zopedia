"""Research Mode orchestrator for Zopedia.

Multi-round source discovery, user curation, wiki ingestion, and maintenance.
Reuses existing wiki tools, ingestion pipeline, and LLM infrastructure.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Research session state (in-memory, keyed by session_id)
# ---------------------------------------------------------------------------

_research_sessions: dict[str, asyncio.Event] = {}
_research_approvals: dict[str, dict] = {}
_research_cancelled: dict[str, bool] = {}

# Depth presets
_DEPTH_PRESETS = {
    "shallow":  {"rounds": 2, "sources_per_round": 5},
    "standard": {"rounds": 3, "sources_per_round": 10},
    "deep":     {"rounds": 5, "sources_per_round": 15},
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class ResearchConfig:
    topic: str
    rounds: int = 3
    sources_per_round: int = 10
    auto_mode: bool = False
    trusted_sources: list[str] = field(default_factory=list)
    blocked_sources: list[str] = field(default_factory=list)
    research_depth: str = "standard"
    source_types: list[str] = field(default_factory=list)


def _apply_depth_preset(config: ResearchConfig) -> ResearchConfig:
    """Apply a depth preset if rounds/sources_per_round were not explicitly set."""
    preset = _DEPTH_PRESETS.get(config.research_depth)
    if preset and config.rounds == 3 and config.sources_per_round == 10:
        config.rounds = preset["rounds"]
        config.sources_per_round = preset["sources_per_round"]
    return config


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(event_type: str, **kwargs) -> dict:
    return {"type": event_type, **kwargs}


def _is_blocked(url: str, blocked: list[str]) -> bool:
    if not blocked:
        return False
    domain = urlparse(url).netloc.lower()
    url_lower = url.lower()
    return any(b.lower() in domain or b.lower() in url_lower for b in blocked)


def _is_trusted(url: str, trusted: list[str]) -> bool:
    if not trusted:
        return False
    domain = urlparse(url).netloc.lower()
    url_lower = url.lower()
    return any(t.lower() in domain or t.lower() in url_lower for t in trusted)


def _source_type(url: str) -> str:
    """Classify a URL into a source type."""
    domain = urlparse(url).netloc.lower()
    if any(d in domain for d in ("arxiv.org", "biorxiv.org", "medrxiv.org", "semanticscholar.org", "scholar.google.com")):
        return "paper"
    if any(d in domain for d in ("youtube.com", "youtu.be")):
        return "youtube"
    if any(d in domain for d in ("twitter.com", "x.com")):
        return "tweet"
    if url.endswith(".pdf"):
        return "pdf"
    return "webpage"


def _extract_query_terms(topic: str) -> list[str]:
    """Extract key terms from a topic for deduplication checking."""
    words = re.findall(r"[a-zA-Z0-9]{3,}", topic.lower())
    stop = {"the", "and", "for", "with", "that", "this", "what", "when",
            "where", "who", "why", "how", "from", "into", "about", "their",
            "which", "have", "been", "were", "are", "was", "will", "can",
            "its", "not", "but", "all", "has", "had", "more", "some"}
    return [w for w in words if w not in stop]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class ResearchOrchestrator:
    """Manages the multi-round research loop."""

    def __init__(self, wiki_dir: Path, raw_dir: Path, llm_fn):
        self._wiki_dir = Path(wiki_dir)
        self._raw_dir = Path(raw_dir)
        self._wiki_pages_dir = self._wiki_dir / "wiki"
        self._llm_fn = llm_fn
        self._warnings: list[dict] = []

    # -- wiki survey -------------------------------------------------------

    async def _survey_wiki(self, topic: str) -> str:
        """Read wiki index and relevant pages to understand existing knowledge."""
        from core.llm import chat_completions_non_streaming

        index_path = self._wiki_pages_dir / "index-concise.md"
        if not index_path.is_file():
            logger.info("Research: no wiki index found, skipping survey")
            return ""

        index_content = index_path.read_text(encoding="utf-8", errors="ignore")
        if len(index_content) > 12000:
            index_content = index_content[:12000] + "\n\n[... index truncated ...]"

        survey_prompt = [
            {"role": "system", "content": (
                "You are a research assistant. Survey the provided wiki index and answer:\n"
                "1. What is already known about this topic?\n"
                "2. What gaps or missing areas exist?\n"
                "3. What search queries would fill those gaps?\n"
                "4. Follow any citation links if present to propose search queries.\n"
                "Be concise. Focus on actionable gaps."
            )},
            {"role": "user", "content": (
                f"Research topic: {topic}\n\n"
                f"Wiki index:\n{index_content}"
            )},
        ]

        try:
            response = await chat_completions_non_streaming(survey_prompt)
            return (response.get("content") or "").strip()
        except Exception as exc:
            logger.warning("Research: wiki survey failed: %s", exc)
            return ""

    # -- source discovery --------------------------------------------------

    async def _discover_sources(
        self, topic: str, round_num: int, config: ResearchConfig
    ) -> list[dict]:
        """Use LLM to generate search queries, execute them, and rank results."""
        from core.llm import chat_completions_non_streaming, execute_web_search

        # 1. LLM generates diverse search queries
        query_prompt = [
            {"role": "system", "content": (
                "You are a research strategist. Generate diverse search queries to "
                "explore a research topic from multiple angles. Return a JSON array "
                "of query strings. Aim for variety: different phrasings, subtopics, "
                "competing perspectives, recent developments. Format:\n"
                '{"queries": ["query 1", "query 2", ...]}'
            )},
            {"role": "user", "content": (
                f"Research topic: {topic}\n"
                f"Round: {round_num}/{config.rounds}\n"
                f"Generate {min(5, config.sources_per_round)} search queries."
            )},
        ]

        search_queries = [topic]
        try:
            response = await chat_completions_non_streaming(query_prompt)
            content = (response.get("content") or "").strip()
            match = re.search(r"\{[^}]*\"queries\"[^}]*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                search_queries = parsed.get("queries", [topic])
        except Exception as exc:
            logger.warning("Research: query generation failed: %s", exc)

        # 2. Execute searches (limited to avoid rate limiting)
        all_sources: list[dict] = []
        seen_urls: set[str] = set()

        for query in search_queries[:5]:
            try:
                result_json = await execute_web_search(query, max_results=5)
                result = json.loads(result_json)
                for r in result.get("results", []):
                    url = r.get("url", "").strip()
                    if not url or url in seen_urls:
                        continue
                    if _is_blocked(url, config.blocked_sources):
                        continue
                    if config.source_types:
                        st = _source_type(url)
                        if st not in config.source_types:
                            continue
                    seen_urls.add(url)
                    all_sources.append({
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "source_type": _source_type(url),
                        "is_trusted": _is_trusted(url, config.trusted_sources),
                        "relevance": 0.5,
                        "already_in_wiki": self._url_in_wiki(url),
                    })
            except Exception as exc:
                logger.warning("Research: search failed for '%s': %s", query, exc)

        # 3. Sort: trusted first, then by relevance
        all_sources.sort(key=lambda s: (not s["is_trusted"], -s.get("relevance", 0)))

        return all_sources[: config.sources_per_round]

    def _url_in_wiki(self, url: str) -> bool:
        """Check if a URL is already referenced in the wiki."""
        if not self._wiki_pages_dir.exists():
            return False
        query_terms = _extract_query_terms(url)
        for page in self._wiki_pages_dir.rglob("*.md"):
            if ".archive" in str(page):
                continue
            try:
                content = page.read_text(encoding="utf-8", errors="ignore")
                if url in content:
                    return True
                if query_terms:
                    path_lower = str(page).lower()
                    if any(t in path_lower for t in query_terms[:2]):
                        if urlparse(url).netloc.lower() in content.lower():
                            return True
            except Exception:
                pass
        return False

    # -- ingestion ---------------------------------------------------------

    async def _ingest_sources(self, urls: list[str]) -> list[dict]:
        """Ingest multiple URLs into the wiki. Runs up to 3 concurrently."""
        results: list[dict] = []
        semaphore = asyncio.Semaphore(3)

        async def _ingest_one(url: str) -> dict:
            async with semaphore:
                raw_file = None
                try:
                    from graphify.ingest import ingest as graphify_ingest
                    from core.wiki.manager import WikiManager
                    from core.wiki.ingestor import WikiIngestor

                    wiki_manager = WikiManager.create(self._wiki_dir, self._llm_fn)
                    wiki_ingestor = WikiIngestor(wiki_manager, self._raw_dir)

                    raw_file = graphify_ingest(url, self._raw_dir)
                    title = wiki_ingestor.ingest_file(raw_file)
                    meta = wiki_ingestor.pop_recent_ingest_metadata(raw_file) or {}
                    source_page = meta.get("source_page", "")
                    return {
                        "url": url,
                        "title": title or raw_file.name,
                        "status": "ingested",
                        "source_page": source_page,
                    }
                except Exception as exc:
                    logger.warning("Research: ingest failed for %s: %s", url, exc)
                    # Clean up any partially-downloaded raw file
                    if raw_file is not None and raw_file.exists():
                        try:
                            raw_file.unlink()
                        except OSError:
                            pass
                    self._warnings.append({
                        "url": url,
                        "error": str(exc),
                    })
                    return {"url": url, "status": "failed", "error": str(exc)}

        tasks = [asyncio.create_task(_ingest_one(url)) for url in urls]
        results = await asyncio.gather(*tasks)
        return list(results)

    # -- maintenance -------------------------------------------------------

    async def _run_maintenance(self) -> AsyncGenerator[tuple[str, dict], None]:
        """Run the full 5-step maintenance cycle — only for the final round."""
        from core.wiki.manager import WikiManager

        manager = WikiManager.create(self._wiki_dir, self._llm_fn)

        # Step 1: Lint
        try:
            lint_result = manager.engine.lint()
        except Exception as exc:
            logger.warning("Research: lint failed: %s", exc)
            lint_result = {"error": str(exc)}
        yield ("lint", lint_result)

        # Step 2: Retry fallback
        try:
            retry_result = manager.retry_fallback_analysis_pages(dry_run=False)
        except Exception as exc:
            logger.warning("Research: retry-fallback failed: %s", exc)
            retry_result = {"error": str(exc)}
        yield ("retry_fallback", retry_result)

        # Step 3-4: enrichment (includes godnodes) → backlinks
        async for event in self._run_light_maintenance(manager):
            yield event

    async def _run_light_maintenance(self, manager=None) -> AsyncGenerator[tuple[str, dict], None]:
        """Run enrichment + backlinks — fast, per-round maintenance.

        Godnodes rebuild is handled internally by enrich_analysis_pages, so we
        don't call it separately here."""
        from core.wiki.manager import WikiManager

        if manager is None:
            manager = WikiManager.create(self._wiki_dir, self._llm_fn)

        # Enrichment (includes godnodes rebuild internally)
        try:
            enrich_result = manager.enrich_analysis_pages(dry_run=False)
        except Exception as exc:
            logger.warning("Research: enrichment failed: %s", exc)
            enrich_result = {"error": str(exc)}
        yield ("enrichment", enrich_result)

        # Backlinks
        try:
            backlinks_result = manager.refresh_analysis_backlinks(dry_run=False)
        except Exception as exc:
            logger.warning("Research: backlinks failed: %s", exc)
            backlinks_result = {"error": str(exc)}
        yield ("backlinks", backlinks_result)

    # -- final summary -----------------------------------------------------

    async def _generate_final_summary(
        self, topic: str, all_ingested: list[dict]
    ) -> AsyncGenerator[str, None]:
        """Run a tool-calling loop so the LLM can read wiki pages, then stream
        a final research summary. Uses the same read_wiki_page tool as chat."""
        from core.llm import (
            chat_completions_non_streaming,
            chat_completions_stream,
            execute_wiki_read,
            WIKI_READ_PAGE_TOOL,
        )

        wiki_dir = str(self._wiki_dir)
        max_cumulative = int(os.getenv("ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS", "500000"))
        max_chars_per_read = int(os.getenv("ZOPEDIA_WIKI_MAX_CHARS_PER_READ", "12000"))

        index_path = self._wiki_pages_dir / "index-concise.md"
        index_content = ""
        if index_path.is_file():
            index_content = index_path.read_text(encoding="utf-8", errors="ignore")
            if len(index_content) > 15000:
                index_content = index_content[:15000] + "\n\n[... index truncated ...]"

        ingested_list = "\n".join(
            f"- {r.get('title', r.get('url', ''))}  ({r.get('url', '')})"
            for r in all_ingested if r.get("status") == "ingested"
        )

        system_prompt = (
            f"You are a research synthesizer. Write a thorough research summary "
            f"on the topic: '{topic}'.\n\n"
            "You have access to a wiki knowledge base via the read_wiki_page tool. "
            "Use it to explore relevant pages, including both newly ingested sources "
            "and pre-existing wiki content.\n\n"
            "Plan your reads: start with key pages, then follow leads to related content.\n\n"
            f"--- Wiki index ---\n{index_content}\n---\n\n"
            f"Newly ingested during this research:\n{ingested_list or '(none)'}"
        )

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Research topic: {topic}\n\n"
                "Read relevant wiki pages to understand the current knowledge, "
                "then tell me you're ready to write the final summary."
            )},
        ]

        tools: list[dict[str, Any]] = [WIKI_READ_PAGE_TOOL]
        cumulative_read_chars = 0
        max_turns = 5

        for _turn in range(max_turns):
            response = await chat_completions_non_streaming(
                messages, tools=tools, temperature=0.2, max_tokens=2048,
            )
            if "error" in response:
                logger.warning("Research: tool-loop LLM error: %s", response.get("error"))
                break

            choice = response.get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                messages.append({"role": "assistant", "content": msg.get("content", "")})
                break

            # Append assistant message with tool calls
            messages.append({
                "role": "assistant",
                "content": msg.get("content"),
                "tool_calls": tool_calls,
            })

            for tc in tool_calls:
                fn = tc.get("function", {})
                if fn.get("name") != "read_wiki_page":
                    continue
                try:
                    args = json.loads(fn.get("arguments", "{}"))
                except json.JSONDecodeError:
                    continue
                page_path = args.get("path", "")
                if not page_path:
                    continue

                result_json = execute_wiki_read(
                    wiki_dir, page_path, max_chars=max_chars_per_read,
                )
                try:
                    size = json.loads(result_json).get("size_chars", 0)
                except json.JSONDecodeError:
                    size = len(result_json)
                cumulative_read_chars += size

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result_json,
                })

            if cumulative_read_chars >= max_cumulative:
                logger.info("Research: read budget reached (%s chars)", cumulative_read_chars)
                break

        # Final synthesis — stream
        messages.append({
            "role": "user",
            "content": (
                "Now write a comprehensive final research summary based on everything "
                "you've read. Structure it as a research report:\n\n"
                "## Executive Summary\n"
                "## Key Findings\n"
                "## Source Analysis\n"
                "## Gaps and Future Directions\n"
                "## References\n\n"
                "Cite specific wiki pages. Be thorough but concise."
            ),
        })

        async for event in chat_completions_stream(messages, temperature=0.3):
            if event.get("type") == "text":
                yield event.get("content", "")

    # -- main loop ---------------------------------------------------------

    async def run_research_stream(
        self, config: ResearchConfig, session_id: str
    ) -> AsyncGenerator[dict, None]:
        """Run the full research loop, yielding SSE events."""
        _research_cancelled[session_id] = False
        config = _apply_depth_preset(config)

        yield _make_event("research_started",
            topic=config.topic,
            total_rounds=config.rounds,
            sources_per_round=config.sources_per_round,
            auto_mode=config.auto_mode,
        )

        all_ingested: list[dict] = []

        try:
            # Phase 1: Survey wiki
            survey = await self._survey_wiki(config.topic)
            yield _make_event("research_survey", content=survey)

            for round_num in range(1, config.rounds + 1):
                if _research_cancelled.get(session_id):
                    yield _make_event("research_cancelled", message="Research cancelled by user.")
                    return

                yield _make_event("research_round_start",
                    round=round_num, total_rounds=config.rounds)

                # Phase 2: Discover sources
                yield _make_event("research_searching", round=round_num, queries=[])
                sources = await self._discover_sources(config.topic, round_num, config)
                yield _make_event("research_sources_found",
                    round=round_num, sources=sources)

                # Phase 3: Approval (manual) or auto-ingest
                approved_urls: list[str] = []
                if config.auto_mode:
                    approved_urls = [
                        s["url"] for s in sources
                        if not s.get("already_in_wiki")
                    ][: config.sources_per_round]
                else:
                    if not sources:
                        yield _make_event("research_round_complete",
                            round=round_num, sources_ingested=0, new_pages=[],
                            message="No new sources found this round.")
                        continue

                    yield _make_event("research_awaiting_approval",
                        round=round_num, source_count=len(sources))

                    # Wait for user approval via /api/research/approve
                    event = asyncio.Event()
                    _research_sessions[session_id] = event
                    try:
                        await asyncio.wait_for(event.wait(), timeout=600)
                    except asyncio.TimeoutError:
                        yield _make_event("research_error",
                            message="Approval timed out (10 minutes). Moving to next round.")
                    approval = _research_approvals.pop(session_id, {})
                    approved_urls = approval.get("approved_urls", [])
                    _research_sessions.pop(session_id, None)

                # Phase 4: Ingest
                results: list[dict] = []
                if approved_urls:
                    for url in approved_urls:
                        if _research_cancelled.get(session_id):
                            break
                        yield _make_event("research_ingest_start", url=url)
                    results = await self._ingest_sources(approved_urls)
                    for r in results:
                        yield _make_event("research_ingest_complete",
                            url=r["url"], title=r.get("title", ""),
                            status=r["status"], error=r.get("error", ""))
                    all_ingested.extend(results)
                else:
                    yield _make_event("research_ingest_complete",
                        url="", title="", status="skipped",
                        message="No sources approved for ingestion.")

                # Phase 5: Maintenance — skip if nothing was ingested this round
                ingested_this_round = [r for r in results if r.get("status") == "ingested"]
                failed_this_round = [r for r in results if r.get("status") == "failed"]

                if ingested_this_round:
                    is_final_round = round_num == config.rounds
                    yield _make_event("research_maintenance_start",
                        step="enrichment" if not is_final_round else "lint")
                    maintenance = self._run_maintenance() if is_final_round else self._run_light_maintenance()
                    async for step_name, step_result in maintenance:
                        if _research_cancelled.get(session_id):
                            break
                        yield _make_event("research_maintenance_progress",
                            step=step_name, details=step_result)
                    step_count = 4 if is_final_round else 2
                    yield _make_event("research_maintenance_complete",
                        summary={"steps_completed": step_count})

                yield _make_event("research_round_complete",
                    round=round_num,
                    sources_ingested=len(ingested_this_round),
                    sources_failed=len(failed_this_round),
                    new_pages=[r.get("url", "") for r in ingested_this_round],
                    failed_pages=[r.get("url", "") for r in failed_this_round])

            # Phase 6: Final summary
            yield _make_event("research_summarizing", message="Generating final report...")
            async for chunk in self._generate_final_summary(config.topic, all_ingested):
                yield _make_event("research_final_summary", content=chunk)

            # Surface any warnings (e.g. PDF URLs that returned HTML)
            if self._warnings:
                yield _make_event("research_warnings", warnings=self._warnings)

            yield _make_event("research_complete",
                total_sources_ingested=len([r for r in all_ingested if r.get("status") == "ingested"]))

        except Exception as exc:
            logger.exception("Research: fatal error")
            yield _make_event("research_error", message=str(exc))
        finally:
            _research_sessions.pop(session_id, None)
            _research_approvals.pop(session_id, None)
            _research_cancelled.pop(session_id, None)
