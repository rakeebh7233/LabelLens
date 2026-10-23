import pytest

from app.matching.normalize import (
    collapse_whitespace,
    fold_ocr_confusions,
    fold_unicode,
    match_key,
    normalize_case,
    strip_punctuation,
)

# fold_unicode


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Stone’s Throw", "Stone's Throw"),
        ("“Reserve”", '"Reserve"'),
        ("Single–Barrel", "Single-Barrel"),
        ("Single—Barrel", "Single-Barrel"),
        ("ﬁne", "fine"),  # fi ligature
        ("ＡＢＣ", "ABC"),  # full-width letters
        ("750 mL", "750 mL"),  # non-breaking space
        ("plain text", "plain text"),
    ],
)
def test_fold_unicode(raw: str, expected: str) -> None:
    assert fold_unicode(raw) == expected


# collapse_whitespace


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Old   Tom  ", "Old Tom"),
        ("Kentucky\nStraight\tBourbon", "Kentucky Straight Bourbon"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_collapse_whitespace(raw: str, expected: str) -> None:
    assert collapse_whitespace(raw) == expected


# strip_punctuation


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stone's throw", "stones throw"),
        ("u.s.a.", "usa"),
        ("jack-daniel", "jack daniel"),
        ("old tom®", "old tom"),
        ("brand™ name", "brand name"),
        ("smith & sons, ltd.", "smith sons ltd"),
        ("rye/bourbon", "rye bourbon"),
        ("(no punctuation)", "no punctuation"),
        ("!!!", ""),
    ],
)
def test_strip_punctuation(raw: str, expected: str) -> None:
    assert strip_punctuation(raw) == expected


# fold_ocr_confusions


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("thr0w", "throw"),
        ("o1d tom", "old tom"),
        ("|ack", "lack"),
        # Digit-only tokens are numbers, not misread letters.
        ("1792 bourbon", "1792 bourbon"),
        ("750 ml", "750 ml"),
        ("no 10", "no 10"),
    ],
)
def test_fold_ocr_confusions(raw: str, expected: str) -> None:
    assert fold_ocr_confusions(raw) == expected


# normalize_case keeps punctuation so case-only differences can be told apart


def test_normalize_case_keeps_punctuation() -> None:
    assert normalize_case("  STONE’S   Throw ") == "stone's throw"
    assert normalize_case("Stones Throw") != normalize_case("Stone's Throw")


# match_key


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("STONE'S THROW", "Stone's Throw"),
        ("STONE'S THROW", "Stone’s Throw"),
        ("Stone's Throw", "Stones Throw"),
        ("Stone's Throw", "  stone's\nthrow "),
        ("STONE'S THR0W", "Stone's Throw"),
        ("Old Tom®", "OLD TOM"),
        ("Kentucky Straight Bourbon Whiskey", "KENTUCKY STRAIGHT BOURBON WHISKEY"),
        ("Single-Barrel", "Single Barrel"),
    ],
)
def test_match_key_equal_for_trivial_differences(a: str, b: str) -> None:
    assert match_key(a) == match_key(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Stone's Throw", "Stone's Toss"),
        ("Bourbon Whiskey", "Rye Whiskey"),
        ("Old Tom", "Old Tim"),
        ("1792 Bourbon", "1793 Bourbon"),
    ],
)
def test_match_key_differs_for_real_differences(a: str, b: str) -> None:
    assert match_key(a) != match_key(b)


@pytest.mark.parametrize("raw", ["", "   ", "\n\t", "®™©", "\x00\x01"])
def test_match_key_handles_degenerate_input(raw: str) -> None:
    assert match_key(raw) == match_key(raw).strip()
