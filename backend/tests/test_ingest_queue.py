"""Durable ingestion queue.

The queue is what keeps ingestion alive after the client disconnects, so its
claim/retry/recovery behaviour is tested directly.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ingest_queue  # noqa: E402


@pytest.fixture()
def queue(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest_queue, "_DB_PATH", str(tmp_path / "ingest_jobs.db"))
    monkeypatch.setattr(ingest_queue, "_SCHEMA_READY_FOR", None)
    monkeypatch.setattr(ingest_queue, "_RETRY_DELAY_SECONDS", 0.0)
    return ingest_queue


def test_enqueue_dedups_pending_job(queue):
    first = queue.enqueue("url", "https://example.com/a")
    second = queue.enqueue("url", "https://example.com/a")
    assert first == second
    assert queue.pending_count() == 1


def test_claim_marks_running_and_increments_attempts(queue):
    job_id = queue.enqueue("raw", "raw/file.pdf")
    job = queue.claim_next()

    assert job is not None
    assert job.id == job_id
    assert job.kind == "raw"
    assert job.attempts == 1
    assert queue.claim_next() is None


def test_failure_is_retried_then_marked_failed(queue, monkeypatch):
    monkeypatch.setattr(queue, "_MAX_ATTEMPTS", 2)
    job_id = queue.enqueue("raw", "raw/file.pdf")

    first = queue.claim_next()
    queue.finish(first, error="boom")
    second = queue.claim_next()
    queue.finish(second, error="boom")

    assert queue.claim_next() is None
    conn = queue._get_conn()
    try:
        row = conn.execute(
            "SELECT status, attempts, error FROM ingest_jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        conn.close()
    assert row["status"] == "failed"
    assert row["attempts"] == 2
    assert row["error"] == "boom"


def test_successful_job_is_not_reclaimed(queue):
    queue.enqueue("raw", "raw/file.pdf")
    job = queue.claim_next()
    queue.finish(job)

    assert queue.claim_next() is None
    assert queue.pending_count() == 0


def test_interrupted_jobs_are_recovered_on_start(queue):
    queue.enqueue("raw", "raw/file.pdf")
    claimed = queue.claim_next()
    assert claimed is not None

    assert queue.reset_running() == 1
    recovered = queue.claim_next()
    assert recovered is not None
    assert recovered.id == claimed.id
    assert recovered.attempts == 2


def test_worker_processes_jobs(queue):
    processed = threading.Event()

    def process(job):
        processed.set()

    worker = queue.IngestWorker(process, poll_seconds=0.05)
    worker.start()
    try:
        queue.enqueue("url", "https://example.com/a")
        assert processed.wait(2.0), "worker did not process the job"
        deadline = time.time() + 2.0
        while queue.pending_count() and time.time() < deadline:
            time.sleep(0.01)
        assert queue.pending_count() == 0
    finally:
        worker.stop()


class FakeIngestor:
    def __init__(self, raw_dir: Path):
        self.raw_dir = raw_dir
        self.file_calls = []
        self.raw_calls = 0

    def ingest_file(self, source, contributor=None):
        self.file_calls.append(str(source))
        return "A page"

    def ingest_pending_raw_files(self, max_files=8, contributor=None):
        self.raw_calls += 1
        return []

    def pop_recent_ingest_metadata(self, source):
        return {"source_page": "sources/a.md"}

    def is_local_source_pending(self, source):
        return False


def test_url_processor_keeps_url_intact_and_marks_dedup(queue, tmp_path, monkeypatch):
    import periodic_store

    marked = []
    monkeypatch.setattr(
        periodic_store,
        "mark_url_globally_ingested",
        lambda url, source_page="": marked.append((url, source_page)),
    )
    fake = FakeIngestor(tmp_path / "raw")
    process = queue.build_processor(lambda: fake)

    process(queue.IngestJob(id=1, kind="url", source="https://example.com/a?b=1", attempts=1))

    assert fake.file_calls == ["https://example.com/a?b=1"]
    assert marked == [("https://example.com/a?b=1", "sources/a.md")]


def test_raw_file_processor_uses_pending_raw_ingest(queue, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "file.pdf"
    source.write_bytes(b"x")
    fake = FakeIngestor(raw_dir)
    process = queue.build_processor(lambda: fake)

    process(queue.IngestJob(id=1, kind="raw", source=str(source), attempts=1))

    assert fake.raw_calls == 1
    assert fake.file_calls == []


def test_raw_processor_retries_when_source_still_pending(queue, tmp_path):
    class PendingIngestor(FakeIngestor):
        def is_local_source_pending(self, source):
            return True

    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = raw_dir / "file.pdf"
    source.write_bytes(b"x")
    fake = PendingIngestor(raw_dir)
    process = queue.build_processor(lambda: fake)

    with pytest.raises(RuntimeError):
        process(queue.IngestJob(id=1, kind="raw", source=str(source), attempts=1))


def test_file_outside_raw_uses_single_file_ingest(queue, tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    source = tmp_path / "outside.pdf"
    source.write_bytes(b"x")
    fake = FakeIngestor(raw_dir)
    process = queue.build_processor(lambda: fake)

    process(queue.IngestJob(id=1, kind="file", source=str(source), attempts=1))

    assert fake.raw_calls == 0
    assert fake.file_calls == [str(source)]
