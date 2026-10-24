"""Read a label image: basic preprocessing + OCR, then heavy fix-ups only if needed.

Keeps the common case (a clean label) to one cheap preprocessing pass and one OCR call, which
is what keeps a single label within the 5 second budget.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.ocr import preprocess
from app.ocr.engine import OcrEngine, OcrResult


@dataclass(frozen=True)
class Pass:
    """One OCR pass: what was read, from which image, after which preprocessing steps."""

    ocr: OcrResult
    # The image OCR ran on; word boxes in `ocr` are in its coordinates.
    image: np.ndarray
    # Plain-language preprocessing steps applied to produce `image`.
    steps: list[str]


@dataclass
class LabelReading:
    best: Pass
    timings_ms: dict[str, float] = field(default_factory=dict)
    # The pass that was not chosen, when a retry ran. Different passes often get different
    # fields right, so callers may take each field from either one.
    alternative: Pass | None = None

    @property
    def ocr(self) -> OcrResult:
        return self.best.ocr

    @property
    def steps(self) -> list[str]:
        return self.best.steps


def _elapsed_ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def confident(threshold: float) -> Callable[[OcrResult], bool]:
    """Default acceptance check: mean OCR confidence at or above threshold."""
    return lambda reading: reading.mean_confidence >= threshold


def read_label(
    image: np.ndarray,
    engine: OcrEngine,
    max_edge: int,
    accept: Callable[[OcrResult], bool],
) -> LabelReading:
    """OCR the image. If accept() rejects the reading, retry on a heavily cleaned copy and keep
    whichever reading scores better.

    Confidence alone is a weak trigger: Tesseract is confident about the words it read and
    silently skips the ones it could not (shadowed or skewed text). The verify service passes a
    stronger check, "does every field match on this reading", so the retry runs exactly when it
    could change the outcome.
    """
    timings: dict[str, float] = {}

    start = time.perf_counter()
    base = preprocess.basic(image, max_edge)
    timings["preprocess"] = _elapsed_ms(start)

    start = time.perf_counter()
    reading = engine.run(base.image)
    timings["ocr"] = _elapsed_ms(start)
    first = Pass(reading, base.image, base.steps)
    if accept(reading):
        return LabelReading(first, timings)

    start = time.perf_counter()
    fixed = preprocess.heavy(base.image)
    timings["preprocess_retry"] = _elapsed_ms(start)

    start = time.perf_counter()
    retry = engine.run(fixed.image)
    timings["ocr_retry"] = _elapsed_ms(start)
    second = Pass(retry, fixed.image, base.steps + fixed.steps)
    if retry.score > reading.score:
        return LabelReading(second, timings, alternative=first)
    return LabelReading(first, timings, alternative=second)
