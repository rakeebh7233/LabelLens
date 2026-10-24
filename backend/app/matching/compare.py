"""Per-field comparison of label text against application data, producing FieldResult.

Pure functions: the caller passes the text found on the label (None when the field was not
found), the OCR confidence for that text, and the thresholds. Reasons quote the original
strings, never the normalized matching keys.
"""

from rapidfuzz import fuzz

from app.config import MatchThresholds
from app.matching.normalize import (
    collapse_whitespace,
    fold_unicode,
    match_key,
    normalize_case,
    strip_punctuation,
)
from app.matching.parsers import AlcoholContent, parse_abv, parse_net_contents
from app.schemas import FieldName, FieldResult, Status

DEFAULT_THRESHOLDS = MatchThresholds()

# How each field is named in reasons.
_FIELD_LABELS = {
    FieldName.BRAND_NAME: "brand name",
    FieldName.CLASS_TYPE: "class/type",
    FieldName.ALCOHOL_CONTENT: "alcohol content",
    FieldName.NET_CONTENTS: "net contents",
    FieldName.GOVERNMENT_WARNING: "government warning",
}


def _fmt(value: float) -> str:
    """45.0 -> "45", 40.5 -> "40.5", 751.1669 -> "751.2"."""
    return f"{value:.1f}".removesuffix(".0")


def _says(found: str, expected: str) -> str:
    return f'Label says "{collapse_whitespace(found)}", application says "{expected}"'


def make_result(
    field: FieldName,
    status: Status,
    expected: str,
    found: str | None,
    confidence: float,
    reason: str | None = None,
) -> FieldResult:
    return FieldResult(
        field=field,
        status=status,
        expected=expected,
        found=collapse_whitespace(found) if found is not None else None,
        reason=reason,
        confidence=confidence,
    )


def _not_found(field: FieldName, expected: str, confidence: float) -> FieldResult:
    return make_result(
        field,
        Status.FAIL,
        expected,
        None,
        confidence,
        f"No {_FIELD_LABELS[field]} found on the label (application says \"{expected}\")",
    )


def downgrade_if_unsure(result: FieldResult, thresholds: MatchThresholds) -> FieldResult:
    """Apply low OCR confidence: it never causes a fail, and it softens a fail it may explain.

    - pass -> review: the match may be luck, so a person should confirm.
    - fail on text that was found -> review: the mismatch may be a misreading (glare, blur).
    - fail because the field was not found at all stays fail.
    """
    if result.confidence >= thresholds.low_ocr_confidence or result.status is Status.REVIEW:
        return result
    shown = f"OCR confidence {result.confidence:.0%}"
    if result.status is Status.PASS:
        note = (
            f"Matches the application, but the label text was hard to read ({shown}) "
            "- please confirm by eye"
        )
    elif result.found is not None:
        note = (
            f"The label text was hard to read ({shown}), so this may be a misreading "
            "- check the label"
        )
    else:
        return result
    reason = f"{result.reason}. {note}" if result.reason else note
    return result.model_copy(update={"status": Status.REVIEW, "reason": reason})


def compare_text(
    field: FieldName,
    expected: str,
    found: str | None,
    confidence: float,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """Brand name and class/type.

    Checks run from strictest to loosest and the first one that holds decides the result, so
    the reason names exactly what differs.
    """
    if found is None or not found.strip():
        return _not_found(field, expected, confidence)

    def result(status: Status, reason: str | None = None) -> FieldResult:
        return make_result(field, status, expected, found, confidence, reason)

    says = _says(found, expected)
    # Curly vs straight quotes, line breaks and repeated spaces are not real differences.
    plain_found = collapse_whitespace(fold_unicode(found))
    plain_expected = collapse_whitespace(fold_unicode(expected))

    if plain_found == plain_expected:
        outcome = result(Status.PASS)
    elif normalize_case(found) == normalize_case(expected):
        outcome = result(Status.REVIEW, f"{says} - differs only in capitalization")
    elif strip_punctuation(plain_found) == strip_punctuation(plain_expected):
        outcome = result(Status.REVIEW, f"{says} - differs only in punctuation")
    elif strip_punctuation(normalize_case(found)) == strip_punctuation(normalize_case(expected)):
        outcome = result(Status.REVIEW, f"{says} - differs only in capitalization and punctuation")
    elif match_key(found) == match_key(expected):
        outcome = result(
            Status.REVIEW,
            f"{says} - probably the same, but some characters may be misread "
            "(for example 0 for O); check the label",
        )
    else:
        score = fuzz.ratio(match_key(found), match_key(expected))
        if score >= thresholds.fuzzy_review:
            outcome = result(
                Status.REVIEW, f"{says} - close but not identical ({score:.0f}% similar)"
            )
        else:
            outcome = result(Status.FAIL, f"{says} - these do not match")
    return downgrade_if_unsure(outcome, thresholds)


def _proof_conflict(value: AlcoholContent, tolerance: float) -> str | None:
    """Describe a stated proof that does not equal 2 x the stated ABV, if any."""
    if value.abv_percent is None or value.proof is None:
        return None
    if abs(value.proof - 2 * value.abv_percent) <= 2 * tolerance:
        return None
    return (
        f"{_fmt(value.proof)} proof does not match {_fmt(value.abv_percent)}% ABV "
        f"(that would be {_fmt(2 * value.abv_percent)} proof)"
    )


def _compare_alcohol_content(
    expected: str,
    found: str | None,
    confidence: float,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """See compare_alcohol_content."""
    field = FieldName.ALCOHOL_CONTENT
    if found is None or not found.strip():
        return _not_found(field, expected, confidence)

    def result(status: Status, reason: str | None = None) -> FieldResult:
        return make_result(field, status, expected, found, confidence, reason)

    label_value = parse_abv(found)
    application_value = parse_abv(expected)
    if application_value is None:
        return result(
            Status.REVIEW,
            f'Could not read an alcohol content from the application value "{expected}"',
        )
    if label_value is None:
        return result(
            Status.REVIEW,
            f'Could not read a number from the label text "{collapse_whitespace(found)}" '
            "- check the label",
        )

    tolerance = thresholds.abv_tolerance
    if conflict := _proof_conflict(label_value, tolerance):
        return result(Status.FAIL, f"{_says(found, expected)} - on the label, {conflict}")
    if conflict := _proof_conflict(application_value, tolerance):
        return result(Status.REVIEW, f"{_says(found, expected)} - in the application, {conflict}")

    label_abv, application_abv = label_value.effective_abv, application_value.effective_abv
    if abs(label_abv - application_abv) > tolerance:
        return result(
            Status.FAIL,
            f"{_says(found, expected)} - {_fmt(label_abv)}% vs {_fmt(application_abv)}% ABV",
        )
    reason = None
    # Explain the conversion when the label's proof was checked against the application's ABV.
    converted = label_value.abv_percent is None and application_value.abv_percent is not None
    if converted and label_value.proof is not None:
        reason = f"Label gives {_fmt(label_value.proof)} proof, which equals {_fmt(label_abv)}% ABV"
    return result(Status.PASS, reason)


def _compare_net_contents(
    expected: str,
    found: str | None,
    confidence: float,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """See compare_net_contents."""
    field = FieldName.NET_CONTENTS
    if found is None or not found.strip():
        return _not_found(field, expected, confidence)

    def result(status: Status, reason: str | None = None) -> FieldResult:
        return make_result(field, status, expected, found, confidence, reason)

    label_value = parse_net_contents(found)
    application_value = parse_net_contents(expected)
    if application_value is None:
        return result(
            Status.REVIEW, f'Could not read a volume from the application value "{expected}"'
        )
    if label_value is None:
        return result(
            Status.REVIEW,
            f'Could not read a volume from the label text "{collapse_whitespace(found)}" '
            "- check the label",
        )

    difference_pct = abs(label_value.ml - application_value.ml) / application_value.ml * 100
    if difference_pct > thresholds.net_contents_tolerance_pct:
        return result(
            Status.FAIL,
            f"{_says(found, expected)} - {_fmt(label_value.ml)} mL vs "
            f"{_fmt(application_value.ml)} mL",
        )
    reason = None
    if label_value.unit != application_value.unit:
        reason = f"Same volume in different units ({_says(found, expected)})"
    return result(Status.PASS, reason)


def compare_alcohol_content(
    expected: str,
    found: str | None,
    confidence: float,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """Compare ABV numerically, converting proof (US proof = 2 x ABV) where needed."""
    result = _compare_alcohol_content(expected, found, confidence, thresholds)
    return downgrade_if_unsure(result, thresholds)


def compare_net_contents(
    expected: str,
    found: str | None,
    confidence: float,
    thresholds: MatchThresholds = DEFAULT_THRESHOLDS,
) -> FieldResult:
    """Compare volumes in mL so 750 mL, 75 cL and 0.75 L are equal."""
    result = _compare_net_contents(expected, found, confidence, thresholds)
    return downgrade_if_unsure(result, thresholds)
