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
from maniml.mobject.mobject import Mobject
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


# ---------------------------------------------------------------------------
# The ledger itself, driven through a real headless scene.

import tempfile
import textwrap

from maniml.__main__ import load_scene_module
from maniml.scene.checkpoints import CheckpointLedger
from maniml.scene.checkpoints import LedgerStale
from maniml.scene.checkpoints import deepcopy_namespace

LEDGER_SCENE = textwrap.dedent('''\
    from maniml import *

    class LedgerScene(Scene):
        def construct(self):
            anchor = Square().shift(LEFT * 3)
            group = VGroup(Circle(), Circle().shift(RIGHT))
            tracker = ValueTracker(1.0)
            live = Dot()
            live.add_updater(lambda m: None)
            self.add(anchor, group, live)
            self.play(FadeIn(group), run_time=0.05)                     # checkpoint 1
            group[0].shift(UP)
            self.play(group.animate.shift(RIGHT * 0.1), run_time=0.05)  # checkpoint 2
            anchor.set_z_index(3)
            tracker.set_value(2.0)
            self.play(FadeIn(Dot()), run_time=0.05)                     # checkpoint 3
            self.play(FadeIn(Dot()), run_time=0.05)                     # checkpoint 4
            group.target.shift(OUT)
            self.play(FadeIn(Dot()), run_time=0.05)                     # checkpoint 5
            self.wait(0.05)
''')


class LedgerSceneTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.scene_file = os.path.join(self.tmpdir.name, 'ledger_scene.py')
        with open(self.scene_file, 'w') as f:
            f.write(LEDGER_SCENE)
        module = load_scene_module(self.scene_file)
        self.scene = module.LedgerScene(window=None)
        self.scene._scene_filepath = self.scene_file
        self.scene.skip_animations = True
        self.scene.setup()
        self.scene._create_checkpoint_zero()

    def tearDown(self):
        self.scene.camera.ctx.release()
        self.tmpdir.cleanup()

    def run_to(self, index):
        while self.scene.current_animation_index < index:
            before = self.scene.current_animation_index
            self.scene.run_next_animation()
            if self.scene.current_animation_index == before:
                break

    def cp(self, index, name):
        return self.scene.animation_checkpoints[index]['namespace'][name]


class LedgerReuse(LedgerSceneTest):
    def test_an_untouched_mobject_is_the_same_object_in_consecutive_checkpoints(self):
        self.run_to(2)
        self.assertIs(self.cp(1, 'anchor'), self.cp(2, 'anchor'))
        state2 = self.scene.animation_checkpoints[2]['state']
        self.assertTrue(any(m is self.cp(2, 'anchor') for m in state2.mobjects),
                        "the state list and the namespace variable must alias the same frozen copy")

    def test_a_moved_family_gets_a_fresh_copy_and_history_keeps_the_old_one(self):
        self.run_to(2)
        g1, g2 = self.cp(1, 'group'), self.cp(2, 'group')
        self.assertIsNot(g1, g2)
        self.assertIsNot(g1.submobjects[0], g2.submobjects[0])
        self.assertLess(g1.submobjects[0].get_center()[1], g2.submobjects[0].get_center()[1] - 0.5)

    def test_state_changes_without_data_changes_force_fresh_copies(self):
        self.run_to(3)
        self.assertIsNot(self.cp(2, 'anchor'), self.cp(3, 'anchor'), "z_index changed")
        self.assertEqual(self.cp(3, 'anchor').z_index, 3)
        self.assertIsNot(self.cp(2, 'tracker'), self.cp(3, 'tracker'), "tracker value changed")
        self.assertEqual(self.cp(3, 'tracker').get_value(), 2.0)
        self.assertEqual(self.cp(2, 'tracker').get_value(), 1.0)

    def test_a_mobject_with_an_updater_is_never_shared(self):
        self.run_to(4)
        self.assertIsNot(self.cp(3, 'live'), self.cp(4, 'live'))

    def test_an_animated_mobject_is_shared_again_once_it_rests(self):
        # .animate leaves a target behind; the target is followed as a
        # reference, not treated as a reason to copy forever
        self.run_to(4)
        self.assertIsNotNone(self.cp(4, 'group').target)
        self.assertIs(self.cp(3, 'group'), self.cp(4, 'group'))

    def test_editing_a_target_between_plays_forces_a_fresh_copy(self):
        # the scene shifts group.target between plays 4 and 5; the group's
        # own revision is untouched, so only the reference walk can see it
        self.run_to(5)
        self.assertIs(self.cp(3, 'group'), self.cp(4, 'group'))
        self.assertIsNot(self.cp(4, 'group'), self.cp(5, 'group'))
        self.assertIsNot(self.cp(4, 'group').target, self.cp(5, 'group').target)
        self.assertEqual(self.cp(4, 'group').target.get_center()[2], 0)
        self.assertEqual(self.cp(5, 'group').target.get_center()[2], 1)

    def test_the_unchanged_survive_a_play_that_touched_nothing_of_theirs(self):
        self.run_to(4)
        self.assertIs(self.cp(3, 'anchor'), self.cp(4, 'anchor'))
        self.assertIs(self.cp(3, 'group'), self.cp(4, 'group'))
        self.assertIs(self.cp(3, 'tracker'), self.cp(4, 'tracker'))

    def test_frozen_copies_are_read_only(self):
        self.run_to(1)
        frozen = self.cp(1, 'anchor')
        with self.assertRaises(ValueError):
            frozen.data["point"][0] = 0
        with self.assertRaises(ValueError):
            self.cp(1, 'tracker').uniforms["value"][:] = 5

    def test_frozen_graphs_carry_no_parent_links_and_thaw_rebuilds_them(self):
        self.run_to(2)
        frozen_group = self.cp(2, 'group')
        self.assertEqual(frozen_group.submobjects[0].parents, [])
        self.scene._restore_checkpoint_for_display(2)
        group = self.scene._live_namespace['group']
        child = group.submobjects[0]
        self.assertEqual(child.parents, [group])
        self.assertTrue(any(m is group for m in self.scene.mobjects))
        before = group.revision
        top_before = group.get_top()[1]
        child.shift(np.array([0, 5.0, 0]))
        self.assertGreater(group.revision, before, "a thawed child no longer reaches its parent")
        self.assertGreater(group.get_top()[1], top_before + 4)

    def test_the_play_after_a_step_back_reuses_what_it_did_not_touch(self):
        self.run_to(2)
        old_anchor = self.cp(2, 'anchor')
        self.scene._restore_checkpoint_for_display(1)
        self.scene.run_next_animation()            # re-makes checkpoint 2
        self.assertEqual(self.scene.current_animation_index, 2)
        self.assertIs(self.cp(2, 'anchor'), old_anchor)
        self.assertIs(self.cp(2, 'anchor'), self.cp(1, 'anchor'))

    def test_history_holds_objects_plus_changes_not_objects_times_checkpoints(self):
        import gc
        self.run_to(4)
        per_checkpoint = []
        distinct = set()
        for index in range(1, 5):
            ns = self.scene.animation_checkpoints[index]['namespace']
            ids = set()
            for value in ns.values():
                if isinstance(value, Mobject):
                    ids.update(id(m) for m in value.get_family())
            per_checkpoint.append(len(ids))
            distinct |= ids
        self.assertLess(len(distinct), sum(per_checkpoint) * 0.6,
                        f"frozen mobjects per checkpoint {per_checkpoint}, distinct {len(distinct)}")
        gc.collect()   # mobject graphs are cyclic; entries die with their live object
        from maniml.scene.checkpoints import _closure
        live_mobjects = set()
        tops = [v for v in self.scene._live_namespace.values() if isinstance(v, Mobject)]
        for top in (*tops, *self.scene.mobjects):
            live_mobjects.update(id(m) for m in _closure(top, None))
        # The previous unit's thawed generation can linger a while in
        # render caches (shader wrappers) and the old exec namespace; the
        # ledger must never hold more than that
        entries = self.scene.checkpoint_ledger.entries
        self.assertLessEqual(len(entries), 2 * len(live_mobjects) + 4,
                             "entries outliving their live mobjects")


class VerifyModeCatchesABypass(unittest.TestCase):
    def test_a_clean_reuse_is_silent_under_verify(self):
        import svgelements as se
        from maniml.mobject.svg.svg_mobject import VMobjectFromSVGPath
        from maniml.mobject.geometry import Arrow
        ledger = CheckpointLedger()
        group = VGroup(Square().set_color("#ff0000"), Circle(), Arrow())
        group.generate_target()
        glyph = VMobjectFromSVGPath(se.Path("M 0 0 L 1 0 L 1 1 Z"))
        ns = {'group': group, 'glyph': glyph, 'tracker': ValueTracker(2.0), 'dots': [DotCloud(), Square()]}
        first = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        old = os.environ.get("MANIML_VERIFY_LEDGER")
        os.environ["MANIML_VERIFY_LEDGER"] = "1"
        try:
            second = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        finally:
            if old is None:
                os.environ.pop("MANIML_VERIFY_LEDGER", None)
            else:
                os.environ["MANIML_VERIFY_LEDGER"] = old
        for name in ('group', 'glyph', 'tracker'):
            self.assertIs(first[name], second[name], name)
        self.assertIs(first['dots'][0], second['dots'][0])
        self.assertIs(first['group'].target, second['group'].target)

    def test_a_mobject_reached_through_a_nested_container_is_followed(self):
        # Table keeps mob_table, a list of lists of its entries; an entry
        # that changes after leaving the family must still spoil the reuse
        ledger = CheckpointLedger()
        entry = Square()
        table = VGroup(entry)
        table.mob_table = [[entry], [Circle()]]
        ns = {'table': table}
        first = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        table.remove(entry)          # bumps the table; the entry stays in mob_table
        second = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        entry.shift(np.array([1.0, 0, 0]))   # bumps only the entry now
        third = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        self.assertIsNot(second['table'], third['table'])
        self.assertIsNot(second['table'].mob_table[0][0], third['table'].mob_table[0][0])
        self.assertEqual(third['table'].mob_table[0][0].get_center()[0], 1.0)

    def test_an_attribute_added_without_a_bump_forces_a_fresh_copy(self):
        ledger = CheckpointLedger()
        group = VGroup(Square())
        ns = {'group': group}
        first = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        group.label = Circle()      # plain attribute write: no revision bump
        second = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        self.assertIsNot(first['group'], second['group'])
        self.assertIsInstance(second['group'].label, Circle)

    def test_a_raw_write_without_a_bump_raises_at_the_next_save(self):
        ledger = CheckpointLedger()
        anchor = Square()
        ns = {'anchor': anchor}
        deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        anchor.data["point"][0] += 1        # bypasses every mutator: no bump
        old = os.environ.get("MANIML_VERIFY_LEDGER")
        os.environ["MANIML_VERIFY_LEDGER"] = "1"
        try:
            with self.assertRaises(LedgerStale) as caught:
                deepcopy_namespace(ns, ledger=ledger, mode="freeze")
            self.assertIn("data.point", str(caught.exception))
        finally:
            if old is None:
                os.environ.pop("MANIML_VERIFY_LEDGER", None)
            else:
                os.environ["MANIML_VERIFY_LEDGER"] = old
        # Without verify mode the stale copy would have been reused silently;
        # with the bump it is copied afresh either way.
        anchor.note_changed_data()
        copied = deepcopy_namespace(ns, ledger=ledger, mode="freeze")
        self.assertTrue(np.array_equal(copied['anchor'].get_points(), anchor.get_points()))


class FrontierSkipsTheThaw(LedgerSceneTest):
    def test_stepping_forward_keeps_the_live_objects(self):
        self.run_to(2)
        anchor = self.scene._live_namespace['anchor']
        self.assertTrue(any(m is anchor for m in self.scene.mobjects))
        self.scene.run_next_animation()
        self.assertEqual(self.scene.current_animation_index, 3)
        self.assertIs(self.scene._live_namespace['anchor'], anchor)
        self.assertTrue(any(m is anchor for m in self.scene.mobjects))
        self.assertEqual(anchor.z_index, 3, "the unit ran against the live objects")

    def test_a_navigation_makes_the_next_step_thaw_again(self):
        self.run_to(3)
        self.scene._restore_checkpoint_for_display(1)
        shown = self.scene._live_namespace['anchor']
        self.assertFalse(self.scene._live_is_checkpoint(1))
        self.scene.run_next_animation()
        self.assertEqual(self.scene.current_animation_index, 2)
        self.assertIsNot(self.scene._live_namespace['anchor'], shown)
        self.assertTrue(self.scene._live_is_checkpoint(2))
        # the frozen history is untouched by either route
        self.assertIs(self.cp(1, 'anchor'), self.cp(2, 'anchor'))

    def test_an_exec_error_falls_back_to_a_thaw(self):
        self.run_to(2)
        live_anchor = self.scene._live_namespace['anchor']
        with open(self.scene_file, 'a') as f:
            pass
        # make the next unit fail: poison the live namespace's Dot
        self.scene._live_namespace['Dot'] = lambda *a, **k: (_ for _ in ()).throw(ValueError('boom'))
        self.scene.run_next_animation()
        self.assertEqual(self.scene.current_animation_index, 2)
        self.assertFalse(self.scene._live_is_checkpoint(2))
        self.assertTrue(all(m is not live_anchor for m in self.scene.mobjects),
                        "after a failed unit the screen shows a thawed copy of the checkpoint")
