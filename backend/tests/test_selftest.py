import logging
import shutil
from pathlib import Path

import numpy as np
import pytest

from app.config import available_cpus, get_settings
from app.ocr.engine import OcrError, OcrResult, OcrWord, TesseractEngine
from app.selftest import SELF_TEST_TEXT, run_self_test


class FakeEngine:
    name = "fake"

    def __init__(self, text: str | None) -> None:
        self.text = text

    def run(self, image: np.ndarray) -> OcrResult:
        if self.text is None:
            raise OcrError("The OCR engine (Tesseract) is not installed on the server")
        words = tuple(OcrWord(w, 0, 0, 1, 1, 0.9, (1, 1, 1)) for w in self.text.split())
        return OcrResult(words, 0.9)


def test_self_test_passes_and_logs_timing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="labellens"):
        assert run_self_test(FakeEngine(SELF_TEST_TEXT), get_settings())
    assert "batch workers" in caplog.text
    assert "OCR self-test passed: fake read the sample in" in caplog.text


def test_self_test_reports_missing_tesseract_without_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="labellens"):
        assert not run_self_test(FakeEngine(None), get_settings())
    assert "OCR self-test failed: The OCR engine (Tesseract) is not installed" in caplog.text


def test_self_test_flags_a_misread(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="labellens"):
        assert not run_self_test(FakeEngine("LABELIENS SELF TEST"), get_settings())
    assert "misread" in caplog.text


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract is not installed")
def test_self_test_with_real_tesseract() -> None:
    assert run_self_test(TesseractEngine(), get_settings())


def test_available_cpus_honours_the_container_quota(tmp_path: Path) -> None:
    cpu_max = tmp_path / "cpu.max"
    cpu_max.write_text("50000 100000\n")
    assert available_cpus(cpu_max) == 0.5
    cpu_max.write_text("max 100000\n")
    assert available_cpus(cpu_max) >= 1
    assert available_cpus(tmp_path / "missing") >= 1
