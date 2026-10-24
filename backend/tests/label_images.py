"""Synthetic label images for OCR tests: render text with Pillow, then damage the photo.

The damage functions live in scripts/samples_lib/defects.py (shared with the sample
generator) and are re-exported here.
"""

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from app.schemas import STANDARD_GOVERNMENT_WARNING
from samples_lib.defects import blurred, dim_and_uneven, rotated, with_glare

__all__ = ["blurred", "dim_and_uneven", "encode_png", "render_label", "rotated", "with_glare"]

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
    bold_prefix: bool = True,
    warning_size: int = 28,
) -> np.ndarray:
    """A clean, front-on label as a BGR image. As on a real label, the warning's first two
    words ("GOVERNMENT WARNING:") are bold unless bold_prefix is False."""
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
    regular, bold = _font(warning_size), _font(warning_size, bold=True)
    space = draw.textlength(" ", font=regular)
    x, line_height = margin, int(warning_size * 1.35)
    for i, word in enumerate(warning.split()):
        font = bold if bold_prefix and i < 2 else regular
        length = draw.textlength(word, font=font)
        if x > margin and x + length > width - margin:
            x, y = margin, y + line_height
        draw.text((x, y), word, fill="black", font=font)
        x += length + space
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def encode_png(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()
