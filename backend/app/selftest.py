"""Startup self-test: is Tesseract installed, and how quickly does it read on this machine.

It reads one small rendered line of text, which also loads Tesseract's language data so the
first real request does not pay for it (worth having after a cold start on a sleeping host).
Never raises: a missing engine is logged and reported by /api/health, not a crash.
"""

import logging
import time

import cv2
import numpy as np

from app.config import Settings, available_cpus
from app.ocr.engine import OcrEngine, OcrError

logger = logging.getLogger("labellens")

SELF_TEST_TEXT = "LABELLENS SELF TEST"


def _sample_image() -> np.ndarray:
    image = np.full((80, 760), 255, dtype=np.uint8)
    cv2.putText(image, SELF_TEST_TEXT, (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.4, 0, 3, cv2.LINE_AA)
    return image


def run_self_test(engine: OcrEngine, settings: Settings) -> bool:
    """Log the resources the app sees and whether OCR works. True when it read the sample."""
    logger.info(
        "Starting with %.2f CPUs available, %d batch workers, batch cap %d photos / %d MB",
        available_cpus(),
        settings.batch_workers,
        settings.max_batch_files,
        settings.max_batch_mb,
    )
    started = time.perf_counter()
    try:
        result = engine.run(_sample_image())
    except OcrError as exc:
        logger.error("OCR self-test failed: %s. Label checks will not work.", exc)
        return False
    elapsed_ms = (time.perf_counter() - started) * 1000
    read = " ".join(w.text for w in result.words)
    if read.upper() != SELF_TEST_TEXT:
        logger.warning("OCR self-test misread the sample: got %r in %.0f ms", read, elapsed_ms)
        return False
    logger.info("OCR self-test passed: %s read the sample in %.0f ms", engine.name, elapsed_ms)
    return True
