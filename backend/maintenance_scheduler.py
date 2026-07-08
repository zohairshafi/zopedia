"""Background scheduler that runs wiki maintenance on configured schedules.

Polls the scheduled_maintenance table every 60 seconds and executes the
maintenance pipeline (merge → retry-fallback → enrich → rebuild-index)
for any due entries.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from main import AppState  # type: ignore[import-untyped]

from maintenance_store import list_due, update_schedule

logger = logging.getLogger(__name__)


def _compute_next_run(
    interval_type: str,
    run_hour: int | None = None,
    run_dow: int | None = None,
    run_dom: int | None = None,
    from_time: datetime | None = None,
) -> str:
    """Compute the next run timestamp from now."""
    now = from_time or datetime.now(timezone.utc)
    if interval_type == "hourly":
        nxt = now + timedelta(hours=1)
    elif interval_type == "daily":
        nxt = now + timedelta(days=1)
        if run_hour is not None:
            nxt = nxt.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    elif interval_type == "weekly":
        nxt = now + timedelta(weeks=1)
        if run_dow is not None:
            while nxt.weekday() != run_dow:
                nxt += timedelta(days=1)
        if run_hour is not None:
            nxt = nxt.replace(hour=run_hour, minute=0, second=0, microsecond=0)
    elif interval_type == "monthly":
        nxt = now + timedelta(days=30)
        if run_dom is not None:
            try:
                nxt = nxt.replace(day=min(run_dom, 28))
            except ValueError:
                pass
    else:
        nxt = now + timedelta(days=1)
    return nxt.isoformat()


async def run_maintenance_pipeline(app, username: str, with_web_fill: bool) -> dict:
    """Execute the full maintenance pipeline and return a result summary.

    This runs synchronously on a background thread so the scheduler loop
    is not blocked by the potentially long-running wiki operations.
    """
    mgr = app.state.wiki_manager

    def _run():
        mgr.merge_duplicate_knowledge_pages(dry_run=False)
        mgr.retry_fallback_analysis_pages(dry_run=False)
        mgr.enrich_analysis_pages(
            dry_run=False,
            fill_gaps_from_web=with_web_fill,
            max_web_gap_queries=8 if with_web_fill else None,
        )
        mgr.refresh_analysis_backlinks(dry_run=False, max_links_per_page=128)
        return {"status": "completed", "web_fill": with_web_fill}

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _run)


class MaintenanceScheduler:
    """Polls the store every *check_interval* seconds and runs due schedules."""

    def __init__(self, app, check_interval: int = 60):
        self._app = app
        self._interval = check_interval
        self._task: asyncio.Task | None = None

    async def _loop(self) -> None:
        while True:
            try:
                due = list_due()
                for entry in due:
                    asyncio.create_task(self._execute_one(entry))
            except Exception:
                logger.exception("Maintenance scheduler poll error")
            await asyncio.sleep(self._interval)

    async def _execute_one(self, entry: dict) -> None:
        sid = entry["id"]
        username = entry["username"]
        with_web = bool(entry.get("with_web_fill", 0))
        logger.info(
            "Running scheduled maintenance %s (%s)", sid,
            "web-fill" if with_web else "no-web-fill",
        )
        try:
            await run_maintenance_pipeline(self._app, username, with_web)
        except Exception:
            logger.exception("Scheduled maintenance %s failed", sid)

        # Advance the clock even if the run failed (so it doesn't retry
        # every 60 seconds forever).
        update_schedule(
            sid, username,
            last_run_at=datetime.now(timezone.utc).isoformat(),
            next_run_at=_compute_next_run(
                entry["interval_type"],
                entry.get("run_hour"),
                entry.get("run_dow"),
                entry.get("run_dom"),
            ),
        )

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop())
            logger.info("Maintenance scheduler started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("Maintenance scheduler stopped")
