import itertools

import pytest
from pydantic import ValidationError

from app.schemas import (
    STANDARD_GOVERNMENT_WARNING,
    ApplicationData,
    FieldName,
    FieldResult,
    LabelResult,
    Status,
    worst_status,
)

P, R, F = Status.PASS, Status.REVIEW, Status.FAIL


def _field(status: Status, name: FieldName = FieldName.BRAND_NAME) -> FieldResult:
    reason = None if status is Status.PASS else "Label differs from application"
    return FieldResult(
        field=name, status=status, expected="X", found="X", reason=reason, confidence=0.9
    )


def _application(**overrides: str) -> ApplicationData:
    values = {
        "brand_name": "Stone's Throw",
        "class_type": "Bourbon Whiskey",
        "alcohol_content": "45% ABV",
        "net_contents": "750 mL",
    }
    return ApplicationData(**(values | overrides))


# worst_status


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([P], P),
        ([P, P, P], P),
        ([P, R, P], R),
        ([R, F], F),
        ([P, R, F], F),
        ([F], F),
    ],
)
def test_worst_status_picks_most_severe(statuses: list[Status], expected: Status) -> None:
    assert worst_status(statuses) is expected


@pytest.mark.parametrize("order", list(itertools.permutations([P, R, F])))
def test_worst_status_ignores_order(order: tuple[Status, ...]) -> None:
    assert worst_status(order) is F


def test_worst_status_of_nothing_is_fail() -> None:
    assert worst_status([]) is F


def test_worst_status_accepts_a_generator() -> None:
    assert worst_status(s for s in [P, R]) is R


# LabelResult.overall_status


def test_overall_status_is_worst_field() -> None:
    result = LabelResult(
        label_id="1",
        fields=[_field(P), _field(R, FieldName.CLASS_TYPE), _field(P, FieldName.NET_CONTENTS)],
    )
    assert result.overall_status is R


def test_overall_status_all_pass() -> None:
    assert LabelResult(label_id="1", fields=[_field(P)]).overall_status is P


def test_error_forces_fail() -> None:
    result = LabelResult(label_id="1", fields=[_field(P)], error="The image could not be read.")
    assert result.overall_status is F


def test_no_fields_is_fail() -> None:
    assert LabelResult(label_id="1", fields=[]).overall_status is F


def test_overall_status_is_serialized() -> None:
    dumped = LabelResult(label_id="1", fields=[_field(R)]).model_dump(mode="json")
    assert dumped["overall_status"] == "review"
    assert dumped["fields"][0]["status"] == "review"
    assert dumped["timings_ms"] == {}
    assert dumped["warnings"] == []


# FieldResult


@pytest.mark.parametrize("confidence", [-0.1, 1.01])
def test_confidence_must_be_between_0_and_1(confidence: float) -> None:
    with pytest.raises(ValidationError):
        FieldResult(
            field=FieldName.BRAND_NAME, status=P, expected="X", found="X", confidence=confidence
        )


@pytest.mark.parametrize("status", [R, F])
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_non_pass_requires_reason(status: Status, reason: str | None) -> None:
    with pytest.raises(ValidationError, match="must include a reason"):
        FieldResult(
            field=FieldName.BRAND_NAME,
            status=status,
            expected="X",
            found="Y",
            reason=reason,
            confidence=0.5,
        )


def test_pass_needs_no_reason() -> None:
    result = FieldResult(
        field=FieldName.BRAND_NAME, status=P, expected="X", found="X", confidence=1.0
    )
    assert result.reason is None


def test_found_may_be_missing() -> None:
    result = FieldResult(
        field=FieldName.NET_CONTENTS,
        status=F,
        expected="750 mL",
        found=None,
        reason="Net contents not found on the label",
        confidence=0.0,
    )
    assert result.found is None


# ApplicationData


def test_government_warning_defaults_to_standard_text() -> None:
    assert _application().government_warning == STANDARD_GOVERNMENT_WARNING


def test_application_strips_whitespace() -> None:
    assert _application(brand_name="  Stone's Throw \n").brand_name == "Stone's Throw"


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_required_field_is_rejected(blank: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _application(brand_name=blank)
    assert exc.value.errors()[0]["loc"] == ("brand_name",)


def test_missing_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ApplicationData(brand_name="X", class_type="Y", alcohol_content="45%")  # type: ignore[call-arg]


def test_extra_keys_are_ignored() -> None:
    app = _application(filename="label1.png")
    assert not hasattr(app, "filename")


# Standard warning text


def test_standard_warning_is_normalized() -> None:
    assert STANDARD_GOVERNMENT_WARNING.startswith("GOVERNMENT WARNING: (1) According")
    assert STANDARD_GOVERNMENT_WARNING.endswith("may cause health problems.")
    assert "  " not in STANDARD_GOVERNMENT_WARNING
    assert "\n" not in STANDARD_GOVERNMENT_WARNING
