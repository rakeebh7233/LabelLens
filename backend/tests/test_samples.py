"""Regression suite: every generated sample label through verify_label, against expected.json.

Regenerate the samples with `python scripts/make_samples.py`. Run with `-s` to see the median
time per label.
"""

import csv
import json
import shutil
import statistics
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.schemas import ApplicationData, LabelResult
from app.services.verify import verify_label
from samples_lib.spec import KNOWN_GAPS

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
EXPECTED: dict[str, dict[str, object]] = json.loads((SAMPLES / "expected.json").read_text())
# Generous so slow CI machines do not flake; the 5 s budget is for a normal laptop.
CEILING_MS = 8000
# Degraded photos run the slower second pass every time.
SLOW = {"18_", "19_", "20_", "20b", "21_", "22_"}

_timings: list[float] = []


def _application(filename: str) -> ApplicationData:
    with (SAMPLES / "applications.csv").open(encoding="utf-8") as handle:
        row = next(r for r in csv.DictReader(handle) if r["filename"] == filename)
    return ApplicationData(**{k: v for k, v in row.items() if k != "filename" and v})


def _matches(expected: str, actual: str) -> bool:
    if expected == "not_fail":
        return actual != "fail"
    if expected == "not_pass":
        return actual != "pass"
    return actual == expected


def _params() -> Iterator[object]:
    for filename in EXPECTED:
        marks = []
        if filename[:3] in SLOW:
            marks.append(pytest.mark.slow)
        if filename in KNOWN_GAPS:
            marks.append(pytest.mark.xfail(reason=KNOWN_GAPS[filename], strict=True))
        yield pytest.param(filename, marks=marks, id=filename.removesuffix(".png"))


@pytest.fixture(scope="module", autouse=True)
def _report_median() -> Iterator[None]:
    yield
    if _timings:
        print(f"\nSample labels: median {statistics.median(_timings):.0f} ms, "
              f"max {max(_timings):.0f} ms over {len(_timings)} labels")  # fmt: skip


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
@pytest.mark.parametrize("filename", list(_params()))
def test_sample(filename: str) -> None:
    expected = EXPECTED[filename]
    result: LabelResult = verify_label(
        (SAMPLES / "labels" / filename).read_bytes(), _application(filename), filename=filename
    )
    _timings.append(result.timings_ms["total"])
    details = [(f.field.value, f.status.value, f.reason) for f in result.fields]

    assert _matches(expected["overall"], result.overall_status), details
    for field in result.fields:
        if field.field.value in expected["fields"]:
            assert _matches(expected["fields"][field.field.value], field.status), details
    assert result.timings_ms["total"] < CEILING_MS


def test_every_sample_has_an_image_and_a_manifest_row() -> None:
    with (SAMPLES / "applications.csv").open(encoding="utf-8") as handle:
        rows = {r["filename"] for r in csv.DictReader(handle)}
    for filename in EXPECTED:
        assert (SAMPLES / "labels" / filename).is_file(), filename
        assert filename in rows, filename
