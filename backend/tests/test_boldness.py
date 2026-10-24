import shutil

import numpy as np
import pytest
from PIL import Image, ImageDraw
from samples_lib.render import font

from app.extract.boldness import Boldness, classify_prefix, stroke_width
from app.extract.warning import check_warning_in
from app.ocr import preprocess
from app.ocr.engine import OcrWord, TesseractEngine
from app.schemas import STANDARD_GOVERNMENT_WARNING, Status
from tests.label_images import render_label

needs_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None, reason="Tesseract is not installed"
)

FAMILIES = ("DejaVuSans", "DejaVuSerif")


def render_warning(
    family: str = "DejaVuSans", size: int = 28, bold_prefix: bool = True
) -> tuple[np.ndarray, list[OcrWord]]:
    """The warning as a grayscale image plus one OCR-style word box per word (exact ink boxes,
    so these tests exercise the measurement without depending on OCR)."""
    image = Image.new("L", (1500, 30 * size), 250)
    draw = ImageDraw.Draw(image)
    regular, bold = font(family, size), font(f"{family}-Bold", size)
    words: list[OcrWord] = []
    x, y, line = 40, 40, 0
    for i, text in enumerate(STANDARD_GOVERNMENT_WARNING.split()):
        typeface = bold if bold_prefix and i < 2 else regular
        length = draw.textlength(text, font=typeface)
        if x + length > 1460:
            x, y, line = 40, y + int(size * 1.35), line + 1
        draw.text((x, y), text, fill=20, font=typeface)
        left, top, right, bottom = (int(v) for v in draw.textbbox((x, y), text, font=typeface))
        words.append(OcrWord(text, left, top, right - left, bottom - top, 0.95, (1, 1, line)))
        x += length + draw.textlength(" ", font=regular)
    return np.array(image), words


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("size", [18, 22, 28, 40])
@pytest.mark.parametrize("bold_prefix", [True, False])
def test_bold_and_regular_prefixes_are_told_apart(family: str, size: int, bold_prefix: bool) -> None:
    gray, words = render_warning(family, size, bold_prefix)
    verdict = classify_prefix(gray, words[:2], words[2:])
    assert verdict.status is (Boldness.BOLD if bold_prefix else Boldness.NOT_BOLD), verdict


@pytest.mark.parametrize("size", [8, 11, 14])
def test_tiny_text_is_unknown_not_a_guess(size: int) -> None:
    for bold_prefix in (True, False):
        gray, words = render_warning(size=size, bold_prefix=bold_prefix)
        verdict = classify_prefix(gray, words[:2], words[2:])
        assert verdict.status is Boldness.UNKNOWN
        assert verdict.note == "text too small to measure"


def test_light_text_on_a_dark_background_measures_the_same() -> None:
    gray, words = render_warning()
    normal = classify_prefix(gray, words[:2], words[2:])
    inverted = classify_prefix(255 - gray, words[:2], words[2:])
    assert inverted.status is Boldness.BOLD
    assert inverted.ratio == pytest.approx(normal.ratio, abs=0.05)


def test_a_bold_word_has_wider_strokes() -> None:
    gray, words = render_warning()
    bold_width, regular_width = stroke_width(gray, words[0]), stroke_width(gray, words[5])
    assert bold_width is not None and regular_width is not None
    assert bold_width > 1.4 * regular_width


def test_merged_word_boxes_are_unknown() -> None:
    """OCR sometimes boxes two lines as one word; the box no longer fits the text size."""
    gray, words = render_warning()
    tall = [
        OcrWord(w.text, w.left, w.top, w.width, w.height * 2, w.confidence, w.line_id)
        for w in words[:2]
    ]
    assert classify_prefix(gray, tall, words[2:]).note == "word boxes do not fit the text"


def test_missing_prefix_or_body_is_unknown() -> None:
    gray, words = render_warning()
    assert classify_prefix(gray, [], words[2:]).note == "prefix not found"
    assert classify_prefix(gray, words[:2], words[2:4]).note == "too few body words to compare"


def test_empty_box_has_no_stroke_width() -> None:
    blank = np.full((100, 100), 250, np.uint8)
    assert stroke_width(blank, OcrWord("x", 200, 200, 10, 10, 0.9, (1, 1, 1))) is None


# Through OCR: the boxes come from Tesseract, as in the verify service.


def _warning_through_ocr(**label: object) -> tuple[Status, str | None]:
    gray = preprocess.basic(render_label(**label), 1600).image  # type: ignore[arg-type]
    result = check_warning_in(TesseractEngine().run(gray), image=gray)
    return result.status, result.reason


@needs_tesseract
def test_ocr_bold_prefix_passes() -> None:
    assert _warning_through_ocr() == (Status.PASS, None)


@needs_tesseract
def test_ocr_regular_prefix_is_review() -> None:
    status, reason = _warning_through_ocr(bold_prefix=False)
    assert status is Status.REVIEW
    assert reason is not None and "does not look bold" in reason


@needs_tesseract
def test_ocr_small_warning_is_review_because_bold_is_unclear() -> None:
    status, reason = _warning_through_ocr(warning_size=15)
    assert status is Status.REVIEW
    assert reason is not None and "not clear enough to tell" in reason
