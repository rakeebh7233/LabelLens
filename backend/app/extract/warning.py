"""Locate the government warning in OCR text and compare it exactly.

Locating is tolerant (case, OCR noise, surrounding label text) so the block can be found at
all. Judging is strict: the wording must match word for word and the "GOVERNMENT WARNING:"
prefix must be in capital letters with its colon. The canonical text is
STANDARD_GOVERNMENT_WARNING in app/schemas.py.
"""

import re
from difflib import SequenceMatcher

from rapidfuzz import fuzz
from rapidfuzz.distance import Levenshtein

from app.config import MatchThresholds
from app.matching.compare import DEFAULT_THRESHOLDS, downgrade_if_unsure, make_result
from app.matching.normalize import collapse_whitespace, fold_unicode
from app.schemas import STANDARD_GOVERNMENT_WARNING, FieldName, FieldResult, Status

PREFIX = "GOVERNMENT WARNING:"

# Below this fuzzy score (0-100) the text does not contain a warning at all. Real warnings
# score 80-100 even with OCR noise; unrelated label text scores around 40.
_LOCATE_MIN_SCORE = 60
# The matched part must cover this share of the warning, so a few stray letters never "match".
_LOCATE_MIN_COVERAGE = 0.3
# A differing word within this many character edits of the expected word is probably OCR
# damage: 1 edit for short words, 2 for words of 8+ letters. "can" vs "may" is 2 edits on a
# 3-letter word, so it counts as a real wording change.
_OCR_LETTERS_PER_EDIT = 4
_OCR_MAX_EDITS = 2
# Runs of at least this many matching words anchor the warning when trimming surrounding text,
# so a common word like "and" in unrelated text cannot extend the block.
_ANCHOR_MIN_WORDS = 3
# More OCR-damaged words than this and the text cannot be trusted to match: fail.
_OCR_MAX_WORDS = 3
_MAX_LISTED_DIFFERENCES = 3

_LINE_END_HYPHEN = re.compile(r"(\w)-\s*\n\s*(\w)")


def prepare(ocr_text: str) -> str:
    """Undo line layout: join words hyphenated across lines, fold unicode, collapse whitespace.

    Joining "preg-\\nnancy" is safe because the warning itself contains no hyphenated words.
    """
    return collapse_whitespace(fold_unicode(_LINE_END_HYPHEN.sub(r"\1\2", ocr_text)))


def _similar(found: str, expected: str) -> bool:
    """Close enough in spelling that the difference is plausibly an OCR misread."""
    allowed = min(_OCR_MAX_EDITS, max(1, len(expected) // _OCR_LETTERS_PER_EDIT))
    return Levenshtein.distance(found, expected) <= allowed


def _trim_to_warning(words: list[str], expected_words: list[str]) -> list[str]:
    """Drop surrounding label text that the fuzzy window caught on either side of the warning.

    The block runs from the first to the last solid run of matching words. Words just outside
    are kept while they still resemble the expected words, so an OCR-damaged first or last word
    stays in and is judged rather than silently discarded.
    """
    found_cf = [w.casefold() for w in words]
    expected_cf = [w.casefold() for w in expected_words]
    matcher = SequenceMatcher(None, expected_cf, found_cf, autojunk=False)
    blocks = [b for b in matcher.get_matching_blocks() if b.size >= _ANCHOR_MIN_WORDS]
    if not blocks:
        return words

    first, last = blocks[0], blocks[-1]
    i, start = first.a, first.b
    while i > 0 and start > 0 and _similar(found_cf[start - 1], expected_cf[i - 1]):
        i, start = i - 1, start - 1
    i, end = last.a + last.size, last.b + last.size
    while i < len(expected_cf) and end < len(found_cf) and _similar(found_cf[end], expected_cf[i]):
        i, end = i + 1, end + 1
    return words[start:end]


def locate_warning(text: str, expected: str = STANDARD_GOVERNMENT_WARNING) -> str | None:
    """Find the warning block in prepared OCR text, or None if the label has no warning."""
    if not text.strip():
        return None
    alignment = fuzz.partial_ratio_alignment(expected.casefold(), text.casefold())
    coverage = (alignment.src_end - alignment.src_start) / len(expected)
    if alignment.score < _LOCATE_MIN_SCORE or coverage < _LOCATE_MIN_COVERAGE:
        return None

    # Widen the match to whole words.
    start, end = alignment.dest_start, alignment.dest_end
    while start > 0 and not text[start - 1].isspace():
        start -= 1
    while end < len(text) and not text[end].isspace():
        end += 1
    words = _trim_to_warning(text[start:end].split(), expected.split())
    return " ".join(words) or None


def _quote(words: list[str], max_words: int = 8) -> str:
    """Quote a run of words, shortening long runs to their first and last few words."""
    if len(words) > max_words:
        words = words[:4] + ["..."] + words[-2:]
    return f'"{" ".join(words)}"'


def _prefix_problem(found: str) -> str | None:
    """Explain why the prefix is wrong, or None if it is "GOVERNMENT WARNING:" exactly.

    OCR noise inside an all-caps prefix ("G0VERNMENT") is not judged here; the word comparison
    treats it like any other misread word.
    """
    words = found.split()
    shown = " ".join(words[:2])
    if len(words) < 2 or not _similar(shown.rstrip(":;.,").casefold(), "government warning"):
        return f'The warning must begin with "{PREFIX}" and this label\'s warning does not'
    if not (words[0] + words[1]).isupper():
        return (
            f'The label has "{shown}" but the warning must begin "{PREFIX}" '
            "in all capital letters"
        )
    if words[1][-1].isalnum():
        return f'The label has "{shown}" - the colon after "GOVERNMENT WARNING" is missing'
    return None


_Opcode = tuple[str, int, int, int, int]


def _describe_differences(ops: list[_Opcode], expected: list[str], found: list[str]) -> str:
    descriptions: list[str] = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "delete":
            descriptions.append(f"missing {_quote(expected[i1:i2])}")
        elif tag == "insert":
            descriptions.append(f"extra {_quote(found[j1:j2])}")
        elif tag == "replace":
            descriptions.append(
                f"{_quote(found[j1:j2])} where it should say {_quote(expected[i1:i2])}"
            )
    listed = descriptions[:_MAX_LISTED_DIFFERENCES]
    more = len(descriptions) - len(listed)
    suffix = f"; and {more} more difference{'s' if more > 1 else ''}" if more else ""
    return "; ".join(listed) + suffix


def compare_warning(
    found: str | None,
    confidence: float,
    expected: str = STANDARD_GOVERNMENT_WARNING,
    prefix_bold: bool | None = None,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """Judge a located warning block strictly against the expected text.

    prefix_bold is the bold detector's verdict: True, False, or None when bold was not checked.
    """
    result = _judge(found, confidence, collapse_whitespace(expected), prefix_bold)
    return downgrade_if_unsure(result, thresholds)


def _judge(
    found: str | None, confidence: float, expected: str, prefix_bold: bool | None
) -> FieldResult:
    """The strict wording, prefix and bold rules; see compare_warning."""
    field = FieldName.GOVERNMENT_WARNING

    def result(status: Status, reason: str | None = None) -> FieldResult:
        return make_result(field, status, expected, found, confidence, reason)

    if found is None or not found.strip():
        return result(Status.FAIL, "No government warning statement found on the label")
    found = prepare(found)

    if expected.startswith(PREFIX) and (problem := _prefix_problem(found)):
        return result(Status.FAIL, problem)

    expected_words, found_words = expected.split(), found.split()
    ops = [
        op
        for op in SequenceMatcher(None, expected_words, found_words, autojunk=False).get_opcodes()
        if op[0] != "equal"
    ]
    if ops:
        likely_misread = all(
            tag == "replace"
            and i2 - i1 == j2 - j1
            and all(
                _similar(f, e) and f.casefold() != e.casefold()  # case is never a misread
                for f, e in zip(found_words[j1:j2], expected_words[i1:i2])
            )
            for tag, i1, i2, j1, j2 in ops
        ) and sum(i2 - i1 for _, i1, i2, _, _ in ops) <= _OCR_MAX_WORDS
        if likely_misread:
            pairs = ", ".join(
                f'"{f}" (should be "{e}")'
                for _, i1, i2, j1, j2 in ops
                for f, e in zip(found_words[j1:j2], expected_words[i1:i2])
            )
            return result(
                Status.REVIEW,
                f"Warning wording matches except for characters that may be misread: {pairs} "
                "- check the label",
            )
        return result(
            Status.FAIL,
            "Warning text differs from the required wording: "
            + _describe_differences(ops, expected_words, found_words),
        )

    if prefix_bold is False:
        return result(
            Status.REVIEW,
            f'Wording matches, but "{PREFIX}" may not be in bold type - check the label',
        )
    reason = None
    if prefix_bold is None:
        reason = f'Wording matches; bold type of "{PREFIX}" was not checked automatically'
    return result(Status.PASS, reason)


def check_warning(
    ocr_text: str,
    confidence: float,
    expected: str = STANDARD_GOVERNMENT_WARNING,
    prefix_bold: bool | None = None,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """Find and judge the warning in the full OCR text of a label. Entry point for verify."""
    found = locate_warning(prepare(ocr_text), collapse_whitespace(expected))
    return compare_warning(found, confidence, expected, prefix_bold, thresholds)
