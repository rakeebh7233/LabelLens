"""Settings read from environment variables, with defaults suitable for local development."""

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Uploads larger than this are rejected with a plain-language error.
    max_upload_mb: int
    # Images are downscaled so their long edge is at most this many pixels before OCR.
    max_image_edge: int
    # Size of the worker pool used for batch jobs.
    batch_workers: int
    # Explicit path to the tesseract binary; None means look it up on PATH.
    tesseract_cmd: str | None
    # Optional cloud LLM vision fallback. Off by default; likely blocked by the agency firewall.
    enable_llm_fallback: bool
    # Built frontend served at "/" when it exists.
    frontend_dist: Path


@lru_cache
def get_settings() -> Settings:
    return Settings(
        max_upload_mb=int(os.getenv("LABELLENS_MAX_UPLOAD_MB", "10")),
        max_image_edge=int(os.getenv("LABELLENS_MAX_IMAGE_EDGE", "1600")),
        batch_workers=int(os.getenv("LABELLENS_BATCH_WORKERS", str(min(4, os.cpu_count() or 1)))),
        tesseract_cmd=os.getenv("LABELLENS_TESSERACT_CMD") or None,
        enable_llm_fallback=_env_bool("LABELLENS_ENABLE_LLM_FALLBACK", False),
        frontend_dist=Path(os.getenv("LABELLENS_FRONTEND_DIST", str(_REPO_ROOT / "frontend" / "dist"))),
    )
