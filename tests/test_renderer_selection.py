"""Renderer dogfood selection preserves sources and serializes GPU lifetimes."""

from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

import numpy as np

from maniml import Scene, Square
from maniml.web import geometry
from maniml.web.geometry import GeometryCache
from maniml.web.viewer import WebViewer


class RendererSelectionProtocol(unittest.TestCase):
    def viewer(self):
        viewer = WebViewer.__new__(WebViewer)
        viewer.scene = Scene(window=None, camera_config={"resolution": (32, 18)})
        viewer.scene.add(Square(fill_opacity=1))
        viewer.server = Mock()
        viewer._renderer_mode = "triangles"
        viewer._geometry_mode = True
        viewer._geometry_cache = GeometryCache()
        viewer._geometry_cache.sent.add("old-delta")
        viewer._last_state = {"old": True}
        return viewer

    def test_switch_resends_current_scene_without_mutating_source_or_checkpoint(self):
        viewer = self.viewer()
        scene = viewer.scene
        mob = scene.mobjects[-1]
        before = mob.data.copy()
        revision = mob.revision
        checkpoint = scene.current_animation_index
        for selected in ("winding", "triangles"):
            viewer._geometry_cache.sent.add("old-delta")
            viewer._handle_event({"type": "mode", "geometry": True, "renderer": selected})
            self.assertEqual(viewer._renderer_mode, selected)
            self.assertFalse(viewer._geometry_cache.sent)
            self.assertTrue(viewer._needs_refresh)
            self.assertIsNone(viewer._last_state)
            with patch("maniml.web.geometry.serialize_scene", return_value=b"fresh") as serialize:
                viewer._handle_event({"type": "geometry_request"})
            serialize.assert_called_once_with(scene, viewer._geometry_cache, renderer=selected)
            viewer.server.broadcast.assert_called_with(b"fresh")
            self.assertEqual(scene.current_animation_index, checkpoint)
            self.assertEqual(mob.revision, revision)
            np.testing.assert_array_equal(mob.data, before)
        self.assertIsNone(scene.camera._renderer)

    def test_rejected_frame_resets_cache_reports_error_and_valid_frame_recovers(self):
        viewer = self.viewer()
        with patch("maniml.web.geometry.serialize_scene", side_effect=ValueError("unsupported shape")):
            viewer._send_geometry()
            viewer._send_geometry()
        self.assertFalse(viewer._geometry_cache.sent)
        viewer.server.broadcast.assert_not_called()
        viewer.server.broadcast_json.assert_called_once()
        self.assertEqual(viewer._render_error["message"], "unsupported shape")
        with patch("maniml.web.geometry.serialize_scene", return_value=b"full frame"):
            viewer._send_geometry()
        self.assertIsNone(viewer._render_error)
        viewer.server.broadcast.assert_called_once_with(b"full frame")
        viewer.server.broadcast_json.assert_called_with({"type": "render_error", "error": None})

    def test_invalid_selection_does_not_change_renderer_or_cache(self):
        viewer = self.viewer()
        for selected in ("pixel", {}, None):
            viewer._handle_event({"type": "mode", "geometry": True, "renderer": selected})
            self.assertEqual(viewer._renderer_mode, "triangles")
            self.assertEqual(viewer._geometry_cache.sent, {"old-delta"})
        viewer.server.broadcast_json.assert_not_called()

    def test_old_clients_enable_default_and_playback_pause_keeps_selection(self):
        viewer = self.viewer()
        viewer._handle_event({"type": "mode", "geometry": True})
        self.assertEqual(viewer._renderer_mode, "triangles")
        self.assertIsNone(viewer._last_state, "initial renderer enable needs a fresh state snapshot")
        viewer._handle_event({"type": "mode", "geometry": True, "renderer": "winding"})
        viewer._handle_event({"type": "mode", "geometry": False})
        self.assertEqual(viewer._renderer_mode, "winding")
        self.assertFalse(viewer._geometry_mode)

    def test_explicit_same_mode_request_is_acknowledged_but_readiness_is_not(self):
        viewer = self.viewer()
        viewer._handle_event({"type": "mode", "geometry": False, "renderer": "triangles",
                              "renderer_origin": "first-tab", "renderer_request": 17})
        viewer.server.broadcast_json.assert_called_once_with({
            "type": "renderer", "renderer": "triangles", "origin": "first-tab", "request": 17})
        viewer.server.broadcast_json.reset_mock()
        viewer._handle_event({"type": "mode", "geometry": True})
        viewer.server.broadcast_json.assert_not_called()
        viewer._handle_event({"type": "mode", "geometry": False, "renderer": "winding",
                              "renderer_origin": "second-tab", "renderer_request": 18})
        viewer.server.broadcast_json.assert_called_once_with({
            "type": "renderer", "renderer": "winding", "origin": "second-tab", "request": 18})

    def test_invalid_renderer_request_id_does_not_change_selection(self):
        for request_id in (True, 0, -1, 1.5, "1", 2**53):
            with self.subTest(request_id=request_id):
                viewer = self.viewer()
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "winding",
                                      "renderer_request": request_id})
                self.assertEqual(viewer._renderer_mode, "triangles")
                self.assertEqual(viewer._geometry_cache.sent, {"old-delta"})
                viewer.server.broadcast_json.assert_not_called()

    def test_phase_b_is_the_whole_stack_and_only_while_selected(self):
        """The dropdown's Phase B: patches, nets and GPU programs regardless
        of the environment, stamped as its own renderer so the client draws
        it; Phase A's environment rules and the export path are untouched,
        and the program override goes when the selection does."""
        import json
        from maniml.utils import programs
        viewer = self.viewer()
        scene = viewer.scene
        try:
            viewer._handle_event({"type": "mode", "geometry": True, "renderer": "phase_b"})
            self.assertEqual(viewer._renderer_mode, "phase_b")
            self.assertEqual(programs.mode(), "gpu")
            self.assertEqual(programs.env_mode(), "off")
            def header_of(message):
                length = int.from_bytes(message[1:5], "little")
                return json.loads(message[5:5 + length])
            message = geometry.serialize_scene(scene, viewer._geometry_cache, renderer="phase_b")
            self.assertEqual(header_of(message)["renderer"], "phase_b")
            cache = viewer._geometry_cache
            self.assertEqual((cache.fill_generator, cache.surface_generator, cache.program_mode),
                             ("patches", "nets", "gpu"))
            # An export or checkpoint still made meanwhile is Phase A under
            # its own environment, not the on-screen selection
            plain = geometry.GeometryCache()
            self.assertEqual(header_of(geometry.serialize_scene(scene, plain))["renderer"],
                             "triangles")
            self.assertEqual((plain.fill_generator, plain.surface_generator, plain.program_mode),
                             ("meshes", "grids", "off"))
            viewer._handle_event({"type": "mode", "geometry": True, "renderer": "triangles"})
            self.assertEqual(programs.mode(), "off")
            viewer._handle_event({"type": "mode", "geometry": True, "renderer": "nonsense"})
            self.assertEqual(viewer._renderer_mode, "triangles")
        finally:
            programs.set_override(None)


@unittest.skipIf(shutil.which("node") is None, "node not available")
class RendererSelectionLifecycle(unittest.TestCase):
    def test_viewer_negotiates_reload_reconnect_and_multitab_selection_from_server_state(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("renderer_negotiation.cjs"))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_inflight_draw_switch_back_stale_payloads_and_failed_init(self):
        result = subprocess.run(["node", str(Path(__file__).with_name("renderer_selection.cjs"))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
