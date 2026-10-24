"""FastAPI application: API routes plus the built frontend served from the same origin.

Handlers are plain `def`, so FastAPI runs them in its thread pool and blocking OCR never
stalls the server. Every error reaches the user as {"detail": "<plain sentence>"}; stack traces
are logged, never returned.
"""

import logging
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import PurePosixPath

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.schemas import ApplicationData, BatchJob, JobState, LabelResult
from app.services.batch import BatchRunner, JobStore, results_csv
from app.services.manifest import ManifestError, Upload, base_name, pair_uploads, parse_manifest
from app.services.verify import verify_label

logger = logging.getLogger(__name__)
settings = get_settings()

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff")
MANIFEST_MAX_BYTES = 2 * 1024 * 1024
_FIELD_LABELS = {
    "brand_name": "brand name",
    "class_type": "class/type",
    "alcohol_content": "alcohol content",
    "net_contents": "net contents",
}


class UploadProblem(Exception):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class BatchCreated(BaseModel):
    job_id: str
    total: int


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    store = JobStore(ttl_s=settings.batch_ttl_minutes * 60)
    app.state.batch = BatchRunner(store, workers=settings.batch_workers)
    yield
    app.state.batch.shutdown()


app = FastAPI(title="LabelLens", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": "Some of the information sent was not in the expected form."},
    )


@app.exception_handler(Exception)
def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500, content={"detail": "Something went wrong on our side. Please try again."}
    )


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + f" and {words[-1]}"


def read_image(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an uploaded photo into memory, checking type and size. Raises UploadProblem."""
    name = base_name(upload.filename or "") or "The file"
    if PurePosixPath(name).suffix.casefold() not in IMAGE_EXTENSIONS:
        raise UploadProblem(
            f"{name} is not a supported photo type. Please use JPEG, PNG, WebP or TIFF.",
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        )
    data = upload.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise UploadProblem(
            f"{name} is larger than the {settings.max_upload_mb} MB limit. "
            "Please use a smaller photo.",
            status.HTTP_413_CONTENT_TOO_LARGE,
        )
    if not data:
        raise UploadProblem(f"{name} is empty.", status.HTTP_400_BAD_REQUEST)
    return data


@app.get("/api/health")
def health() -> dict[str, object]:
    tesseract = settings.tesseract_cmd or shutil.which("tesseract")
    return {"status": "ok", "tesseract_available": tesseract is not None}


@app.post("/api/verify", response_model=LabelResult)
def verify(
    image: UploadFile | None = File(None),
    brand_name: str = Form(""),
    class_type: str = Form(""),
    alcohol_content: str = Form(""),
    net_contents: str = Form(""),
    government_warning: str = Form(""),
) -> LabelResult:
    """Check one label photo against the application fields."""
    values = {
        "brand_name": brand_name,
        "class_type": class_type,
        "alcohol_content": alcohol_content,
        "net_contents": net_contents,
    }
    blank = [_FIELD_LABELS[key] for key, value in values.items() if not value.strip()]
    if image is None and blank:
        raise HTTPException(400, "Please choose a photo of the label and fill in every field.")
    if image is None:
        raise HTTPException(400, "Please choose a photo of the label.")
    if blank:
        raise HTTPException(422, f"Please fill in the {_join(blank)}.")
    if government_warning.strip():
        values["government_warning"] = government_warning
    try:
        application = ApplicationData(**values)
        data = read_image(image, settings.max_upload_mb * 1024 * 1024)
    except ValidationError:
        raise HTTPException(422, "Please check the application fields.") from None
    except UploadProblem as problem:
        raise HTTPException(problem.status_code, problem.message) from None
    return verify_label(data, application, filename=base_name(image.filename or ""))


@app.post("/api/batch", response_model=BatchCreated, status_code=status.HTTP_202_ACCEPTED)
def create_batch(
    request: Request,
    images: list[UploadFile] = File(default_factory=list),
    manifest: UploadFile | None = File(None),
) -> BatchCreated:
    """Start checking many photos against a CSV manifest; poll GET /api/batch/{job_id}."""
    if manifest is None:
        raise HTTPException(
            400, "Please include the spreadsheet (CSV file) that lists each photo's details."
        )
    if not images:
        raise HTTPException(400, "Please choose at least one label photo.")
    if len(images) > settings.max_batch_files:
        raise HTTPException(
            400,
            f"A batch can have at most {settings.max_batch_files} photos; this one has "
            f"{len(images)}. Please split it into smaller batches.",
        )
    if not (manifest.filename or "").casefold().endswith(".csv"):
        raise HTTPException(
            415, "The spreadsheet must be saved as a CSV file (in Excel: File > Save As > CSV)."
        )
    manifest_data = manifest.file.read(MANIFEST_MAX_BYTES + 1)
    if len(manifest_data) > MANIFEST_MAX_BYTES:
        raise HTTPException(413, "The spreadsheet is larger than 2 MB.")
    try:
        rows = parse_manifest(manifest_data)
    except ManifestError as exc:
        raise HTTPException(400, str(exc)) from None

    budget = settings.max_batch_mb * 1024 * 1024
    uploads: list[Upload] = []
    for image in images:
        try:
            data = read_image(image, settings.max_upload_mb * 1024 * 1024)
        except UploadProblem as problem:
            uploads.append(Upload(image.filename or "", None, problem.message))
            continue
        budget -= len(data)
        if budget < 0:
            raise HTTPException(
                413,
                f"These photos add up to more than {settings.max_batch_mb} MB. "
                "Please split them into smaller batches.",
            )
        uploads.append(Upload(image.filename or "", data))

    items = pair_uploads(uploads, rows)
    runner: BatchRunner = request.app.state.batch
    return BatchCreated(job_id=runner.submit(items), total=len(items))


def _job_or_404(request: Request, job_id: str, since: int = 0) -> BatchJob:
    job = request.app.state.batch.store.get(job_id, since)
    if job is None:
        raise HTTPException(
            404,
            "This batch was not found. Results are kept for "
            f"{settings.batch_ttl_minutes} minutes after a batch finishes.",
        )
    return job


@app.get("/api/batch/{job_id}", response_model=BatchJob)
def get_batch(request: Request, job_id: str, since: int = 0) -> BatchJob:
    """Progress plus the results finished so far. Pass `since` = results already received."""
    return _job_or_404(request, job_id, since)


@app.delete("/api/batch/{job_id}", response_model=BatchJob)
def cancel_batch(request: Request, job_id: str) -> BatchJob:
    """Stop checking. Labels already checked stay in the results and the export."""
    _job_or_404(request, job_id)
    request.app.state.batch.store.cancel(job_id)
    return _job_or_404(request, job_id)


@app.get("/api/batch/{job_id}/export.csv")
def export_batch(request: Request, job_id: str) -> Response:
    job = _job_or_404(request, job_id)
    if job.state not in (JobState.DONE, JobState.CANCELLED):
        raise HTTPException(409, "This batch is still running. Export when it has finished.")
    return Response(
        content=results_csv(job.results),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="labellens-{job_id[:8]}.csv"'},
    )


# Mounted last so it never shadows /api routes. Skipped in dev, where Vite serves the frontend.
if settings.frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=settings.frontend_dist, html=True), name="frontend")
