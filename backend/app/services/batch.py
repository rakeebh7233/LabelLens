"""Parallel batch runner and the in-memory job store.

Labels run on a bounded thread pool. Threads are enough for real parallelism here: Tesseract
runs as a separate process and OpenCV releases the GIL, so the CPU-heavy work is not held
back by Python. Results are appended as each label finishes, so a poller sees the table fill
in. One label failing never affects the others: verify_label turns every failure into a
result, and the worker also guards against anything unexpected.
"""

import csv
import io
import logging
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.schemas import (
    BatchJob,
    BatchProgress,
    FieldName,
    JobState,
    LabelResult,
    Status,
)
from app.services.manifest import BatchItem
from app.services.verify import UNEXPECTED_ERROR, verify_label

logger = logging.getLogger(__name__)

Verifier = Callable[..., LabelResult]


@dataclass
class _Job:
    job: BatchJob
    finished_at: float | None = None
    results: list[LabelResult] = field(default_factory=list)


class JobStore:
    """Thread-safe store of batch jobs. Finished jobs are dropped after `ttl_s` seconds.

    This is the only shared mutable state in the app. Nothing is persisted: restarting the
    server forgets every job, which matches the rule that uploads and results are not stored.
    """

    def __init__(self, ttl_s: float) -> None:
        self._ttl_s = ttl_s
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def create(self, total: int) -> str:
        job_id = uuid.uuid4().hex
        job = BatchJob(
            job_id=job_id,
            state=JobState.QUEUED,
            created_at=datetime.now(UTC),
            progress=BatchProgress(total=total),
        )
        with self._lock:
            self._purge()
            self._jobs[job_id] = _Job(job)
        return job_id

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry and entry.job.state is JobState.QUEUED:
                entry.job.state = JobState.RUNNING

    def add_result(self, job_id: str, result: LabelResult) -> None:
        with self._lock:
            entry = self._jobs.get(job_id)
            if entry is None:
                return
            entry.results.append(result)
            progress = entry.job.progress
            progress.completed += 1
            status = result.overall_status
            if status is Status.PASS:
                progress.passed += 1
            elif status is Status.REVIEW:
                progress.review += 1
            else:
                progress.failed += 1
            if progress.completed >= progress.total:
                entry.job.state = JobState.DONE
                entry.finished_at = time.monotonic()

    def get(self, job_id: str, since: int = 0) -> BatchJob | None:
        """A snapshot of the job with the results after the first `since`."""
        with self._lock:
            self._purge()
            entry = self._jobs.get(job_id)
            if entry is None:
                return None
            return entry.job.model_copy(
                update={
                    "progress": entry.job.progress.model_copy(),
                    "results": list(entry.results[max(0, since) :]),
                },
            )

    def _purge(self) -> None:
        """Drop finished jobs past their TTL. Caller holds the lock."""
        now = time.monotonic()
        expired = [
            job_id
            for job_id, entry in self._jobs.items()
            if entry.finished_at is not None and now - entry.finished_at > self._ttl_s
        ]
        for job_id in expired:
            del self._jobs[job_id]


class BatchRunner:
    def __init__(self, store: JobStore, workers: int, verify: Verifier = verify_label) -> None:
        self.store = store
        self._verify = verify
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="batch")

    def submit(self, items: list[BatchItem]) -> str:
        """Start checking every item; returns the job id immediately."""
        job_id = self.store.create(total=len(items))
        for item in items:
            if item.problem or item.image is None or item.application is None:
                # Known problem (no match, bad file): report it straight away.
                message = item.problem or UNEXPECTED_ERROR
                self.store.add_result(job_id, _error_result(item, message))
            else:
                self._pool.submit(self._run, job_id, item)
        return job_id

    def _run(self, job_id: str, item: BatchItem) -> None:
        self.store.mark_running(job_id)
        try:
            assert item.image is not None and item.application is not None
            result = self._verify(item.image, item.application, filename=item.filename)
        except Exception:
            logger.exception("Batch worker failed on %s", item.filename)
            result = _error_result(item, UNEXPECTED_ERROR)
        finally:
            item.image = None  # release the upload as soon as it has been checked
        self.store.add_result(job_id, result)

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def _error_result(item: BatchItem, message: str) -> LabelResult:
    return LabelResult(label_id=uuid.uuid4().hex, filename=item.filename, fields=[], error=message)


# CSV export

_SEVERITY_ORDER = {Status.FAIL: 0, Status.REVIEW: 1, Status.PASS: 2}
# Spreadsheet apps run cells starting with these as formulas; label text comes from OCR.
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    text = "" if value is None else str(value)
    return f"'{text}" if text.startswith(_FORMULA_START) else text


def results_csv(results: list[LabelResult]) -> str:
    """One row per label, fails first, then review, then pass; by file name within each."""
    header = ["filename", "overall_status", "problem"]
    for name in FieldName:
        header += [f"{name}_status", f"{name}_found", f"{name}_reason"]
    header.append("seconds")

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    ordered = sorted(
        results, key=lambda r: (_SEVERITY_ORDER[r.overall_status], (r.filename or "").casefold())
    )
    for result in ordered:
        by_field = {f.field: f for f in result.fields}
        row: list[object] = [result.filename, result.overall_status, result.error]
        for name in FieldName:
            f = by_field.get(name)
            row += [f.status, f.found, f.reason] if f else ["", "", ""]
        total_ms = result.timings_ms.get("total")
        row.append(f"{total_ms / 1000:.1f}" if total_ms is not None else "")
        writer.writerow([_cell(v) for v in row])
    return out.getvalue()

