"""GPU pass timestamps (MANIML_GPU_TIMESTAMPS=1, wgpu_renderer._PassTimestamps):
the device request, the query slots and resolve on the fake device, and,
with MANIML_TEST_GPU=1, real frames' timings."""

import importlib.util
import os
import unittest
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import Mock, PropertyMock, patch

import numpy as np

from maniml.constants import BLUE, RED
from maniml.mobject.geometry import Square
from maniml.web.generated_geometry import serialize_generated_frame
from maniml.web.geometry import GeometryCache, parse_geometry_message
from tests.renderer_fixtures import build_scene

HAVE_LYON = bool(os.environ.get("MANIML_LYON_LIBRARY")) or importlib.util.find_spec("maniml.web.maniml_lyon_fill")
HAVE_WGPU = importlib.util.find_spec("wgpu") is not None
timestamps_on = patch.dict(os.environ, MANIML_GPU_TIMESTAMPS="1")


def _squares(border=4):
    shapes = [Square(side_length=1, fill_color=color, fill_opacity=1, stroke_width=0,
                     fill_border_width=border).shift([x, 0, 0])
              for color, x in ((RED, -.25), (BLUE, .25))]
    return build_scene(*shapes, resolution=(960, 540))


def _frame(scene, cache, tessellator, *, samples=4, supersample=2, **kwargs):
    from maniml.web.triangle_scene import prepare_triangle_frame
    frame = prepare_triangle_frame(scene, tessellator, mesh_cache=cache,
                                   fill_borders=True, gpu_borders=True, **kwargs)
    frame.samples, frame.supersample = samples, supersample
    return parse_geometry_message(serialize_generated_frame(frame, scene.camera.uniforms, GeometryCache()))


def _cached(scene, cache, tessellator):
    """The scene's next frame on the wire as one whose geometry the
    renderer already retains: no payload, no border layout."""
    header, _ = _frame(scene, cache, tessellator, patch_fills=True)
    for batch in header["batches"]:
        batch["cached"] = True
        for key in ("offset", "index_offset"):
            batch.pop(key, None)
        batch["border"].pop("layout", None)
    header["border_data"] = header["object_data"] = header["paint_data"] = {}
    return header, b""


def _invariants(case, timings):
    """What every frame's timings satisfy: durations of a pass and of the
    frame are non-negative (exclusive time is a pass's end past the latest
    end before it, so a pass Metal finished inside earlier work reads
    zero, never negative), the frame spans its longest pass, the
    attribution adds up to the frame exactly, and the raw ticks span the
    frame."""
    case.assertGreater(timings["period_ns"], 0)
    for entry in timings["passes"]:
        case.assertGreaterEqual(entry["ms"], 0, entry)
        case.assertGreaterEqual(entry["exclusive_ms"], 0, entry)
        case.assertLessEqual(entry["ms"], timings["total_ms"] + 1e-9, entry)
    case.assertGreaterEqual(timings["total_ms"], 0)
    case.assertGreaterEqual(timings["readback_ms"], 0)
    case.assertAlmostEqual(sum(entry["exclusive_ms"] for entry in timings["passes"]), timings["total_ms"])
    case.assertAlmostEqual(sum(entry["ms"] for entry in timings["passes"]), timings["sum_ms"])
    # Pass durations overlap on a tiling GPU (a render pass begins at its
    # vertex stage), so their sum can exceed the frame, but not by more
    # than the pass count allows.
    case.assertLessEqual(timings["sum_ms"], len(timings["passes"]) * timings["total_ms"] + 1e-9)
    case.assertGreaterEqual(timings["end_tick"], timings["begin_tick"])
    case.assertAlmostEqual((timings["end_tick"] - timings["begin_tick"]) * timings["period_ns"] / 1e6,
                           timings["total_ms"])


@unittest.skipUnless(HAVE_WGPU, "the renderer imports wgpu")
class DeviceRequest(unittest.TestCase):
    """The constructor asks the adapter for timestamps only under the flag,
    and only when the adapter offers them."""

    def construct(self, features):
        import wgpu
        from maniml.web import wgpu_renderer
        device = SimpleNamespace(create_shader_module=Mock(), create_sampler=Mock(), queue=object())
        adapter = SimpleNamespace(features=set(features), request_device_sync=Mock(return_value=device))
        with patch.object(wgpu.gpu, "request_adapter_sync", return_value=adapter), \
                patch.object(wgpu_renderer, "_timestamp_period_ns", return_value=1.0):
            renderer = wgpu_renderer.WgpuRenderer()
        return renderer, adapter.request_device_sync.call_args.kwargs["required_features"]

    def test_off_asks_for_no_feature_and_keeps_no_timings(self):
        with patch.dict(os.environ):
            os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
            renderer, features = self.construct(["timestamp-query"])
        self.assertEqual(list(features), [])
        self.assertIsNone(renderer._timestamps)
        self.assertFalse(hasattr(renderer, "gpu_timings"))

    def test_on_requests_the_feature_the_adapter_offers(self):
        import wgpu
        with timestamps_on:
            renderer, features = self.construct(["timestamp-query", "shader-f16"])
        self.assertEqual(list(features), [wgpu.FeatureName.timestamp_query])
        self.assertIsNotNone(renderer._timestamps)
        self.assertIsNone(renderer.gpu_timings)

    def test_on_without_the_feature_carries_on_without_timings(self):
        with timestamps_on:
            renderer, features = self.construct(["shader-f16"])
        self.assertEqual(list(features), [])
        self.assertIsNone(renderer._timestamps)
        self.assertIsNone(renderer.gpu_timings)


@unittest.skipUnless(HAVE_LYON and HAVE_WGPU, "needs the Lyon helper and wgpu")
class TimestampCommands(unittest.TestCase):
    """Query slots, resolve and readback on the fake device of
    tests.test_generated_wgpu, with ticks the fake resolve invents: slot s
    of the k-th query set reads 10**7 * (k + 1) + 1000 * s."""

    PERIOD_NS = 2.5

    def setUp(self):
        from maniml.web.triangle_geometry import LyonFillTessellator
        from tests.test_generated_wgpu import _Buffer, _Device, _Encoder, _Pass
        self.tessellator = LyonFillTessellator()
        sets = []

        class Staging(_Buffer):
            def __init__(self, data, events):
                super().__init__(data, events)
                self.data = bytearray(self.data)
                self.mapped = False

            def map_sync(self, mode, offset=0, size=None):
                self.events.append(("map_sync", self))
                self.mapped = True

            def read_mapped(self):
                assert self.mapped
                return memoryview(bytes(self.data))

            def unmap(self):
                self.events.append(("unmap", self))
                self.mapped = False

        class Encoder(_Encoder):
            def begin_compute_pass(self, **descriptor):
                self.events.append(("begin_compute_pass", descriptor))
                return _Pass(self.events)

            def resolve_query_set(self, query_set, first, count, destination, offset):
                self.events.append(("resolve_query_set", query_set, first, count, destination, offset))
                base = 10 ** 7 * (sets.index(query_set) + 1)
                for slot in range(first, first + count):
                    destination.data[offset + 8 * slot:offset + 8 * slot + 8] = (base + 1000 * slot).to_bytes(8, "little")

            def copy_buffer_to_buffer(self, source, source_offset, target, target_offset, size):
                super().copy_buffer_to_buffer(source, source_offset, target, target_offset, size)
                if isinstance(source, Staging):
                    target.data[target_offset:target_offset + size] = source.data[source_offset:source_offset + size]

        class Device(_Device):
            def create_command_encoder(self):
                return Encoder(self.events)

            def create_buffer(self, *, size, usage):
                buffer = Staging(bytes(size), self.events)
                buffer.usage = usage
                self.buffers.append(buffer)
                return buffer

            def create_query_set(self, *, type, count):
                query_set = SimpleNamespace(type=type, count=count, destroy=Mock())
                sets.append(query_set)
                self.events.append(("create_query_set", query_set))
                return query_set

            def create_bind_group_layout(self, **descriptor):
                return ("layout", len(descriptor["entries"]))

            def create_pipeline_layout(self, **descriptor):
                return ("pipeline_layout", len(descriptor["bind_group_layouts"]))

        self.sets = sets
        self.Device = Device

    def renderer(self, timestamps, capacity=64):
        from maniml.web.wgpu_renderer import WgpuRenderer, _PassTimestamps
        renderer = WgpuRenderer.__new__(WgpuRenderer)
        renderer.device = self.Device()
        for name in ("_generated_geometry", "_generated_uniforms", "_generated_textures",
                     "_generated_paints", "_generated_paint_bindings", "_border_sources",
                     "_border_outputs", "_object_tables", "_patch_uniforms", "_net_sources",
                     "_net_outputs", "_program_sources", "_program_outputs", "_program_pipelines",
                     "texture_cache"):
            setattr(renderer, name, {})
        renderer._patch_layouts = renderer._net_compute_pipeline = renderer._border_compute_pipeline = None
        renderer._stale_index_buffers = []
        renderer.sampler = object()
        renderer._ensure_targets = Mock()
        renderer._modules = {"resolve2": object(), "border_compute": object(), "patch_fill": object()}
        renderer._spatial_pipeline = renderer._spatial_texture = renderer._spatial_binding = None
        renderer.resolve_texture = None
        renderer.out_texture = renderer.device.create_texture(size=(128, 72, 1))
        renderer.out_view = renderer.out_texture.create_view()
        renderer.depth_view = object()
        renderer._pipeline = Mock(side_effect=lambda name, samples: SimpleNamespace(
            name=name, get_bind_group_layout=lambda group: (name, samples, group)))
        renderer._patch_pipeline = lambda kind, depth, samples: SimpleNamespace(name=("patch", kind, depth))
        renderer._timestamps = _PassTimestamps(renderer.device, self.PERIOD_NS, capacity) if timestamps else None
        return renderer

    def passes(self, events):
        return [event[1].get("timestamp_writes") for event in events
                if event[0] in ("begin_compute_pass", "begin_render_pass")]

    def test_off_stamps_nothing_and_makes_no_query_set(self):
        renderer = self.renderer(timestamps=False)
        from maniml.web.triangle_scene import TriangleMeshCache
        header, raw = _frame(_squares(), TriangleMeshCache(), self.tessellator, patch_fills=True)
        renderer.render(header, raw)
        events = renderer.device.events
        self.assertEqual(self.passes(events), [None, None, None])
        self.assertFalse(any(event[0] in ("create_query_set", "resolve_query_set", "map_sync") for event in events))
        submit, = [event for event in events if event[0] == "submit"]
        self.assertEqual(len(submit[1]), 1)
        self.assertFalse(hasattr(renderer, "gpu_timings"))

    def test_each_pass_gets_two_slots_resolved_on_the_first_read(self):
        from maniml.web.triangle_scene import TriangleMeshCache
        renderer, cache = self.renderer(timestamps=True), TriangleMeshCache()
        scene = _squares()
        header, raw = _frame(scene, cache, self.tessellator, patch_fills=True)
        renderer.render(header, raw)
        events = renderer.device.events
        query_set, = self.sets
        self.assertEqual(query_set.count, 64)
        self.assertEqual(self.passes(events), [
            {"query_set": query_set, "beginning_of_pass_write_index": 2 * i, "end_of_pass_write_index": 2 * i + 1}
            for i in range(3)])
        # render() ends at the frame's readback, as it does with the flag
        # off: one submission and no resolve until something reads the
        # timings, which a harness does after its timer stops.
        commands = ("submit", "resolve_query_set", "map_sync", "unmap")
        self.assertEqual([event[0] for event in events if event[0] in commands], ["submit"])
        timings = renderer.gpu_timings
        self.assertIs(renderer.gpu_timings, timings, "a second read resolves nothing more")
        resolve, = [event for event in events if event[0] == "resolve_query_set"]
        self.assertEqual(resolve[1:4], (query_set, 0, 6))
        self.assertEqual(resolve[5], 0)
        copy = next(event for event in events if event[0] == "copy_buffer_to_buffer" and event[1] is resolve[4])
        self.assertEqual((copy[2], copy[4], copy[5]), (0, 0, 256))
        # The frame's submission is the one it always was; the resolve is a
        # second one, encoded after it, and the map follows.
        self.assertEqual([event[0] for event in events if event[0] in commands],
                         ["submit", "resolve_query_set", "submit", "map_sync", "unmap"])
        frame_submit, resolve_submit = [event for event in events if event[0] == "submit"]
        self.assertEqual(len(frame_submit[1]), 1)
        self.assertEqual(len(resolve_submit[1]), 1)
        self.assertGreaterEqual(timings["readback_ms"], 0)
        scale = self.PERIOD_NS / 1e6
        self.assertEqual(timings["period_ns"], self.PERIOD_NS)
        self.assertEqual([entry["label"] for entry in timings["passes"]], ["borders", "out", "resolve"])
        np.testing.assert_allclose([entry["ms"] for entry in timings["passes"]], [1000 * scale] * 3)
        np.testing.assert_allclose([entry["exclusive_ms"] for entry in timings["passes"]],
                                   [1000 * scale, 2000 * scale, 2000 * scale])
        np.testing.assert_allclose([timings["total_ms"], timings["sum_ms"]], [5000 * scale, 3000 * scale])
        self.assertEqual((timings["begin_tick"], timings["end_tick"]), (10 ** 7, 10 ** 7 + 5000))
        _invariants(self, timings)
        # A cached frame whose borders are current runs no compute pass, and
        # the query set is reused from slot 0.
        renderer.device.events.clear()
        renderer.render(*_cached(scene, cache, self.tessellator))
        self.assertEqual([entry["label"] for entry in renderer.gpu_timings["passes"]], ["out", "resolve"])
        self.assertEqual(self.sets, [query_set])
        self.assertEqual([p["beginning_of_pass_write_index"] for p in self.passes(renderer.device.events)], [0, 2])

    def test_a_pass_that_ended_inside_earlier_work_is_attributed_nothing(self):
        """Metal finishes independent compute passes out of order; the
        attribution stays non-negative and adds up to the frame."""
        from maniml.web.wgpu_renderer import _PassTimestamps
        timestamps = _PassTimestamps(self.Device(), self.PERIOD_NS)
        timestamps.begin_frame()
        for label in ("borders", "borders", "borders", "out", "resolve"):
            timestamps.writes(label)
        timestamps.frame_complete()
        # begin/end ticks per pass: the second border pass ends before the
        # first, the third begins before both end.
        ticks = [(100, 400), (150, 300), (200, 500), (450, 900), (800, 1000)]
        timestamps._resolve = lambda: None
        staging = SimpleNamespace(map_sync=lambda mode: None, unmap=lambda: None,
                                  read_mapped=lambda: np.array([tick for pair in ticks for tick in pair],
                                                               dtype="<u8").tobytes())
        timestamps.staging_buffer, timestamps.spans = staging, [0]
        timings = timestamps.read()
        scale = self.PERIOD_NS / 1e6
        np.testing.assert_allclose([entry["exclusive_ms"] for entry in timings["passes"]],
                                   np.array([300, 0, 100, 400, 100]) * scale)
        np.testing.assert_allclose(timings["total_ms"], 900 * scale)
        self.assertEqual((timings["begin_tick"], timings["end_tick"]), (100, 1000))
        _invariants(self, timings)

    def test_a_frame_beyond_one_query_set_numbers_its_output_passes(self):
        from tests.test_generated_wgpu import _border_wire
        # 256 coverage objects reopen the scene pass once (a stencil clear)
        # and each generates its border: 259 passes, past a 64-slot set and
        # the two that follow it.
        header, raw, _, _ = _border_wire(copies=256, capacity=16)
        renderer = self.renderer(timestamps=True)
        renderer.render(header, raw)
        labels = [entry["label"] for entry in renderer.gpu_timings["passes"]]
        self.assertEqual(labels, ["borders"] * 256 + ["out/0", "out/1", "resolve"])
        self.assertEqual([query_set.count for query_set in self.sets], [64, 128, 256, 512])
        events = renderer.device.events
        resolves = [event for event in events if event[0] == "resolve_query_set"]
        self.assertEqual([(event[1], event[2], event[3], event[5]) for event in resolves],
                         [(self.sets[0], 0, 64, 0), (self.sets[1], 0, 128, 512),
                          (self.sets[2], 0, 256, 1536), (self.sets[3], 0, 70, 3584)])
        scale = self.PERIOD_NS / 1e6
        self.assertTrue(all(entry["ms"] == 1000 * scale for entry in renderer.gpu_timings["passes"]))
        _invariants(self, renderer.gpu_timings)
        # The sets outlive the frame; a smaller next frame (whose one border
        # output is current, so no compute pass) reuses the first.
        renderer.device.events.clear()
        header, raw, _, _ = _border_wire(copies=1, capacity=16)
        renderer.render(header, raw)
        self.assertEqual([entry["label"] for entry in renderer.gpu_timings["passes"]], ["out", "resolve"])
        self.assertEqual(len(self.sets), 4)
        self.assertEqual([p["query_set"] for p in self.passes(renderer.device.events)], [self.sets[0]] * 2)


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "real GPU timestamps not requested")
class TimestampFrames(unittest.TestCase):
    """Real frames on the real device: labels in submission order, the
    invariants above, and the GPU's clock against the wall clock."""

    @classmethod
    def setUpClass(cls):
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.wgpu_renderer import WgpuRenderer
        cls.tessellator = LyonFillTessellator()
        with timestamps_on:
            cls.timed = WgpuRenderer()
        with patch.dict(os.environ):
            os.environ.pop("MANIML_GPU_TIMESTAMPS", None)
            cls.plain = WgpuRenderer()

    @classmethod
    def tearDownClass(cls):
        cls.timed.close()
        cls.plain.close()

    def render(self, renderer, header, raw):
        start = perf_counter()
        image = renderer.render(header, raw)
        return image, 1000 * (perf_counter() - start)

    def test_patch_frame_passes_in_order_and_below_the_wall_clock(self):
        from maniml.web.triangle_scene import TriangleMeshCache
        if self.timed._timestamps is None:
            self.skipTest("the adapter offers no timestamp queries")
        scene, cache = _squares(), TriangleMeshCache()
        header, raw = _frame(scene, cache, self.tessellator, patch_fills=True)
        _, wall = self.render(self.timed, header, raw)
        timings = self.timed.gpu_timings
        self.assertEqual([entry["label"] for entry in timings["passes"]], ["borders", "out", "resolve"])
        _invariants(self, timings)
        self.assertLess(timings["total_ms"], wall, "the GPU's clock runs no faster than the wall's")
        self.assertGreater(timings["total_ms"], 0)
        for _ in range(3):
            previous_end = timings["end_tick"]
            _, wall = self.render(self.timed, *_cached(scene, cache, self.tessellator))
            timings = self.timed.gpu_timings
            self.assertEqual([entry["label"] for entry in timings["passes"]], ["out", "resolve"])
            _invariants(self, timings)
            # Slots are reused from 0 each frame; the stamps must be this
            # frame's, not the previous frame's late end sample.
            self.assertGreater(timings["begin_tick"], previous_end, "stale slot")
            self.assertGreater(timings["total_ms"], 0)
            self.assertLess(timings["total_ms"], wall)
            self.assertLess(timings["total_ms"], 100, "milliseconds, not some other unit")

    def test_resolve_runs_on_the_first_read_not_inside_render(self):
        """The instrument's resolve (about 1.5 ms) must not sit inside the
        interval the harnesses time: after the readback, render() of the
        instrumented renderer takes what the plain one's does."""
        from statistics import median
        from benchmarks.generated_output import QueueObserver
        from maniml.web.triangle_scene import TriangleMeshCache
        if self.timed._timestamps is None:
            self.skipTest("the adapter offers no timestamp queries")
        renderers = {"timed": self.timed, "plain": self.plain}
        scenes = {name: (_squares(), TriangleMeshCache()) for name in renderers}
        queues = {name: QueueObserver(renderer) for name, renderer in renderers.items()}
        post = {name: [] for name in renderers}
        try:
            for name, (scene, cache) in scenes.items():
                renderers[name].render(*_frame(scene, cache, self.tessellator, patch_fills=True))
            for trial in range(8):
                for name in ("timed", "plain") if trial % 2 == 0 else ("plain", "timed"):
                    renderer, queue, (scene, cache) = renderers[name], queues[name], scenes[name]
                    queue.reset()
                    renderer.render(*_cached(scene, cache, self.tessellator))
                    completed = perf_counter()
                    self.assertEqual((queue.submissions, queue.reads, queue.timing_submissions), (1, 1, 0))
                    post[name].append(1000 * (completed - queue.read_completed_at))
                    if name == "timed":
                        timings = renderer.gpu_timings
                        self.assertEqual(queue.timing_submissions, 1)
                        self.assertIs(renderer.gpu_timings, timings)
                        self.assertEqual(queue.timing_submissions, 1, "one resolve per frame")
                        self.assertGreater(timings["readback_ms"], 0)
        finally:
            for queue in queues.values():
                queue.close()
        self.assertLess(abs(median(post["timed"]) - median(post["plain"])), 0.3, post)

    def test_many_concurrent_border_passes_keep_the_attribution_summable(self):
        """One compute pass per border batch: Metal runs them concurrently
        and finishes them out of order (a few dozen of these 256 end before
        an earlier one on the M3), which once read as negative exclusive
        time. The frame's attribution must still be non-negative and add up."""
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.test_generated_wgpu import _border_wire
        if self.timed._timestamps is None:
            self.skipTest("the adapter offers no timestamp queries")
        header, raw, _, _ = _border_wire(copies=256, capacity=16)
        with timestamps_on:
            renderer = WgpuRenderer()  # fresh, so every border output is generated
        try:
            _, wall = self.render(renderer, header, raw)
            timings = renderer.gpu_timings
        finally:
            renderer.close()
        self.assertEqual([entry["label"] for entry in timings["passes"]],
                         ["borders"] * 256 + ["out/0", "out/1", "resolve"])
        _invariants(self, timings)
        self.assertTrue(all(entry["ms"] > 0 for entry in timings["passes"]), "no zero or stale stamp")
        self.assertLess(timings["total_ms"], wall)
        borders = sum(entry["exclusive_ms"] for entry in timings["passes"] if entry["label"] == "borders")
        self.assertGreater(borders, 0)
        self.assertLessEqual(borders, timings["total_ms"])

    def test_mesh_frame_and_no_resolve_pass(self):
        from maniml.web.triangle_scene import TriangleMeshCache
        if self.timed._timestamps is None:
            self.skipTest("the adapter offers no timestamp queries")
        header, raw = _frame(_squares(), TriangleMeshCache(), self.tessellator)
        self.render(self.timed, header, raw)
        self.assertEqual([entry["label"] for entry in self.timed.gpu_timings["passes"]], ["borders", "out", "resolve"])
        _invariants(self, self.timed.gpu_timings)
        header, raw = _frame(_squares(border=0), TriangleMeshCache(), self.tessellator, samples=1, supersample=1)
        self.render(self.timed, header, raw)
        self.assertEqual([entry["label"] for entry in self.timed.gpu_timings["passes"]], ["out"])
        _invariants(self, self.timed.gpu_timings)

    def test_off_asks_nothing_of_the_device(self):
        from maniml.web.triangle_scene import TriangleMeshCache
        self.assertNotIn("timestamp-query", self.plain.device.features)
        self.assertIsNone(self.plain._timestamps)
        self.assertFalse(hasattr(self.plain, "gpu_timings"))
        header, raw = _frame(_squares(), TriangleMeshCache(), self.tessellator, patch_fills=True)
        image, _ = self.render(self.plain, header, raw)
        self.assertEqual(image.size, (960, 540))
        self.assertFalse(hasattr(self.plain, "gpu_timings"))

    def test_without_the_feature_the_renderer_draws_without_timings(self):
        from maniml.web.triangle_scene import TriangleMeshCache
        from maniml.web.wgpu_renderer import WgpuRenderer
        from wgpu.backends.wgpu_native._api import GPUAdapter
        with timestamps_on, patch.object(GPUAdapter, "features", new_callable=PropertyMock, return_value=frozenset()):
            renderer = WgpuRenderer()
        try:
            self.assertIsNone(renderer._timestamps)
            self.assertIsNone(renderer.gpu_timings)
            header, raw = _frame(_squares(), TriangleMeshCache(), self.tessellator, patch_fills=True)
            timed = np.asarray(self.timed.render(header, raw), dtype=int)
            image = np.asarray(renderer.render(header, raw), dtype=int)
            self.assertIsNone(renderer.gpu_timings)
            np.testing.assert_array_equal(image, timed, "timestamps change no pixel")
        finally:
            renderer.close()


if __name__ == "__main__":
    unittest.main()
