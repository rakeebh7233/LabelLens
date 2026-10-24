import csv
import dataclasses
import io
import shutil
import threading
import time
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app import main
from app.schemas import ApplicationData, FieldName, FieldResult, LabelResult, Status
from app.services.batch import BatchRunner, JobStore
from tests.label_images import encode_png, render_label

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Tesseract is not installed"
)

FIELDS = {
    "brand_name": "OLD TOM DISTILLERY",
    "class_type": "Kentucky Straight Bourbon Whiskey",
    "alcohol_content": "45% Alc./Vol. (90 Proof)",
    "net_contents": "750 mL",
}
GOOD_PNG = encode_png(render_label(brand=FIELDS["brand_name"]))
HEADER = "filename,brand_name,class_type,alcohol_content,net_contents,government_warning\n"


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(main.app) as test_client:  # runs the lifespan, which starts the batch pool
        yield test_client


def manifest(*filenames: str) -> bytes:
    row = ",".join(f'"{v}"' for v in FIELDS.values())
    return (HEADER + "".join(f"{name},{row},\n" for name in filenames)).encode()


def post_batch(
    client: TestClient, photos: list[tuple[str, bytes]], manifest_data: bytes | None
):  # type: ignore[no-untyped-def]
    files = [("images", (name, data, "application/octet-stream")) for name, data in photos]
    if manifest_data is not None:
        files.append(("manifest", ("applications.csv", manifest_data, "text/csv")))
    return client.post("/api/batch", files=files)


def wait_for_batch(
    client: TestClient, job_id: str, timeout: float = 60
) -> dict:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while True:
        job = client.get(f"/api/batch/{job_id}").json()
        if job["state"] == "done":
            return job
        assert time.monotonic() < deadline, f"batch not done: {job['progress']}"
        time.sleep(0.1)


# POST /api/verify


@needs_tesseract
def test_verify_good_label(client: TestClient) -> None:
    response = client.post(
        "/api/verify", data=FIELDS, files={"image": ("old_tom.png", GOOD_PNG, "image/png")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "pass"
    assert body["filename"] == "old_tom.png"
    assert len(body["fields"]) == 5
    assert all(0 <= f["ocr_confidence"] <= 1 for f in body["fields"])
    assert body["timings_ms"]["total"] < 5000


def test_verify_rejects_unsupported_file_type(client: TestClient) -> None:
    response = client.post(
        "/api/verify", data=FIELDS, files={"image": ("label.gif", b"GIF89a", "image/gif")}
    )
    assert response.status_code == 415
    assert response.json() == {
        "detail": "label.gif is not a supported photo type. Please use JPEG, PNG, WebP or TIFF."
    }


def test_verify_corrupt_image_is_a_result_with_a_plain_error(client: TestClient) -> None:
    response = client.post(
        "/api/verify", data=FIELDS, files={"image": ("corrupt.png", b"not a png", "image/png")}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "fail"
    assert body["error"].startswith("This file could not be read as an image")


def test_verify_rejects_too_large_file(client: TestClient) -> None:
    big = b"\0" * (main.settings.max_upload_mb * 1024 * 1024 + 1)
    files = {"image": ("big.png", big, "image/png")}
    response = client.post("/api/verify", data=FIELDS, files=files)
    assert response.status_code == 413
    assert "larger than the 10 MB limit" in response.json()["detail"]


def test_verify_rejects_empty_file(client: TestClient) -> None:
    response = client.post("/api/verify", data=FIELDS, files={"image": ("e.png", b"", "image/png")})
    assert response.status_code == 400
    assert response.json()["detail"] == "e.png is empty."


def test_verify_requires_a_photo(client: TestClient) -> None:
    response = client.post("/api/verify", data=FIELDS)
    assert response.status_code == 400
    assert response.json()["detail"] == "Please choose a photo of the label."


def test_verify_names_the_missing_fields(client: TestClient) -> None:
    data = FIELDS | {"brand_name": " ", "net_contents": ""}
    response = client.post(
        "/api/verify", data=data, files={"image": ("a.png", GOOD_PNG, "image/png")}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "Please fill in the brand name and net contents."


# POST /api/batch: request-level problems are rejected


@pytest.mark.parametrize(
    ("photos", "manifest_data", "code", "detail"),
    [
        ([("a.png", GOOD_PNG)], None, 400, "Please include the spreadsheet"),
        ([], manifest(), 400, "Please choose at least one label photo."),
        ([("a.png", GOOD_PNG)], b"filename\na.png\n", 400, "missing these columns"),
        ([("a.png", GOOD_PNG)], HEADER.encode(), 400, "no rows"),
    ],
)
def test_batch_rejects_unusable_requests(
    client: TestClient,
    photos: list[tuple[str, bytes]],
    manifest_data: bytes | None,
    code: int,
    detail: str,
) -> None:
    response = post_batch(client, photos, manifest_data)
    assert response.status_code == code
    assert detail in response.json()["detail"]


def test_batch_manifest_must_be_csv(client: TestClient) -> None:
    files = [
        ("images", ("a.png", GOOD_PNG, "image/png")),
        ("manifest", ("applications.xlsx", b"PK", "application/octet-stream")),
    ]
    response = client.post("/api/batch", files=files)
    assert response.status_code == 415
    assert "CSV" in response.json()["detail"]


def test_batch_rejects_too_many_photos(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, max_batch_files=2))
    photos = [(f"{i}.png", GOOD_PNG) for i in range(3)]
    response = post_batch(client, photos, manifest("0.png", "1.png", "2.png"))
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail.startswith("A batch can have at most 2 photos; this one has 3.")


def test_batch_rejects_too_much_data(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "settings", dataclasses.replace(main.settings, max_batch_mb=0))
    response = post_batch(client, [("a.png", GOOD_PNG)], manifest("a.png"))
    assert response.status_code == 413
    assert "add up to more than 0 MB" in response.json()["detail"]


# POST /api/batch: per-photo problems become error rows, the batch carries on


@needs_tesseract
def test_one_bad_file_in_a_batch_of_ten_does_not_stop_the_others(client: TestClient) -> None:
    photos = [(f"{i:02}.png", GOOD_PNG) for i in range(9)]
    photos.insert(4, ("corrupt.png", b"this is not an image"))
    photos += [("orphan_image.png", GOOD_PNG), ("label.gif", b"GIF89a")]
    names = [name for name, _ in photos if name != "orphan_image.png"] + ["missing_file.png"]
    response = post_batch(client, photos, manifest(*names))
    assert response.status_code == 202
    created = response.json()
    assert created["total"] == 13

    job = wait_for_batch(client, created["job_id"])
    by_name = {r["filename"]: r for r in job["results"]}
    assert job["progress"]["passed"] == 9
    assert job["progress"]["failed"] == 4
    assert by_name["corrupt.png"]["error"].startswith("This file could not be read as an image")
    assert by_name["orphan_image.png"]["error"] == "This photo has no row in the spreadsheet"
    assert by_name["missing_file.png"]["error"] == "No photo was uploaded for this spreadsheet row"
    assert by_name["label.gif"]["error"].startswith("label.gif is not a supported photo type")


@needs_tesseract
def test_twenty_label_batch_completes_and_reports_progress(client: TestClient) -> None:
    """Phase 7 acceptance: progress is visible while running and the batch finishes."""
    names = [f"{i:02}.png" for i in range(20)]
    response = post_batch(client, [(n, GOOD_PNG) for n in names], manifest(*names))
    job_id = response.json()["job_id"]

    seen: list[int] = []
    received: list[dict] = []  # type: ignore[type-arg]
    deadline = time.monotonic() + 120
    while True:
        job = client.get(f"/api/batch/{job_id}", params={"since": len(received)}).json()
        received += job["results"]  # only results not received yet
        seen.append(job["progress"]["completed"])
        if job["state"] == "done":
            break
        assert time.monotonic() < deadline
        time.sleep(0.1)

    assert seen == sorted(seen)
    assert len(set(seen)) > 2, f"progress was not reported along the way: {seen}"
    assert sorted(r["filename"] for r in received) == names
    assert job["progress"] == {"total": 20, "completed": 20, "passed": 20, "review": 0, "failed": 0}


# GET /api/batch/{id} and export


def test_unknown_batch_is_404_with_a_plain_message(client: TestClient) -> None:
    for path in ("/api/batch/nope", "/api/batch/nope/export.csv"):
        response = client.get(path)
        assert response.status_code == 404
        assert "This batch was not found" in response.json()["detail"]


def test_export_waits_for_the_batch_then_returns_csv(client: TestClient) -> None:
    release = threading.Event()

    def held_verify(image: bytes, application: ApplicationData, *, filename: str) -> LabelResult:
        release.wait(5)
        if filename == "b.png":
            error = "This file could not be read as an image"
            return LabelResult(label_id=filename, filename=filename, fields=[], error=error)
        passed = FieldResult(
            field=FieldName.BRAND_NAME,
            status=Status.PASS,
            expected="x",
            found="x",
            ocr_confidence=1,
        )
        return LabelResult(label_id=filename, filename=filename, fields=[passed])

    runner = BatchRunner(JobStore(ttl_s=60), workers=2, verify=held_verify)
    client.app.state.batch = runner  # type: ignore[attr-defined]
    photos = [("a.png", GOOD_PNG), ("b.png", GOOD_PNG)]
    response = post_batch(client, photos, manifest("a.png", "b.png"))
    job_id = response.json()["job_id"]

    running = client.get(f"/api/batch/{job_id}/export.csv")
    assert running.status_code == 409
    assert running.json()["detail"] == "This batch is still running. Export when it has finished."

    release.set()
    wait_for_batch(client, job_id)
    export = client.get(f"/api/batch/{job_id}/export.csv")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("text/csv")
    disposition = export.headers["content-disposition"]
    assert disposition == f'attachment; filename="labellens-{job_id[:8]}.csv"'
    rows = list(csv.DictReader(io.StringIO(export.text)))
    assert [r["filename"] for r in rows] == ["b.png", "a.png"]  # fails first


def test_cancel_stops_a_batch_and_allows_export(client: TestClient) -> None:
    release = threading.Event()

    def held_verify(image: bytes, application: ApplicationData, *, filename: str) -> LabelResult:
        release.wait(5)
        return LabelResult(label_id=filename, filename=filename, fields=[], error="x")

    runner = BatchRunner(JobStore(ttl_s=60), workers=1, verify=held_verify)
    client.app.state.batch = runner  # type: ignore[attr-defined]
    photos = [("a.png", GOOD_PNG), ("b.png", GOOD_PNG)]
    job_id = post_batch(client, photos, manifest("a.png", "b.png")).json()["job_id"]

    cancelled = client.delete(f"/api/batch/{job_id}")
    release.set()
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert client.get(f"/api/batch/{job_id}/export.csv").status_code == 200
    assert client.delete("/api/batch/nope").status_code == 404
    runner.shutdown()


def test_errors_never_leak_stack_traces(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(main, "verify_label", explode)
    test_client = TestClient(main.app, raise_server_exceptions=False)
    response = test_client.post(
        "/api/verify", data=FIELDS, files={"image": ("a.png", GOOD_PNG, "image/png")}
    )
    assert response.status_code == 500
    assert response.json() == {"detail": "Something went wrong on our side. Please try again."}
