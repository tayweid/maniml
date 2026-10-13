"""TransformMatchingParts: what matches transforms, what does not fades.

A retitle that changes one word (``Negative Externality`` to
``Negative Externality: DWL`` and back) must move only that word: the
matched glyphs transform in place, the unmatched ones fade in place, as
current ManimCE's default has it. Before 2026-10-11 the mismatches flew
to and from the other string's centre (ManimGL's FadeOutToPoint and
FadeInFromPoint), which made a one-word change look like the whole title
moving.

The titles are real Tex, so these tests need the template's compiler and
dvisvgm on PATH and skip without them (CI's runners have neither), as the
real-TeX quality fixtures do: no substitute glyph stands in.
"""

from __future__ import annotations

import shutil
import unittest

import numpy as np

from maniml import (
    LEFT, UP, FadeIn, FadeOut, FadeTransformPieces, Scene, Tex, Transform,
    TransformMatchingShapes, TransformMatchingTex,
)
from maniml.utils.tex_file_writing import get_tex_config

MISSING_TEX_TOOLS = [tool for tool in (get_tex_config()[0], "dvisvgm")
                     if shutil.which(tool) is None]


def title(text):
    return Tex(text).scale(0.9).to_edge(UP, buff=0.4).to_edge(LEFT, buff=0.6)


@unittest.skipIf(MISSING_TEX_TOOLS, "Tex needs " + ", ".join(MISSING_TEX_TOOLS) + " on PATH")
class MatchingTests(unittest.TestCase):
    def test_one_word_change_fades_only_that_word(self):
        old, new = title('Negative Externality'), title('Negative Externality: DWL')
        anim = TransformMatchingTex(old, new)
        kinds = [(type(a).__name__, len(a.mobject.family_members_with_points()))
                 for a in anim.anims]
        self.assertEqual(kinds, [("Transform", 19), ("FadeIn", 4)])
        transform = anim.anims[0]
        self.assertLess(
            np.abs(transform.target_mobject.get_center() - transform.mobject.get_center()).max(),
            0.02, "the matched glyphs stand still")
        back = TransformMatchingTex(new, old)
        self.assertEqual(
            [(type(a).__name__, len(a.mobject.family_members_with_points())) for a in back.anims],
            [("Transform", 19), ("FadeOut", 4)])

    def test_a_whole_word_swap_fades_both_ways(self):
        old, new = title('Negative Externality: Efficiency'), title('Negative Externality: DWL')
        anim = TransformMatchingTex(old, new)
        self.assertEqual(
            [(type(a).__name__, len(a.mobject.family_members_with_points())) for a in anim.anims],
            [("Transform", 20), ("FadeOut", 10), ("FadeIn", 3)])

    def test_mismatch_options_follow_ce(self):
        old, new = title('Negative Externality: Efficiency'), title('Negative Externality: DWL')
        anim = TransformMatchingTex(old, new, transform_mismatches=True)
        self.assertEqual([type(a) for a in anim.anims], [Transform, Transform])
        anim = TransformMatchingTex(old, new, fade_transform_mismatches=True)
        self.assertEqual([type(a) for a in anim.anims], [Transform, FadeTransformPieces])

    def test_shapes_match_without_strings(self):
        old, new = title('AB'), title('BA')
        anim = TransformMatchingShapes(old, new)
        # Both glyphs have a counterpart of the same shape: two transforms,
        # nothing to fade.
        self.assertEqual([type(a) for a in anim.anims], [Transform, Transform])
        self.assertFalse([a for a in anim.anims if isinstance(a, (FadeIn, FadeOut))])

    def test_the_play_leaves_the_target_on_screen(self):
        scene = Scene(window=None)
        old, new = title('Negative Externality'), title('Negative Externality: DWL')
        scene.add(old)
        scene.play(TransformMatchingTex(old, new), run_time=0.1)
        self.assertIn(new, scene.mobjects)
        self.assertNotIn(old, scene.mobjects)
        family = scene.get_mobject_family_members()
        self.assertTrue(all(glyph in family for glyph in new.family_members_with_points()))
        self.assertFalse(any(glyph in family for glyph in old.family_members_with_points()))


if __name__ == "__main__":
    unittest.main()
