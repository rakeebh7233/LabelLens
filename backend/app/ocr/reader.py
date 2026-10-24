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


@dataclass
class LabelReading:
    ocr: OcrResult
    # Plain-language preprocessing steps applied to the image that produced `ocr`.
    steps: list[str]
    timings_ms: dict[str, float] = field(default_factory=dict)
    # The reading that was not chosen, with its steps, when a retry ran. Different readings
    # often get different fields right, so callers may take each field from either one.
    alternative: tuple[OcrResult, list[str]] | None = None


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
    if accept(reading):
        return LabelReading(reading, base.steps, timings)

    start = time.perf_counter()
    fixed = preprocess.heavy(base.image)
    timings["preprocess_retry"] = _elapsed_ms(start)

    start = time.perf_counter()
    retry = engine.run(fixed.image)
    timings["ocr_retry"] = _elapsed_ms(start)
    retry_steps = base.steps + fixed.steps
    if retry.score > reading.score:
        return LabelReading(retry, retry_steps, timings, alternative=(reading, base.steps))
    return LabelReading(reading, base.steps, timings, alternative=(retry, retry_steps))
