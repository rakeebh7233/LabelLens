"""What each sample label shows, what the application says, and the expected verdict.

All brands are fictional. "Old Tom Distillery" and "Stone's Throw" come from the assignment
brief. Spec names that belong to real companies (Harbor Light, Cedar Ridge) are replaced with
invented ones (Harbor Wren, Bramblewick, Quillmoor).
"""

from dataclasses import dataclass, field, replace

from app.schemas import STANDARD_GOVERNMENT_WARNING

# Expected statuses: "pass", "review", "fail", or the looser "not_fail" (pass or review, for
# degraded photos of a good label) and "not_pass" (review or fail, for hidden fields).
Expected = str
FIELDS = ("brand_name", "class_type", "alcohol_content", "net_contents", "government_warning")


@dataclass(frozen=True)
class LabelText:
    """What is printed on the label."""

    brand: str
    class_type: str
    alcohol: str
    net: str
    # Other printed lines (bottler, origin, "CONTAINS SULFITES"); they must not confuse matching.
    extra: tuple[str, ...] = ()


@dataclass(frozen=True)
class Application:
    """What the agent enters for this label."""

    brand_name: str
    class_type: str
    alcohol_content: str
    net_contents: str


@dataclass(frozen=True)
class Defect:
    """An image-level defect from defects.py; `amount` is its main parameter, if any."""

    name: str
    amount: float = 0.0


@dataclass(frozen=True)
class LabelSpec:
    id: str
    filename: str
    layout: str  # spirits | beer | wine
    label_text: LabelText
    application: Application
    # What is different about this sample, for the README.
    tests: str
    expected_overall: Expected
    # Only fields listed here are asserted.
    expected_fields: dict[str, Expected] = field(default_factory=dict)
    # standard | titlecase | reworded | missing_sentence2 | absent | prefix_not_bold
    warning_variant: str = "standard"
    warning_size: int = 26
    image_defects: tuple[Defect, ...] = ()
    # Paper colour (RGB); varied so the OCR does not overfit to one look.
    background: tuple[int, int, int] = (250, 247, 240)


# Samples whose expected result the pipeline does not produce yet, and why. Each needs a
# decision: change the rule, change the sample, or accept the limitation. test_samples.py
# marks them as strict expected failures, so a change that fixes one is noticed.
# Samples whose expected result the pipeline does not produce yet (strict xfail in the tests).
KNOWN_GAPS: dict[str, str] = {}


def warning_text(variant: str) -> str | None:
    """The warning as printed for a variant, derived from the canonical text."""
    w = STANDARD_GOVERNMENT_WARNING
    if variant in ("standard", "prefix_not_bold"):
        return w
    if variant == "titlecase":
        return w.replace("GOVERNMENT WARNING:", "Government Warning:")
    if variant == "reworded":
        return w.replace(
            "women should not drink alcoholic beverages during pregnancy",
            "pregnant women should avoid alcoholic beverages",
        )
    if variant == "missing_sentence2":
        return w.split(" (2)")[0]
    if variant == "absent":
        return None
    raise ValueError(f"unknown warning variant {variant!r}")


def _all(status: Expected) -> dict[str, Expected]:
    return {name: status for name in FIELDS}


def _only(name: str, status: Expected) -> dict[str, Expected]:
    return _all("pass") | {name: status}


OLD_TOM_LABEL = LabelText(
    brand="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol="45% Alc./Vol. (90 Proof)",
    net="750 mL",
    extra=("Distilled and bottled by Old Tom Distillery, Bardstown, Kentucky",),
)
OLD_TOM_APP = Application(
    brand_name="OLD TOM DISTILLERY",
    class_type="Kentucky Straight Bourbon Whiskey",
    alcohol_content="45% Alc./Vol. (90 Proof)",
    net_contents="750 mL",
)
STONES_LABEL = replace(OLD_TOM_LABEL, brand="STONE'S THROW", extra=("Product of USA",))
STONES_APP = replace(OLD_TOM_APP, brand_name="STONE'S THROW")


def _perfect(id: str, filename: str, tests: str, defects: tuple[Defect, ...], expected: Expected,
             **changes: object) -> LabelSpec:  # fmt: skip
    """The perfect Old Tom label with only image defects added.

    For pass and not_fail every field is asserted; for review only the overall status is,
    since which field turns to review depends on where the damage lands.
    """
    fields = _all(expected) if expected in ("pass", "not_fail") else {}
    return LabelSpec(
        id, filename, "spirits", OLD_TOM_LABEL, OLD_TOM_APP, tests, expected,
        expected_fields=fields, image_defects=defects, **changes,  # type: ignore[arg-type]
    )  # fmt: skip


SPECS: list[LabelSpec] = [
    LabelSpec(
        "01", "01_old_tom_perfect.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        "Nothing: the reference label.", "pass", _all("pass"),
    ),
    LabelSpec(
        "02", "02_stones_throw_case.png", "spirits", STONES_LABEL,
        replace(STONES_APP, brand_name="Stone's Throw"),
        "Label brand STONE'S THROW, application Stone's Throw (Dave's example).",
        "review", _only("brand_name", "review"), background=(244, 238, 226),
    ),
    LabelSpec(
        "03", "03_brand_curly_apostrophe.png", "spirits",
        replace(STONES_LABEL, brand="STONE’S THROW"), STONES_APP,
        "Label uses a curly apostrophe, application a straight one.",
        "pass", _all("pass"), background=(236, 242, 236),
    ),
    LabelSpec(
        "04", "04_brand_ocr_like_typo.png", "spirits",
        replace(OLD_TOM_LABEL, brand="OLD T0M DISTILLERY"), OLD_TOM_APP,
        "Label prints OLD T0M with a zero, application OLD TOM. Accepted limitation: OCR reads "
        "the zero as the letter O (confidence 0.94), so it matches.",
        "pass", _all("pass"),
    ),
    LabelSpec(
        "05", "05_wrong_brand.png", "spirits",
        replace(OLD_TOM_LABEL, brand="HARBOR WREN", extra=("Bottled by Harbor Wren Spirits Co.",)),
        OLD_TOM_APP, "Label brand HARBOR WREN, application OLD TOM DISTILLERY.",
        "fail", _only("brand_name", "fail"), background=(240, 244, 250),
    ),
    LabelSpec(
        "06", "06_wrong_abv.png", "spirits",
        replace(OLD_TOM_LABEL, alcohol="40% Alc./Vol. (80 Proof)"), OLD_TOM_APP,
        "Label 40% (80 proof), application 45% (90 proof).",
        "fail", _only("alcohol_content", "fail"),
    ),
    LabelSpec(
        "07", "07_proof_only.png", "spirits", replace(OLD_TOM_LABEL, alcohol="90 PROOF"),
        replace(OLD_TOM_APP, alcohol_content="45% Alc./Vol."),
        "Label prints only 90 PROOF, application 45% Alc./Vol.",
        "pass", _all("pass"), background=(246, 240, 230),
    ),
    LabelSpec(
        "08", "08_wrong_net_contents.png", "spirits", replace(OLD_TOM_LABEL, net="700 mL"),
        OLD_TOM_APP, "Label 700 mL, application 750 mL.", "fail", _only("net_contents", "fail"),
    ),
    LabelSpec(
        "09", "09_net_contents_units.png", "spirits", replace(OLD_TOM_LABEL, net="75 cL"),
        OLD_TOM_APP, "Label 75 cL, application 750 mL.", "pass", _all("pass"),
        background=(238, 238, 244),
    ),
    LabelSpec(
        "10", "10_warning_titlecase.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        'Warning prefix printed "Government Warning:" (Jenny\'s rejection case).',
        "fail", _only("government_warning", "fail"), warning_variant="titlecase",
    ),
    LabelSpec(
        "11", "11_warning_reworded.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        "Warning sentence (1) paraphrased.", "fail", _only("government_warning", "fail"),
        warning_variant="reworded", background=(244, 240, 232),
    ),
    LabelSpec(
        "12", "12_warning_missing_sentence2.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        "Warning sentence (2) left out.", "fail", _only("government_warning", "fail"),
        warning_variant="missing_sentence2",
    ),
    LabelSpec(
        "13", "13_warning_absent.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        "No warning at all.", "fail", _only("government_warning", "fail"),
        warning_variant="absent", background=(236, 242, 236),
    ),
    LabelSpec(
        "14", "14_warning_not_bold.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        '"GOVERNMENT WARNING:" printed in regular weight instead of bold.',
        "review", _only("government_warning", "review"), warning_variant="prefix_not_bold",
    ),
    LabelSpec(
        "15", "15_warning_tiny_text.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        "Warning printed at 11 px. OCR reads none of it, which looks the same as no warning; "
        "failing is the conservative outcome and is accepted.",
        "fail", _only("government_warning", "fail"), warning_size=11,
    ),
    LabelSpec(
        "16", "16_beer_label.png", "beer",
        LabelText(
            "BRAMBLEWICK BREWING", "Pale Ale", "5.2% ALC/VOL", "12 FL OZ",
            ("Brewed and canned by Bramblewick Brewing Co., Asheville, NC",),
        ),
        Application("BRAMBLEWICK BREWING", "Pale Ale", "5.2% ALC/VOL", "12 FL OZ"),
        "Beer layout and units (fl oz).", "pass", _all("pass"), background=(255, 244, 214),
    ),
    LabelSpec(
        "17", "17_wine_label.png", "wine",
        LabelText(
            "QUILLMOOR CELLARS", "Cabernet Sauvignon", "13.5% ALC. BY VOL.", "750 ML",
            ("2021", "Estate Grown and Bottled", "CONTAINS SULFITES"),
        ),
        Application("QUILLMOOR CELLARS", "Cabernet Sauvignon", "13.5% ALC. BY VOL.", "750 mL"),
        "Wine layout with extra text (vintage, CONTAINS SULFITES).", "pass", _all("pass"),
        background=(246, 243, 236),
    ),
    _perfect("18", "18_rotated_12deg.png", "Perfect label rotated 12 degrees (deskew).",
             (Defect("rotate", 12),), "pass"),
    _perfect("19", "19_perspective_skew.png", "Perfect label photographed at an angle.",
             (Defect("perspective", 0.12),), "not_fail"),
    _perfect("20", "20_glare.png", "Bright glare patch over part of the text.",
             (Defect("glare"),), "not_fail"),
    LabelSpec(
        "20b", "20b_glare_hides_abv.png", "spirits", OLD_TOM_LABEL, OLD_TOM_APP,
        "Glare completely hides the alcohol content: must never pass.",
        "not_pass", {"alcohol_content": "not_pass"},
        image_defects=(Defect("glare_over_alcohol"),),
    ),
    _perfect("21", "21_low_light_blur.png", "Dark, low contrast, slightly blurred and noisy.",
             (Defect("low_light", 21),), "not_fail"),
    _perfect("22", "22_curved_text.png", "Text bent slightly, as on a round bottle.",
             (Defect("curved", 0.035),), "review"),
]  # fmt: skip
