import pytest

from app.config import MatchThresholds
from app.matching.compare import compare_alcohol_content, compare_net_contents, compare_text
from app.schemas import FieldName, FieldResult, Status

P, R, F = Status.PASS, Status.REVIEW, Status.FAIL
BRAND = FieldName.BRAND_NAME
SURE = 0.95


# compare_text (brand name, class/type)


def test_stones_throw_case_difference_is_review_not_fail() -> None:
    """Dave's example: obviously the same brand, so the agent decides."""
    result = compare_text(BRAND, "STONE'S THROW", "Stone's Throw", SURE)
    assert result.status is R
    assert result.reason == (
        'Label says "Stone\'s Throw", application says "STONE\'S THROW" '
        "- differs only in capitalization"
    )


@pytest.mark.parametrize(
    ("expected", "found", "status", "reason_contains"),
    [
        # Identical, or different only in ways that are not real differences.
        ("Stone's Throw", "Stone's Throw", P, None),
        ("Stone's Throw", "Stone’s Throw", P, None),  # curly apostrophe
        ("Stone's Throw", "  Stone's\nThrow ", P, None),  # OCR line break
        # Judgment calls.
        ("STONE'S THROW", "stone's throw", R, "only in capitalization"),
        ("Stone's Throw", "Stones Throw", R, "only in punctuation"),
        ("Old Tom", "Old Tom®", R, "only in punctuation"),
        ("STONE'S THROW", "Stones Throw", R, "capitalization and punctuation"),
        ("Stone's Throw", "Stone's Thr0w", R, "misread"),
        ("Kentucky Straight Bourbon Whiskey", "Kentucky Straight Bourbon Whisky", R, "% similar"),
        ("Stone's Throw", "Stone's Throws", R, "% similar"),
        # Clear mismatches.
        ("Stone's Throw", "Rock Toss", F, "do not match"),
        ("Bourbon Whiskey", "Rye Whiskey", F, "do not match"),
        ("Old Tom", "Old Tim", F, "do not match"),
    ],
)
def test_compare_text(expected: str, found: str, status: Status, reason_contains: str | None) -> None:
    result = compare_text(BRAND, expected, found, SURE)
    assert result.status is status
    if reason_contains is None:
        assert result.reason is None
    else:
        assert result.reason is not None and reason_contains in result.reason


@pytest.mark.parametrize("found", [None, "", "   "])
def test_compare_text_missing_is_fail(found: str | None) -> None:
    result = compare_text(FieldName.CLASS_TYPE, "Bourbon Whiskey", found, SURE)
    assert result.status is F
    assert result.found is None
    assert result.reason == 'No class/type found on the label (application says "Bourbon Whiskey")'


def test_compare_text_reports_found_with_whitespace_collapsed() -> None:
    result = compare_text(BRAND, "Old Tom", "Old\n  Tom", SURE)
    assert result.found == "Old Tom"


def test_fuzzy_threshold_is_configurable() -> None:
    strict = MatchThresholds(fuzzy_review=99)
    loose = MatchThresholds(fuzzy_review=50)
    assert compare_text(BRAND, "Stone's Throw", "Stone's Throws", SURE, strict).status is F
    assert compare_text(BRAND, "Old Tom", "Old Tim", SURE, loose).status is R


# Low OCR confidence


@pytest.mark.parametrize(
    ("compare", "expected", "found"),
    [
        (lambda e, f, c: compare_text(BRAND, e, f, c), "Old Tom", "Old Tom"),
        (compare_alcohol_content, "45% ABV", "45% Alc./Vol."),
        (compare_net_contents, "750 mL", "750 mL"),
    ],
)
def test_low_confidence_downgrades_pass_to_review(compare, expected: str, found: str) -> None:  # type: ignore[no-untyped-def]
    result = compare(expected, found, 0.3)
    assert result.status is R
    assert "hard to read (OCR confidence 30%)" in result.reason


def test_low_confidence_never_causes_fail() -> None:
    assert compare_text(BRAND, "Old Tom", "old tom", 0.1).status is R


@pytest.mark.parametrize(
    "result",
    [
        compare_text(BRAND, "Old Tom", "Rock Toss", 0.3),
        compare_alcohol_content("45% ABV", "40% ABV", 0.3),
        compare_net_contents("750 mL", "700 mL", 0.3),
    ],
)
def test_low_confidence_mismatch_is_review_as_a_possible_misreading(result: FieldResult) -> None:
    """Glare or blur can garble a correct label; a person decides rather than an auto-fail."""
    assert result.status is R
    assert result.reason is not None
    assert result.reason.endswith(
        "The label text was hard to read (OCR confidence 30%), so this may be a misreading "
        "- check the label"
    )


def test_clearly_read_mismatch_stays_fail() -> None:
    assert compare_text(BRAND, "Old Tom", "Rock Toss", SURE).status is F


def test_missing_field_stays_fail_even_at_low_confidence() -> None:
    assert compare_text(BRAND, "Old Tom", None, 0.0).status is F
    assert compare_net_contents("750 mL", None, 0.0).status is F


def test_low_confidence_threshold_is_configurable() -> None:
    lenient = MatchThresholds(low_ocr_confidence=0.2)
    assert compare_text(BRAND, "Old Tom", "Old Tom", 0.3, lenient).status is P


def test_low_confidence_keeps_existing_pass_reason() -> None:
    result = compare_net_contents("750 mL", "75 cL", 0.3)
    assert result.status is R
    assert result.reason is not None
    assert result.reason.startswith("Same volume in different units")
    assert "hard to read" in result.reason


# compare_alcohol_content


@pytest.mark.parametrize(
    ("expected", "found", "status", "reason_contains"),
    [
        ("45% ABV", "45% Alc./Vol.", P, None),
        ("45% ABV", "45% Alc./Vol. (90 Proof)", P, None),
        ("45% ABV (90 proof)", "45% ABV", P, None),
        ("45%", "45.0% ABV", P, None),
        ("40,5% vol", "40.5% alc/vol", P, None),
        # Proof on one side, ABV on the other: convert and compare.
        ("45% ABV", "90 Proof", P, "90 proof, which equals 45% ABV"),
        ("90 proof", "45% ABV", P, None),
        ("90 proof", "90 PROOF", P, None),
        # Mismatches.
        ("45% ABV", "40% ABV", F, "40% vs 45% ABV"),
        ("45% ABV", "80 Proof", F, "40% vs 45% ABV"),
        ("45% ABV", "45.5% ABV", F, "45.5% vs 45% ABV"),
        # Label contradicts itself: fail. Application contradicts itself: agent decides.
        ("45% ABV", "45% ABV (100 Proof)", F, "on the label, 100 proof does not match 45% ABV"),
        ("45% ABV (100 proof)", "45% ABV", R, "in the application, 100 proof"),
        # Unreadable values go to review rather than failing outright.
        ("45% ABV", "Alc. by vol.", R, "Could not read a number from the label"),
        ("forty-five percent", "45% ABV", R, "Could not read an alcohol content from the application"),
    ],
)
def test_compare_alcohol_content(
    expected: str, found: str, status: Status, reason_contains: str | None
) -> None:
    result = compare_alcohol_content(expected, found, SURE)
    assert result.field is FieldName.ALCOHOL_CONTENT
    assert result.status is status
    if reason_contains is None:
        assert result.reason is None
    else:
        assert result.reason is not None and reason_contains in result.reason


def test_alcohol_content_missing_is_fail() -> None:
    result = compare_alcohol_content("45% ABV", None, SURE)
    assert result.status is F
    assert result.reason is not None and "No alcohol content found" in result.reason


# compare_net_contents


@pytest.mark.parametrize(
    ("expected", "found", "status", "reason_contains"),
    [
        ("750 mL", "750 mL", P, None),
        ("750 mL", "750ml", P, None),
        ("750 mL", "750 ML.", P, None),
        ("750 mL", "75 cL", P, "Same volume in different units"),
        ("750 mL", "0.75 L", P, "Same volume in different units"),
        ("1.75 L", "1750 mL", P, "Same volume in different units"),
        # 25.4 fl oz is 751.2 mL: within tolerance.
        ("750 mL", "25.4 FL OZ", P, "Same volume in different units"),
        # Mismatches.
        ("750 mL", "700 mL", F, "700 mL vs 750 mL"),
        ("750 mL", "1 L", F, "1000 mL vs 750 mL"),
        ("750 mL", "75 mL", F, "75 mL vs 750 mL"),
        # Unreadable values go to review.
        ("750 mL", "seven fifty", R, "Could not read a volume from the label"),
        ("a bottle", "750 mL", R, "Could not read a volume from the application"),
    ],
)
def test_compare_net_contents(
    expected: str, found: str, status: Status, reason_contains: str | None
) -> None:
    result = compare_net_contents(expected, found, SURE)
    assert result.field is FieldName.NET_CONTENTS
    assert result.status is status
    if reason_contains is None:
        assert result.reason is None
    else:
        assert result.reason is not None and reason_contains in result.reason


def test_net_contents_tolerance_is_configurable() -> None:
    exact = MatchThresholds(net_contents_tolerance_pct=0.01)
    assert compare_net_contents("750 mL", "25.4 FL OZ", SURE, exact).status is F


def test_net_contents_missing_is_fail() -> None:
    result = compare_net_contents("750 mL", None, SURE)
    assert result.status is F
    assert result.reason == 'No net contents found on the label (application says "750 mL")'
