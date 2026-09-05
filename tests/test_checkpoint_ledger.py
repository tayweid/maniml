"""The checkpoint ledger's change signal.

Every mutation a checkpoint must see bumps ``Mobject.revision`` and the
revision of every ancestor; reads and lazily filled derived columns do
not. ``ledger_stale_attribute`` is the verify-mode comparison that
catches a mutation site the counter missed, by naming the attribute.
"""

import os
import unittest

import numpy as np

from maniml.mobject.geometry import Circle
from maniml.mobject.geometry import Square
from maniml.mobject.types.dot_cloud import DotCloud
from maniml.mobject.types.vectorized_mobject import VGroup
from maniml.mobject.value_tracker import ValueTracker
from maniml.scene.checkpoints import DERIVED_DATA_KEYS
from maniml.scene.checkpoints import ledger_stale_attribute
from maniml.scene.checkpoints import verify_ledger_enabled


class RevisionBumps(unittest.TestCase):
    def assertBumps(self, mob, action, what):
        before = mob.revision
        action(mob)
        self.assertGreater(mob.revision, before, f"{what} did not bump the revision")

    def assertKeeps(self, mob, action, what):
        before = mob.revision
        action(mob)
        self.assertEqual(mob.revision, before, f"{what} bumped the revision")

    def test_point_and_style_mutators_bump(self):
        cases = [
            ("shift", lambda m: m.shift(np.array([1.0, 0, 0]))),
            ("scale", lambda m: m.scale(2)),
            ("rotate", lambda m: m.rotate(0.3)),
            ("set_color", lambda m: m.set_color("#ff0000")),
            ("set_opacity", lambda m: m.set_opacity(0.5)),
            ("set_stroke", lambda m: m.set_stroke(width=8)),
            ("set_points", lambda m: m.set_points(m.get_points() * 2)),
            ("become", lambda m: m.become(Circle())),
            ("interpolate", lambda m: m.interpolate(Square(), Square().shift(np.array([1.0, 0, 0])), 0.5)),
        ]
        for what, action in cases:
            with self.subTest(what):
                self.assertBumps(Square(), action, what)

    def test_state_mutators_bump(self):
        cases = [
            ("set_uniform", lambda m: m.set_uniform(shading=np.array([0.1, 0.2, 0.3]))),
            ("fix_in_frame", lambda m: m.fix_in_frame()),
            ("apply_depth_test", lambda m: m.apply_depth_test()),
            ("set_clip_plane", lambda m: m.set_clip_plane(vect=np.array([0, 0, 1.0]), threshold=0.5)),
            ("add submobject", lambda m: m.add(Circle())),
            ("remove submobject", lambda m: m.remove(m.submobjects[0])),
            ("set_submobjects", lambda m: m.set_submobjects([Circle()])),
            ("add_updater", lambda m: m.add_updater(lambda mob: None)),
            ("remove_updater", lambda m: m.remove_updater(m.updaters[0])),
            ("clear_updaters", lambda m: m.clear_updaters()),
            ("suspend_updating", lambda m: m.suspend_updating()),
            ("resume_updating", lambda m: m.resume_updating()),
            ("set_z_index", lambda m: m.set_z_index(3)),
            ("z_index assignment", lambda m: setattr(m, "z_index", 4)),
            ("generate_target", lambda m: m.generate_target()),
            ("save_state", lambda m: m.save_state()),
            ("lock_data", lambda m: m.lock_data(["point"])),
            ("unlock_data", lambda m: m.unlock_data()),
        ]
        for what, action in cases:
            with self.subTest(what):
                mob = VGroup(Square())
                mob.add_updater(lambda m: None)
                if what in ("lock_data",):
                    mob.clear_updaters()   # lock_data is a no-op with updaters
                self.assertBumps(mob, action, what)

    def test_tracker_and_cloud_uniform_writes_bump(self):
        self.assertBumps(ValueTracker(1.0), lambda t: t.set_value(2.0), "ValueTracker.set_value")
        self.assertBumps(ValueTracker(1.0), lambda t: t.increment_value(1.0), "ValueTracker.increment_value")
        self.assertBumps(DotCloud(), lambda d: d.set_glow_factor(0.5), "DotCloud.set_glow_factor")
        self.assertBumps(Square(), lambda s: s.set_joint_type("bevel"), "VMobject.set_joint_type")

    def test_reads_and_derived_columns_do_not_bump(self):
        sq = Square()
        sq.get_joint_angles(refresh=True)   # settle the lazily filled columns
        sq.get_unit_normal(refresh=True)
        cases = [
            ("get_points", lambda m: m.get_points()),
            ("get_center", lambda m: m.get_center()),
            ("get_bounding_box", lambda m: m.get_bounding_box()),
            ("get_joint_angles(refresh)", lambda m: m.get_joint_angles(refresh=True)),
            ("get_unit_normal(refresh)", lambda m: m.get_unit_normal(refresh=True)),
            ("get_family", lambda m: m.get_family()),
            ("copy", lambda m: m.copy()),
            ("looks_identical", lambda m: m.looks_identical(Square())),
        ]
        for what, action in cases:
            with self.subTest(what):
                self.assertKeeps(sq, action, what)

    def test_a_change_below_bumps_every_ancestor(self):
        leaf = Square()
        middle = VGroup(leaf)
        top = VGroup(middle, Circle())
        before = (top.revision, middle.revision, leaf.revision)
        leaf.shift(np.array([1.0, 0, 0]))
        self.assertTrue(all(a > b for a, b in zip((top.revision, middle.revision, leaf.revision), before)))
        before = (top.revision, middle.revision)
        leaf.set_z_index(2)
        self.assertGreater(top.revision, before[0])
        self.assertGreater(middle.revision, before[1])

    def test_a_change_in_the_parent_leaves_the_child_alone(self):
        leaf = Square()
        top = VGroup(leaf)
        before = leaf.revision
        top.set_z_index(5)
        top.add(Circle())
        self.assertEqual(leaf.revision, before)


class CopyLess(unittest.TestCase):
    def test_a_glyph_copy_shares_its_svg_path_and_owns_its_points(self):
        import copy
        import svgelements as se
        from maniml.mobject.svg.svg_mobject import VMobjectFromSVGPath
        glyph = VMobjectFromSVGPath(se.Path("M 0 0 L 1 0 L 1 1 Z"))
        twin = copy.deepcopy(glyph)
        self.assertIs(twin.path_obj, glyph.path_obj)
        self.assertIsNot(twin.data, glyph.data)
        self.assertTrue(np.array_equal(twin.get_points(), glyph.get_points()))
        twin.shift(np.array([1.0, 0, 0]))
        self.assertFalse(np.array_equal(twin.get_points(), glyph.get_points()))

    def test_an_ordinary_deep_copy_still_owns_everything(self):
        import copy
        group = VGroup(Square(), Circle())
        twin = copy.deepcopy(group)
        for a, b in zip(group.get_family(), twin.get_family()):
            self.assertIsNot(a, b)
            self.assertIsNot(a.data, b.data)
            self.assertIsNot(a.uniforms, b.uniforms)
        self.assertIs(twin.submobjects[0].parents[0], twin)


class VerifyComparison(unittest.TestCase):
    def frozen_pair(self):
        live = VGroup(Square(), Circle())
        return live, live.deepcopy()

    def test_identical_copies_are_not_stale(self):
        live, frozen = self.frozen_pair()
        self.assertIsNone(ledger_stale_attribute(live, frozen))

    def test_a_raw_point_write_is_named(self):
        live, frozen = self.frozen_pair()
        live.submobjects[0].data["point"][0] += 1     # bypasses every mutator
        self.assertEqual(ledger_stale_attribute(live, frozen), "submobjects.data.point")
        self.assertEqual(ledger_stale_attribute(live.submobjects[0], frozen.submobjects[0]), "data.point")

    def test_a_derived_column_write_is_not_a_difference(self):
        live, frozen = self.frozen_pair()
        for key in DERIVED_DATA_KEYS:
            if key in live.submobjects[0].data.dtype.names:
                live.submobjects[0].data[key][:] = 0.123
        self.assertIsNone(ledger_stale_attribute(live, frozen))

    def test_uniforms_updaters_z_index_and_locks_are_named(self):
        tracker = ValueTracker(1.0)
        frozen = tracker.deepcopy()
        tracker.uniforms["value"][:] = 2.0
        self.assertEqual(ledger_stale_attribute(tracker, frozen), "uniforms.value")

        live, frozen = self.frozen_pair()
        live.updaters.append(lambda m: None)
        self.assertEqual(ledger_stale_attribute(live, frozen), "updaters")

        live, frozen = self.frozen_pair()
        live.z_index = 7
        self.assertEqual(ledger_stale_attribute(live, frozen), "_z_index")

        live, frozen = self.frozen_pair()
        live.locked_data_keys = {"point"}
        self.assertEqual(ledger_stale_attribute(live, frozen), "locked_data_keys")

        live, frozen = self.frozen_pair()
        live.submobjects.pop()
        self.assertEqual(ledger_stale_attribute(live, frozen), "submobjects")

    def test_render_only_state_is_ignored(self):
        live, frozen = self.frozen_pair()
        live._data_has_changed = not frozen._data_has_changed
        live._is_animating = True
        live.bounding_box = live.bounding_box + 1
        live.get_family()
        self.assertIsNone(ledger_stale_attribute(live, frozen))

    def test_memo_decides_submobject_identity_when_given(self):
        live, frozen = self.frozen_pair()
        memo = {id(sub): fsub for sub, fsub in zip(live.submobjects, frozen.submobjects)}
        self.assertIsNone(ledger_stale_attribute(live, frozen, memo))
        memo[id(live.submobjects[0])] = Square()
        self.assertEqual(ledger_stale_attribute(live, frozen, memo), "submobjects")

    def test_verify_mode_reads_the_environment(self):
        old = os.environ.pop("MANIML_VERIFY_LEDGER", None)
        try:
            self.assertFalse(verify_ledger_enabled())
            os.environ["MANIML_VERIFY_LEDGER"] = "1"
            self.assertTrue(verify_ledger_enabled())
        finally:
            os.environ.pop("MANIML_VERIFY_LEDGER", None)
            if old is not None:
                os.environ["MANIML_VERIFY_LEDGER"] = old


if __name__ == "__main__":
    unittest.main()
