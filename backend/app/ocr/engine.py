"""OcrEngine interface and Tesseract implementation.

The rest of the app depends only on OcrEngine and OcrResult, so another local engine
(RapidOCR, PaddleOCR) can be swapped in by implementing `run`.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import pytesseract


class OcrError(RuntimeError):
    """OCR could not run at all (engine missing, crashed or timed out)."""


@dataclass(frozen=True)
class OcrWord:
    text: str
    left: int
    top: int
    width: int
    height: int
    # 0-1
    confidence: float
    # Words with the same line_id are on the same text line, in reading order.
    line_id: tuple[int, int, int]


@dataclass(frozen=True)
class OcrResult:
    words: tuple[OcrWord, ...]
    # Mean word confidence, 0-1; 0 when nothing was read.
    mean_confidence: float
    # Engine-specific note on how the text was read, e.g. "psm 6".
    mode: str = ""

    @property
    def text(self) -> str:
        """Words joined by spaces, lines by newlines (later steps rely on the line breaks)."""
        lines: list[list[str]] = []
        previous: tuple[int, int, int] | None = None
        for word in self.words:
            if word.line_id != previous:
                lines.append([])
                previous = word.line_id
            lines[-1].append(word.text)
        return "\n".join(" ".join(line) for line in lines)

    @property
    def score(self) -> float:
        """Confidence-weighted character count, used to pick the better of two readings.

        Mean confidence alone would favour a reading that found only a few easy words.
        """
        return sum(len(w.text) * w.confidence for w in self.words)


class OcrEngine(Protocol):
    name: str

    def run(self, image: np.ndarray) -> OcrResult: ...


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


class TesseractEngine:
    """Tesseract via pytesseract. Local only; no network calls.

    Reads with page segmentation mode 6 (one uniform block of text) first. If confidence is
    low it retries with mode 11 (sparse text, suits scattered label layouts) and keeps the
    reading with the higher score.
    """

    name = "tesseract"

    def __init__(
        self,
        tesseract_cmd: str | None = None,
        retry_below: float = 0.75,
        timeout_s: float = 20,
        modes: tuple[int, ...] = (6, 11),
    ) -> None:
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
        self.retry_below = retry_below
        self.timeout_s = timeout_s
        self.modes = modes

    def _read(self, image: np.ndarray, psm: int) -> OcrResult:
        try:
            data = pytesseract.image_to_data(
                image,
                config=f"--psm {psm}",
                output_type=pytesseract.Output.DICT,
                timeout=self.timeout_s,
            )
        except pytesseract.TesseractNotFoundError as exc:
            raise OcrError("The OCR engine (Tesseract) is not installed on the server") from exc
        except (RuntimeError, pytesseract.TesseractError) as exc:
            # pytesseract raises RuntimeError on timeout.
            raise OcrError("The OCR engine could not read this image") from exc

        words = tuple(
            OcrWord(
                text=text.strip(),
                left=data["left"][i],
                top=data["top"][i],
                width=data["width"][i],
                height=data["height"][i],
                confidence=float(data["conf"][i]) / 100,
                line_id=(data["block_num"][i], data["par_num"][i], data["line_num"][i]),
            )
            for i, text in enumerate(data["text"])
            # conf is -1 for layout rows (blocks, lines) that carry no word.
            if text.strip() and float(data["conf"][i]) >= 0
        )
        return OcrResult(words, _mean([w.confidence for w in words]), mode=f"psm {psm}")

    def run(self, image: np.ndarray) -> OcrResult:
        best = self._read(image, self.modes[0])
        for psm in self.modes[1:]:
            if best.mean_confidence >= self.retry_below:
                break
            candidate = self._read(image, psm)
            if candidate.score > best.score:
                best = candidate
        return best
