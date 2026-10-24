"""Parse alcohol content (ABV and proof) and net contents from label or application text.

Parsers return None when nothing usable is found and never raise, because their input is
often noisy OCR output. Comparison rules (tolerances, ABV vs proof) live in compare.py.
"""

import re
from dataclasses import dataclass

from app.matching.normalize import fold_unicode

# A number with an optional decimal part; a comma counts as a decimal mark ("40,5%").
_NUMBER = r"(\d+(?:[.,]\d+)?)"

_PERCENT = _NUMBER + r"\s*(?:%|percent\b)"
_ALC_WORD = r"(?:abv|alc(?:ohol)?|by\s*vol(?:ume)?)\b"
# Tried in order, so a percentage beside an alcohol word wins over a bare one. This keeps
# "100% Blue Agave ... 40% Alc/Vol" from being read as 100% ABV.
_ABV_PATTERNS = [
    re.compile(_PERCENT + r"\s*\.?\s*" + _ALC_WORD, re.IGNORECASE),
    re.compile(r"\b" + _ALC_WORD + r"[^\d%]{0,15}?" + _PERCENT, re.IGNORECASE),
    re.compile(_PERCENT, re.IGNORECASE),
    # "ABV 45" / "Alc. 45" / "45 ABV" when OCR dropped the % sign.
    re.compile(r"\b(?:abv|alc(?:ohol)?)\b\.?\s*:?\s*" + _NUMBER, re.IGNORECASE),
    re.compile(_NUMBER + r"\s*(?:abv|alc)\b", re.IGNORECASE),
]
_PROOF = re.compile(_NUMBER + r"\s*°?\s*proof\b", re.IGNORECASE)

ML_PER_FL_OZ = 29.5735
_ML_PER_UNIT = {
    "mL": 1.0,
    "cL": 10.0,
    "L": 1000.0,
    "fl oz": ML_PER_FL_OZ,
    "pt": 16 * ML_PER_FL_OZ,
    "qt": 32 * ML_PER_FL_OZ,
    "gal": 128 * ML_PER_FL_OZ,
}

# Longer spellings first so "milliliters" is not read as "m" + "l...".
_UNIT_PATTERNS: list[tuple[str, str]] = [
    ("mL", r"millilit(?:er|re)s?|ml"),
    ("cL", r"centilit(?:er|re)s?|cl"),
    ("L", r"lit(?:er|re)s?|ltr|l"),
    # Plain "oz" on a beverage label means fluid ounces. OCR often reads the O as a zero.
    ("fl oz", r"fl(?:uid)?\.?\s*(?:ounces?|[o0]z)\.?|ounces?|[o0]z"),
    ("pt", r"pints?|pt"),
    ("qt", r"quarts?|qt"),
    ("gal", r"gallons?|gal"),
]
_UNIT_ALTERNATIVES = "|".join(f"(?P<u{i}>{p})" for i, (_, p) in enumerate(_UNIT_PATTERNS))
# The trailing lookahead stops "1 Lemon" from reading as 1 litre.
_NET_CONTENTS = re.compile(
    r"(\d+(?:[.,]\d+)*)\s*(?:" + _UNIT_ALTERNATIVES + r")(?![a-z])", re.IGNORECASE
)


@dataclass(frozen=True)
class AlcoholContent:
    """At least one of abv_percent and proof is set."""

    abv_percent: float | None
    proof: float | None

    @property
    def effective_abv(self) -> float:
        """ABV in percent, derived from proof (US proof = 2 x ABV) when only proof is given."""
        if self.abv_percent is not None:
            return self.abv_percent
        assert self.proof is not None
        return self.proof / 2


@dataclass(frozen=True)
class NetContents:
    value: float
    # Canonical unit: one of mL, cL, L, fl oz, pt, qt, gal.
    unit: str

    @property
    def ml(self) -> float:
        return self.value * _ML_PER_UNIT[self.unit]


def _to_float(raw: str) -> float | None:
    """Parse "45", "40.5", "40,5" (decimal comma) or "1,000" (thousands separator)."""
    if "," in raw and "." not in raw:
        whole, _, frac = raw.rpartition(",")
        # Exactly three digits after a single comma reads as thousands: "1,750 mL".
        raw = whole + frac if len(frac) == 3 and "," not in whole else raw.replace(",", ".")
    else:
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


def _first_number(pattern: re.Pattern[str], text: str, upper: float) -> float | None:
    """First match of pattern whose number lies in (0, upper]."""
    for match in pattern.finditer(text):
        value = _to_float(match.group(1))
        if value is not None and 0 < value <= upper:
            return value
    return None


def parse_abv(text: str | None) -> AlcoholContent | None:
    """Find ABV and/or proof, e.g. "45% Alc./Vol. (90 Proof)" -> abv 45.0, proof 90.0.

    Values outside the physically possible range (ABV over 100%, proof over 200) are ignored.
    Whether ABV and proof agree with each other is left to the comparison step.
    """
    if not text:
        return None
    text = fold_unicode(text)
    abv = next(
        (v for p in _ABV_PATTERNS if (v := _first_number(p, text, 100)) is not None), None
    )
    proof = _first_number(_PROOF, text, 200)
    if abv is None and proof is None:
        return None
    return AlcoholContent(abv_percent=abv, proof=proof)


def parse_net_contents(text: str | None) -> NetContents | None:
    """Find the first volume, e.g. "750 mL", "75cl", "1.75L", "25.4 FL. OZ."."""
    if not text:
        return None
    text = fold_unicode(text)
    for match in _NET_CONTENTS.finditer(text):
        value = _to_float(match.group(1))
        if value is None or value <= 0:
            continue
        unit = next(
            canonical
            for i, (canonical, _) in enumerate(_UNIT_PATTERNS)
            if match.group(f"u{i}") is not None
        )
        return NetContents(value=value, unit=unit)
    return None
