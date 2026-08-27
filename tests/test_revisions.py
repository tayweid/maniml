import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from maniml.mobject.mobject import Mobject
from maniml.revisions import SEMANTIC_ID_ATTR
from maniml.revisions import ShadowRevisionStore
from maniml.revisions import _component_hashes
from maniml.revisions import semantic_id


def fake_scene(*mobjects):
    return SimpleNamespace(
        mobjects=list(mobjects),
        camera=SimpleNamespace(
            background_rgba=(0, 0, 0, 1),
            fps=30,
            pixel_width=1920,
            pixel_height=1080,
        ),
    )


class SemanticIdentityTests(unittest.TestCase):
    def test_public_copy_gets_fresh_identity_but_checkpoint_copy_keeps_it(self):
        child = Mobject()
        parent = Mobject().add(child)
        scene = fake_scene(parent)
        store = ShadowRevisionStore(enabled=True)
        store.prepare(scene)

        parent_id = semantic_id(parent)
        child_id = semantic_id(child)
        snapshot = copy.deepcopy(parent)
        authored_copy = parent.copy(deep=True)
        authored_deepcopy = parent.deepcopy()

        self.assertEqual(semantic_id(snapshot, assign=False), parent_id)
        self.assertEqual(
            semantic_id(snapshot.submobjects[0], assign=False), child_id)
        self.assertFalse(hasattr(authored_copy, SEMANTIC_ID_ATTR))
        self.assertFalse(
            hasattr(authored_copy.submobjects[0], SEMANTIC_ID_ATTR))
        self.assertFalse(hasattr(authored_deepcopy, SEMANTIC_ID_ATTR))
        self.assertFalse(
            hasattr(authored_deepcopy.submobjects[0], SEMANTIC_ID_ATTR))

        store.prepare(fake_scene(parent, authored_copy, authored_deepcopy))
        self.assertNotEqual(semantic_id(authored_copy), parent_id)
        self.assertNotEqual(
            semantic_id(authored_copy.submobjects[0]), child_id)
        self.assertNotEqual(semantic_id(authored_deepcopy), parent_id)
        self.assertNotEqual(
            semantic_id(authored_deepcopy.submobjects[0]), child_id)

    def test_become_keeps_the_receivers_identity(self):
        receiver = Mobject()
        donor = Mobject()
        store = ShadowRevisionStore(enabled=True)
        store.prepare(fake_scene(receiver, donor))
        receiver_id = semantic_id(receiver)

        receiver.become(donor)

        self.assertEqual(semantic_id(receiver), receiver_id)

    def test_renderer_derived_fields_do_not_create_semantic_changes(self):
        from maniml.mobject.types.vectorized_mobject import VMobject

        mobject = VMobject()
        mobject.data = np.zeros(1, dtype=mobject.data_dtype)
        before = _component_hashes(mobject)["geometry"]
        mobject.data["joint_angle"] = 0.75
        mobject.data["base_normal"] = (0, 0, 1)

        self.assertEqual(_component_hashes(mobject)["geometry"], before)


class ShadowRevisionTests(unittest.TestCase):
    def setUp(self):
        self.left = Mobject()
        self.right = Mobject()
        self.scene = fake_scene(self.left, self.right)
        self.store = ShadowRevisionStore(enabled=True)
        self.store.prepare(self.scene)

    def test_direct_array_mutation_changes_only_that_object(self):
        first = self.store.commit(self.scene, 0, reason="checkpoint_zero")
        quiet = self.store.commit(self.scene, 1, reason="play")
        self.left.data = self.left.data.copy()
        self.left.data.resize(1, refcheck=False)
        self.left.data["point"][0, 0] = 1
        changed = self.store.commit(self.scene, 2, reason="play")

        self.assertEqual(set(first.added), {
            semantic_id(self.left), semantic_id(self.right)})
        self.assertEqual(quiet.changed, {})
        self.assertEqual(
            set(changed.changed), {semantic_id(self.left)})
        self.assertIn("geometry", changed.changed[semantic_id(self.left)])
        self.assertEqual(changed.missed_hints, (semantic_id(self.left),))

    def test_builtin_mutation_hook_predicts_the_changed_object(self):
        self.left.data = np.zeros(1, dtype=self.left.data_dtype)
        self.right.data = np.zeros(1, dtype=self.right.data_dtype)
        self.store.commit(self.scene, 0, reason="checkpoint_zero")

        changed_data = self.left.data.copy()
        changed_data["point"][0, 0] = 2
        self.left.set_data(changed_data)
        record = self.store.commit(self.scene, 1, reason="play")

        self.assertEqual(set(record.changed), {semantic_id(self.left)})
        self.assertEqual(set(record.dirty_hints), {semantic_id(self.left)})
        self.assertEqual(record.missed_hints, ())
        self.assertEqual(
            [(ref.semantic_id, ref.component) for ref in record.resource_refs],
            [(semantic_id(self.left), "geometry")],
        )
        self.assertGreater(record.resource_refs[0].byte_size, 0)
        first_state = self.store._states_by_checkpoint[0]
        second_state = self.store._states_by_checkpoint[1]
        self.assertIsNot(
            first_state[semantic_id(self.left)],
            second_state[semantic_id(self.left)],
        )
        self.assertIs(
            first_state[semantic_id(self.right)],
            second_state[semantic_id(self.right)],
        )

    def test_style_is_separate_from_geometry(self):
        self.left.data = np.zeros(1, dtype=self.left.data_dtype)
        self.store.commit(self.scene, 0, reason="checkpoint_zero")

        self.left.set_color("#ff0000")
        record = self.store.commit(self.scene, 1, reason="play")

        self.assertEqual(
            record.changed[semantic_id(self.left)], ("style",))
        self.assertEqual(
            [ref.component for ref in record.resource_refs], ["style"])

    def test_texture_and_updater_configuration_have_components(self):
        self.store.commit(self.scene, 0, reason="checkpoint_zero")
        self.left.texture_paths = {"Texture": "/tmp/example.png"}
        self.right.add_updater(lambda mob: mob, call=False)

        record = self.store.commit(self.scene, 1, reason="play")

        self.assertEqual(
            record.changed[semantic_id(self.left)], ("texture",))
        self.assertEqual(
            record.changed[semantic_id(self.right)], ("updaters",))
        self.assertIn(semantic_id(self.left), record.missed_hints)
        self.assertNotIn(semantic_id(self.right), record.missed_hints)

    def test_add_remove_and_camera_change_are_explicit(self):
        first = self.store.commit(self.scene, 0, reason="checkpoint_zero")
        newcomer = Mobject()
        self.scene.mobjects.append(newcomer)
        self.scene.camera.background_rgba = (1, 1, 1, 1)
        self.store.prepare(self.scene)

        second = self.store.commit(self.scene, 1, reason="play")
        self.scene.mobjects.remove(self.right)
        third = self.store.commit(self.scene, 2, reason="play")

        self.assertTrue(first.camera_changed)
        self.assertTrue(second.camera_changed)
        self.assertEqual(second.added, (semantic_id(newcomer),))
        self.assertEqual(third.removed, (semantic_id(self.right),))
        self.assertFalse(third.camera_changed)

    def test_child_reorder_preserves_ids_and_changes_family(self):
        parent = Mobject().add(self.left, self.right)
        scene = fake_scene(parent)
        store = ShadowRevisionStore(enabled=True)
        store.prepare(scene)
        store.commit(scene, 0, reason="checkpoint_zero")
        child_ids = (semantic_id(self.left), semantic_id(self.right))

        parent.reverse_submobjects()
        record = store.commit(scene, 1, reason="play")

        self.assertEqual(
            (semantic_id(self.left), semantic_id(self.right)), child_ids)
        self.assertIn("family", record.changed[semantic_id(parent)])

    def test_scene_reorder_is_a_commit_without_fake_object_changes(self):
        self.store.commit(self.scene, 0, reason="checkpoint_zero")
        self.scene.mobjects.reverse()

        record = self.store.commit(self.scene, 1, reason="play")

        self.assertEqual(record.changed, {})
        self.assertEqual(record.scene_order, (
            semantic_id(self.right), semantic_id(self.left)))

    def test_checkpoint_deepcopy_preserves_shadow_endpoint_parity(self):
        record = self.store.commit(self.scene, 0, reason="checkpoint_zero")
        copied_state = SimpleNamespace(mobjects=copy.deepcopy(self.scene.mobjects))

        self.assertTrue(self.store.validate_checkpoint(copied_state, record))
        self.assertEqual(self.store.validation_failures, [])

    def test_checkpoint_validation_rejects_a_corrupt_resource(self):
        record = self.store.commit(self.scene, 0, reason="checkpoint_zero")
        resource_id = record.resource_refs[0].resource_id
        self.store.resources[resource_id] = b"corrupt"
        copied_state = SimpleNamespace(mobjects=copy.deepcopy(self.scene.mobjects))

        self.assertFalse(self.store.validate_checkpoint(copied_state, record))
        self.assertEqual(
            self.store.validation_failures[-1]["checkpoint"], 0)

    def test_suffix_replacement_keeps_one_lineage(self):
        self.store.commit(self.scene, 0, reason="checkpoint_zero")
        self.store.commit(self.scene, 1, reason="play")
        self.left.data = np.zeros(1, dtype=self.left.data_dtype)
        self.left.data["point"][0, 0] = 3
        suffix = self.store.commit(self.scene, 2, reason="play")
        suffix_resources = {
            ref.resource_id for ref in suffix.resource_refs if ref.new
        }

        self.left.data = np.zeros(0, dtype=self.left.data_dtype)
        self.store.commit(self.scene, 1, reason="edited_play")

        self.assertEqual(
            [record.checkpoint for record in self.store.commits], [0, 1])
        self.assertTrue(suffix_resources.isdisjoint(self.store.resources))

    def test_optional_json_is_compact_commit_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "shadow.json"
            store = ShadowRevisionStore(
                enabled=True, path=path, resource_budget_bytes=1)
            store.prepare(self.scene)
            store.commit(self.scene, 0, reason="checkpoint_zero")

            payload = json.loads(path.read_text())

        self.assertEqual(payload["format"], 1)
        self.assertEqual(len(payload["commits"]), 1)
        self.assertNotIn("components", payload["commits"][0])
        self.assertEqual(payload["resources"]["budget_bytes"], 1)
        self.assertGreater(payload["resources"]["over_budget_bytes"], 0)
        self.assertEqual(payload["history"]["checkpoints"], 1)

    def test_large_components_are_bounded_resource_chunks(self):
        store = ShadowRevisionStore(
            enabled=True, resource_chunk_bytes=64)
        self.left.data = np.zeros(100, dtype=self.left.data_dtype)
        store.prepare(self.scene)

        record = store.commit(self.scene, 0, reason="checkpoint_zero")
        refs = [
            ref for ref in record.resource_refs
            if ref.semantic_id == semantic_id(self.left)
            and ref.component == "geometry"
        ]

        self.assertGreater(len(refs), 1)
        self.assertTrue(all(ref.byte_size <= 64 for ref in refs))
        self.assertEqual([ref.chunk for ref in refs], list(range(len(refs))))
        self.assertTrue(all(ref.chunks == len(refs) for ref in refs))


if __name__ == "__main__":
    unittest.main()
