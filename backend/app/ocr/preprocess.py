"""OpenCV preprocessing pipeline (resize cap, grayscale, CLAHE, deskew, glare).

Small functions on numpy images. `basic` is cheap and always runs; `heavy` adds the slower
fix-ups and is only used when OCR confidence on the basic image is low (see ocr/reader.py).
Each returns the processed image plus the names of the steps it applied, so the UI can show
what was done to the photo.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

# Skew below this (degrees) is left alone; Tesseract copes with it and rotating blurs text.
_MIN_SKEW_DEG = 0.5
_MAX_SKEW_DEG = 15.0
# Deskew angle search runs on a copy of this size, which is plenty to see text lines.
_DESKEW_WORK_EDGE = 800
# Pixels at least this bright count as glare (blown-out highlights).
_GLARE_LEVEL = 250
# Glare covering less than this share is noise; more than this is a white label, not glare.
_GLARE_MIN_SHARE, _GLARE_MAX_SHARE = 0.0005, 0.25


class ImageDecodeError(ValueError):
    """The uploaded bytes are not an image OpenCV can read."""


@dataclass
class Preprocessed:
    image: np.ndarray
    steps: list[str] = field(default_factory=list)


def decode_image(data: bytes) -> np.ndarray:
    """Decode uploaded bytes to a BGR image. Phone-photo EXIF orientation is applied."""
    array = np.frombuffer(data, dtype=np.uint8)
    image = cv2.imdecode(array, cv2.IMREAD_COLOR) if array.size else None
    if image is None:
        raise ImageDecodeError("This file could not be read as an image")
    return image


def resize_to_max_edge(image: np.ndarray, max_edge: int) -> np.ndarray:
    """Downscale so the long edge is at most max_edge. Never upscales."""
    height, width = image.shape[:2]
    scale = max_edge / max(height, width)
    if scale >= 1:
        return image
    size = (round(width * scale), round(height * scale))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def enhance_contrast(gray: np.ndarray) -> np.ndarray:
    """CLAHE: local contrast boost that copes with uneven lighting better than global stretch."""
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)


def _line_score(binary: np.ndarray, angle: float) -> float:
    """How sharply text rows stand out when the image is rotated by angle (higher is better)."""
    height, width = binary.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    rotated = cv2.warpAffine(binary, matrix, (width, height), flags=cv2.INTER_NEAREST)
    rows = rotated.sum(axis=1, dtype=np.float64)
    return float(np.square(np.diff(rows)).sum())


def estimate_skew(gray: np.ndarray) -> float:
    """Angle (degrees, counter-clockwise) that makes text lines horizontal; 0 if unsure.

    Projection-profile search: rotate a small binarized copy through candidate angles and keep
    the one where row sums change most sharply, which is when text lines are level. More
    robust on labels than minAreaRect, which is thrown off by borders and artwork.
    """
    small = resize_to_max_edge(gray, _DESKEW_WORK_EDGE)
    _, binary = cv2.threshold(small, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    if binary.mean() < 0.005:  # blank image
        return 0.0
    def score(angle: float) -> float:
        return _line_score(binary, angle)

    coarse = max(np.arange(-_MAX_SKEW_DEG, _MAX_SKEW_DEG + 0.1, 1.0), key=score)
    fine = max(np.arange(coarse - 1, coarse + 1.01, 0.2), key=score)
    return round(float(fine), 1)


def rotate(gray: np.ndarray, angle: float) -> np.ndarray:
    """Rotate about the centre, growing the canvas so corners are not cut off."""
    height, width = gray.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_width, new_height = int(height * sin + width * cos), int(height * cos + width * sin)
    matrix[0, 2] += new_width / 2 - width / 2
    matrix[1, 2] += new_height / 2 - height / 2
    background = int(np.median(gray))
    return cv2.warpAffine(
        gray, matrix, (new_width, new_height), flags=cv2.INTER_CUBIC, borderValue=background
    )


def glare_mask(gray: np.ndarray) -> np.ndarray | None:
    """Mask of blown-out highlight patches, or None when there is no glare worth fixing."""
    mask = (gray >= _GLARE_LEVEL).astype(np.uint8)
    share = float(mask.mean())
    if not _GLARE_MIN_SHARE <= share <= _GLARE_MAX_SHARE:
        return None
    return cv2.dilate(mask, np.ones((5, 5), np.uint8))


def flatten_illumination(gray: np.ndarray) -> np.ndarray:
    """Divide out the slowly varying background (shadows, bright gradients from glare)."""
    kernel = max(15, (min(gray.shape) // 20) | 1)
    background = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), kernel)
    return cv2.divide(gray, background, scale=255)


def binarize(gray: np.ndarray) -> np.ndarray:
    """Adaptive threshold: black text on white, robust to leftover uneven lighting."""
    block = max(15, (min(gray.shape) // 30) | 1)
    return cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block, 15
    )


def basic(image: np.ndarray, max_edge: int) -> Preprocessed:
    """Always-on, cheap pass: resize cap, grayscale, CLAHE."""
    result = Preprocessed(image)
    resized = resize_to_max_edge(image, max_edge)
    if resized.shape != image.shape:
        result.steps.append(f"resized to {max(resized.shape[:2])}px")
    result.image = enhance_contrast(to_grayscale(resized))
    result.steps.append("contrast boost")
    return result


def heavy(gray: np.ndarray) -> Preprocessed:
    """Slower fix-ups for hard photos: glare repair, lighting flatten, deskew, threshold.

    Takes the output of basic(). Glare is repaired before deskew so bright patches do not
    skew the line search.
    """
    result = Preprocessed(gray)
    image = gray
    if (mask := glare_mask(image)) is not None:
        image = cv2.inpaint(image, mask, 3, cv2.INPAINT_TELEA)
        result.steps.append("glare reduced")
    image = flatten_illumination(image)
    result.steps.append("lighting evened out")
    angle = estimate_skew(image)
    if _MIN_SKEW_DEG <= abs(angle) <= _MAX_SKEW_DEG:
        image = rotate(image, angle)
        result.steps.append(f"straightened by {abs(angle):.1f}°")
    result.image = binarize(image)
    result.steps.append("converted to black and white")
    return result
