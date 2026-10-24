import pytest

from app.extract import fields
from app.ocr.engine import OcrResult, OcrWord
from app.schemas import STANDARD_GOVERNMENT_WARNING


def ocr(*lines: str | tuple[str, int], confidence: float = 0.95) -> OcrResult:
    """Build an OcrResult from text lines, top to bottom. A line may carry a text height."""
    words: list[OcrWord] = []
    top = 0
    for number, line in enumerate(lines):
        text, height = line if isinstance(line, tuple) else (line, 30)
        for word in text.split():
            words.append(OcrWord(word, 0, top, 10 * len(word), height, confidence, (1, 1, number)))
        top += height + 20
    return OcrResult(tuple(words), confidence)


LABEL = ocr(
    ("OLD TOM", 90),
    ("DISTILLERY", 90),
    "Kentucky Straight Bourbon Whiskey",
    "45% Alc./Vol. (90 Proof)",
    "750 mL",
    STANDARD_GOVERNMENT_WARNING,
)


# Text fields: search for the expected value


def test_brand_found_across_a_line_break() -> None:
    found = fields.find_brand("OLD TOM DISTILLERY", LABEL)
    assert found == fields.Found("OLD TOM DISTILLERY", 0.95)


def test_brand_found_despite_case_and_ocr_noise() -> None:
    label = ocr(("ST0NE'S THROW", 90), "Bourbon")
    found = fields.find_brand("Stone's Throw", label)
    assert found is not None and found.text == "ST0NE'S THROW"


def test_brand_found_when_ocr_splits_a_word() -> None:
    label = ocr(("STONE' S THROW", 90), "Bourbon")
    found = fields.find_brand("STONE'S THROW", label)
    assert found is not None and found.text == "STONE' S THROW"


def test_different_brand_falls_back_to_the_most_prominent_line() -> None:
    label = ocr("Product of USA", ("HARBOR LIGHT", 90), "Pale Ale", "5% ALC/VOL", "12 FL OZ")
    found = fields.find_brand("OLD TOM DISTILLERY", label)
    assert found is not None and found.text == "HARBOR LIGHT"


def test_class_type_found_by_search() -> None:
    found = fields.find_class_type("Kentucky Straight Bourbon Whiskey", LABEL)
    assert found is not None and found.text == "Kentucky Straight Bourbon Whiskey"


def test_different_class_type_falls_back_to_vocabulary() -> None:
    label = ocr(("HARBOR LIGHT", 90), "India Pale Ale", "5% ALC/VOL")
    found = fields.find_class_type("Vodka", label)
    assert found is not None and found.text == "India Pale Ale"


def test_short_class_type_does_not_match_inside_the_warning() -> None:
    """"Wine" must not be "found" as "women" in the warning text."""
    label = ocr(("HARBOR LIGHT", 90), "5% ALC/VOL", STANDARD_GOVERNMENT_WARNING)
    assert fields.find_class_type("Wine", label) is None


def test_text_fields_not_found_on_blank_reading() -> None:
    empty = OcrResult((), 0.0)
    assert fields.find_brand("Old Tom", empty) is None
    assert fields.find_class_type("Bourbon", empty) is None


def test_found_confidence_is_the_weakest_word() -> None:
    words = (
        OcrWord("Bourbon", 0, 0, 10, 30, 0.92, (1, 1, 1)),
        OcrWord("Whiskey", 0, 0, 10, 30, 0.33, (1, 1, 1)),
    )
    found = fields.find_class_type("Bourbon Whiskey", OcrResult(words, 0.6))
    assert found == fields.Found("Bourbon Whiskey", 0.33)


# Numbers: parse every line, keep the one closest to the expected value


@pytest.mark.parametrize(
    ("lines", "expected", "found"),
    [
        (["Bourbon", "45% Alc./Vol. (90 Proof)"], "45% ABV", "45% Alc./Vol. (90 Proof)"),
        (["45% ALC./VOL.", "90 PROOF"], "45%", "45% ALC./VOL. 90 PROOF"),  # proof line joined
        (["90 PROOF"], "45% ABV", "90 PROOF"),
        (["100% Blue Agave", "40% ALC/VOL"], "40% ABV", "40% ALC/VOL"),
        (["40% ALC/VOL"], "45% ABV", "40% ALC/VOL"),  # a mismatch is still reported
        (["Bourbon", "750 mL"], "45% ABV", None),
    ],
)
def test_find_alcohol_content(lines: list[str], expected: str, found: str | None) -> None:
    result = fields.find_alcohol_content(expected, ocr(*lines))
    assert (result.text if result else None) == found


@pytest.mark.parametrize(
    ("lines", "expected", "found"),
    [
        (["Bourbon", "750 mL"], "750 mL", "750 mL"),
        (["750 mL", "25.4 FL OZ"], "25.4 fl oz", "25.4 FL OZ"),
        (["700 mL"], "750 mL", "700 mL"),
        (["45% ALC/VOL"], "750 mL", None),
    ],
)
def test_find_net_contents(lines: list[str], expected: str, found: str | None) -> None:
    result = fields.find_net_contents(expected, ocr(*lines))
    assert (result.text if result else None) == found


def test_numbers_fall_back_to_first_line_when_application_is_unparseable() -> None:
    label = ocr("750 mL", "1 L")
    result = fields.find_net_contents("a bottle", label)
    assert result is not None and result.text == "750 mL"
