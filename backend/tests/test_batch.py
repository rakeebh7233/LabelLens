import csv
import io
import threading
import time

from app.schemas import (
    ApplicationData,
    FieldName,
    FieldResult,
    JobState,
    LabelResult,
    Status,
)
from app.services.batch import BatchRunner, JobStore, results_csv
from app.services.manifest import BatchItem
from app.services.verify import UNEXPECTED_ERROR

APP = ApplicationData(
    brand_name="Old Tom", class_type="Bourbon", alcohol_content="45%", net_contents="750 mL"
)


def _field(status: Status, name: FieldName = FieldName.BRAND_NAME, found: str = "x") -> FieldResult:
    reason = None if status is Status.PASS else "Label differs"
    return FieldResult(
        field=name, status=status, expected="x", found=found, reason=reason, ocr_confidence=0.9
    )


def _result(filename: str, status: Status) -> LabelResult:
    return LabelResult(
        label_id=filename, filename=filename, fields=[_field(status)], timings_ms={"total": 1234}
    )


def fake_verify(image: bytes, application: ApplicationData, *, filename: str) -> LabelResult:
    """Status is encoded in the image bytes; b"boom" raises to simulate a worker crash."""
    if image == b"boom":
        raise RuntimeError("boom")
    return _result(filename, Status(image.decode()))


def wait_done(store: JobStore, job_id: str, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while store.get(job_id).state is not JobState.DONE:  # type: ignore[union-attr]
        assert time.monotonic() < deadline, "batch did not finish"
        time.sleep(0.01)


# JobStore


def test_store_tracks_progress_and_finishes() -> None:
    store = JobStore(ttl_s=60)
    job_id = store.create(total=3)
    assert store.get(job_id).state is JobState.QUEUED  # type: ignore[union-attr]
    store.mark_running(job_id)
    store.add_result(job_id, _result("a", Status.PASS))
    store.add_result(job_id, _result("b", Status.REVIEW))
    job = store.get(job_id)
    assert job is not None and job.state is JobState.RUNNING
    assert (job.progress.completed, job.progress.passed, job.progress.review) == (2, 1, 1)
    store.add_result(job_id, _result("c", Status.FAIL))
    job = store.get(job_id)
    assert job is not None and job.state is JobState.DONE and job.progress.failed == 1


def test_store_since_returns_only_new_results() -> None:
    store = JobStore(ttl_s=60)
    job_id = store.create(total=3)
    for name in "abc":
        store.add_result(job_id, _result(name, Status.PASS))
    job = store.get(job_id, since=2)
    assert job is not None
    assert [r.filename for r in job.results] == ["c"]
    assert job.progress.completed == 3


def test_store_snapshot_is_not_affected_by_later_results() -> None:
    store = JobStore(ttl_s=60)
    job_id = store.create(total=2)
    snapshot = store.get(job_id)
    store.add_result(job_id, _result("a", Status.PASS))
    assert snapshot is not None and snapshot.results == [] and snapshot.progress.completed == 0


def test_store_forgets_finished_jobs_after_ttl() -> None:
    store = JobStore(ttl_s=0.05)
    done = store.create(total=1)
    store.add_result(done, _result("a", Status.PASS))
    running = store.create(total=5)
    time.sleep(0.1)
    assert store.get(done) is None
    assert store.get(running) is not None  # unfinished jobs are never expired
    assert store.get("no-such-job") is None


# BatchRunner


def test_runner_checks_every_item_and_reports_problems_immediately() -> None:
    store = JobStore(ttl_s=60)
    runner = BatchRunner(store, workers=4, verify=fake_verify)
    items = [BatchItem(f"{i}.png", b"pass", APP) for i in range(8)]
    items.append(BatchItem("orphan.png", None, None, "This photo has no row in the spreadsheet"))
    job_id = runner.submit(items)
    wait_done(store, job_id)
    job = store.get(job_id)
    assert job is not None and job.progress.total == 9 and job.progress.passed == 8
    orphan = next(r for r in job.results if r.filename == "orphan.png")
    assert orphan.error == "This photo has no row in the spreadsheet"
    assert orphan.overall_status is Status.FAIL
    runner.shutdown()


def test_one_crashing_label_does_not_stop_the_batch() -> None:
    store = JobStore(ttl_s=60)
    runner = BatchRunner(store, workers=2, verify=fake_verify)
    items = [BatchItem(f"{i}.png", b"pass", APP) for i in range(9)]
    items.insert(4, BatchItem("bad.png", b"boom", APP))
    job_id = runner.submit(items)
    wait_done(store, job_id)
    job = store.get(job_id)
    assert job is not None
    assert (job.progress.completed, job.progress.passed, job.progress.failed) == (10, 9, 1)
    bad = next(r for r in job.results if r.filename == "bad.png")
    assert bad.error == UNEXPECTED_ERROR
    runner.shutdown()


def test_runner_releases_photo_bytes_after_checking() -> None:
    store = JobStore(ttl_s=60)
    runner = BatchRunner(store, workers=1, verify=fake_verify)
    item = BatchItem("a.png", b"pass", APP)
    wait_done(store, runner.submit([item]))
    assert item.image is None
    runner.shutdown()


def test_runner_uses_a_bounded_pool() -> None:
    active, peak, lock = 0, 0, threading.Lock()

    def slow_verify(image: bytes, application: ApplicationData, *, filename: str) -> LabelResult:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return _result(filename, Status.PASS)

    store = JobStore(ttl_s=60)
    runner = BatchRunner(store, workers=3, verify=slow_verify)
    wait_done(store, runner.submit([BatchItem(f"{i}.png", b"x", APP) for i in range(12)]))
    assert peak == 3
    runner.shutdown()


def test_cancel_stops_remaining_labels_and_keeps_finished_ones() -> None:
    started, release = threading.Event(), threading.Event()

    def held_verify(image: bytes, application: ApplicationData, *, filename: str) -> LabelResult:
        if filename == "0.png":
            return _result(filename, Status.PASS)
        started.set()
        release.wait(5)
        return _result(filename, Status.PASS)

    store = JobStore(ttl_s=60)
    runner = BatchRunner(store, workers=1, verify=held_verify)
    items = [BatchItem(f"{i}.png", b"x", APP) for i in range(5)]
    job_id = runner.submit(items)
    assert started.wait(5)  # 0.png done, 1.png in flight, 2-4 queued
    assert store.cancel(job_id)
    release.set()
    deadline = time.monotonic() + 5
    while any(item.image is not None for item in items):  # queued labels skip and release
        assert time.monotonic() < deadline, "queued labels were not released"
        time.sleep(0.01)
    runner.shutdown()

    job = store.get(job_id)
    assert job is not None and job.state is JobState.CANCELLED
    assert [r.filename for r in job.results] == ["0.png"]
    assert job.progress.completed == 1


def test_cancel_leaves_a_finished_job_done() -> None:
    store = JobStore(ttl_s=60)
    job_id = store.create(total=1)
    store.add_result(job_id, _result("a", Status.PASS))
    assert store.cancel(job_id)
    assert store.get(job_id).state is JobState.DONE  # type: ignore[union-attr]
    assert not store.cancel("nope")


# results_csv


def _rows(text: str) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(text)))


def test_csv_puts_fails_first_then_review_then_pass() -> None:
    results = [
        _result("b.png", Status.PASS),
        _result("c.png", Status.REVIEW),
        _result("a.png", Status.FAIL),
        LabelResult(label_id="x", filename="z.png", fields=[], error="This file could not be read"),
    ]
    rows = _rows(results_csv(results))
    assert [r["filename"] for r in rows] == ["a.png", "z.png", "c.png", "b.png"]
    assert rows[1]["problem"] == "This file could not be read"
    assert rows[0]["brand_name_status"] == "fail"
    assert rows[0]["seconds"] == "1.2"
    assert rows[1]["brand_name_status"] == ""


def test_csv_has_a_column_set_per_field() -> None:
    header = results_csv([]).splitlines()[0].split(",")
    for name in FieldName:
        assert {f"{name}_status", f"{name}_found", f"{name}_reason"} <= set(header)


def test_csv_neutralizes_cells_that_spreadsheets_would_run_as_formulas() -> None:
    result = LabelResult(
        label_id="x",
        filename="=HYPERLINK(evil).png",
        fields=[_field(Status.FAIL, found="-45% ABV")],
    )
    row = _rows(results_csv([result]))[0]
    assert row["filename"] == "'=HYPERLINK(evil).png"
    assert row["brand_name_found"] == "'-45% ABV"
