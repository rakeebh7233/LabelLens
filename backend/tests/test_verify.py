import shutil

import numpy as np
import pytest

from app.ocr.engine import OcrError, OcrResult, OcrWord
from app.schemas import STANDARD_GOVERNMENT_WARNING as W
from app.schemas import ApplicationData, FieldName, Status
from app.services.verify import (
    HARD_TO_READ_WARNING,
    NO_TEXT_WARNING,
    UNEXPECTED_ERROR,
    verify_label,
)
from tests.label_images import encode_png, render_label, rotated, with_glare

P, R, F = Status.PASS, Status.REVIEW, Status.FAIL

OLD_TOM = ApplicationData(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
)
OLD_TOM_LABEL = dict(
    brand="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol="45% Alc./Vol. (90 Proof)",
    net="750 mL",
)
PNG = encode_png(np.full((100, 100, 3), 255, np.uint8))

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Tesseract is not installed"
)


def statuses(result) -> dict[FieldName, Status]:  # type: ignore[no-untyped-def]
    return {f.field: f.status for f in result.fields}


# Control flow and error handling, with fake engines (no Tesseract needed)


def _reading(text: str, confidence: float) -> OcrResult:
    words = tuple(
        OcrWord(word, 0, 40 * n, 10, 30, confidence, (1, 1, n))
        for n, line in enumerate(text.splitlines())
        for word in line.split()
    )
    return OcrResult(words, confidence)


PERFECT_TEXT = "\n".join(
    [
        "OLD TOM DISTILLERY",
        "Kentucky Straight Bourbon Whiskey",
        "45% Alc./Vol. (90 Proof)",
        "750 mL",
        W,
    ]
)
TITLE_CASE_WARNING = W.replace("GOVERNMENT WARNING", "Government Warning")


class FixedEngine:
    name = "fixed"

    def __init__(self, reading: OcrResult) -> None:
        self.reading = reading
        self.calls = 0

    def run(self, image: np.ndarray) -> OcrResult:
        self.calls += 1
        return self.reading


class BrokenEngine:
    name = "broken"

    def __init__(self, error: Exception) -> None:
        self.error = error

    def run(self, image: np.ndarray) -> OcrResult:
        raise self.error


def test_all_fields_pass_in_one_ocr_pass() -> None:
    engine = FixedEngine(_reading(PERFECT_TEXT, 0.95))
    result = verify_label(PNG, OLD_TOM, filename="old_tom.png", label_id="abc", engine=engine)
    assert result.overall_status is P
    assert engine.calls == 1  # no retry once every field passes
    assert result.label_id == "abc" and result.filename == "old_tom.png"
    assert [f.field for f in result.fields] == list(FieldName)
    assert result.ocr_confidence == 0.95
    assert result.preprocessing == ["contrast boost"]
    assert {"decode", "preprocess", "ocr", "compare", "total"} <= set(result.timings_ms)
    assert result.warnings == []


def test_retries_when_a_field_does_not_pass() -> None:
    engine = FixedEngine(_reading(PERFECT_TEXT.replace("750 mL", "700 mL"), 0.95))
    result = verify_label(PNG, OLD_TOM, engine=engine)
    assert engine.calls == 2
    assert statuses(result)[FieldName.NET_CONTENTS] is F
    assert "ocr_retry" in result.timings_ms


def test_unreadable_file_is_an_error_result_not_an_exception() -> None:
    result = verify_label(b"this is not an image", OLD_TOM, filename="corrupt.png")
    assert result.overall_status is F
    assert result.fields == []
    assert result.error == (
        "This file could not be read as an image. Please upload a JPEG or PNG photo of the label."
    )
    assert "total" in result.timings_ms


def test_ocr_failure_is_an_error_result() -> None:
    engine = BrokenEngine(OcrError("The OCR engine could not read this image"))
    result = verify_label(PNG, OLD_TOM, engine=engine)
    assert result.overall_status is F
    assert result.error == "The OCR engine could not read this image. Please try again."


def test_unexpected_failure_is_a_plain_error_without_details() -> None:
    result = verify_label(PNG, OLD_TOM, engine=BrokenEngine(ZeroDivisionError("boom")))
    assert result.error == UNEXPECTED_ERROR
    assert "boom" not in result.error


def test_no_text_fails_every_field_with_a_hint() -> None:
    result = verify_label(PNG, OLD_TOM, engine=FixedEngine(OcrResult((), 0.0)))
    assert result.error is None
    assert set(statuses(result).values()) == {F}
    assert result.warnings == [NO_TEXT_WARNING]


def test_hard_to_read_photo_gets_a_hint() -> None:
    result = verify_label(PNG, OLD_TOM, engine=FixedEngine(_reading(PERFECT_TEXT, 0.4)))
    assert result.warnings == [HARD_TO_READ_WARNING]
    assert result.overall_status is R  # low confidence turns passes into review, never fail


def test_custom_warning_text_from_application_is_used() -> None:
    custom = OLD_TOM.model_copy(update={"government_warning": W + " Drink responsibly."})
    result = verify_label(PNG, custom, engine=FixedEngine(_reading(PERFECT_TEXT, 0.95)))
    assert statuses(result)[FieldName.GOVERNMENT_WARNING] is F


# End to end with Tesseract


@needs_tesseract
def test_old_tom_label_passes_every_field_within_budget() -> None:
    """Phase 6 acceptance: every field passes and the whole check is well under 5 seconds."""
    result = verify_label(encode_png(render_label(**OLD_TOM_LABEL)), OLD_TOM)
    assert result.overall_status is P, [(f.field, f.reason) for f in result.fields]
    assert set(statuses(result).values()) == {P}
    assert result.timings_ms["total"] < 5000


@pytest.mark.parametrize(
    ("label_changes", "field", "status"),
    [
        ({"brand": "HARBOR LIGHT"}, FieldName.BRAND_NAME, F),
        ({"alcohol": "40% Alc./Vol. (80 Proof)"}, FieldName.ALCOHOL_CONTENT, F),
        ({"alcohol": "90 PROOF"}, FieldName.ALCOHOL_CONTENT, P),
        ({"net": "700 mL"}, FieldName.NET_CONTENTS, F),
        ({"net": "75 cL"}, FieldName.NET_CONTENTS, P),
        ({"warning": TITLE_CASE_WARNING}, FieldName.GOVERNMENT_WARNING, F),
        ({"warning": ""}, FieldName.GOVERNMENT_WARNING, F),
    ],
)
@needs_tesseract
def test_label_defects_are_caught(
    label_changes: dict[str, str], field: FieldName, status: Status
) -> None:
    result = verify_label(encode_png(render_label(**(OLD_TOM_LABEL | label_changes))), OLD_TOM)
    assert statuses(result)[field] is status, [(f.field, f.reason) for f in result.fields]


@needs_tesseract
def test_stones_throw_capitalization_is_review_end_to_end() -> None:
    application = OLD_TOM.model_copy(update={"brand_name": "Stone's Throw"})
    label = render_label(**(OLD_TOM_LABEL | {"brand": "STONE'S THROW"}))
    result = verify_label(encode_png(label), application)
    assert statuses(result)[FieldName.BRAND_NAME] is R
    assert result.overall_status is R


@pytest.mark.parametrize("damage", [lambda i: rotated(i, 12), with_glare])
@needs_tesseract
def test_damaged_photo_of_a_good_label_never_fails(damage) -> None:  # type: ignore[no-untyped-def]
    result = verify_label(encode_png(damage(render_label(**OLD_TOM_LABEL))), OLD_TOM)
    assert result.overall_status is not F, [(f.field, f.reason) for f in result.fields]
