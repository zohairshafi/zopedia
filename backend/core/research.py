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
from typing import AsyncGenerator, Callable, Optional
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
    timelimit: str = "m"  # '', 'd', 'w', 'm', 'y'


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
    for t in trusted:
        t_lower = t.lower().strip()
        if t_lower in domain or t_lower in url_lower:
            return True
        # Also match by the trusted source's own domain (e.g. youtube.com/@Channel
        # should match youtube.com/watch?v=... since the channel isn't in the video URL)
        if "://" in t_lower:
            trusted_domain = urlparse(t_lower).netloc.lower()
            if trusted_domain and trusted_domain in domain:
                return True
    return False


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

    async def _survey_wiki(self, topic: str, prior_report: str | None = None) -> AsyncGenerator[dict, None]:
        """Read wiki index and let the LLM explore relevant pages via tool calls.
        Yields tool_start/tool_end/tool_status events, then a research_survey event."""
        from core.llm import (
            chat_completions_non_streaming,
            extract_content,
            execute_wiki_read,
            WIKI_READ_PAGE_TOOL,
        )

        wiki_dir = str(self._wiki_pages_dir)
        max_cumulative = int(os.getenv("ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS", "500000"))
        max_chars_per_read = int(os.getenv("ZOPEDIA_WIKI_MAX_CHARS_PER_READ", "12000"))
        max_turns = int(os.getenv("ZOPEDIA_WIKI_MAX_TOOL_TURNS", "8"))

        # Prefer the hierarchical god-nodes index; fall back to flat concise index
        index_path = self._wiki_pages_dir / "index-godnodes.md"
        if not index_path.exists():
            index_path = self._wiki_pages_dir / "index-concise.md"
        index_content = ""
        if index_path.is_file():
            index_content = index_path.read_text(encoding="utf-8", errors="ignore")
            if len(index_content) > 12000:
                index_content = index_content[:12000] + "\n\n[... index truncated ...]"
        else:
            logger.info("Research: no wiki index found, skipping survey")
            yield {"type": "research_survey", "content": ""}
            return

        system_prompt = (
            "You are a research assistant surveying a wiki knowledge base. "
            "Use the read_wiki_page tool to explore pages relevant to the topic. "
            "Identify:\n"
            "1. What is already known about this topic?\n"
            "2. What gaps or missing areas exist?\n"
            "3. What search queries would fill those gaps?\n\n"
            f"--- Wiki index ---\n{index_content}\n---"
        )
        if prior_report:
            prior_context = (
                "\n\n## Prior Research Report\n"
                "The following is the research report from the PREVIOUS run. "
                "Use it to understand what was already covered. "
                "Focus your wiki exploration on:\n"
                "- New information not in the prior report\n"
                "- Gaps or areas the prior report identified as needing more research\n"
                "- Updates or changes to topics covered in the prior report\n\n"
                f"{prior_report[:8000]}\n"
            )
            system_prompt += prior_context

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": (
                f"Research topic: {topic}\n\n"
                "Read relevant wiki pages, then provide your survey analysis."
            )},
        ]

        tools: list[dict[str, Any]] = [WIKI_READ_PAGE_TOOL]
        cumulative_read_chars = 0

        for turn in range(1, max_turns + 1):
            yield {"type": "research_tool_status", "text": f"Surveying wiki... (turn {turn})"}

            response = await chat_completions_non_streaming(
                messages, tools=tools, temperature=0.2, max_tokens=8192,
            )
            if "error" in response:
                logger.warning("Research: survey tool-loop error: %s", response.get("error"))
                break

            choice = response.get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                messages.append({"role": "assistant", "content": msg.get("content", "")})
                break

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

                tc_id = tc.get("id", f"call_{turn}")
                yield {
                    "type": "research_tool_start",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "arguments": {"path": page_path},
                }

                result_json = execute_wiki_read(
                    wiki_dir, page_path, max_chars=max_chars_per_read,
                )
                try:
                    result_data = json.loads(result_json)
                    size = result_data.get("size_chars", 0)
                    preview = result_data.get("content", "")[:200]
                except json.JSONDecodeError:
                    size = len(result_json)
                    preview = ""

                cumulative_read_chars += size

                yield {
                    "type": "research_tool_end",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "result": json.dumps({"path": page_path, "size_chars": size, "preview": preview}),
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_json,
                })

            if cumulative_read_chars >= max_cumulative:
                logger.info("Research: survey read budget reached (%s chars)", cumulative_read_chars)
                break

        # Get the final survey analysis
        messages.append({
            "role": "user",
            "content": (
                "Based on what you've read, provide a concise survey analysis:\n"
                "1. What is already known about this topic?\n"
                "2. What gaps or missing areas exist?\n"
                "3. What search queries would fill those gaps?\n"
                "Focus on actionable gaps."
            ),
        })

        try:
            response = await chat_completions_non_streaming(
                messages, temperature=0.3, max_tokens=8192,
            )
            survey_text = extract_content(response)
        except Exception as exc:
            logger.warning("Research: survey analysis failed: %s", exc)
            survey_text = ""

        yield {"type": "research_survey", "content": survey_text}

    # -- source discovery --------------------------------------------------

    async def _discover_sources(
        self, topic: str, round_num: int, config: ResearchConfig,
        prior_report: str | None = None,
    ) -> list[dict]:
        """Use LLM to generate search queries, execute them, and rank results."""
        from core.llm import chat_completions_non_streaming, execute_web_search, execute_video_search, extract_content

        num_queries = min(8, max(3, config.sources_per_round // 2))  # ddgs hits 7+ engines per query

        # 1. LLM generates diverse search queries
        source_type_hint = ""
        if config.source_types:
            st_labels = [st for st in config.source_types if st != "webpage"]
            if st_labels:
                source_type_hint = (
                    f"\nIMPORTANT: Focus on these source types: {', '.join(st_labels)}. "
                    "Generate queries that will find results from these specific platforms "
                    "(e.g. include 'site:youtube.com' for youtube, 'site:x.com' for tweets, "
                    "'site:arxiv.org' for papers)."
                )

        query_prompt = [
            {"role": "system", "content": (
                "You are a research strategist. Generate diverse search queries to "
                "explore a research topic from multiple angles. Return a JSON array "
                "of query strings. Aim for variety: different phrasings, subtopics, "
                "competing perspectives, recent developments.\n"
                f"Today's date is {datetime.now(timezone.utc).strftime('%B %d, %Y')}. "
                "Use date-specific queries where relevant "
                "(e.g. include month/year/day terms for recent news but might be unnecessary for research papers"
                " where old research might be relevent. Or include it if you want state of the art research, use your best judgement)."
                f"{source_type_hint}\n"
                "Format:\n"
                '{"queries": ["query 1", "query 2", ...]}'
            )},
            {"role": "user", "content": (
                f"Research topic: {topic}\n"
                f"Round: {round_num}/{config.rounds}\n"
                f"Generate {num_queries} diverse search queries."
                + (
                    f"\n\nPRIOR RESEARCH (from a previous run):\n"
                    f"{prior_report[:5000]}\n\n"
                    f"Today is {datetime.now(timezone.utc).strftime('%B %d, %Y')}. "
                    f"Generate queries that find NEW or UPDATED information "
                    f"NOT covered in the prior report above. Focus on developments, news, "
                    f"or data published after the prior run."
                    if prior_report else ""
                )
            )},
        ]

        search_queries = [topic]
        try:
            response = await chat_completions_non_streaming(
                query_prompt, max_tokens=8192,
            )
            content = extract_content(response)
            match = re.search(r"\{[^}]*\"queries\"[^}]*\}", content, re.DOTALL)
            if match:
                parsed = json.loads(match.group(0))
                search_queries = parsed.get("queries", [topic])
        except Exception as exc:
            logger.warning("Research: query generation failed: %s", exc)

        # 2. Build query list: (query, max_results, search_type)
        # search_type: "text" or "video" (ddgs videos endpoint for YouTube)
        all_queries: list[tuple[str, int, str]] = []
        for q in search_queries[:num_queries]:
            all_queries.append((q, 15, "text"))

        # Use the best LLM-generated query (or topic fallback) for targeted searches
        best_query = search_queries[0] if search_queries else topic

        # Add platform-targeted searches when source_types are specified
        if config.source_types:
            for st in config.source_types:
                if st == "youtube":
                    all_queries.append((best_query, 5, "video"))
                elif st == "tweet":
                    all_queries.append((f'site:x.com OR site:twitter.com {best_query}', 5, "text"))
                elif st == "paper":
                    all_queries.append((f'site:arxiv.org {best_query}', 5, "text"))
                elif st == "pdf":
                    all_queries.append((f'{best_query} filetype:pdf', 5, "text"))

        # Add trusted-source targeted searches (limited: 3 results, 1 per domain)
        if config.trusted_sources:
            for t in config.trusted_sources:
                t = t.strip().lower()
                if not t:
                    continue
                if t.startswith("http"):
                    parsed = urlparse(t)
                    domain = parsed.netloc
                    path = parsed.path.strip("/")
                    if not domain:
                        continue
                    # YouTube channel: use video search with channel handle
                    if ("youtube.com" in domain or "youtu.be" in domain) and path.startswith("@"):
                        handle = path.split("/")[0].lstrip("@")
                        if handle:
                            all_queries.append((f'{handle} {best_query}', 3, "video"))
                    # X.com / Twitter account: extract username
                    elif domain in ("x.com", "twitter.com") and path and "/" not in path:
                        all_queries.append((f'from:{path} {best_query}', 3, "text"))
                    else:
                        all_queries.append((f'site:{domain} {best_query}', 3, "text"))
                elif "/" not in t:
                    all_queries.append((f'site:{t} {best_query}', 3, "text"))
                else:
                    all_queries.append((f'{best_query} {t}', 3, "text"))

        # Deduplicate queries
        seen_queries: set[str] = set()
        unique_queries: list[tuple[str, int, str]] = []
        for q, n, st in all_queries:
            key = f"{st}:{q}"
            if key not in seen_queries:
                seen_queries.add(key)
                unique_queries.append((q, n, st))
        all_queries = unique_queries

        # 3. Execute searches (with brief delay to avoid rate limiting)
        all_sources: list[dict] = []
        seen_urls: set[str] = set()

        for i, (query, max_results, search_type) in enumerate(all_queries):
            if i > 0:
                await asyncio.sleep(1.5)  # avoid hammering search engines
            try:
                if search_type == "video":
                    result_json = await execute_video_search(
                        query, max_results=max_results, timelimit=config.timelimit,
                    )
                else:
                    result_json = await execute_web_search(
                        query, max_results=max_results, timelimit=config.timelimit,
                    )
                result = json.loads(result_json)
                new_count = 0
                for r in result.get("results", []):
                    url = r.get("url", "").strip()
                    if not url or url in seen_urls:
                        continue
                    if _is_blocked(url, config.blocked_sources):
                        continue
                    st = _source_type(url)
                    if config.source_types and st not in config.source_types:
                        continue
                    seen_urls.add(url)
                    all_sources.append({
                        "url": url,
                        "title": r.get("title", ""),
                        "snippet": r.get("snippet", ""),
                        "source_type": st,
                        "is_trusted": _is_trusted(url, config.trusted_sources),
                        "relevance": 0.5,
                        "already_in_wiki": self._url_in_wiki(url),
                    })
                    new_count += 1
                logger.info(
                    "Research: query %d/%d returned %d new sources (total: %d)",
                    i + 1, len(all_queries), new_count, len(all_sources),
                )
            except Exception as exc:
                logger.warning("Research: search failed for '%s': %s", query, exc)

        # 4. Sort: trusted first, then by relevance (preliminary — LLM ranking will refine)
        all_sources.sort(key=lambda s: (not s["is_trusted"], -s.get("relevance", 0)))

        # Return up to 2x sources_per_round so the ranking step has enough
        # candidates to choose from. The final truncation happens after ranking.
        return all_sources[: max(config.sources_per_round * 2, 15)]

    def _url_in_wiki(self, url: str) -> bool:
        """Check if a URL is already referenced in the wiki (exact match only)."""
        if not self._wiki_pages_dir.exists():
            return False
        url_clean = url.strip().rstrip("/")
        # Build a set of URL variants to check (handles arxiv /abs/ vs /pdf/)
        variants = {url, url_clean}
        arxiv_match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})", url)
        if arxiv_match:
            aid = arxiv_match.group(1)
            variants.add(f"arxiv.org/abs/{aid}")
            variants.add(f"arxiv.org/pdf/{aid}")
            variants.add(aid)
        for page in self._wiki_pages_dir.rglob("*.md"):
            if ".archive" in str(page):
                continue
            try:
                content = page.read_text(encoding="utf-8", errors="ignore")
                if any(v in content for v in variants):
                    return True
            except Exception:
                pass
        return False

    # -- ingestion ---------------------------------------------------------

    async def _rank_sources(self, topic: str, sources: list[dict]) -> list[dict]:
        """Use the LLM to rank discovered sources by relevance and domain authority.

        Cost: one small LLM call per round (~1-3s). Returns reordered list.
        Falls back to original order on any error.
        """
        if len(sources) < 2:
            return sources

        # Log original order
        original_labels = [f"{s.get('source_type','?')}:{urlparse(s['url']).netloc}" for s in sources]
        logger.info(
            "Research ranking: %d sources for topic '%s' — original order:\n  %s",
            len(sources), topic[:60],
            "\n  ".join(f"{i}. {l}" for i, l in enumerate(original_labels)),
        )

        source_entries = []
        for i, s in enumerate(sources):
            domain = urlparse(s["url"]).netloc
            source_entries.append(
                f"{i}. [{s.get('source_type', 'webpage')}] {s.get('title', '')}\n"
                f"   Domain: {domain}\n"
                f"   Snippet: {(s.get('snippet', '') or '')[:200]}"
            )

        prompt = f"""Research topic: "{topic}"

Rank these sources by how USEFUL they are for researching this specific topic.

CRITICAL RULES:
1. PRIMARY RELEVANCE: Does this source directly address the topic, or does it only
   mention keywords tangentially? A paper about "computing as the new oil" is NOT
   relevant to actual oil markets. Demote sources that only use keywords metaphorically.
2. DOMAIN AUTHORITY: For economics/finance topics, prioritize: .gov, .edu, major
   financial publications (Bloomberg, Reuters, FT, WSJ, Economist, Investopedia),
   international organizations (World Bank, IMF, EIA, BEA, Fed). For tech topics,
   prioritize: major tech publications, official company sources, arxiv.org.
3. SOURCE QUALITY: Penalize spam domains, SEO blogs, link farms, personal blogs,
   social media (quora.com, tiktok.com, linkedin.com), and low-authority sites.
4. A source with high domain authority that directly addresses the topic should
   ALWAYS rank above a tangentially-relevant source, regardless of domain.

Return ONLY a JSON array of indices (0-based), most useful first. Include ALL.
Example: [3, 0, 5, 1, 2, 4]

Sources:
{chr(10).join(source_entries)}"""

        logger.info("Research ranking: full prompt (%d chars)", len(prompt))
        ranked = await self._llm_rank(sources, prompt, topic)
        if ranked is not None:
            return ranked

        logger.info("Research ranking: LLM ranking failed, keeping original order")
        return sources

    async def _llm_rank(
        self, sources: list[dict], prompt: str, topic: str,
    ) -> list[dict] | None:
        """Try LLM-based ranking. Returns ranked list or None on failure."""
        from core.llm import chat_completions_non_streaming, extract_content

        logger.info("Research ranking: calling LLM for topic '%s'...", topic[:60])
        try:
            response = await asyncio.wait_for(
                chat_completions_non_streaming(
                    [{"role": "user", "content": prompt}],
                    temperature=0.2, max_tokens=512,
                    thinking={"type": "disabled"},
                ),
                timeout=15,
            )
        except asyncio.TimeoutError:
            logger.warning("Research ranking: LLM call timed out (15s)")
            return None
        except Exception as exc:
            logger.warning("Research: source ranking LLM call failed: %s", exc)
            return None

        error_msg = response.get("error", "")
        content = extract_content(response)
        if error_msg:
            logger.warning("Research ranking: LLM error: %s", error_msg[:200])
            return None

        match = re.search(r"\[[\d,\s]+\]", content)
        if not match:
            logger.warning("Research ranking: no JSON array found in LLM response: %s", content[:100])
            return None

        ranked_indices = json.loads(match.group())
        valid_indices = [
            idx for idx in ranked_indices
            if isinstance(idx, int) and 0 <= idx < len(sources)
        ]
        if not valid_indices:
            logger.warning("Research ranking: no valid indices in LLM response: %s", content[:100])
            return None

        seen: set[int] = set()
        ranked: list[dict] = []
        for idx in valid_indices:
            if idx not in seen:
                ranked.append(sources[idx])
                seen.add(idx)
        for i, s in enumerate(sources):
            if i not in seen:
                ranked.append(s)

        ranked_labels = [f"{s.get('source_type','?')}:{urlparse(s['url']).netloc}" for s in ranked]
        logger.info(
            "Research ranking: LLM reordered %d sources for topic '%s' — ranked order:\n  %s",
            len(ranked), topic[:60],
            "\n  ".join(f"{i}. {l}" for i, l in enumerate(ranked_labels)),
        )
        return ranked

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
        """Run backlinks only — fast, per-round maintenance.
        Full maintenance (lint, retry, enrichment, backlinks) runs at the final round."""

        if manager is None:
            from core.wiki.manager import WikiManager
            manager = WikiManager.create(self._wiki_dir, self._llm_fn)

        # Backlinks only
        try:
            backlinks_result = manager.refresh_analysis_backlinks(dry_run=False)
        except Exception as exc:
            logger.warning("Research: backlinks failed: %s", exc)
            backlinks_result = {"error": str(exc)}
        yield ("backlinks", backlinks_result)

    # -- final summary -----------------------------------------------------

    async def _generate_final_summary(
        self, topic: str, all_ingested: list[dict],
        prior_report: str | None = None,
    ) -> AsyncGenerator[dict, None]:
        """Run a tool-calling loop so the LLM can read wiki pages, then stream
        a final research summary. Uses the same read_wiki_page tool as chat.
        Yields SSE event dicts directly (tool_start, tool_end, tool_status,
        final_summary chunks) so the frontend can show wiki-reading activity."""
        from core.llm import (
            chat_completions_non_streaming,
            chat_completions_stream,
            execute_wiki_read,
            WIKI_READ_PAGE_TOOL,
        )

        wiki_dir = str(self._wiki_pages_dir)
        max_cumulative = int(os.getenv("ZOPEDIA_WIKI_MAX_CUMULATIVE_READ_CHARS", "500000"))
        max_chars_per_read = int(os.getenv("ZOPEDIA_WIKI_MAX_CHARS_PER_READ", "12000"))

        # Prefer the hierarchical god-nodes index; fall back to flat concise index
        index_path = self._wiki_pages_dir / "index-godnodes.md"
        if not index_path.exists():
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
        if prior_report:
            system_prompt += (
                "\n\n## Prior Report (from previous run)\n"
                f"{prior_report[:8000]}\n\n"
                "IMPORTANT: Your report MUST include a '## What Changed Since Last Run' "
                "section that compares your findings against the prior report above. Highlight:\n"
                "- New sources, entities, or concepts discovered this run\n"
                "- Updated or changed information\n"
                "- Gaps from the prior report that were addressed\n"
                "- Gaps that remain unresolved"
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
        max_turns = int(os.getenv("ZOPEDIA_WIKI_MAX_TOOL_TURNS", "8"))

        for turn in range(1, max_turns + 1):
            yield {"type": "research_tool_status", "text": f"Exploring wiki knowledge... (turn {turn})"}

            response = await chat_completions_non_streaming(
                messages, tools=tools, temperature=0.2, max_tokens=8192,
            )
            if "error" in response:
                logger.warning("Research: tool-loop LLM error: %s", response.get("error"))
                break

            choice = response.get("choices", [{}])[0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []

            if not tool_calls:
                messages.append({"role": "assistant", "content": msg.get("content", "")})
                yield {"type": "research_tool_status", "text": "Synthesizing final report..."}
                break

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

                tc_id = tc.get("id", f"call_{turn}")
                yield {
                    "type": "research_tool_start",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "arguments": {"path": page_path},
                }

                result_json = execute_wiki_read(
                    wiki_dir, page_path, max_chars=max_chars_per_read,
                )
                try:
                    result_data = json.loads(result_json)
                    size = result_data.get("size_chars", 0)
                    preview = result_data.get("content", "")[:200]
                except json.JSONDecodeError:
                    size = len(result_json)
                    preview = ""

                cumulative_read_chars += size

                yield {
                    "type": "research_tool_end",
                    "tool_name": "read_wiki_page",
                    "tool_call_id": tc_id,
                    "result": json.dumps({"path": page_path, "size_chars": size, "preview": preview}),
                }

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": result_json,
                })

            if cumulative_read_chars >= max_cumulative:
                logger.info("Research: read budget reached (%s chars)", cumulative_read_chars)
                yield {"type": "research_tool_status", "text": f"Read budget reached ({cumulative_read_chars:,} chars). Synthesizing..."}
                break

        # Final synthesis — stream
        synthesis_sections = (
            "## What Changed Since Last Run\n"
            "## Executive Summary\n"
            "## Key Findings\n"
            "## Source Analysis\n"
            "## Gaps and Future Directions\n"
            "## References\n"
            if prior_report else
            "## Executive Summary\n"
            "## Key Findings\n"
            "## Source Analysis\n"
            "## Gaps and Future Directions\n"
            "## References\n"
        )
        messages.append({
            "role": "user",
            "content": (
                "Now write a comprehensive final research summary based on everything "
                "you've read. Structure it as a research report:\n\n"
                f"{synthesis_sections}\n"
                "Cite specific wiki pages. Be thorough but concise."
            ),
        })

        async for event in chat_completions_stream(
            messages, temperature=0.3, max_tokens=32000,
        ):
            if event.get("type") == "text":
                yield {"type": "research_final_summary", "content": event.get("content", "")}

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
            # Phase 1: Survey wiki (tool-calling — yields tool_start/tool_end/tool_status + research_survey)
            async for event in self._survey_wiki(config.topic):
                yield event

            for round_num in range(1, config.rounds + 1):
                if _research_cancelled.get(session_id):
                    yield _make_event("research_cancelled", message="Research cancelled by user.")
                    return

                yield _make_event("research_round_start",
                    round=round_num, total_rounds=config.rounds)

                # Phase 2: Discover sources
                yield _make_event("research_searching", round=round_num, queries=[])
                sources = await self._discover_sources(config.topic, round_num, config)
                sources = await self._rank_sources(config.topic, sources)
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
                    step_count = 4 if is_final_round else 1
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
            async for event in self._generate_final_summary(config.topic, all_ingested):
                yield event

            # Surface any warnings (e.g. PDF URLs that returned HTML)
            if self._warnings:
                yield _make_event("research_warnings", warnings=self._warnings)

            # Generate a concise title for the research
            yield _make_event("research_tool_status", text="Generating title...")
            try:
                from core.llm import chat_completions_non_streaming, extract_content
                title_response = await chat_completions_non_streaming(
                    [
                        {"role": "system", "content": (
                            "Generate a concise, descriptive title (5-8 words) for a research "
                            "report. Return ONLY the title, no quotes, no punctuation at the end."
                        )},
                        {"role": "user", "content": (
                            f"Research topic: {config.topic}\n"
                            f"Sources ingested: {len([r for r in all_ingested if r.get('status') == 'ingested'])}\n"
                            f"Rounds: {config.rounds}\n\n"
                            "Generate a concise title for this research."
                        )},
                    ],
                    temperature=0.4, max_tokens=64,
                    thinking={"type": "disabled"},
                )
                raw_title = extract_content(title_response).strip('"').strip("'")
                if raw_title:
                    yield _make_event("research_title", title=f"Research: {raw_title}")
            except Exception:
                pass

            yield _make_event("research_complete",
                total_sources_ingested=len([r for r in all_ingested if r.get("status") == "ingested"]))

        except Exception as exc:
            logger.exception("Research: fatal error")
            yield _make_event("research_error", message=str(exc))
        finally:
            _research_sessions.pop(session_id, None)
            _research_approvals.pop(session_id, None)
            _research_cancelled.pop(session_id, None)

    # -- headless execution (for periodic research) ------------------------

    async def run_research_headless(
        self,
        config: ResearchConfig,
        session_id: str,
        url_already_ingested: Callable[[str], bool] | None = None,
        prior_report: str | None = None,
    ) -> dict:
        """Run a complete research cycle without SSE streaming.

        Returns a result dict suitable for saving as a chat thread.
        Forces auto_mode; filters to trusted-only sources during periodic runs.
        If prior_report is provided, it is injected into survey, discovery,
        and final summary prompts so the model can avoid redundant work and
        highlight what changed.
        """
        started_at = datetime.now(timezone.utc).isoformat()
        all_ingested: list[dict] = []
        final_report_parts: list[str] = []
        warnings: list[dict] = []

        # Force auto mode — no user interaction in headless mode
        config = _apply_depth_preset(config)
        config.auto_mode = True

        try:
            # Phase 1: Survey wiki (consume generator, needed for context)
            async for _event in self._survey_wiki(config.topic, prior_report=prior_report):
                pass

            for round_num in range(1, config.rounds + 1):
                # Phase 2: Discover sources
                sources = await self._discover_sources(config.topic, round_num, config, prior_report=prior_report)
                sources = await self._rank_sources(config.topic, sources)

                # Filter to trusted-only during periodic runs (when trusted sources set)
                if config.trusted_sources:
                    trusted = [s for s in sources if s["is_trusted"]]
                    non_trusted = [s for s in sources if not s["is_trusted"]]
                    for s in non_trusted:
                        warnings.append({
                            "url": s["url"],
                            "title": s.get("title", ""),
                            "error": "Skipped (not trusted) during periodic run",
                        })
                    sources = trusted

                # Filter out previously ingested URLs
                if url_already_ingested:
                    sources = [s for s in sources if not url_already_ingested(s["url"])]

                if not sources:
                    logger.info("Research headless: no new sources in round %d", round_num)
                    continue

                approved_urls = [
                    s["url"] for s in sources
                    if not s.get("already_in_wiki")
                ][: config.sources_per_round]

                # Phase 4: Ingest
                results: list[dict] = []
                if approved_urls:
                    results = await self._ingest_sources(approved_urls)
                    all_ingested.extend(results)
                    # Track ingested URLs for dedup
                    for r in results:
                        if r.get("status") == "ingested" and r.get("url"):
                            pass  # caller handles via url_already_ingested

                # Phase 5: Maintenance
                ingested_this_round = [r for r in results if r.get("status") == "ingested"]
                if ingested_this_round:
                    is_final = round_num == config.rounds
                    maintenance = self._run_maintenance() if is_final else self._run_light_maintenance()
                    async for _step_name, _step_result in maintenance:
                        pass

            # Phase 6: Final summary
            async for event in self._generate_final_summary(config.topic, all_ingested, prior_report=prior_report):
                if event.get("type") == "research_final_summary":
                    final_report_parts.append(event.get("content", ""))

            # Collect all warnings
            warnings.extend(self._warnings)

            # Title generation
            title = None
            try:
                from core.llm import chat_completions_non_streaming, extract_content
                title_response = await chat_completions_non_streaming(
                    [
                        {"role": "system", "content": (
                            "Generate a concise, descriptive title (5-8 words) for a research "
                            "report. Return ONLY the title, no quotes, no punctuation at the end."
                        )},
                        {"role": "user", "content": (
                            f"Research topic: {config.topic}\n"
                            f"Sources ingested: {len([r for r in all_ingested if r.get('status') == 'ingested'])}\n"
                            f"Rounds: {config.rounds}\n\n"
                            "Generate a concise title for this research."
                        )},
                    ],
                    temperature=0.4, max_tokens=64,
                    thinking={"type": "disabled"},
                )
                raw_title = extract_content(title_response).strip('"').strip("'")
                if raw_title:
                    title = f"Research: {raw_title}"
            except Exception:
                pass

            ingested_urls = [r["url"] for r in all_ingested if r.get("status") == "ingested"]
            return {
                "topic": config.topic,
                "final_report": "".join(final_report_parts),
                "total_ingested": len(ingested_urls),
                "ingested_urls": ingested_urls,
                "warnings": warnings,
                "title": title or config.topic,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
            }
        except Exception:
            logger.exception("Research headless: fatal error for topic '%s'", config.topic)
            return {
                "topic": config.topic,
                "final_report": "",
                "total_ingested": 0,
                "warnings": warnings,
                "title": config.topic,
                "started_at": started_at,
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "error": "Research failed — see logs for details",
            }
