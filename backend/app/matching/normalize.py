"""Text normalization for matching.

Each step is a small pure function so comparison code can apply them one at a time and say
which kind of difference it found (case only, punctuation only, ...). Everything here builds
matching keys; displayed text and reasons always quote the original strings.
"""

import unicodedata

# Typographic variants that OCR and word processors produce interchangeably.
_TYPOGRAPHY = str.maketrans(
    {
        "‘": "'",  # left single quote
        "’": "'",  # right single quote / curly apostrophe
        "‚": "'",
        "‛": "'",
        "′": "'",  # prime
        "´": "'",  # acute accent
        "`": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',  # double prime
        "‐": "-",  # hyphen
        "‑": "-",  # non-breaking hyphen
        "‒": "-",  # figure dash
        "–": "-",  # en dash
        "—": "-",  # em dash
        "−": "-",  # minus sign
    }
)

# Punctuation removed without leaving a gap, so "Stone's" -> "stones" and "U.S.A." -> "usa".
# All other punctuation and symbols become a space, so "Jack-Daniel" -> "jack daniel".
_JOINING_PUNCTUATION = frozenset("'.")

# Letter look-alikes OCR produces for 0 and 1 (and "|" for l).
_OCR_LOOKALIKES = str.maketrans({"0": "o", "1": "l", "|": "l"})


def fold_unicode(text: str) -> str:
    """Apply NFKC (ligatures, full-width forms, non-breaking spaces) and straighten quotes/dashes."""
    return unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY)


def collapse_whitespace(text: str) -> str:
    """Trim and turn every run of whitespace, including newlines, into a single space."""
    return " ".join(text.split())


def strip_punctuation(text: str) -> str:
    """Remove punctuation and symbols (including (R) and TM marks); see _JOINING_PUNCTUATION."""
    out: list[str] = []
    for ch in text:
        if ch in _JOINING_PUNCTUATION:
            continue
        category = unicodedata.category(ch)
        out.append(" " if category[0] in "PS" else ch)
    return collapse_whitespace("".join(out))


def fold_ocr_confusions(text: str) -> str:
    """Read 0 as o, 1 as l and | as l, but only inside words that also contain letters.

    Deliberately conservative: "thr0w" becomes "throw", while numbers like "1792" or "750" are
    left alone because a token made only of digits is far more likely to really be a number.
    """
    tokens = text.split(" ")
    return " ".join(
        token.translate(_OCR_LOOKALIKES) if any(ch.isalpha() for ch in token) else token
        for token in tokens
    )


def normalize_case(text: str) -> str:
    """Unicode folding, case folding and whitespace only. Punctuation is kept."""
    return collapse_whitespace(fold_unicode(text).casefold())


def match_key(text: str) -> str:
    """Full normalization: case, unicode, whitespace, punctuation and OCR look-alikes.

    Two values with the same match key differ only in trivial ways.
    """
    return strip_punctuation(fold_ocr_confusions(normalize_case(text)))
