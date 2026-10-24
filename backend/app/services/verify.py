"""Orchestrates verification of one label: decode -> preprocess + OCR -> compare every field.

Never raises for a bad image or an OCR failure: those become a LabelResult with `error` set,
so one bad file in a batch is just one failed row.
"""

import logging
import time
import uuid
from functools import lru_cache

from app.config import Settings, get_settings
from app.extract import fields
from app.extract.warning import check_warning
from app.matching.compare import compare_alcohol_content, compare_net_contents, compare_text
from app.ocr.engine import OcrEngine, OcrError, OcrResult, TesseractEngine
from app.ocr.preprocess import ImageDecodeError, decode_image
from app.ocr.reader import read_label
from app.schemas import ApplicationData, FieldName, FieldResult, LabelResult, Status

logger = logging.getLogger(__name__)

NO_TEXT_WARNING = (
    "No text could be found on this image. Check that it is a clear photo of the label."
)
HARD_TO_READ_WARNING = (
    "The photo was hard to read, so results may be less reliable. "
    "A sharper, evenly lit photo may help."
)
UNEXPECTED_ERROR = "Something went wrong while checking this label. Please try again."


@lru_cache
def get_engine() -> OcrEngine:
    settings = get_settings()
    return TesseractEngine(settings.tesseract_cmd, retry_below=settings.ocr_retry_confidence)


def compare_fields(
    application: ApplicationData, ocr: OcrResult, settings: Settings
) -> list[FieldResult]:
    """Compare every field against one OCR reading. Pure apart from the inputs."""
    thresholds = settings.thresholds

    def located(found: fields.Found | None) -> tuple[str | None, float]:
        return (found.text, found.confidence) if found else (None, 0.0)

    brand = located(fields.find_brand(application.brand_name, ocr))
    class_type = located(fields.find_class_type(application.class_type, ocr))
    alcohol = located(fields.find_alcohol_content(application.alcohol_content, ocr))
    net = located(fields.find_net_contents(application.net_contents, ocr))
    return [
        compare_text(FieldName.BRAND_NAME, application.brand_name, *brand, thresholds),
        compare_text(FieldName.CLASS_TYPE, application.class_type, *class_type, thresholds),
        compare_alcohol_content(application.alcohol_content, *alcohol, thresholds),
        compare_net_contents(application.net_contents, *net, thresholds),
        # The warning spans many lines, so it is judged against the whole reading's confidence.
        check_warning(
            ocr.text,
            ocr.mean_confidence,
            application.government_warning,
            prefix_bold=None,
            thresholds=thresholds,
        ),
    ]


def verify_label(
    image_bytes: bytes,
    application: ApplicationData,
    *,
    filename: str | None = None,
    label_id: str | None = None,
    engine: OcrEngine | None = None,
    settings: Settings | None = None,
) -> LabelResult:
    """Check one label image against its application data."""
    settings = settings or get_settings()
    engine = engine or get_engine()
    label_id = label_id or uuid.uuid4().hex
    started = time.perf_counter()

    def failed(message: str, timings: dict[str, float]) -> LabelResult:
        timings["total"] = round((time.perf_counter() - started) * 1000, 1)
        return LabelResult(
            label_id=label_id, filename=filename, fields=[], timings_ms=timings, error=message
        )

    timings: dict[str, float] = {}
    try:
        step = time.perf_counter()
        image = decode_image(image_bytes)
        timings["decode"] = round((time.perf_counter() - step) * 1000, 1)

        # Retry with heavier cleanup unless every field already passes on the first reading.
        def all_fields_pass(ocr: OcrResult) -> bool:
            return all(r.status is Status.PASS for r in compare_fields(application, ocr, settings))

        reading = read_label(image, engine, settings.max_image_edge, accept=all_fields_pass)
        timings.update(reading.timings_ms)

        step = time.perf_counter()
        results = compare_fields(application, reading.ocr, settings)
        timings["compare"] = round((time.perf_counter() - step) * 1000, 1)
    except ImageDecodeError as exc:
        return failed(f"{exc}. Please upload a JPEG or PNG photo of the label.", timings)
    except OcrError as exc:
        logger.warning("OCR failed for %s: %s", filename or label_id, exc.__cause__ or exc)
        return failed(f"{exc}. Please try again.", timings)
    except Exception:
        logger.exception("Unexpected error verifying %s", filename or label_id)
        return failed(UNEXPECTED_ERROR, timings)

    warnings: list[str] = []
    if not reading.ocr.words:
        warnings.append(NO_TEXT_WARNING)
    elif reading.ocr.mean_confidence < settings.thresholds.low_ocr_confidence:
        warnings.append(HARD_TO_READ_WARNING)

    timings["total"] = round((time.perf_counter() - started) * 1000, 1)
    return LabelResult(
        label_id=label_id,
        filename=filename,
        fields=results,
        timings_ms=timings,
        preprocessing=reading.steps,
        ocr_confidence=round(reading.ocr.mean_confidence, 3),
        warnings=warnings,
    )
