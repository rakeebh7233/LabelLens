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
class MatchThresholds:
    # rapidfuzz ratio (0-100) at or above which a non-identical brand or class/type is "review".
    fuzzy_review: float = 90.0
    # OCR confidence (0-1) below which a matching field is downgraded from pass to review.
    low_ocr_confidence: float = 0.6
    # Volumes within this percentage count as the same (25.4 fl oz is 751.2 mL, not 750).
    net_contents_tolerance_pct: float = 0.5
    # ABV values (in percentage points) closer than this are equal; absorbs float rounding.
    abv_tolerance: float = 0.05


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
    thresholds: MatchThresholds


@lru_cache
def get_settings() -> Settings:
    return Settings(
        max_upload_mb=int(os.getenv("LABELLENS_MAX_UPLOAD_MB", "10")),
        max_image_edge=int(os.getenv("LABELLENS_MAX_IMAGE_EDGE", "1600")),
        batch_workers=int(os.getenv("LABELLENS_BATCH_WORKERS", str(min(4, os.cpu_count() or 1)))),
        tesseract_cmd=os.getenv("LABELLENS_TESSERACT_CMD") or None,
        enable_llm_fallback=_env_bool("LABELLENS_ENABLE_LLM_FALLBACK", False),
        frontend_dist=Path(os.getenv("LABELLENS_FRONTEND_DIST", str(_REPO_ROOT / "frontend" / "dist"))),
        thresholds=MatchThresholds(
            fuzzy_review=float(os.getenv("LABELLENS_FUZZY_REVIEW_THRESHOLD", "90")),
            low_ocr_confidence=float(os.getenv("LABELLENS_LOW_OCR_CONFIDENCE", "0.6")),
            net_contents_tolerance_pct=float(os.getenv("LABELLENS_NET_CONTENTS_TOLERANCE_PCT", "0.5")),
        ),
    )
