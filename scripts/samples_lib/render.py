"""Drawing primitives: paper, wrapped text blocks and the warning with a bold prefix.

Every drawn block records its bounding box under a key ("brand", "alcohol", ...) so defects
can target a specific line (for example glare over the alcohol content).
"""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONT_DIR = Path(__file__).resolve().parents[1] / "fonts"
Box = tuple[int, int, int, int]
Colour = tuple[int, int, int]
INK: Colour = (28, 24, 20)


@lru_cache
def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    """A bundled font by file stem, e.g. font("DejaVuSerif-Bold", 40)."""
    return ImageFont.truetype(str(FONT_DIR / f"{name}.ttf"), size)


@dataclass
class Canvas:
    image: Image.Image
    draw: ImageDraw.ImageDraw
    boxes: dict[str, Box] = field(default_factory=dict)

    @property
    def width(self) -> int:
        return self.image.width

    @property
    def height(self) -> int:
        return self.image.height

    def record(self, key: str, box: Box) -> None:
        if key in self.boxes:
            left, top, right, bottom = self.boxes[key]
            box = (min(left, box[0]), min(top, box[1]), max(right, box[2]), max(bottom, box[3]))
        self.boxes[key] = box


def new_canvas(width: int, height: int, paper: Colour, seed: int) -> Canvas:
    """Paper of the given colour with faint, seeded mottling so it is not perfectly flat.

    The mottling is low-frequency (coarse noise scaled up smoothly): per-pixel grain made
    every PNG about 2.8 MB because random noise does not compress.
    """
    rng = np.random.default_rng(seed)
    coarse = rng.normal(0, 4, (height // 40, width // 40)).astype(np.float32)
    mottle = np.array(Image.fromarray(coarse, "F").resize((width, height), Image.BICUBIC))
    pixels = np.array(paper, np.float32)[None, None, :] + mottle[..., None]
    image = Image.fromarray(np.clip(pixels, 0, 255).round().astype(np.uint8), "RGB")
    return Canvas(image, ImageDraw.Draw(image))


def wrap(
    draw: ImageDraw.ImageDraw, text: str, typeface: ImageFont.FreeTypeFont, width: int
) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=typeface) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def text_block(
    canvas: Canvas,
    key: str,
    text: str,
    typeface: ImageFont.FreeTypeFont,
    top: int,
    *,
    left: int = 80,
    width: int | None = None,
    align: str = "center",
    fill: Colour = INK,
    spacing: float = 1.3,
) -> int:
    """Draw wrapped text; returns the y just below it."""
    width = width or canvas.width - 2 * left
    y = top
    for line in wrap(canvas.draw, text, typeface, width):
        length = canvas.draw.textlength(line, font=typeface)
        x = left + (width - length) / 2 if align == "center" else left
        canvas.draw.text((x, y), line, fill=fill, font=typeface)
        box = canvas.draw.textbbox((x, y), line, font=typeface)
        canvas.record(key, (int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        y += int(typeface.size * spacing)
    return y


def warning_block(
    canvas: Canvas,
    text: str,
    top: int,
    *,
    size: int,
    regular: str,
    bold: str,
    bold_prefix: bool = True,
    left: int = 80,
    width: int | None = None,
    fill: Colour = INK,
) -> int:
    """The warning, wrapped word by word, with its first two words in bold when bold_prefix.

    Only an all-caps "GOVERNMENT WARNING:" prefix is set in bold here; the title-case
    variant keeps whatever weight bold_prefix says, since that sample tests capitals only.
    """
    width = width or canvas.width - 2 * left
    regular_font, bold_font = font(regular, size), font(bold, size)
    words = text.split()
    styled = [
        (word, bold_font if bold_prefix and i < 2 else regular_font) for i, word in enumerate(words)
    ]
    space = canvas.draw.textlength(" ", font=regular_font)
    x, y, line_height = left, top, int(size * 1.35)
    for word, typeface in styled:
        length = canvas.draw.textlength(word, font=typeface)
        if x > left and x + length > left + width:
            x, y = left, y + line_height
        canvas.draw.text((x, y), word, fill=fill, font=typeface)
        box = canvas.draw.textbbox((x, y), word, font=typeface)
        canvas.record("warning", (int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        x += length + space
    return y + line_height
