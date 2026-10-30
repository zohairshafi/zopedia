"""Durable server-side wiki ingestion queue.

Upload and URL-ingest requests only enqueue a job and return. A worker thread
claims jobs from SQLite, so ingestion keeps running when the client disconnects
or the phone is turned off, and resumes after a server restart.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from utils.auth_root import get_auth_root

logger = logging.getLogger(__name__)

_DB_PATH = os.path.join(get_auth_root(), "ingest_jobs.db")
_MAX_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 15.0
_SCHEMA_READY_FOR: Optional[str] = None
_DB_LOCK = threading.Lock()
_WAKE = threading.Event()


@dataclass(frozen=True)
class IngestJob:
    id: int
    kind: str
    source: str
    attempts: int


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _ensure_schema() -> None:
    global _SCHEMA_READY_FOR
    if _SCHEMA_READY_FOR == _DB_PATH:
        return

    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = _get_conn()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                next_attempt_at REAL NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS ingest_jobs_status_next "
            "ON ingest_jobs (status, next_attempt_at, id)"
        )
        conn.commit()
    finally:
        conn.close()
    _SCHEMA_READY_FOR = _DB_PATH


def enqueue(kind: str, source: str, dedup: bool = True) -> int:
    """Add a job and wake the worker. Returns the job id.

    With ``dedup``, an existing pending or running job for the same kind and
    source is reused instead of stacking duplicates.
    """
    _ensure_schema()
    now = time.time()
    with _DB_LOCK:
        conn = _get_conn()
        try:
            if dedup:
                existing = conn.execute(
                    "SELECT id FROM ingest_jobs "
                    "WHERE kind = ? AND source = ? AND status IN ('pending', 'running') "
                    "LIMIT 1",
                    (kind, source),
                ).fetchone()
                if existing:
                    return int(existing["id"])

            cursor = conn.execute(
                "INSERT INTO ingest_jobs "
                "(kind, source, status, attempts, created_at, updated_at, next_attempt_at) "
                "VALUES (?, ?, 'pending', 0, ?, ?, 0)",
                (kind, source, now, now),
            )
            conn.commit()
            job_id = int(cursor.lastrowid)
        finally:
            conn.close()

    _WAKE.set()
    return job_id


def claim_next() -> Optional[IngestJob]:
    """Atomically mark the oldest due job running and return it."""
    _ensure_schema()
    now = time.time()
    with _DB_LOCK:
        conn = _get_conn()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id, kind, source, attempts FROM ingest_jobs "
                "WHERE status = 'pending' AND next_attempt_at <= ? "
                "ORDER BY id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None

            attempts = int(row["attempts"]) + 1
            conn.execute(
                "UPDATE ingest_jobs SET status = 'running', attempts = ?, updated_at = ? "
                "WHERE id = ?",
                (attempts, now, row["id"]),
            )
            conn.commit()
            return IngestJob(
                id=int(row["id"]),
                kind=str(row["kind"]),
                source=str(row["source"]),
                attempts=attempts,
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def finish(job: IngestJob, error: Optional[str] = None) -> None:
    """Complete a job, or schedule a retry after a failure."""
    _ensure_schema()
    now = time.time()
    with _DB_LOCK:
        conn = _get_conn()
        try:
            if error is None:
                conn.execute(
                    "UPDATE ingest_jobs SET status = 'done', error = NULL, updated_at = ? "
                    "WHERE id = ?",
                    (now, job.id),
                )
            elif job.attempts >= _MAX_ATTEMPTS:
                conn.execute(
                    "UPDATE ingest_jobs SET status = 'failed', error = ?, updated_at = ? "
                    "WHERE id = ?",
                    (error, now, job.id),
                )
                logger.error(
                    "Ingest job %s (%s %s) failed after %s attempts: %s",
                    job.id, job.kind, job.source, job.attempts, error,
                )
            else:
                retry_at = now + _RETRY_DELAY_SECONDS * job.attempts
                conn.execute(
                    "UPDATE ingest_jobs SET status = 'pending', error = ?, "
                    "updated_at = ?, next_attempt_at = ? WHERE id = ?",
                    (error, now, retry_at, job.id),
                )
                logger.warning(
                    "Ingest job %s (%s %s) failed (attempt %s); retrying in %.0fs: %s",
                    job.id, job.kind, job.source, job.attempts,
                    retry_at - now, error,
                )
            conn.commit()
        finally:
            conn.close()


def reset_running() -> int:
    """Return jobs left running by a crash or shutdown to the pending queue."""
    _ensure_schema()
    with _DB_LOCK:
        conn = _get_conn()
        try:
            cursor = conn.execute(
                "UPDATE ingest_jobs SET status = 'pending', next_attempt_at = 0, updated_at = ? "
                "WHERE status = 'running'",
                (time.time(),),
            )
            conn.commit()
            return int(cursor.rowcount or 0)
        finally:
            conn.close()


def pending_count() -> int:
    _ensure_schema()
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM ingest_jobs WHERE status IN ('pending', 'running')"
        ).fetchone()
        return int(row["count"]) if row else 0
    finally:
        conn.close()


def build_processor(
    get_ingestor: Callable[[], object],
) -> Callable[[IngestJob], None]:
    """Build the callable that performs one job against the current ingestor.

    The getter is resolved per job so a soft wiki reload swaps the ingestor
    without restarting the worker.
    """

    def process(job: IngestJob) -> None:
        ingestor = get_ingestor()
        if ingestor is None:
            raise RuntimeError("Wiki ingestor is not available")

        if job.kind == "url":
            _process_url(ingestor, job.source)
            return

        if job.kind == "file":
            path = Path(job.source).expanduser()
            try:
                path.resolve().relative_to(ingestor.raw_dir.expanduser().resolve())
                in_raw = True
            except ValueError:
                in_raw = False
            if in_raw:
                _process_raw(ingestor, job.source)
            else:
                title = ingestor.ingest_file(path, contributor="Zopedia")
                if not title:
                    raise RuntimeError(f"Ingestion returned no result for {path}")
            return

        if job.kind == "raw":
            _process_raw(ingestor, job.source)
            return

        raise ValueError(f"Unknown ingest job kind: {job.kind}")

    return process


def _process_raw(ingestor, source: Optional[str] = None) -> None:
    ingestor.ingest_pending_raw_files(max_files=8, contributor="Zopedia")

    # A batch can finish while one source failed (the ingestor reverts its
    # hash). Retry that source instead of marking the queue job successful.
    if source and source != "startup":
        path = Path(source).expanduser()
        if path.exists() and ingestor.is_local_source_pending(path):
            raise RuntimeError(f"Ingestion did not complete for {path}")


def _process_url(ingestor, url: str) -> None:
    from periodic_store import mark_url_globally_ingested

    # The endpoint rejects URLs already in the dedup table before enqueueing.
    # Retries must still re-attempt a URL whose earlier attempt failed partway,
    # so do not skip here on a partially-written dedup row.
    title = ingestor.ingest_file(url, contributor="Zopedia")
    if not title:
        raise RuntimeError(f"Ingestion returned no result for {url}")

    metadata = ingestor.pop_recent_ingest_metadata(url) or {}
    source_page = str(metadata.get("source_page", "") or "")
    mark_url_globally_ingested(url, source_page)


class IngestWorker:
    """Single-threaded worker that drains the durable queue."""

    def __init__(
        self,
        processor: Callable[[IngestJob], None],
        poll_seconds: float = 2.0,
    ) -> None:
        self._processor = processor
        self._poll_seconds = max(0.2, poll_seconds)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        recovered = reset_running()
        if recovered:
            logger.info("Recovered %d interrupted ingest job(s) after restart", recovered)
        self._thread = threading.Thread(
            target=self._run, name="wiki-ingest-worker", daemon=True
        )
        self._thread.start()
        # Sweep raw/ on startup so a file written just before a crash (before
        # its job was committed) is still ingested after the restart.
        enqueue("raw", "startup", dedup=False)
        logger.info("Wiki ingest worker started (%d pending job(s))", pending_count())

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        _WAKE.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            job = claim_next()
            if job is None:
                _WAKE.wait(self._poll_seconds)
                _WAKE.clear()
                continue

            try:
                self._processor(job)
            except Exception as exc:
                logger.exception("Ingest job %s failed", job.id)
                finish(job, error=str(exc) or exc.__class__.__name__)
            else:
                finish(job)
