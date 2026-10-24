"""Find each field's value on the label, given what the application says it should be.

Verification asks "is the expected value on the label?", so text fields are found by searching
the OCR words for the span that best matches the expected value. That is far more robust than
guessing which text is the brand. Free extraction (most prominent line for the brand, a beverage
vocabulary for class/type) is only a fallback, so that a label carrying a different value is
reported as `Label says "HARBOR LIGHT"` rather than just "not found".

Numbers are found by parsing every line and keeping the one closest to the expected value.
The government warning is located separately by extract/warning.py.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz

from app.matching.normalize import match_key
from app.matching.parsers import parse_abv, parse_net_contents
from app.ocr.engine import OcrResult, OcrWord
from app.schemas import STANDARD_GOVERNMENT_WARNING

# A span scoring below this (0-100) against the expected value is not that value at all.
_MIN_SPAN_SCORE = 60
# Spans may have this many words fewer or more than the expected value (OCR splits and merges
# words: "STONE' S", "OLDTOM").
_SPAN_SLACK = 2
# The brand is usually printed large in the top part of the label.
_BRAND_TOP_SHARE = 0.5

CLASS_VOCABULARY = frozenset(
    {
        "whiskey", "whisky", "bourbon", "rye", "scotch", "vodka", "gin", "rum", "tequila",
        "mezcal", "brandy", "cognac", "liqueur", "wine", "cabernet", "merlot", "chardonnay",
        "pinot", "sauvignon", "riesling", "zinfandel", "champagne", "sparkling", "beer", "ale",
        "lager", "stout", "porter", "pilsner", "ipa", "cider", "mead", "sake",
    }
)  # fmt: skip

_WARNING_PREFIX_KEY = match_key("GOVERNMENT WARNING")
_WARNING_WORD_COUNT = len(STANDARD_GOVERNMENT_WARNING.split())


@dataclass(frozen=True)
class Found:
    """A value found on the label and how sure OCR was of it (0-1)."""

    text: str
    # The weakest word's confidence. A mean would hide one garbled word among clear ones
    # (on the glare sample, "Bourbon" at 0.92 next to a garbled word at 0.33 averages to 0.79).
    confidence: float


def _found(words: Sequence[OcrWord]) -> Found:
    return Found(" ".join(w.text for w in words), min(w.confidence for w in words))


def _outside_warning(words: Sequence[OcrWord]) -> list[OcrWord]:
    """Drop the government warning so short values ("Ale", "Gin") cannot match words in it."""
    keys = [match_key(w.text) for w in words]
    for i in range(len(words) - 1):
        if f"{keys[i]} {keys[i + 1]}" == _WARNING_PREFIX_KEY:
            return [*words[:i], *words[i + _WARNING_WORD_COUNT :]]
    return list(words)


def best_matching_span(expected: str, words: Sequence[OcrWord]) -> tuple[Found, float] | None:
    """The run of consecutive words most similar to expected, with its score (0-100).

    Spans may cross line breaks, since long brand names wrap. Ties go to the shorter span.
    """
    target = match_key(expected)
    if not target or not words:
        return None
    size = len(expected.split())
    best: tuple[float, int, int] | None = None  # (score, start, end)
    for length in range(max(1, size - _SPAN_SLACK), size + _SPAN_SLACK + 1):
        for start in range(len(words) - length + 1):
            text = " ".join(w.text for w in words[start : start + length])
            score = fuzz.ratio(match_key(text), target)
            if best is None or score > best[0]:
                best = (score, start, start + length)
    if best is None:
        return None
    score, start, end = best
    return _found(words[start:end]), score


def _most_prominent_line(ocr: OcrResult, page_height: float) -> Found | None:
    """The line with the tallest text in the top half of the label: usually the brand."""
    lines = [
        line
        for line in ocr.lines
        if line[0].top <= page_height * _BRAND_TOP_SHARE and any(w.text.isalpha() for w in line)
    ]
    if not lines:
        return None
    tallest = max(lines, key=lambda line: sum(w.height for w in line) / len(line))
    return _found(tallest)


def _vocabulary_line(lines: Sequence[Sequence[OcrWord]]) -> Found | None:
    """The first line containing a known beverage class word."""
    for line in lines:
        if any(match_key(w.text) in CLASS_VOCABULARY for w in line):
            return _found(line)
    return None


def find_brand(expected: str, ocr: OcrResult) -> Found | None:
    words = _outside_warning(ocr.words)
    match = best_matching_span(expected, words)
    if match and match[1] >= _MIN_SPAN_SCORE:
        return match[0]
    page_height = max((w.top + w.height for w in ocr.words), default=0)
    return _most_prominent_line(ocr, page_height)


def find_class_type(expected: str, ocr: OcrResult) -> Found | None:
    words = _outside_warning(ocr.words)
    match = best_matching_span(expected, words)
    if match and match[1] >= _MIN_SPAN_SCORE:
        return match[0]
    kept = {id(w) for w in words}
    return _vocabulary_line([line for line in ocr.lines if all(id(w) in kept for w in line)])


def find_alcohol_content(expected: str, ocr: OcrResult) -> Found | None:
    """The line whose ABV is closest to the expected one, plus a separate proof line if any.

    Adding the proof line lets the comparison catch a label whose ABV and proof disagree.
    """
    candidates = [(line, value) for line in ocr.lines if (value := parse_abv(_found(line).text))]
    if not candidates:
        return None
    target = parse_abv(expected)
    line, value = (
        min(candidates, key=lambda c: abs(c[1].effective_abv - target.effective_abv))
        if target
        else candidates[0]
    )
    words = list(line)
    if value.proof is None:
        proof_lines = [l for l, v in candidates if v.abv_percent is None and v.proof is not None]
        if proof_lines:
            words += proof_lines[0]
    return _found(words)


def find_net_contents(expected: str, ocr: OcrResult) -> Found | None:
    """The line whose volume is closest to the expected one."""
    candidates = [
        (line, value) for line in ocr.lines if (value := parse_net_contents(_found(line).text))
    ]
    if not candidates:
        return None
    target = parse_net_contents(expected)
    line, _ = min(candidates, key=lambda c: abs(c[1].ml - target.ml)) if target else candidates[0]
    return _found(line)
