"""Synthetic label images for OCR tests: render text with Pillow, then damage the photo."""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.schemas import STANDARD_GOVERNMENT_WARNING

_FONT_DIRS = [Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu")]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for directory in _FONT_DIRS:
        if (directory / name).exists():
            return ImageFont.truetype(str(directory / name), size)
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, width: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def render_label(
    brand: str = "STONE'S THROW",
    class_type: str = "Kentucky Straight Bourbon Whiskey",
    alcohol: str = "45% Alc./Vol. (90 Proof)",
    net: str = "750 mL",
    warning: str = STANDARD_GOVERNMENT_WARNING,
    width: int = 1200,
    height: int = 1500,
) -> np.ndarray:
    """A clean, front-on label as a BGR image."""
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    margin, y = 80, 100
    blocks = [(brand, 96, True), (class_type, 48, False), (alcohol, 44, False), (net, 44, False)]
    for text, size, bold in blocks:
        font = _font(size, bold)
        for line in _wrap(draw, text, font, width - 2 * margin):
            draw.text((margin, y), line, fill="black", font=font)
            y += int(size * 1.35)
        y += 30
    font = _font(28)
    for line in _wrap(draw, warning, font, width - 2 * margin):
        draw.text((margin, y), line, fill="black", font=font)
        y += 38
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def rotated(image: np.ndarray, degrees: float) -> np.ndarray:
    """Rotate counter-clockwise on a canvas grown to fit, so no text is cut off."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    cos, sin = abs(matrix[0, 0]), abs(matrix[0, 1])
    new_width, new_height = int(height * sin + width * cos), int(height * cos + width * sin)
    matrix[0, 2] += (new_width - width) / 2
    matrix[1, 2] += (new_height - height) / 2
    return cv2.warpAffine(image, matrix, (new_width, new_height), borderValue=(255, 255, 255))


def blurred(image: np.ndarray, sigma: float = 2.0) -> np.ndarray:
    return cv2.GaussianBlur(image, (0, 0), sigma)


def with_glare(image: np.ndarray) -> np.ndarray:
    """A bright elliptical hotspot washing out part of the label, as from a flash or lamp."""
    height, width = image.shape[:2]
    yy, xx = np.mgrid[0:height, 0:width]
    dx, dy = (xx - width * 0.7) / (width * 0.18), (yy - height * 0.3) / (height * 0.1)
    spot = np.exp(-(dx**2 + dy**2))
    tinted = image.astype(np.float32) * 0.75 + 30  # off-white paper so the hotspot stands out
    lit = tinted + spot[..., None] * 255
    return np.clip(lit, 0, 255).astype(np.uint8)


def dim_and_uneven(image: np.ndarray) -> np.ndarray:
    """Low light with a shadow falling across the label."""
    height, width = image.shape[:2]
    gradient = np.linspace(0.9, 0.3, width, dtype=np.float32)[None, :, None]
    return np.clip(image.astype(np.float32) * gradient, 0, 255).astype(np.uint8)


def encode_png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()
