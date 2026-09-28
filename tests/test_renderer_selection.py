"""Renderer dogfood selection preserves sources and serializes GPU lifetimes."""

import os
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
        viewer.server.clients.return_value = frozenset()
        viewer._renderer_mode = "triangles"
        viewer._geometry_mode = True
        viewer._geometry_cache = GeometryCache()
        viewer._client_formats = {}
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

    def test_deltas_only_while_every_client_announced_format_8(self):
        """Format 8 (docs/phase_b4_plan.md, B4.8) is negotiated per client:
        the viewer's one cache streams deltas only while every client
        connected has said, in its last mode message, that it reads them.
        A change starts an epoch, so the next frame is a full frame."""
        from maniml.web.viewer import LogBuffer
        viewer = self.viewer()
        viewer.logs = LogBuffer()
        viewer.server.clients.return_value = frozenset({1, 2})
        viewer._handle_event({"type": "_connect", "alone": True, "client": 1})
        viewer._handle_event({"type": "_connect", "alone": False, "client": 2})
        viewer._handle_event({"type": "mode", "geometry": True, "format": 8, "_client": 1})
        self.assertFalse(viewer._deltas_negotiated(), "client 2 has not spoken")
        viewer._handle_event({"type": "mode", "geometry": True, "_client": 2})
        self.assertFalse(viewer._deltas_negotiated(), "client 2 reads format 7")
        viewer._handle_event({"type": "mode", "geometry": True, "format": 8, "_client": 2})
        self.assertTrue(viewer._deltas_negotiated())
        cache = viewer._geometry_cache
        epoch = cache.epoch
        with patch("maniml.web.geometry.serialize_scene", return_value=b"frame"):
            viewer._send_geometry()
        self.assertTrue(cache.deltas)
        self.assertEqual(cache.epoch, epoch + 1)
        # A client that says otherwise, or a third that joins, ends it.
        viewer._handle_event({"type": "mode", "geometry": True, "format": 7, "_client": 1})
        self.assertFalse(viewer._deltas_negotiated())
        viewer._handle_event({"type": "mode", "geometry": True, "format": 8, "_client": 1})
        viewer.server.clients.return_value = frozenset({1, 2, 3})
        self.assertFalse(viewer._deltas_negotiated())
        # The one that had not announced it leaves: the rest still read it.
        viewer.server.clients.return_value = frozenset({1, 2})
        self.assertTrue(viewer._deltas_negotiated())
        viewer.server.clients.return_value = frozenset({2})
        self.assertTrue(viewer._deltas_negotiated())
        self.assertEqual(set(viewer._client_formats), {2})
        viewer.server.clients.return_value = frozenset()
        self.assertFalse(viewer._deltas_negotiated(), "no client, no stream")
        # A new client at an empty viewer inherits nothing.
        viewer.server.clients.return_value = frozenset({4})
        viewer._handle_event({"type": "_connect", "alone": True, "client": 4})
        self.assertFalse(viewer._deltas_negotiated())

    def test_a_frame_that_changes_nothing_is_not_broadcast(self):
        from maniml.performance import performance
        viewer = self.viewer()
        with patch("maniml.web.geometry.serialize_scene", return_value=None), \
                patch.object(performance, "increment") as increment:
            viewer._send_geometry()
        viewer.server.broadcast.assert_not_called()
        increment.assert_called_once_with("transport.geometry_skipped")

    def test_invalid_renderer_request_id_does_not_change_selection(self):
        for request_id in (True, 0, -1, 1.5, "1", 2**53):
            with self.subTest(request_id=request_id):
                viewer = self.viewer()
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "winding",
                                      "renderer_request": request_id})
                self.assertEqual(viewer._renderer_mode, "triangles")
                self.assertEqual(viewer._geometry_cache.sent, {"old-delta"})
                viewer.server.broadcast_json.assert_not_called()

    @staticmethod
    def header_of(message):
        import json
        length = int.from_bytes(message[1:5], "little")
        return json.loads(message[5:5 + length])

    @staticmethod
    def stack(cache):
        return cache.fill_generator, cache.surface_generator, cache.program_mode

    def test_phase_b_is_the_whole_stack_and_only_while_selected(self):
        """The dropdown's Phase B: patches, nets and GPU programs regardless
        of the environment, stamped as its own renderer so the client draws
        it; the default's environment rules and the export path are
        untouched, and the program override goes when the selection does."""
        from maniml.utils import programs
        viewer = self.viewer()
        scene = viewer.scene
        with patch.dict("os.environ"):
            for name in ("MANIML_FILL", "MANIML_SURFACE", "MANIML_PROGRAMS"):
                os.environ.pop(name, None)
            try:
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "phase_b"})
                self.assertEqual(viewer._renderer_mode, "phase_b")
                self.assertEqual(programs.mode(), "gpu")
                self.assertEqual(programs.env_mode(), programs.DEFAULT_MODE)
                message = geometry.serialize_scene(scene, viewer._geometry_cache, renderer="phase_b")
                self.assertEqual(self.header_of(message)["renderer"], "phase_b")
                self.assertEqual(self.stack(viewer._geometry_cache), ("patches", "nets", "gpu"))
                # An export or checkpoint still made meanwhile is the
                # default stack, not the on-screen selection
                plain = geometry.GeometryCache()
                self.assertEqual(self.header_of(geometry.serialize_scene(scene, plain))["renderer"],
                                 "triangles")
                self.assertEqual(self.stack(plain), (geometry.DEFAULT_FILL, geometry.DEFAULT_SURFACE,
                                                     programs.DEFAULT_MODE))
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "triangles"})
                self.assertEqual(programs.mode(), programs.DEFAULT_MODE)
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "nonsense"})
                self.assertEqual(viewer._renderer_mode, "triangles")
            finally:
                programs.set_override(None)

    def test_phase_a_is_phase_a_whatever_the_environment_or_the_defaults(self):
        """The dropdown's Phase A (B5.4, docs/phase_b4_plan.md "The flips"):
        meshes, grids and programs off whatever the environment or the
        generators' defaults say, and its plays write no programs while it
        is selected; its frames are the bytes Phase A always wrote, stamped
        "triangles", while the default ("triangles") follows the
        environment."""
        from maniml.utils import programs
        viewer = self.viewer()
        scene = viewer.scene
        phase_b = {"MANIML_FILL": "patches", "MANIML_SURFACE": "nets", "MANIML_PROGRAMS": "gpu"}
        flipped = {"DEFAULT_FILL": "patches", "DEFAULT_SURFACE": "nets"}
        try:
            with patch.dict("os.environ"):
                for name in phase_b:
                    os.environ.pop(name, None)
                reference = geometry.serialize_scene(scene, geometry.GeometryCache(), renderer="phase_a")
            with patch.dict("os.environ", phase_b), patch.multiple(geometry, **flipped), \
                    patch.object(programs, "DEFAULT_MODE", "gpu"):
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "phase_a"})
                self.assertEqual(viewer._renderer_mode, "phase_a")
                self.assertEqual(programs.mode(), "off")
                message = geometry.serialize_scene(scene, viewer._geometry_cache, renderer="phase_a")
                self.assertEqual(message, reference)
                self.assertEqual(self.header_of(message)["renderer"], "triangles")
                self.assertEqual(self.stack(viewer._geometry_cache), ("meshes", "grids", "off"))
                viewer._handle_event({"type": "mode", "geometry": True, "renderer": "triangles"})
                self.assertIsNone(programs._override)
                self.assertEqual(programs.mode(), "gpu")
                self.assertFalse(viewer._geometry_cache.sent, "a switch from Phase A to the default resets")
                geometry.serialize_scene(scene, viewer._geometry_cache, renderer="triangles")
                self.assertEqual(self.stack(viewer._geometry_cache), ("patches", "nets", "gpu"))
            with patch.dict("os.environ"), patch.multiple(geometry, **flipped), \
                    patch.object(programs, "DEFAULT_MODE", "gpu"):
                for name in phase_b:
                    os.environ.pop(name, None)
                cache = geometry.GeometryCache()
                geometry.serialize_scene(scene, cache, renderer="triangles")
                self.assertEqual(self.stack(cache), ("patches", "nets", "gpu"), "the defaults, where no flag speaks")
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
