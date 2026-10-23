import pytest

from app.matching.parsers import (
    ML_PER_FL_OZ,
    AlcoholContent,
    NetContents,
    parse_abv,
    parse_net_contents,
)

GARBAGE = [
    None,
    "",
    "   ",
    "no numbers here",
    "%%%",
    "proof",
    "ABV",
    "mL",
    "...,,,",
    "\x00\xff�",
    "9" * 500,
    "1e309%",
    "Ⅻ%",  # roman numeral twelve, not a digit
    "😀 750 😀",
]


# parse_abv


@pytest.mark.parametrize(
    ("raw", "abv", "proof"),
    [
        ("45%", 45.0, None),
        ("45 %", 45.0, None),
        ("45% ABV", 45.0, None),
        ("45 % ABV", 45.0, None),
        ("ABV 45%", 45.0, None),
        ("Alc 45% by vol", 45.0, None),
        ("ALC. 45% BY VOL.", 45.0, None),
        ("45% Alc./Vol.", 45.0, None),
        ("45% Alc./Vol. (90 Proof)", 45.0, 90.0),
        ("45% ABV (90 proof)", 45.0, 90.0),
        ("40.5% alc/vol", 40.5, None),
        ("40,5 % vol", 40.5, None),  # European decimal comma
        ("12.5 percent alcohol by volume", 12.5, None),
        ("Alcohol 13.5% by volume", 13.5, None),
        ("90 Proof", None, 90.0),
        ("90 PROOF", None, 90.0),
        ("90° proof", None, 90.0),
        ("101.4 proof", None, 101.4),
        # % sign lost by OCR
        ("ABV 45", 45.0, None),
        ("Alc. 45", 45.0, None),
        ("45 ABV", 45.0, None),
        # A bare percentage that is not alcohol must not win over the real ABV.
        ("100% Blue Agave Tequila 40% Alc/Vol", 40.0, None),
        ("100% agave, 80 proof", 100.0, 80.0),
        # Out-of-range values are ignored.
        ("150% ABV (90 Proof)", None, 90.0),
        ("45% ABV (250 proof)", 45.0, None),
        ("0.5% ABV", 0.5, None),
        # A dash is read as a separator, not a minus sign.
        ("Bourbon -45%", 45.0, None),
    ],
)


def test_parse_abv(raw: str, abv: float | None, proof: float | None) -> None:
    assert parse_abv(raw) == AlcoholContent(abv_percent=abv, proof=proof)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("45% ABV", 45.0), ("90 Proof", 45.0), ("86 proof", 43.0), ("45% (100 proof)", 45.0)],
)


def test_effective_abv(raw: str, expected: float) -> None:
    result = parse_abv(raw)
    assert result is not None
    assert result.effective_abv == expected


@pytest.mark.parametrize("raw", GARBAGE + ["0%", "200% ABV", "0 proof", "750 mL"])


def test_parse_abv_returns_none_on_garbage(raw: str | None) -> None:
    assert parse_abv(raw) is None


# parse_net_contents


@pytest.mark.parametrize(
    ("raw", "value", "unit"),
    [
        ("750 mL", 750.0, "mL"),
        ("750ml", 750.0, "mL"),
        ("750 ML", 750.0, "mL"),
        ("750 mL.", 750.0, "mL"),
        ("750 milliliters", 750.0, "mL"),
        ("750 millilitres", 750.0, "mL"),
        ("75 cL", 75.0, "cL"),
        ("75cl", 75.0, "cL"),
        ("1 L", 1.0, "L"),
        ("1L", 1.0, "L"),
        ("1.75L", 1.75, "L"),
        ("1,75 L", 1.75, "L"),  # European decimal comma
        ("1 liter", 1.0, "L"),
        ("1.5 litres", 1.5, "L"),
        ("1,000 mL", 1000.0, "mL"),  # thousands separator
        ("25.4 FL OZ", 25.4, "fl oz"),
        ("25.4 fl. oz.", 25.4, "fl oz"),
        ("25.4 FL.OZ", 25.4, "fl oz"),
        ("12 fluid ounces", 12.0, "fl oz"),
        ("12 OZ", 12.0, "fl oz"),
        ("1 pint", 1.0, "pt"),
        ("1 qt", 1.0, "qt"),
        ("1 gallon", 1.0, "gal"),
        ("NET CONTENTS: 750 mL", 750.0, "mL"),
        ("Contents 750 mL (25.4 fl oz)", 750.0, "mL"),
        ("12 x 355 mL", 355.0, "mL"),
    ],
)


def test_parse_net_contents(raw: str, value: float, unit: str) -> None:
    assert parse_net_contents(raw) == NetContents(value=value, unit=unit)


@pytest.mark.parametrize(
    ("raw", "ml"),
    [
        ("750 mL", 750.0),
        ("75 cL", 750.0),
        ("0.75 L", 750.0),
        ("1.75L", 1750.0),
        ("25.4 FL OZ", 25.4 * ML_PER_FL_OZ),
        ("1 gal", 128 * ML_PER_FL_OZ),
    ],
)


def test_net_contents_ml(raw: str, ml: float) -> None:
    result = parse_net_contents(raw)
    assert result is not None
    assert result.ml == pytest.approx(ml)


def test_equivalent_volumes_compare_equal_in_ml() -> None:
    volumes = [parse_net_contents(s) for s in ("750 mL", "750ml", "75 cL", "0.75 L")]
    assert all(v is not None for v in volumes)
    assert {round(v.ml, 6) for v in volumes if v is not None} == {750.0}


@pytest.mark.parametrize(
    "raw", GARBAGE + ["0 mL", "1 Lemon", "750", "45% ABV", "mL 750", "12 olives"]
)


def test_parse_net_contents_returns_none_on_garbage(raw: str | None) -> None:
    assert parse_net_contents(raw) is None
