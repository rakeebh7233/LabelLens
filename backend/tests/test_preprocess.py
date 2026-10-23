import numpy as np
import pytest

from app.ocr import preprocess
from app.ocr.preprocess import ImageDecodeError
from tests.label_images import encode_png, render_label, rotated, with_glare

CLEAN = render_label()
CLEAN_GRAY = preprocess.to_grayscale(CLEAN)


# decode_image


def test_decode_image_reads_png_bytes() -> None:
    image = preprocess.decode_image(encode_png(CLEAN))
    assert image.shape == CLEAN.shape


@pytest.mark.parametrize("data", [b"", b"not an image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50])
def test_decode_image_rejects_non_images(data: bytes) -> None:
    with pytest.raises(ImageDecodeError, match="could not be read as an image"):
        preprocess.decode_image(data)


# resize_to_max_edge


@pytest.mark.parametrize(
    ("shape", "expected"),
    [
        ((3000, 4000, 3), (1200, 1600, 3)),
        ((4000, 3000, 3), (1600, 1200, 3)),
        ((1600, 1000, 3), (1600, 1000, 3)),
        # Small images are never upscaled.
        ((400, 300, 3), (400, 300, 3)),
    ],
)
def test_resize_to_max_edge(shape: tuple[int, int, int], expected: tuple[int, int, int]) -> None:
    assert preprocess.resize_to_max_edge(np.zeros(shape, np.uint8), 1600).shape == expected


# to_grayscale / enhance_contrast


def test_to_grayscale_is_2d_and_idempotent() -> None:
    assert CLEAN_GRAY.ndim == 2
    assert preprocess.to_grayscale(CLEAN_GRAY) is CLEAN_GRAY


def test_enhance_contrast_stretches_a_flat_image() -> None:
    faded = (CLEAN_GRAY // 4 + 120).astype(np.uint8)
    boosted = preprocess.enhance_contrast(faded)
    assert np.ptp(boosted) > np.ptp(faded)


# estimate_skew: returns the angle that levels the text, so the opposite of the rotation


@pytest.mark.parametrize("degrees", [-12.0, -7.0, -3.0, 0.0, 2.0, 5.0, 10.0])
def test_estimate_skew(degrees: float) -> None:
    gray = preprocess.to_grayscale(rotated(CLEAN, degrees))
    assert preprocess.estimate_skew(gray) == pytest.approx(-degrees, abs=0.5)


def test_estimate_skew_on_blank_image_is_zero() -> None:
    assert preprocess.estimate_skew(np.full((500, 500), 255, np.uint8)) == 0.0


def test_test_helper_rotation_keeps_all_text_on_canvas() -> None:
    tilted = preprocess.to_grayscale(rotated(CLEAN, 10))
    border = np.concatenate([tilted[0], tilted[-1], tilted[:, 0], tilted[:, -1]])
    assert border.min() == 255


def test_rotate_grows_canvas_to_keep_corners() -> None:
    out = preprocess.rotate(CLEAN_GRAY, 10)
    assert out.shape[0] > CLEAN_GRAY.shape[0] and out.shape[1] > CLEAN_GRAY.shape[1]


# glare


def test_has_glare_ignores_a_plain_white_label() -> None:
    assert not preprocess.has_glare(CLEAN_GRAY)


def test_has_glare_finds_a_hotspot() -> None:
    assert preprocess.has_glare(preprocess.to_grayscale(with_glare(CLEAN)))


def test_flatten_illumination_evens_out_a_gradient() -> None:
    gradient = np.tile(np.linspace(80, 240, 600, dtype=np.float32), (400, 1)).astype(np.uint8)
    flat = preprocess.flatten_illumination(gradient)
    assert np.ptp(flat) < np.ptp(gradient) / 4


# basic / heavy


def test_basic_resizes_and_reports_steps() -> None:
    big = np.full((3200, 2400, 3), 255, np.uint8)
    result = preprocess.basic(big, 1600)
    assert result.image.ndim == 2
    assert max(result.image.shape) == 1600
    assert result.steps == ["resized to 1600px", "contrast boost"]


def test_basic_does_not_report_resize_when_not_needed() -> None:
    assert preprocess.basic(CLEAN, 1600).steps == ["contrast boost"]


def test_heavy_straightens_a_rotated_label() -> None:
    base = preprocess.basic(rotated(CLEAN, 10), 1600)
    result = preprocess.heavy(base.image)
    assert "straightened by 10.0°" in result.steps
    assert set(np.unique(result.image)) <= {0, 255}


def test_heavy_leaves_a_straight_label_unrotated() -> None:
    result = preprocess.heavy(preprocess.basic(CLEAN, 1600).image)
    assert not any(step.startswith("straightened") for step in result.steps)
    assert result.steps == ["lighting evened out", "converted to black and white"]


def test_heavy_reports_glare() -> None:
    result = preprocess.heavy(preprocess.basic(with_glare(CLEAN), 1600).image)
    assert result.steps[0] == "glare evened out"


def test_heavy_leaves_no_dark_outline_around_glare() -> None:
    """Regression: inpainting the hotspot used to leave a black ring through the text.

    Counts pixels that are black after processing the glare photo but white after processing
    the clean label. The old code produced 0.61% such pixels, the current code 0.04%.
    """

    def heavy(image: np.ndarray) -> np.ndarray:
        return preprocess.heavy(preprocess.basic(image, 1600).image).image

    spurious_ink = (heavy(with_glare(CLEAN)) == 0) & (heavy(CLEAN) == 255)
    assert spurious_ink.mean() < 0.002
