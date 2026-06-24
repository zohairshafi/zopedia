"""Periodic research scheduler — asyncio-based background task management.

Runs inside the FastAPI event loop. Loads enabled configs at startup and
creates a background asyncio.Task for each that sleeps until next_run_at,
then executes headless research, saves results as chat threads, and repeats.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from chat_history_store import append_thread_messages, get_thread_messages
from core.llm import wiki_llm_fn
from core.research import ResearchConfig, ResearchOrchestrator
from periodic_store import (
    get_config,
    get_thread_id,
    is_url_already_ingested,
    list_enabled_configs,
    mark_run,
    mark_url_ingested,
    set_thread_id,
)

logger = logging.getLogger(__name__)

# Re-raise for route layer
CancelledError = asyncio.CancelledError

INTERVAL_SECONDS = {
    "hourly": 3600,
    "daily": 86400,
    "weekly": 604800,
    "monthly": 2592000,  # 30 days
}


def _compute_next_run(
    interval_type: str,
    from_dt: datetime | None = None,
    run_hour: int | None = None,
    run_dow: int | None = None,
    run_dom: int | None = None,
) -> str:
    """Compute the next run timestamp, respecting day-of-week/month and hour."""
    now = from_dt or datetime.now(timezone.utc)
    hour = run_hour if run_hour is not None else now.hour

    if interval_type == "hourly":
        next_dt = now.replace(minute=0, second=0, microsecond=0)
        if next_dt <= now:
            next_dt = datetime.fromtimestamp(next_dt.timestamp() + 3600, tz=timezone.utc)
    elif interval_type == "weekly" and run_dow is not None:
        # Find the next occurrence of the specified day-of-week at the right hour
        days_ahead = run_dow - now.weekday()
        if days_ahead < 0:
            days_ahead += 7
        next_dt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        next_dt = datetime.fromtimestamp(
            next_dt.timestamp() + days_ahead * 86400, tz=timezone.utc
        )
        if next_dt <= now:
            next_dt = datetime.fromtimestamp(next_dt.timestamp() + 7 * 86400, tz=timezone.utc)
    elif interval_type == "monthly" and run_dom is not None:
        # Try the specified day of this month; if it passed or doesn't exist, clamp
        try:
            next_dt = now.replace(day=run_dom, hour=hour, minute=0, second=0, microsecond=0)
        except ValueError:
            # Day doesn't exist in current month (e.g. Feb 30), use last day
            last_day = _days_in_month(now.year, now.month)
            next_dt = now.replace(day=last_day, hour=hour, minute=0, second=0, microsecond=0)
        if next_dt <= now:
            # Move to next month
            if now.month == 12:
                next_dt = next_dt.replace(year=now.year + 1, month=1)
            else:
                next_dt = next_dt.replace(month=now.month + 1)
            # Clamp to days in the new month
            next_dt = next_dt.replace(
                day=min(run_dom, _days_in_month(next_dt.year, next_dt.month))
            )
    else:
        # Daily or no specific day constraint — use hour if set
        next_dt = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if next_dt <= now:
            next_dt = datetime.fromtimestamp(next_dt.timestamp() + 86400, tz=timezone.utc)

    return next_dt.isoformat()


def _days_in_month(year: int, month: int) -> int:
    """Return the number of days in a given month."""
    if month == 12:
        return (datetime(year + 1, 1, 1, tzinfo=timezone.utc) - datetime(year, 12, 1, tzinfo=timezone.utc)).days
    return (datetime(year, month + 1, 1, tzinfo=timezone.utc) - datetime(year, month, 1, tzinfo=timezone.utc)).days


def _get_wiki_dirs():
    vault = Path(os.getenv("ZOPEDIA_WIKI_VAULT", "./wiki_data")).expanduser()
    return vault, vault / "raw"


class PeriodicScheduler:
    """Manages background asyncio tasks for periodic research configs."""

    def __init__(self, default_username: str = "default"):
        self._tasks: dict[str, asyncio.Task] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._default_username = default_username

    async def start(self) -> None:
        """Load all enabled configs and schedule them."""
        configs = list_enabled_configs()
        logger.info("PeriodicScheduler: loading %d enabled configs", len(configs))
        for cfg in configs:
            await self._schedule_one(cfg)
        logger.info("PeriodicScheduler: started with %d tasks", len(self._tasks))

    async def shutdown(self) -> None:
        """Cancel all running tasks."""
        logger.info("PeriodicScheduler: shutting down %d tasks", len(self._tasks))
        for config_id, task in list(self._tasks.items()):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    async def add_config(self, config_id: str, username: str) -> None:
        """Schedule a newly created config."""
        cfg = get_config(config_id, username)
        if cfg and cfg.get("enabled"):
            await self._schedule_one(cfg)

    def remove_config(self, config_id: str) -> None:
        """Cancel and remove a config's task."""
        task = self._tasks.pop(config_id, None)
        self._locks.pop(config_id, None)
        if task:
            task.cancel()
            logger.info("PeriodicScheduler: removed config %s", config_id)

    async def update_config(self, config_id: str, username: str) -> None:
        """Re-schedule a config after it was updated (remove old task, add new)."""
        cfg = get_config(config_id, username)
        if not cfg:
            return
        self.remove_config(config_id)
        if cfg.get("enabled"):
            await self._schedule_one(cfg)

    async def run_now(self, config_id: str, username: str) -> None:
        """Trigger immediate execution of a config."""
        cfg = get_config(config_id, username)
        if not cfg:
            raise ValueError(f"Config {config_id} not found")
        logger.info("PeriodicScheduler: running config %s now", config_id)

        # Mark started immediately so UI shows the run was triggered
        now = datetime.now(timezone.utc).isoformat()
        from periodic_store import update_config
        update_config(config_id, username, last_run_at=now)

        # Ensure a lock exists (normally created by _schedule_one, but
        # run_now may be called before the first scheduled run).
        if config_id not in self._locks:
            self._locks[config_id] = asyncio.Lock()

        async def _locked_run():
            async with self._locks[config_id]:
                await self._execute_research(cfg)

        asyncio.create_task(
            _locked_run(), name=f"periodic-{config_id}-manual"
        )

    # -- internals ---------------------------------------------------------

    async def _schedule_one(self, cfg: dict) -> None:
        """Create a background asyncio.Task that loops for this config."""
        config_id = cfg["id"]
        username = cfg.get("username", self._default_username)

        # Avoid duplicate tasks
        if config_id in self._tasks:
            return
        if config_id not in self._locks:
            self._locks[config_id] = asyncio.Lock()

        async def loop() -> None:
            while True:
                try:
                    cfg = get_config(config_id, username)
                    if not cfg or not cfg.get("enabled"):
                        self._tasks.pop(config_id, None)
                        return

                    next_run_str = cfg.get("next_run_at")
                    if next_run_str:
                        try:
                            next_run = datetime.fromisoformat(next_run_str)
                            now = datetime.now(timezone.utc)
                            sleep_seconds = (next_run - now).total_seconds()
                            if sleep_seconds > 0:
                                logger.info(
                                    "Periodic: %s sleeping for %.0fs until %s",
                                    config_id, sleep_seconds, next_run_str,
                                )
                                await asyncio.sleep(sleep_seconds)
                        except (ValueError, TypeError):
                            pass

                    # Re-check after sleep
                    cfg = get_config(config_id, username)
                    if not cfg or not cfg.get("enabled"):
                        return

                    async with self._locks[config_id]:
                        await self._execute_research(cfg)

                    # Compute and persist next run
                    run_hour = cfg.get("run_hour")
                    run_dow = cfg.get("run_dow")
                    run_dom = cfg.get("run_dom")
                    next_run = _compute_next_run(
                        cfg["interval_type"],
                        run_hour=run_hour,
                        run_dow=run_dow,
                        run_dom=run_dom,
                    )
                    mark_run(
                        config_id,
                        datetime.now(timezone.utc).isoformat(),
                        next_run,
                    )
                except asyncio.CancelledError:
                    logger.info("Periodic: task cancelled for %s", config_id)
                    return
                except Exception:
                    logger.exception("Periodic: error in loop for %s", config_id)
                    # Wait a bit before retrying to avoid tight error loops
                    await asyncio.sleep(60)

        task = asyncio.create_task(loop(), name=f"periodic-{config_id}")
        self._tasks[config_id] = task

    async def _execute_research(self, cfg: dict) -> None:
        """Run a single headless research execution and save results."""
        topic = cfg["topic"]
        config_id = cfg["id"]
        username = cfg.get("username", self._default_username)
        logger.info("Periodic: executing research for %s: %s", config_id, topic)

        try:
            config_data = json.loads(cfg["config_json"])
        except (json.JSONDecodeError, TypeError):
            logger.warning("Periodic: invalid config_json for %s", config_id)
            return

        config = ResearchConfig(
            topic=config_data.get("topic", topic),
            rounds=int(config_data.get("rounds", 3)),
            sources_per_round=int(config_data.get("sources_per_round", 10)),
            auto_mode=True,
            trusted_sources=list(config_data.get("trusted_sources", [])),
            blocked_sources=list(config_data.get("blocked_sources", [])),
            research_depth=str(config_data.get("research_depth", "standard")),
            source_types=list(config_data.get("source_types", [])),
            timelimit=str(config_data.get("timelimit", "m")),
        )

        wiki_dir, raw_dir = _get_wiki_dirs()
        orchestrator = ResearchOrchestrator(wiki_dir, raw_dir, wiki_llm_fn)
        session_id = uuid.uuid4().hex[:16]

        def _check_ingested(url: str) -> bool:
            return is_url_already_ingested(config_id, url)

        # Fetch prior run's report so the model knows what was already covered
        prior_report = None
        existing_thread_id = get_thread_id(config_id)
        if existing_thread_id:
            try:
                thread_msgs = get_thread_messages(existing_thread_id, username)
                for msg in reversed(thread_msgs):
                    if msg.get("role") == "assistant":
                        content = msg.get("content", "")
                        if isinstance(content, list):
                            # content may be stored as a list of parts
                            content = "".join(
                                part.get("text", "") for part in content
                                if isinstance(part, dict) and part.get("type") == "text"
                            )
                        if content and len(content) > 200:
                            prior_report = content
                            break
            except Exception:
                logger.exception("Periodic: failed to fetch prior report for %s", config_id)

        result = await orchestrator.run_research_headless(
            config, session_id, url_already_ingested=_check_ingested,
            prior_report=prior_report,
        )

        # Track ingested URLs for dedup
        for url in result.get("ingested_urls", []):
            mark_url_ingested(config_id, url)

        # Save as chat thread — persist thread_id so subsequent runs append
        now = datetime.now(timezone.utc).isoformat()
        existing_thread_id = get_thread_id(config_id)

        if existing_thread_id:
            # Append new run to the same thread
            run_label = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            error_text = ""
            if result.get("error"):
                error_text = f"\n**Error:** {result['error']}\n"
            warnings_text = ""
            if result.get("warnings"):
                warnings_text = (
                    f"\nWarnings:\n" + "\n".join(
                        f"- {w.get('url','')}: {w.get('error','')}"
                        for w in result["warnings"]
                    )
                )
            if result['total_ingested'] == 0 and not result.get("error") and not result.get("warnings"):
                warnings_text = "\nNo new sources were discovered. This may indicate that all search results were already ingested, filtered by trusted sources, or that the web search returned no results for this topic."
            context_msg = (
                f"---\n"
                f"### Run at {run_label}\n"
                f"Sources ingested: {result['total_ingested']}\n"
                f"{error_text}"
                f"{warnings_text}"
            )

            content_text = context_msg
            if result["final_report"]:
                content_text += f"\n\n{result['final_report']}"
            messages = [{
                "id": f"{existing_thread_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                "role": "assistant",
                "content": [{"type": "text", "text": content_text}],
                "parent_id": None,
                "created_at": now,
            }]

            try:
                append_thread_messages(
                    thread_id=existing_thread_id,
                    username=username,
                    title=result.get("title", topic),
                    updated_at=now,
                    messages=messages,
                )
                logger.info("Periodic: appended to thread %s for %s", existing_thread_id, config_id)
            except Exception:
                logger.exception("Periodic: failed to append to thread %s", config_id)
        else:
            # First run — create new thread
            thread_id = f"periodic-{config_id}"
            set_thread_id(config_id, thread_id)

            error_text = ""
            if result.get("error"):
                error_text = f"\n**Error:** {result['error']}\n"
            warnings_text = ""
            if result.get("warnings"):
                warnings_text = (
                    f"\nWarnings:\n" + "\n".join(
                        f"- {w.get('url','')}: {w.get('error','')}"
                        for w in result["warnings"]
                    )
                )
            if result['total_ingested'] == 0 and not result.get("error") and not result.get("warnings"):
                warnings_text = "\nNo new sources were discovered. This may indicate that all search results were already ingested, filtered by trusted sources, or that the web search returned no results for this topic."
            context_msg = (
                f"Periodic research on: {topic}\n"
                f"Interval: {cfg['interval_type']}\n"
                f"Sources ingested: {result['total_ingested']}\n"
                f"Started: {result['started_at']}\n"
                f"Completed: {result['completed_at']}\n"
                f"{error_text}"
                f"{warnings_text}"
            )

            messages = [
                {
                    "id": f"{thread_id}-ctx",
                    "role": "system",
                    "content": [{"type": "text", "text": context_msg}],
                    "parent_id": None,
                    "created_at": now,
                },
            ]
            if result["final_report"]:
                messages.append({
                    "id": f"{thread_id}-report",
                    "role": "assistant",
                    "content": [{"type": "text", "text": result["final_report"]}],
                    "parent_id": None,
                    "created_at": now,
                })

            try:
                # Use append_thread_messages (not upsert_thread) so we
                # never DELETE existing messages.  If get_thread_id
                # returned None due to a DB glitch but the thread
                # already exists, upsert_thread would wipe all prior
                # runs.  append_thread_messages uses INSERT OR IGNORE
                # and creates the thread if needed via ON CONFLICT.
                append_thread_messages(
                    thread_id=thread_id,
                    username=username,
                    title=result.get("title", topic),
                    updated_at=now,
                    messages=messages,
                )
                logger.info("Periodic: created thread %s for %s", thread_id, config_id)
            except Exception:
                logger.exception("Periodic: failed to create thread for %s", config_id)
