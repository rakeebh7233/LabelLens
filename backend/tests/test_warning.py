import pytest

from app.config import MatchThresholds
from app.extract.warning import (
    block_confidence,
    check_warning,
    check_warning_in,
    compare_warning,
    locate_warning,
    prepare,
)
from app.ocr.engine import OcrResult, OcrWord
from app.schemas import STANDARD_GOVERNMENT_WARNING as W
from app.schemas import FieldName, Status

P, R, F = Status.PASS, Status.REVIEW, Status.FAIL
SURE = 0.95
BOLD_NOTE = 'Wording matches; bold type of "GOVERNMENT WARNING:" was not checked automatically'

SENTENCE_1 = W.split(" (2)")[0]
TITLE_CASE = W.replace("GOVERNMENT WARNING", "Government Warning")
# Warning with the first and last words damaged by OCR.
EDGES_DAMAGED = "G0VERNMENT" + W.removeprefix("GOVERNMENT").removesuffix("problems.") + "problerns."
LINE_WRAPPED = """GOVERNMENT WARNING: (1) According to the Surgeon
General, women should not drink alcoholic beverages during preg-
nancy because of the risk of birth defects. (2) Consumption of alco-
holic beverages impairs your ability to drive a car or operate
machinery, and may cause health problems."""
EMBEDDED = (
    "OLD TOM DISTILLERY\nKENTUCKY STRAIGHT BOURBON WHISKEY\n45% ALC./VOL. (90 PROOF) 750 mL\n"
    + W
    + "\nDISTILLED AND BOTTLED BY OLD TOM DISTILLERY, LOUISVILLE, KENTUCKY"
)


# prepare


def test_prepare_joins_line_end_hyphens_and_collapses_whitespace() -> None:
    assert prepare(LINE_WRAPPED) == W


def test_prepare_keeps_hyphens_that_are_not_at_line_end() -> None:
    assert prepare("single-barrel\nbourbon") == "single-barrel bourbon"


# locate_warning


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (W, W),
        (prepare(EMBEDDED), W),
        (prepare(LINE_WRAPPED), W),
        (TITLE_CASE, TITLE_CASE),
        # Missing sentence (2) followed by other label text: the other text is not swallowed.
        (SENTENCE_1 + " Distilled and bottled by Old Tom Distillery, Louisville", SENTENCE_1),
        # OCR-damaged first and last words are kept so they can be judged.
        ("BRAND 45% " + EDGES_DAMAGED + " BOTTLED BY", EDGES_DAMAGED),
    ],
)
def test_locate_warning(text: str, expected: str) -> None:
    assert locate_warning(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "abc",
        "OLD TOM KENTUCKY STRAIGHT BOURBON WHISKEY 45% ALC/VOL 750 ML DISTILLED AND BOTTLED BY",
        "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor. " * 5,
    ],
)
def test_locate_warning_returns_none_without_a_warning(text: str) -> None:
    assert locate_warning(text) is None


# check_warning: full OCR text in, FieldResult out


def test_title_case_prefix_fails_with_clear_reason() -> None:
    """Jenny's rule: "Government Warning:" is a rejection even though the words are right."""
    result = check_warning(TITLE_CASE, SURE)
    assert result.status is F
    assert result.reason == (
        'The label has "Government Warning:" but the warning must begin '
        '"GOVERNMENT WARNING:" in all capital letters'
    )


def test_minor_ocr_noise_is_review_and_names_the_words() -> None:
    noisy = W.replace("pregnancy", "pregnancv").replace("machinery", "machlnery")
    result = check_warning(noisy, SURE)
    assert result.status is R
    assert result.reason is not None
    assert '"pregnancv" (should be "pregnancy")' in result.reason
    assert '"machlnery," (should be "machinery,")' in result.reason


@pytest.mark.parametrize(
    ("ocr_text", "status", "reason_contains"),
    [
        # Exact, and exact once layout is undone.
        (W, P, BOLD_NOTE),
        (LINE_WRAPPED, P, BOLD_NOTE),
        (EMBEDDED, P, BOLD_NOTE),
        # Prefix problems.
        (W.replace("GOVERNMENT WARNING", "GOVERNMENT Warning"), F, "in all capital letters"),
        (W.replace("WARNING:", "WARNING"), F, "the colon after"),
        (W.removeprefix("GOVERNMENT WARNING: "), F, 'must begin with "GOVERNMENT WARNING:"'),
        # OCR read the colon as a semicolon: a misread, not a missing colon.
        (W.replace("WARNING:", "WARNING;"), R, '"WARNING;" (should be "WARNING:")'),
        (W.replace("GOVERNMENT", "G0VERNMENT"), R, "may be misread"),
        # Wording problems.
        (SENTENCE_1, F, 'missing "(2) Consumption of alcoholic ... health problems."'),
        (W.replace("should not", "must not"), F, '"must" where it should say "should"'),
        (W.replace("should not drink", "shouldn't drink"), F, "where it should say"),
        (W.replace("and may cause", "and can cause"), F, '"can" where it should say "may"'),
        (W.replace("birth defects", "serious birth defects"), F, 'extra "serious"'),
        # Body case is checked strictly too.
        (W.replace("Surgeon General", "surgeon general"), F, "where it should say"),
        # A one-letter change on a short word is a different word, not a misread.
        (W.replace("drive a car", "drive the car"), F, '"the" where it should say "a"'),
        # Too much damage to call it a misread.
        (
            W.replace("women", "wornen").replace("drink", "drlnk")
            .replace("risk", "rlsk").replace("defects", "defccts"),
            F,
            "and 1 more difference",
        ),
        # No warning at all.
        ("OLD TOM BOURBON 45% ALC/VOL 750 mL", F, "No government warning statement found"),
        ("", F, "No government warning statement found"),
    ],
)
def test_check_warning(ocr_text: str, status: Status, reason_contains: str) -> None:
    result = check_warning(ocr_text, SURE)
    assert result.field is FieldName.GOVERNMENT_WARNING
    assert result.status is status
    assert result.reason is not None and reason_contains in result.reason


# Bold verdict


@pytest.mark.parametrize(
    ("prefix_bold", "status", "reason"),
    [
        (True, P, None),
        (None, P, BOLD_NOTE),
        (
            False,
            R,
            'Wording matches, but "GOVERNMENT WARNING:" may not be in bold type - check the label',
        ),
    ],
)
def test_bold_verdict(prefix_bold: bool | None, status: Status, reason: str | None) -> None:
    result = check_warning(W, SURE, prefix_bold=prefix_bold)
    assert result.status is status
    assert result.reason == reason


def test_wording_failure_wins_over_bold() -> None:
    assert check_warning(SENTENCE_1, SURE, prefix_bold=True).status is F


# Low OCR confidence


def test_low_confidence_downgrades_pass_to_review() -> None:
    result = check_warning(W, 0.3, prefix_bold=True)
    assert result.status is R
    assert result.reason is not None and "hard to read (OCR confidence 30%)" in result.reason


def test_low_confidence_wording_fail_becomes_review() -> None:
    """On a barely readable photo a "missing" sentence may just not have been read."""
    result = check_warning(SENTENCE_1, 0.1)
    assert result.status is R
    assert result.reason is not None and "may be a misreading" in result.reason


def test_confident_wording_fail_stays_fail() -> None:
    assert check_warning(SENTENCE_1, SURE).status is F


def test_absent_warning_stays_fail_at_low_confidence() -> None:
    assert check_warning("OLD TOM BOURBON 45% ALC/VOL", 0.1).status is F


def test_low_confidence_threshold_comes_from_thresholds() -> None:
    lenient = MatchThresholds(low_ocr_confidence=0.2)
    assert check_warning(W, 0.3, prefix_bold=True, thresholds=lenient).status is P


# Expected text and reported values


def test_custom_expected_text_is_respected() -> None:
    custom = W.replace("health problems.", "health problems. Drink responsibly.")
    assert check_warning(custom, SURE, expected=custom, prefix_bold=True).status is P
    assert check_warning(W, SURE, expected=custom).status is F


def test_found_is_the_located_block_not_the_whole_label() -> None:
    result = check_warning(EMBEDDED, SURE)
    assert result.found == W
    assert result.expected == W


def test_compare_warning_without_text_fails() -> None:
    result = compare_warning(None, SURE)
    assert result.status is F
    assert result.found is None


# check_warning_in: confidence comes from the warning's own words


def _words(text: str, confidence_of: dict[str, float] | None = None) -> OcrResult:
    lookup = confidence_of or {}
    return OcrResult(
        tuple(
            OcrWord(word, 0, 0, 10, 10, lookup.get(word, 0.95), (1, 1, n))
            for n, line in enumerate(text.splitlines())
            for word in line.split()
        ),
        0.95,
    )


def test_block_confidence_ignores_the_rest_of_the_label() -> None:
    reading = _words("OLD TOM\n" + W, {"OLD": 0.1, "TOM": 0.1})
    assert block_confidence(W, reading.words) == 0.95


def test_garbled_warning_on_a_clear_label_is_review_not_fail() -> None:
    """Curved text: a fifth or more of the warning's words unreadable -> may be a misreading."""
    garbled = W.replace("Surgeon General, women", "Surg eon Gen . wo").replace(
        "impairs your ability", "imp vai asin"
    )
    shaky = {w: 0.2 for w in ("Surg", "eon", "Gen", ".", "wo", "imp", "vai", "asin", "of", "the")}
    result = check_warning_in(_words("OLD TOM DISTILLERY\n" + garbled, shaky))
    assert result.status is R
    assert result.reason is not None and "may be a misreading" in result.reason


def test_crisp_reworded_warning_still_fails() -> None:
    reworded = W.replace("should not", "must not")
    result = check_warning_in(_words(reworded, {"must": 0.3}))  # one shaky word is not enough
    assert result.status is F
