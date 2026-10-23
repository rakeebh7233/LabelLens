import shutil
import time
from collections.abc import Callable

import numpy as np
import pytesseract
import pytest

from app.matching.normalize import match_key
from app.ocr import preprocess
from app.ocr.engine import OcrError, OcrResult, OcrWord, TesseractEngine
from app.ocr.reader import confident, read_label
from tests.label_images import blurred, dim_and_uneven, render_label, rotated, with_glare

BRAND = "STONE'S THROW"
CLEAN = render_label(brand=BRAND)

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Tesseract is not installed"
)


def brand_read(reading: OcrResult) -> bool:
    return match_key(BRAND) in match_key(reading.text)


# OcrResult


def _word(text: str, confidence: float, line: int) -> OcrWord:
    return OcrWord(text, 0, 0, 10, 10, confidence, (1, 1, line))


def test_ocr_result_text_keeps_line_breaks() -> None:
    result = OcrResult(
        (_word("STONE'S", 0.9, 1), _word("THROW", 0.9, 1), _word("Bourbon", 0.8, 2)), 0.87
    )
    assert result.text == "STONE'S THROW\nBourbon"


def test_ocr_result_score_rewards_more_confident_text() -> None:
    few = OcrResult((_word("abc", 1.0, 1),), 1.0)
    many = OcrResult((_word("abc", 0.8, 1), _word("defghij", 0.8, 1)), 0.8)
    assert many.score > few.score  # higher mean confidence alone would pick `few`


# read_label control flow, with a fake engine (no Tesseract needed)


class FakeEngine:
    name = "fake"

    def __init__(self, *readings: OcrResult) -> None:
        self.readings = list(readings)
        self.calls = 0

    def run(self, image: np.ndarray) -> OcrResult:
        self.calls += 1
        return self.readings.pop(0)


WEAK = OcrResult((_word("ST0NE", 0.5, 1),), 0.5)
STRONG = OcrResult((_word("STONE'S", 0.95, 1), _word("THROW", 0.95, 1)), 0.95)


def test_read_label_stops_after_one_pass_when_accepted() -> None:
    engine = FakeEngine(STRONG)
    result = read_label(CLEAN, engine, 1600, confident(0.75))
    assert engine.calls == 1
    assert result.ocr is STRONG
    assert result.steps == ["contrast boost"]
    assert set(result.timings_ms) == {"preprocess", "ocr"}


def test_read_label_retries_and_keeps_the_better_reading() -> None:
    engine = FakeEngine(WEAK, STRONG)
    result = read_label(CLEAN, engine, 1600, confident(0.75))
    assert engine.calls == 2
    assert result.ocr is STRONG
    assert "converted to black and white" in result.steps
    assert set(result.timings_ms) == {"preprocess", "ocr", "preprocess_retry", "ocr_retry"}


def test_read_label_keeps_the_first_reading_when_the_retry_is_worse() -> None:
    engine = FakeEngine(STRONG, WEAK)
    result = read_label(CLEAN, engine, 1600, lambda reading: False)
    assert result.ocr is STRONG
    assert result.steps == ["contrast boost"]
    assert "ocr_retry" in result.timings_ms


# Real Tesseract


@needs_tesseract
def test_clean_label_is_read_in_one_pass_well_under_three_seconds() -> None:
    start = time.perf_counter()
    result = read_label(CLEAN, TesseractEngine(), 1600, confident(0.75))
    elapsed = time.perf_counter() - start
    assert brand_read(result.ocr)
    assert "ocr_retry" not in result.timings_ms
    assert elapsed < 3


@needs_tesseract
def test_rotated_ten_degrees_is_still_read() -> None:
    result = read_label(rotated(CLEAN, 10), TesseractEngine(), 1600, confident(0.75))
    assert brand_read(result.ocr)
    assert "straightened by 10.0°" in result.steps


@pytest.mark.parametrize(
    ("name", "damage"),
    [
        ("rotated -7", lambda image: rotated(image, -7)),
        ("rotated 10", lambda image: rotated(image, 10)),
        ("blurred", blurred),
        ("glare", with_glare),
        ("dim and uneven", dim_and_uneven),
        ("rotated with glare", lambda image: with_glare(rotated(image, 10))),
    ],
)
@needs_tesseract
def test_pipeline_reads_brand_on_damaged_photos(
    name: str, damage: Callable[[np.ndarray], np.ndarray]
) -> None:
    """With the field-level acceptance check that verify will use, the brand is always read."""
    result = read_label(damage(CLEAN), TesseractEngine(), 1600, brand_read)
    assert brand_read(result.ocr), f"{name}: {result.ocr.text[:80]!r}"


@pytest.mark.parametrize("damage", [lambda i: rotated(i, -7), dim_and_uneven, with_glare, blurred])
@needs_tesseract
def test_pipeline_improves_or_preserves_the_basic_reading(
    damage: Callable[[np.ndarray], np.ndarray],
) -> None:
    engine = TesseractEngine()
    image = damage(CLEAN)
    basic_only = engine.run(preprocess.basic(image, 1600).image)
    pipeline = read_label(image, engine, 1600, lambda reading: False)
    assert pipeline.ocr.score >= basic_only.score


@needs_tesseract
def test_engine_reads_nothing_from_a_blank_image() -> None:
    result = TesseractEngine().run(np.full((300, 300), 255, np.uint8))
    assert result.words == ()
    assert result.mean_confidence == 0.0


@needs_tesseract
def test_engine_word_confidences_are_fractions() -> None:
    result = TesseractEngine().run(preprocess.basic(CLEAN, 1600).image)
    assert result.words
    assert all(0 <= w.confidence <= 1 for w in result.words)
    assert "\n" in result.text


def test_missing_tesseract_raises_plain_ocr_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", "/nonexistent/tesseract")
    with pytest.raises(OcrError, match="not installed"):
        TesseractEngine().run(np.full((50, 50), 255, np.uint8))
