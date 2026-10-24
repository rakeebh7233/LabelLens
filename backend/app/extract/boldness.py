"""Stroke-width heuristic: is "GOVERNMENT WARNING:" printed bolder than the warning text?

For each word box, the ink is separated from the background (Otsu) and its mean stroke width
is estimated as 2 x ink area / outline length: a stroke of width w and length L has area wL
and an outline of about 2L. This works below a pixel, which matters because warning text is
small: at a typical 19-20 px cap height, regular strokes are about 2.4 px and bold about 4.
A distance transform (median ridge value) was tried first and failed: its values come in
steps of about 0.4-0.6 px, as large as the whole bold effect, and it called a regular prefix
bold and a bold one regular on the samples.

Stroke width grows with text size, so each width is divided by a comparable height: the
prefix's cap height (it is all capitals) and, for the body, the height of words with tall
letters (b d f h k l t or capitals) and no descenders, which is close to the cap height.
x-height would not work here: the all-caps prefix has none, and comparing its cap height to
the body's x-height would shrink the prefix by about 1.4x, roughly the whole bold effect.

The verdict is unknown, never a guess, when the text is too small to measure, when the word
boxes look wrong (OCR sometimes merges two lines into one box), when too few body words can
be measured, or when the ratio falls between the bold and regular bands.

Calibrated on the sample labels and on DejaVu Sans and Serif at 8-31 px cap height (see
docs/DECISIONS.md): from 10 px up, bold prefixes measured 1.38-1.88 and regular ones
0.96-1.19. Only the bold threshold decides an outcome; not_bold and unknown both mean review.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import median

import cv2
import numpy as np

from app.ocr.engine import OcrWord


class Boldness(StrEnum):
    BOLD = "bold"
    NOT_BOLD = "not_bold"
    UNKNOWN = "unknown"


# Prefix-to-body ratio of normalized stroke width. A regular prefix measures slightly above
# 1 because all-caps words have more vertical strokes per unit of height.
BOLD_MIN_RATIO = 1.30
REGULAR_MAX_RATIO = 1.22
# Below about 10 px cap height strokes are 1-2 px and the ratio is noise (a regular prefix
# measured 1.42 at 9 px); 12 px leaves a margin.
MIN_TEXT_HEIGHT_PX = 12
MIN_BODY_WORDS = 3
# Box heights within this factor of each other count as the same text size.
_HEIGHT_TOLERANCE = 1.3
_PAD_PX = 2

_TALL = set("bdfhklt") | set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_DESCENDING = set("gjpqy") | set(",;()")


@dataclass(frozen=True)
class BoldVerdict:
    status: Boldness
    # Prefix stroke width over body stroke width, both normalized by text height.
    ratio: float | None = None
    # Why the verdict is unknown, for logs and tests.
    note: str = ""


def stroke_width(gray: np.ndarray, word: OcrWord) -> float | None:
    """Stroke width in pixels of the ink inside a word's box, or None if there is no ink."""
    h, w = gray.shape[:2]
    top, left = max(0, word.top - _PAD_PX), max(0, word.left - _PAD_PX)
    bottom = min(h, word.top + word.height + _PAD_PX)
    right = min(w, word.left + word.width + _PAD_PX)
    crop = gray[top:bottom, left:right]
    if crop.size == 0:
        return None
    _, ink = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if np.count_nonzero(ink) > ink.size / 2:  # light text on a dark background
        ink = cv2.bitwise_not(ink)
    contours, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    outline = sum(cv2.arcLength(contour, True) for contour in contours)
    if outline == 0:
        return None
    return 2 * np.count_nonzero(ink) / outline


def _is_reference_word(text: str) -> bool:
    """A body word whose box height approximates the cap height: tall letters, no descenders."""
    letters = text.strip(".:")
    return (
        len(letters) >= 3
        and letters.isalpha()
        and any(c in _TALL for c in letters)
        and not any(c in _DESCENDING for c in letters)
    )


def _same_size(a: float, b: float) -> bool:
    return max(a, b) <= _HEIGHT_TOLERANCE * min(a, b)


def _normalized_widths(gray: np.ndarray, words: Sequence[OcrWord]) -> list[float]:
    widths = []
    for word in words:
        width = stroke_width(gray, word)
        if width:
            widths.append(width / word.height)
    return widths


def classify_prefix(
    gray: np.ndarray, prefix: Sequence[OcrWord], body: Sequence[OcrWord]
) -> BoldVerdict:
    """Compare the prefix words' stroke width with the warning body's.

    `gray` must be the image the OCR boxes refer to.
    """
    if not prefix:
        return BoldVerdict(Boldness.UNKNOWN, note="prefix not found")
    if min(w.height for w in prefix) < MIN_TEXT_HEIGHT_PX:
        return BoldVerdict(Boldness.UNKNOWN, note="text too small to measure")
    reference = [w for w in body if _is_reference_word(w.text)]
    if len(reference) < MIN_BODY_WORDS:
        return BoldVerdict(Boldness.UNKNOWN, note="too few body words to compare")
    heights = [w.height for w in prefix]
    if not (
        _same_size(min(heights), max(heights))
        and _same_size(median(heights), median(w.height for w in reference))
    ):
        return BoldVerdict(Boldness.UNKNOWN, note="word boxes do not fit the text")

    prefix_widths = _normalized_widths(gray, prefix)
    body_widths = _normalized_widths(gray, reference)
    if not prefix_widths or len(body_widths) < MIN_BODY_WORDS:
        return BoldVerdict(Boldness.UNKNOWN, note="no ink found in the word boxes")

    ratio = round(median(prefix_widths) / median(body_widths), 2)
    if ratio >= BOLD_MIN_RATIO:
        return BoldVerdict(Boldness.BOLD, ratio)
    if ratio <= REGULAR_MAX_RATIO:
        return BoldVerdict(Boldness.NOT_BOLD, ratio)
    return BoldVerdict(Boldness.UNKNOWN, ratio, "between the bold and regular ranges")
