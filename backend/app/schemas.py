"""Pydantic request/response models for the label verification domain."""

from collections.abc import Iterable
from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

STANDARD_GOVERNMENT_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic "
    "beverages during pregnancy because of the risk of birth defects. (2) Consumption of "
    "alcoholic beverages impairs your ability to drive a car or operate machinery, and may "
    "cause health problems."
)


class Status(StrEnum):
    PASS = "pass"
    REVIEW = "review"
    FAIL = "fail"


class FieldName(StrEnum):
    BRAND_NAME = "brand_name"
    CLASS_TYPE = "class_type"
    ALCOHOL_CONTENT = "alcohol_content"
    NET_CONTENTS = "net_contents"
    GOVERNMENT_WARNING = "government_warning"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"


_SEVERITY = {Status.PASS: 0, Status.REVIEW: 1, Status.FAIL: 2}


def worst_status(statuses: Iterable[Status]) -> Status:
    """Return the most severe status. Nothing verified is never a pass, so empty input is FAIL."""
    return max(statuses, key=_SEVERITY.__getitem__, default=Status.FAIL)


class ApplicationData(BaseModel):
    """What the applicant declared. Values are kept as typed; parsing happens in matching/parsers."""

    model_config = ConfigDict(str_strip_whitespace=True)

    brand_name: str = Field(min_length=1)
    class_type: str = Field(min_length=1)
    alcohol_content: str = Field(min_length=1)
    net_contents: str = Field(min_length=1)
    government_warning: str = Field(default=STANDARD_GOVERNMENT_WARNING, min_length=1)


class FieldResult(BaseModel):
    field: FieldName
    status: Status
    expected: str
    # None means the value was not found on the label at all.
    found: str | None
    # Plain-English explanation an agent can read at a glance. Required for review and fail.
    reason: str | None = None
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _non_pass_needs_reason(self) -> Self:
        if self.status is not Status.PASS and not (self.reason and self.reason.strip()):
            raise ValueError(f"a {self.status} result for {self.field} must include a reason")
        return self


class LabelResult(BaseModel):
    label_id: str
    filename: str | None = None
    fields: list[FieldResult]
    timings_ms: dict[str, float] = Field(default_factory=dict)
    # Plain-language image fix-ups applied before OCR, e.g. "straightened by 10.0°".
    preprocessing: list[str] = Field(default_factory=list)
    # Mean OCR word confidence (0-1) for the reading the results are based on.
    ocr_confidence: float | None = Field(default=None, ge=0, le=1)
    # Non-fatal notes such as "Image is blurry; results may be less reliable".
    warnings: list[str] = Field(default_factory=list)
    # Set when the label could not be processed at all (e.g. unreadable image).
    error: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def overall_status(self) -> Status:
        if self.error:
            return Status.FAIL
        return worst_status(f.status for f in self.fields)


class BatchProgress(BaseModel):
    total: int = Field(ge=0)
    completed: int = Field(default=0, ge=0)
    passed: int = Field(default=0, ge=0)
    review: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)


class BatchJob(BaseModel):
    job_id: str
    state: JobState
    created_at: datetime
    progress: BatchProgress
    results: list[LabelResult] = Field(default_factory=list)
