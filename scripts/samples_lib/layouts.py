"""Three label layouts. Each draws a LabelSpec onto a fresh canvas and returns it.

They differ in typeface, alignment, decoration and where things sit, so the OCR and field
search are not tuned to one look.
"""

from collections.abc import Callable

from samples_lib.render import INK, Canvas, font, new_canvas, text_block, warning_block
from samples_lib.spec import LabelSpec, warning_text

WIDTH, HEIGHT = 1200, 1600


def _seed(spec: LabelSpec) -> int:
    return sum(ord(c) * (i + 1) for i, c in enumerate(spec.id))


def _warning(
    canvas: Canvas, spec: LabelSpec, top: int, regular: str, bold: str, **kw: object
) -> None:
    text = warning_text(spec.warning_variant)
    if text is None:
        return
    bold_prefix = spec.warning_variant != "prefix_not_bold"
    warning_block(
        canvas, text, top, size=spec.warning_size, regular=regular, bold=bold,
        bold_prefix=bold_prefix, **kw,  # type: ignore[arg-type]
    )  # fmt: skip


def spirits(spec: LabelSpec) -> Canvas:
    """Framed, centred, sans serif: brand at the top, warning boxed at the bottom."""
    canvas = new_canvas(WIDTH, HEIGHT, spec.background, _seed(spec))
    text = spec.label_text
    canvas.draw.rectangle((40, 40, WIDTH - 40, HEIGHT - 40), outline=INK, width=4)
    y = text_block(canvas, "brand", text.brand, font("DejaVuSans-Bold", 92), 110, left=90)
    canvas.draw.line((300, y + 10, WIDTH - 300, y + 10), fill=INK, width=3)
    y = text_block(canvas, "class_type", text.class_type, font("DejaVuSans", 50), y + 50, left=90)
    y = text_block(canvas, "alcohol", text.alcohol, font("DejaVuSans", 46), y + 40, left=90)
    y = text_block(canvas, "net", text.net, font("DejaVuSans-Bold", 46), y + 30, left=90)
    for line in text.extra:
        y = text_block(canvas, "extra", line, font("DejaVuSans", 30), y + 30, left=90)
    _warning(canvas, spec, max(y + 70, 1080), "DejaVuSans", "DejaVuSans-Bold", left=90)
    return canvas


def beer(spec: LabelSpec) -> Canvas:
    """A coloured band holding the brand, big style name, ABV and volume side by side."""
    canvas = new_canvas(WIDTH, HEIGHT, spec.background, _seed(spec))
    text = spec.label_text
    canvas.draw.rectangle((0, 90, WIDTH, 330), fill=(232, 200, 140))
    text_block(canvas, "brand", text.brand, font("DejaVuSansMono-Bold", 74), 160, left=60)
    style = font("DejaVuSans-Bold", 110)
    y = text_block(canvas, "class_type", text.class_type, style, 430, left=60)
    small = font("DejaVuSansMono", 48)
    text_block(canvas, "alcohol", text.alcohol, small, y + 80, left=80, align="left", width=500)
    text_block(canvas, "net", text.net, small, y + 80, left=720, align="left", width=420)
    y += 80 + 48 * 2
    for line in text.extra:
        y = text_block(canvas, "extra", line, font("DejaVuSans", 30), y + 20, left=80)
    _warning(canvas, spec, max(y + 80, 1120), "DejaVuSans", "DejaVuSans-Bold", left=80)
    return canvas


def wine(spec: LabelSpec) -> Canvas:
    """Serif, centred and airy, with a double rule and small caps-style details."""
    canvas = new_canvas(WIDTH, HEIGHT, spec.background, _seed(spec))
    text = spec.label_text
    canvas.draw.rectangle((70, 70, WIDTH - 70, HEIGHT - 70), outline=(110, 30, 40), width=3)
    canvas.draw.rectangle((84, 84, WIDTH - 84, HEIGHT - 84), outline=(110, 30, 40), width=1)
    vintage, *details = text.extra or ("",)
    y = text_block(canvas, "extra", vintage, font("DejaVuSerif", 44), 150, left=120)
    y = text_block(canvas, "brand", text.brand, font("DejaVuSerif-Bold", 80), y + 40, left=120)
    y = text_block(canvas, "class_type", text.class_type, font("DejaVuSerif", 62), y + 50, left=120)
    for line in details:
        y = text_block(canvas, "extra", line, font("DejaVuSerif", 34), y + 30, left=120)
    y = text_block(canvas, "alcohol", text.alcohol, font("DejaVuSerif", 40), y + 60, left=120)
    y = text_block(canvas, "net", text.net, font("DejaVuSerif", 40), y + 10, left=120)
    _warning(canvas, spec, max(y + 70, 1100), "DejaVuSerif", "DejaVuSerif-Bold", left=120)
    return canvas


LAYOUTS: dict[str, Callable[[LabelSpec], Canvas]] = {
    "spirits": spirits,
    "beer": beer,
    "wine": wine,
}
