"""Image defects that imitate imperfect photos of a label. BGR numpy images in and out.

Deterministic: anything random takes a seed. The OCR unit tests (backend/tests) use the
first four functions too, so changing them changes those tests' inputs.
"""

import cv2
import numpy as np

Box = tuple[int, int, int, int]  # left, top, right, bottom


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


def glare_over(image: np.ndarray, box: Box) -> np.ndarray:
    """Blow out one region completely (pure white), as when glare hides a whole line."""
    left, top, right, bottom = box
    pad_x, pad_y = (right - left) // 6 + 20, (bottom - top) // 2 + 20
    centre = ((left + right) // 2, (top + bottom) // 2)
    axes = ((right - left) // 2 + pad_x, (bottom - top) // 2 + pad_y)
    mask = np.zeros(image.shape[:2], np.float32)
    cv2.ellipse(mask, centre, axes, 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), 12)
    mask = np.clip(mask * 1.6, 0, 1)  # solid white core, soft edge
    lit = image.astype(np.float32) * (1 - mask[..., None]) + 255 * mask[..., None]
    return lit.astype(np.uint8)


def perspective(image: np.ndarray, strength: float = 0.12) -> np.ndarray:
    """Photographed from the side: the right edge is further away and shorter."""
    height, width = image.shape[:2]
    inset = height * strength
    src = np.float32([[0, 0], [width, 0], [width, height], [0, height]])
    dst = np.float32([[0, 0], [width * 0.92, inset], [width * 0.92, height - inset], [0, height]])
    matrix = cv2.getPerspectiveTransform(src, dst)
    return cv2.warpPerspective(image, matrix, (width, height), borderValue=(255, 255, 255))


def low_light(image: np.ndarray, seed: int) -> np.ndarray:
    """Dark, low contrast, slightly out of focus, with sensor noise."""
    dark = image.astype(np.float32) * 0.45 + 25
    soft = cv2.GaussianBlur(dark, (0, 0), 1.4)
    noise = np.random.default_rng(seed).normal(0, 7, image.shape).astype(np.float32)
    return np.clip(soft + noise, 0, 255).astype(np.uint8)


def curved(image: np.ndarray, depth: float = 0.035) -> np.ndarray:
    """Text bent as on a round bottle: lines bow downward toward the edges."""
    height, width = image.shape[:2]
    xx, yy = np.meshgrid(np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32))
    offset = ((xx - width / 2) / (width / 2)) ** 2 * height * depth
    return cv2.remap(
        image, xx, yy - offset, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE
    )
