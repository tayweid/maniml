"""Colours for a white page: the print stills (``--print``).

A scene is drawn for a dark background, so its colours are light: white
text, pale blue and yellow strokes. Laid on a white page they vanish. The
print stills keep the picture and move each colour to where it reads on
white, in OKLab (perceptual lightness L, chroma C, hue h):

- a neutral colour turns over: white becomes black, a light grey a dark
  one, so text and axes keep their contrast, the other way round;
- a colour keeps its hue and is darkened to at most ``PRINT_LIGHTNESS``,
  so a blue stays blue and a yellow becomes an olive that a printer can
  hold, its chroma cut only as far as sRGB requires.

Between the two, a colour is mixed by how colourful it is
(``NEUTRAL_CHROMA``), so a near-white pastel goes dark as white does and
there is no seam between a grey and a dusty blue.

Then a floor (Taylor, 2026-10-17: "every colour passes 4.5:1"): a colour
that was meant to be seen on the dark page (OKLab L at least
``SEEN_LIGHTNESS`` there) ends at least ``MIN_CONTRAST`` against white by
WCAG's own measure, darkened further where the cap alone falls short (a
lightness cap is not a luminance cap: hues differ). A colour that was dark
on the dark page — a faint grid, a black mask — keeps its mirror, faint on
white as it was faint on black. Alpha is untouched: the
page shows through where the background did. Each distinct colour of an
image is mapped once, which keeps a full-HD still to a few hundred
milliseconds.
"""
from __future__ import annotations

import numpy as np

# The lightest a colour may be on paper: OKLab L 0.55 gives manim's palette
# 4.6:1 and more against white.
PRINT_LIGHTNESS = 0.55
# The chroma at which a colour counts as a colour rather than a grey.
NEUTRAL_CHROMA = 0.06
# WCAG 2's AA contrast for normal-size text, against the white page...
MIN_CONTRAST = 4.5
# ...held for every colour at least this light on the dark page.
SEEN_LIGHTNESS = 0.5

_LMS_FROM_LINEAR = np.array([
    [0.4122214708, 0.5363325363, 0.0514459929],
    [0.2119034982, 0.6806995451, 0.1073969566],
    [0.0883024619, 0.2817188376, 0.6299787005],
])
_LAB_FROM_LMS = np.array([
    [0.2104542553, 0.7936177850, -0.0040720468],
    [1.9779984951, -2.4285922050, 0.4505937099],
    [0.0259040371, 0.7827717662, -0.8086757660],
])
_LMS_FROM_LAB = np.linalg.inv(_LAB_FROM_LMS)
_LINEAR_FROM_LMS = np.linalg.inv(_LMS_FROM_LINEAR)


def _to_linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)


def _to_srgb(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    return np.where(linear <= 0.0031308, linear * 12.92,
                    1.055 * linear ** (1 / 2.4) - 0.055)


def srgb_to_oklab(srgb: np.ndarray) -> np.ndarray:
    """(..., 3) sRGB in [0, 1] to (..., 3) OKLab."""
    lms = _to_linear(srgb) @ _LMS_FROM_LINEAR.T
    return np.cbrt(lms) @ _LAB_FROM_LMS.T


def _oklab_to_linear(lab: np.ndarray) -> np.ndarray:
    return ((lab @ _LMS_FROM_LAB.T) ** 3) @ _LINEAR_FROM_LMS.T


def oklab_to_srgb(lab: np.ndarray) -> np.ndarray:
    """(..., 3) OKLab to (..., 3) sRGB in [0, 1], clipped."""
    return _to_srgb(_oklab_to_linear(lab))


def _in_gamut(lab: np.ndarray) -> np.ndarray:
    linear = _oklab_to_linear(lab)
    return np.all((linear >= -1e-6) & (linear <= 1 + 1e-6), axis=-1)


def contrast_on_white(srgb: np.ndarray) -> np.ndarray:
    """WCAG 2's contrast ratio of (..., 3) sRGB colours against white."""
    luminance = _to_linear(np.clip(srgb, 0.0, 1.0)) @ np.array([0.2126, 0.7152, 0.0722])
    return 1.05 / (luminance + 0.05)


def _fit_chroma(target: np.ndarray) -> np.ndarray:
    """Cut each colour's chroma, hue held, until sRGB can show it."""
    target = target.copy()
    fits = _in_gamut(target)
    if fits.all():
        return target
    low = np.zeros(len(target))
    high = np.ones(len(target))
    for _ in range(16):
        middle = (low + high) / 2
        trial = target.copy()
        trial[:, 1:] *= middle[:, None]
        ok = _in_gamut(trial)
        low = np.where(ok, middle, low)
        high = np.where(ok, high, middle)
    scale = np.where(fits, 1.0, low)
    target[:, 1:] *= scale[:, None]
    return target


def _rendered(lab: np.ndarray) -> np.ndarray:
    """What the PNG will hold: sRGB rounded to eight bits."""
    return np.rint(oklab_to_srgb(lab) * 255.0) / 255.0


def map_colors(srgb: np.ndarray) -> np.ndarray:
    """(N, 3) sRGB in [0, 1], drawn for a dark background, to the colours
    that read the same way on a white page (the module's rule)."""
    lab = srgb_to_oklab(srgb)
    lightness = lab[:, 0]
    ab = lab[:, 1:]
    chroma = np.hypot(ab[:, 0], ab[:, 1])
    colourful = np.clip(chroma / NEUTRAL_CHROMA, 0.0, 1.0)
    turned = 1.0 - lightness
    darkened = np.minimum(lightness, PRINT_LIGHTNESS)
    target = np.empty_like(lab)
    target[:, 0] = colourful * darkened + (1.0 - colourful) * turned
    # A grey keeps no hue to speak of; a colour keeps its own. Chroma is
    # scaled with the mix so a turned grey does not pick up a tint.
    target[:, 1:] = ab * colourful[:, None]
    target = _fit_chroma(target)
    # The floor: darken what was meant to be seen until it reads at
    # MIN_CONTRAST, judged on the eight-bit colour the still will hold.
    seen = lightness >= SEEN_LIGHTNESS
    short = seen & (contrast_on_white(_rendered(target)) < MIN_CONTRAST)
    if short.any():
        rows = np.flatnonzero(short)
        hue_ab = ab[rows] * colourful[rows, None]
        low = np.zeros(len(rows))            # dark enough (black passes)
        high = target[rows, 0].copy()        # not dark enough
        for _ in range(20):
            middle = (low + high) / 2
            trial = np.column_stack([middle, hue_ab])
            trial = _fit_chroma(trial)
            ok = contrast_on_white(_rendered(trial)) >= MIN_CONTRAST
            low = np.where(ok, low, middle)
            high = np.where(ok, middle, high)
        trial = _fit_chroma(np.column_stack([high, hue_ab]))
        passes = contrast_on_white(_rendered(trial)) >= MIN_CONTRAST
        # A last step down for any the search left on the line.
        trial[~passes, 0] = np.maximum(trial[~passes, 0] - 0.01, 0.0)
        target[rows] = _fit_chroma(trial)
    return oklab_to_srgb(target)


def for_white_paper(image):
    """A straight-alpha RGBA PIL image (a transparent still) with its
    colours moved for a white page; alpha as it was."""
    from PIL import Image

    pixels = np.asarray(image.convert("RGBA")).copy()
    alpha = pixels[..., 3]
    drawn = alpha > 0
    if not drawn.any():
        return Image.fromarray(pixels, "RGBA")
    colours, inverse = np.unique(pixels[drawn][:, :3], axis=0, return_inverse=True)
    mapped = map_colors(colours.astype(np.float64) / 255.0)
    mapped = np.rint(mapped * 255.0).astype(np.uint8)
    pixels[..., :3][drawn] = mapped[inverse.reshape(-1)]
    return Image.fromarray(pixels, "RGBA")
