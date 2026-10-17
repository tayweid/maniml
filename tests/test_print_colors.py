"""The print stills' colours (``--print``, maniml/utils/print_colors.py):
what was light on the dark background reads dark on a white page."""

import unittest

import numpy as np

from maniml.utils.print_colors import (
    MIN_CONTRAST,
    PRINT_LIGHTNESS,
    SEEN_LIGHTNESS,
    contrast_on_white,
    for_white_paper,
    map_colors,
    srgb_to_oklab,
)


def hexes(*codes):
    return np.array([[int(code[i:i + 2], 16) / 255 for i in (1, 3, 5)] for code in codes])


def hue(lab):
    return np.degrees(np.arctan2(lab[..., 2], lab[..., 1])) % 360


class MapColorsTest(unittest.TestCase):
    def test_greys_turn_over(self):
        white, black, grey = map_colors(hexes("#FFFFFF", "#000000", "#888888"))
        np.testing.assert_allclose(white, [0, 0, 0], atol=1e-3)
        np.testing.assert_allclose(black, [1, 1, 1], atol=1e-3)
        # A light grey on the dark page is a dark grey on the white one.
        self.assertLess(grey.max(), 0.4)
        self.assertLess(np.ptp(grey), 1e-3)

    def test_a_colour_keeps_its_hue_and_reads_on_white(self):
        palette = hexes("#58C4DD", "#FFFF00", "#FC6255", "#83C167", "#F0AC5F")
        before = srgb_to_oklab(palette)
        after = srgb_to_oklab(map_colors(palette))
        self.assertTrue(np.all(after[:, 0] <= PRINT_LIGHTNESS + 1e-3), after[:, 0])
        np.testing.assert_allclose(hue(after), hue(before), atol=2.0)

    def test_a_dark_colour_is_left_as_it_is(self):
        dark_blue = hexes("#2255AA")
        np.testing.assert_allclose(map_colors(dark_blue), dark_blue, atol=1e-3)

    def test_whatever_was_seen_on_screen_reads_at_aa_on_white(self):
        """WCAG 2 AA for text, 4.5:1 against the page, for every colour
        that was meant to be seen on the dark one, measured on the
        eight-bit colour the PNG holds (Taylor, 2026-10-17)."""
        rng = np.random.default_rng(11)
        colours = np.vstack([rng.random((5000, 3)), hexes(
            "#FFFFFF", "#58C4DD", "#FFFF00", "#F7D96F", "#83C167", "#FC6255",
            "#5CD0B3", "#F0AC5F", "#9A72AC", "#FF862F", "#D147BD")])
        seen = srgb_to_oklab(colours)[:, 0] >= SEEN_LIGHTNESS
        printed = np.rint(map_colors(colours) * 255) / 255
        self.assertGreaterEqual(contrast_on_white(printed[seen]).min(), MIN_CONTRAST)

    def test_every_colour_is_one_srgb_can_show(self):
        rng = np.random.default_rng(7)
        mapped = map_colors(rng.random((500, 3)))
        self.assertTrue(np.all((mapped >= 0) & (mapped <= 1)))


class ForWhitePaperTest(unittest.TestCase):
    def test_alpha_and_the_clear_background_are_untouched(self):
        from PIL import Image

        pixels = np.zeros((4, 4, 4), dtype=np.uint8)
        pixels[1, 1] = [255, 255, 255, 255]   # white text
        pixels[2, 2] = [255, 255, 255, 96]    # its antialiased edge
        image = for_white_paper(Image.fromarray(pixels, "RGBA"))
        out = np.asarray(image)
        self.assertEqual(image.mode, "RGBA")
        np.testing.assert_array_equal(out[..., 3], pixels[..., 3])
        np.testing.assert_array_equal(out[0, 0], [0, 0, 0, 0])
        np.testing.assert_array_equal(out[1, 1], [0, 0, 0, 255])
        np.testing.assert_array_equal(out[2, 2], [0, 0, 0, 96])


if __name__ == "__main__":
    unittest.main()
