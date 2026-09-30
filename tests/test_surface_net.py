"""Surfaces as control nets (docs/phase_b2_plan.md): construction, the CPU
grid the reference renderers draw, alignment, and what stays untouched."""

import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from maniml.constants import RIGHT
from maniml.mobject.three_dimensions import Sphere, Square3D, SurfaceMesh, Torus
from maniml.mobject.types.surface import ParametricSurface, Surface, TexturedSurface
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.types.vmobject_3d import VMobject3D
from maniml.utils import bezier_net


def sampled(surface):
    """What today's construction produced: uv_func on the resolution grid."""
    nu, nv = surface.resolution
    return np.array([surface.uv_func(u, v) for u in np.linspace(*surface.u_range, nu)
                     for v in np.linspace(*surface.v_range, nv)], dtype=float)


class NetConstruction(unittest.TestCase):
    def test_resolution_is_the_net_size_and_the_grid_is_the_sample_grid(self):
        sphere = Sphere(radius=1.4)
        self.assertEqual(sphere.resolution, (101, 51))
        self.assertEqual(sphere.get_num_points(), 101 * 51)
        # The reference renderers draw the net evaluated at two steps per
        # patch: exactly the samples the construction took, so their
        # pixels are unchanged.
        np.testing.assert_allclose(sphere.get_grid_points(), sampled(sphere), atol=2e-6)
        np.testing.assert_allclose(sphere.get_shader_data()["point"],
                                   sampled(sphere)[sphere.get_triangle_indices()], atol=2e-6)
        # The handles of the net lie off the sphere; the surface lies on it.
        radii = np.linalg.norm(sphere.get_points(), axis=1)
        self.assertGreater(radii.max(), 1.4 + 1e-3)
        grid = bezier_net.evaluate(sphere.get_points().reshape(101, 51, 3), 6, 6)
        self.assertLess(np.abs(np.linalg.norm(grid, axis=-1) - 1.4).max(), 1e-3)

    def test_even_resolutions_round_up_to_one_patch(self):
        square = Square3D(side_length=2)
        self.assertEqual(square.resolution, (3, 3))
        self.assertEqual(square.get_num_points(), 9)
        np.testing.assert_allclose(square.get_grid_points()[:, 2], 0, atol=1e-12)
        self.assertEqual(len(square.get_triangle_indices()), 6 * 4)
        plane = Surface(u_range=(-1, 1), v_range=(-1, 1), resolution=(2, 2))
        self.assertEqual(plane.resolution, (3, 3))

    def test_uv_to_point_is_exact_on_the_samples_and_smooth_between(self):
        surface = ParametricSurface(lambda u, v: [u, v, u * u + v], u_range=(0, 2), v_range=(0, 1),
                                    resolution=(5, 5))
        np.testing.assert_allclose(surface.uv_to_point(1.0, 0.5), [1, .5, 1.5], atol=1e-12)
        np.testing.assert_allclose(surface.uv_to_point(2.0, 1.0), [2, 1, 5], atol=1e-12)
        # u² is quadratic: the net reproduces it everywhere, not only at samples.
        np.testing.assert_allclose(surface.uv_to_point(1.3, .2), [1.3, .2, 1.3 ** 2 + .2], atol=1e-12)

    def test_grid_cache_follows_the_revision(self):
        sphere = Sphere(resolution=(9, 5))
        before = sphere.get_grid_points().copy()
        self.assertIs(sphere.get_grid_data(), sphere.get_grid_data())
        sphere.shift(RIGHT)
        after = sphere.get_grid_points()
        np.testing.assert_allclose(after - before, np.broadcast_to([1, 0, 0], after.shape), atol=1e-6)
        self.assertFalse(after.flags.writeable)

    def test_surface_mesh_lines_lie_on_the_surface(self):
        mesh = SurfaceMesh(Sphere(radius=2), resolution=(5, 3))
        for line in mesh.submobjects:
            radii = np.linalg.norm(line.get_points(), axis=1)
            self.assertLess(np.abs(radii - 2).max(), 0.03)

    def test_textured_surface_carries_image_coordinates_per_control_point(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "t.png")
            Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(path)
            textured = TexturedSurface(Sphere(resolution=(9, 5)), path)
            self.assertEqual(textured.resolution, (9, 5))
            grid = textured.get_shader_data()
            self.assertEqual(grid.dtype.names, ("point", "d_normal_point", "im_coords", "opacity"))
            self.assertLessEqual(grid["im_coords"].max(), 1.0)
            self.assertGreaterEqual(grid["im_coords"].min(), 0.0)

    def test_vmobject3d_keeps_its_explicit_mesh(self):
        path = VMobject(fill_opacity=.5).set_points_as_corners(
            [[-1, -1, 0], [1, -1, 0], [1, 1, 1], [-1, 1, 0], [-1, -1, 0]])
        surface = VMobject3D(path, resolution=12)
        self.assertFalse(surface.net)
        np.testing.assert_array_equal(surface.get_shader_data()["point"],
                                      surface.get_points()[surface.get_triangle_indices()])


class NetAlignment(unittest.TestCase):
    def test_transform_alignment_subdivides_without_moving_either_surface(self):
        coarse, fine = Sphere(radius=1, resolution=(9, 5)), Torus()
        # The coarse sphere's true deviation, from a dense evaluation.
        worst = np.abs(np.linalg.norm(bezier_net.evaluate(coarse.get_net(), 40, 40)[..., :3], axis=-1) - 1).max()
        coarse.align_points(fine)
        self.assertEqual(coarse.resolution, fine.resolution)
        self.assertEqual(coarse.get_num_points(), fine.get_num_points())
        # The subdivided coarse sphere is still the coarse sphere: no
        # evaluated point is further from the unit sphere than it could be.
        radii = np.linalg.norm(bezier_net.evaluate(coarse.get_net(), 4, 4)[..., :3], axis=-1)
        self.assertLessEqual(np.abs(radii - 1).max(), worst + 1e-4)  # two samplings of one surface
        self.assertGreater(worst, 0.01, "a four-by-two patch sphere is visibly approximate")
        self.assertEqual(len(coarse.get_triangle_indices()), len(fine.get_triangle_indices()))
        # And a blend is now a blend of control points of equal count.
        coarse.interpolate(coarse.copy(), fine, 0.5)
        self.assertEqual(coarse.get_num_points(), fine.get_num_points())


class NetCacheAccounting(unittest.TestCase):
    def test_a_dead_surfaces_entry_is_taken_off_when_its_id_comes_back(self):
        # CPython hands a dead object's id to the next one made, so a
        # surface replaced between two frames can find its predecessor's
        # entry at its own id before any finish_frame saw that one die.
        # The entry was overwritten with its bytes still counted: the
        # budget filled with nothing until it evicted every live net.
        import gc
        from maniml.web.gpu_net_geometry import NetRecipeCache

        def net(cache, surface):
            return cache.source(surface, revision=surface.revision, pixels_per_unit=100, frame_scale=1)

        def program(cache, surface):
            rows = np.zeros((surface.get_num_points(), surface.data.dtype.itemsize // 4), dtype="f4")
            return cache.program_entry(surface, [rows, rows], pixels_per_unit=100, frame_scale=1)

        for what, read in (("source", net), ("program_entry", program)):
            with self.subTest(what):
                cache, surface = NetRecipeCache(), Sphere(resolution=(7, 5))
                cache.begin_frame()
                net(cache, Sphere(resolution=(9, 9)))   # dies before the frame ends
                gc.collect()
                entry = cache.entries.pop(next(iter(cache.entries)))
                self.assertIsNone(entry.owner())
                cache.entries[id(surface)] = entry   # the state an id reuse leaves
                read(cache, surface)
                self.assertIs(cache.entries[id(surface)].owner(), surface)
                self.assertEqual(cache.nbytes, sum(held.net.nbytes for held in cache.entries.values()))
                cache.finish_frame()
                self.assertEqual(cache.nbytes, sum(held.net.nbytes for held in cache.entries.values()))


class NetCacheSweep(unittest.TestCase):
    """finish_frame sweeps only where an entry went unused (B5.5: a frame
    that used every entry, the still frame's case, sweeps nothing), and
    the reservation's rules give what they gave before their memos."""

    def test_an_unused_entry_is_swept_and_a_frame_that_used_all_is_not(self):
        from maniml.web.gpu_net_geometry import NetRecipeCache
        cache, a, b = NetRecipeCache(), Sphere(resolution=(7, 5)), Sphere(resolution=(9, 5))

        def read(surface, keep=False):
            if keep:
                return cache.keep(surface)
            return cache.source(surface, revision=surface.revision, pixels_per_unit=100, frame_scale=1)

        cache.begin_frame()
        read(a), read(b), read(a)
        self.assertEqual(cache._used, 2, "an entry used twice counts once")
        cache.finish_frame()
        self.assertEqual(len(cache.entries), 2)
        cache.begin_frame()
        read(a, keep=True), read(a, keep=True)
        cache.finish_frame()
        self.assertEqual(list(cache.entries), [id(a)], "the unused entry is swept")
        self.assertEqual(cache.nbytes, sum(entry.net.nbytes for entry in cache.entries.values()))
        cache.begin_frame()
        read(a, keep=True)
        b.shift(RIGHT)
        read(b), read(b)
        a.shift(RIGHT)
        read(a)   # a new net at a used place counts as the one it replaces
        self.assertEqual(cache._used, 2)
        cache.finish_frame()
        self.assertEqual(set(cache.entries), {id(a), id(b)})
        self.assertEqual(cache.nbytes, sum(entry.net.nbytes for entry in cache.entries.values()))

    def test_the_memoized_rules_are_the_rules(self):
        import numpy as np
        from maniml.web import gpu_net_geometry as g
        for density, ppu, scale in ((0.0, 270.0, 1.0), (.013, 270.0, 1.0), (.2, 270.0, .02), (3.1, 540.0, 1 / 64),
                                    (1e-3, 1e3, 1e-9), (float("inf"), 1.0, 1.0)):
            pixels = float(density) * float(ppu) / float(scale)
            expected = (g.MIN_NET_STEPS if not np.isfinite(pixels) or pixels <= 4.0 else
                        int(min(g.MAX_NET_STEPS, max(g.MIN_NET_STEPS, np.ceil(np.sqrt(np.float32(pixels)))))))
            self.assertEqual(g.steps_needed(np.float32(density), ppu, scale), g.steps_needed(density, ppu, scale))
            self.assertEqual(g.steps_needed(density, ppu, scale), expected)
        uniforms = {"frame_rescale_factors": np.array([.25, 1 / 3, 1.0], dtype=np.float32)}
        self.assertEqual(g.pixels_per_unit(uniforms, (960, 540)),
                         float(np.asarray(uniforms["frame_rescale_factors"], dtype=float)[1]) * 540 / 2.0)
        for needed, previous, cap in ((3, None, 32), (3, 8, 32), (9, 8, 32), (20, None, 12), (20, 12, 12)):
            self.assertEqual(g._reserve(needed, previous, cap), g.reserve_steps(needed, previous, cap))


class NetEvaluationPlan(unittest.TestCase):
    """What both drivers decide before the net stage's one dispatch
    (docs/phase_b4_plan.md, B5.5): the steps, and the grouping."""

    def test_steps_follow_the_kernels_rule_and_stay_within_the_capacity(self):
        from maniml.web.gpu_net_geometry import evaluation_steps
        # 90 pixels per unit at frame scale 1 (180 rows, rescale 1).
        self.assertEqual(evaluation_steps(0, 1.0, 180, 1.0, 8), 2)
        self.assertEqual(evaluation_steps(4 / 90, 1.0, 180, 1.0, 8), 2, "four pixels or fewer: two steps")
        self.assertEqual(evaluation_steps(.2, 1.0, 180, 1.0, 8), 5, "ceil(sqrt(18))")
        self.assertEqual(evaluation_steps(.4, 1.0, 180, 1.0, 8), 6, "sqrt(36) is exactly six")
        self.assertEqual(evaluation_steps(.2, 1.0, 180, .5, 8), 6, "a zoom in raises the pixels per unit")
        self.assertEqual(evaluation_steps(.2, 1.0, 180, .1, 8), 8, "at most the capacity")
        self.assertEqual(evaluation_steps(1e300, 1e300, 180, 1e-30, 8), 8, "an overflow is the capacity")
        self.assertEqual(evaluation_steps(float("nan"), 1.0, 180, 1.0, 8), 2)
        with self.assertRaises(ValueError):
            evaluation_steps(.2, 1.0, 180, 1.0, 40)

    def test_a_frames_nets_group_into_dispatches_within_the_budget(self):
        from maniml.web.gpu_net_geometry import dispatch_shape, pack_table, plan_evaluation
        # One dispatch, each source gathered once, outputs and patches in order.
        plan = plan_evaluation([("a", 100, 400, 2), ("b", 60, 400, 3), ("a", 100, 800, 2)], budget=1 << 20)
        self.assertEqual(len(plan), 1)
        self.assertEqual(plan[0]["sources"], [("a", 0, 100), ("b", 100, 60)])
        self.assertEqual(plan[0]["entries"], [(0, 0, 0, 0), (1, 25, 100, 2), (2, 0, 200, 5)])
        self.assertEqual((plan[0]["input_bytes"], plan[0]["output_bytes"], plan[0]["patches"]), (160, 1600, 7))
        # Past the budget in either scratch buffer, the next dispatch; a net
        # larger than the budget alone (read and written in place).
        plan = plan_evaluation([("a", 100, 400, 2), ("b", 100, 400, 3), ("a", 100, 400, 2), ("c", 1000, 4000, 5),
                                ("d", 100, 400, 1)], budget=1000)
        self.assertEqual([[entry[0] for entry in dispatch["entries"]] for dispatch in plan], [[0, 1], [2], [3], [4]])
        self.assertEqual([dispatch["entries"][0][1:] for dispatch in plan[1:]], [(0, 0, 0)] * 3)
        table = np.frombuffer(pack_table([[0, 0, 3, 3, 10, 2, 2, 0], [9, 90, 3, 5, 10, 4, 3, 1]], 3), dtype="<u4")
        self.assertEqual(table.tolist(), [2, 3, 0, 0, 0, 0, 3, 3, 10, 2, 2, 0, 9, 90, 3, 5, 10, 4, 3, 1])
        self.assertEqual(dispatch_shape(7, 65535), (7, 1))
        self.assertEqual(dispatch_shape(70000, 65535), (65535, 2))


class NetRuns(unittest.TestCase):
    """B5.7 (docs/phase_b4_plan.md): a driver draws each net's index pattern
    at the steps it evaluates at, and consecutive nets that can share a
    draw are one batch, a run drawn in one draw over its members' outputs."""

    def test_the_steps_pattern_is_the_capacitys_without_its_zero_area_triangles(self):
        from maniml.web.gpu_net_geometry import net_indices, run_count, run_indices
        for patches, capacity, steps in ((1, 2, 2), (3, 8, 4), (2, 6, 3), (4, 5, 2), (1, 32, 7)):
            with self.subTest(patches=patches, capacity=capacity, steps=steps):
                # The kernel's output: rows and columns past the steps repeat
                # the last, so a vertex stands at (min(a, steps), min(b, steps)).
                side = capacity + 1
                grid = np.array([[patch, min(a, steps), min(b, steps)] for patch in range(patches)
                                 for a in range(side) for b in range(side)])
                full = net_indices(patches, capacity).reshape(-1, 3)
                corners = grid[full]
                u, v = corners[:, 1, 1:] - corners[:, 0, 1:], corners[:, 2, 1:] - corners[:, 0, 1:]
                area = u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0]
                np.testing.assert_array_equal(net_indices(patches, capacity, steps=steps).reshape(-1, 3),
                                              full[area != 0], "the same triangles, in the same order")
                self.assertEqual(run_count([(patches, capacity, steps)]), 6 * patches * steps * steps)
        np.testing.assert_array_equal(net_indices(2, 4, steps=4), net_indices(2, 4))
        with self.assertRaises(ValueError):
            net_indices(1, 4, steps=5)
        members = [(2, 4, 3), (1, 2, 2), (3, 6, 5)]
        np.testing.assert_array_equal(run_indices(members), np.concatenate([
            net_indices(2, 4, 0, 3), net_indices(1, 2, 2 * 25, 2), net_indices(3, 6, 2 * 25 + 9, 5)]))
        self.assertEqual(run_count(members), len(run_indices(members)))

    @staticmethod
    def net(resolution=(7, 5), uniforms=None, pipeline="surface_depth", capacity=4, program=None):
        from maniml.web.triangle_scene import TriangleDraw
        nu, nv = resolution
        patches = ((nu - 1) // 2) * ((nv - 1) // 2)
        return TriangleDraw(pipeline, np.zeros(0, dtype=Sphere().data.dtype), uniforms or {"shading": [0, 0, 0]},
                            count=patches * 6 * capacity ** 2,
                            net=np.zeros((nu * nv, 10), dtype="<f4") + len(pipeline) * nu, net_shape=(nu, nv, 10),
                            net_capacity=capacity, net_density=.1, program=program)

    def test_nets_join_a_run_as_grids_do(self):
        from maniml.web.triangle_scene import coalesce_draws, run_kind
        nets = [self.net(), self.net((9, 7), capacity=6), self.net()]
        run, = coalesce_draws(nets)
        self.assertEqual(run.net_members, tuple(nets))
        self.assertIsNone(run.net)
        self.assertEqual(run.count, sum(draw.count for draw in nets))
        # What cannot share the draw closes the run: another depth mode or
        # uniforms, a textured net, a program's net; and MANIML_NET_RUNS=0.
        barriers = [self.net(pipeline="surface"), self.net(uniforms={"shading": [.5, 0, 0]}),
                    self.net(pipeline="texsurface_depth"), self.net(program={"kind": "blend", "sources": [], "scalars": [0]})]
        self.assertEqual([run_kind(draw) for draw in barriers], ["net", "net", None, None])
        for barrier in barriers:
            with self.subTest(barrier=barrier.pipeline):
                draws = coalesce_draws([nets[0], nets[1], barrier, nets[2], nets[0]])
                self.assertEqual([len(draw.net_members) if draw.net_members else 1 for draw in draws], [2, 1, 2])
        self.assertEqual(coalesce_draws(nets, net_runs=False), nets)
        # A run's output stays within the run cap.
        with patch.object(triangle_scene_module(), "MAX_RUN_OUTPUT_BYTES", 2 * 6 * 25 * 40):
            self.assertEqual([len(draw.net_members) if draw.net_members else 1
                              for draw in coalesce_draws([self.net()] * 5)], [2, 2, 1])

    def test_a_run_is_one_batch_listing_its_members(self):
        from maniml.web.generated_geometry import MessageParts, encode_draw
        from maniml.web.gpu_net_geometry import vertices_per_patch
        from maniml.web.triangle_scene import coalesce_draws
        nets = [self.net(), self.net((9, 7), capacity=6)]
        run, = coalesce_draws(nets)
        batch = encode_draw(run, {"shading": [0, 0, 0]}, parts := MessageParts(None))
        alone = [encode_draw(draw, {"shading": [0, 0, 0]}, MessageParts(None)) for draw in nets]
        self.assertEqual(batch["net"], [single["net"] for single in alone])
        self.assertEqual(batch["num_verts"], sum(single["num_verts"] for single in alone))
        self.assertEqual(batch["count"], sum(single["count"] for single in alone))
        self.assertEqual(batch["num_verts"], 6 * vertices_per_patch(4) + 12 * vertices_per_patch(6))
        self.assertEqual(set(parts.nets), {single["net"]["hash"] for single in alone})
        self.assertNotIn(batch["hash"], {single["hash"] for single in alone})
        again = encode_draw(coalesce_draws(nets)[0], {"shading": [0, 0, 0]}, MessageParts(None))
        self.assertEqual(again["hash"], batch["hash"])
        swapped = encode_draw(coalesce_draws(nets[::-1])[0], {"shading": [0, 0, 0]}, MessageParts(None))
        self.assertNotEqual(swapped["hash"], batch["hash"], "the members' order is the layout")

    def test_the_switch(self):
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        from tests.renderer_fixtures import build_scene
        scene = build_scene(Sphere(radius=.5, resolution=(9, 7)), Sphere(radius=.4, resolution=(7, 5)).shift(RIGHT),
                            resolution=(320, 180), samples=4)
        cache = GeometryCache()
        for value, members in (("1", [2]), ("0", [1, 1]), (None, [2])):
            with self.subTest(runs=value), patch.dict(os.environ, {"MANIML_SURFACE": "nets"}):
                if value is not None:
                    os.environ["MANIML_NET_RUNS"] = value
                else:
                    os.environ.pop("MANIML_NET_RUNS", None)
                header = parse_geometry_message(serialize_scene(scene, cache, renderer="triangles"))[0]
                self.assertEqual([len(batch["net"]) if isinstance(batch["net"], list) else 1
                                  for batch in header["batches"]], members)
                self.assertEqual(cache.net_runs, value != "0")
        with patch.dict(os.environ, {"MANIML_SURFACE": "nets", "MANIML_NET_RUNS": "yes"}), self.assertRaises(ValueError):
            serialize_scene(scene, GeometryCache(), renderer="triangles")


def triangle_scene_module():
    from maniml.web import triangle_scene
    return triangle_scene


if __name__ == "__main__":
    unittest.main()


class ReferenceOrder(unittest.TestCase):
    """The accuracy reference's grid order (tests/surface_fixtures.py,
    grid_ranks, B5.9) is the order grids draw: the surface's triangle
    indices, however sorted."""

    def test_the_grid_order_is_the_surfaces_triangle_indices(self):
        from tests.surface_fixtures import grid_ranks

        sphere = Sphere(radius=1, resolution=(9, 7))
        ranks, order = grid_ranks(sphere)
        self.assertEqual(order, "cells")
        np.testing.assert_array_equal(ranks, np.arange(2 * 8 * 6))
        natural = sphere.get_triangle_indices().reshape(-1, 3).copy()
        sphere.sort_faces_back_to_front(RIGHT)
        ranks, order = grid_ranks(sphere)
        self.assertEqual(order, "sorted")
        drawn = sphere.get_triangle_indices().reshape(-1, 3)
        np.testing.assert_array_equal(drawn[ranks], natural)
        self.assertFalse(np.array_equal(ranks, np.arange(len(ranks))))
        sphere.triangle_indices = sphere.triangle_indices[:-3]
        with self.assertRaises(ValueError):
            grid_ranks(sphere)


@unittest.skipUnless(os.environ.get("MANIML_TEST_GPU") == "1", "GPU image comparison not requested")
class NetEvaluationOnTheGpu(unittest.TestCase):
    """The driver's net stage against the CPU grid (docs/phase_b2_plan.md)."""

    @classmethod
    def setUpClass(cls):
        from maniml.web.triangle_geometry import LyonFillTessellator
        from maniml.web.wgpu_renderer import WgpuRenderer
        cls.tessellator = LyonFillTessellator()
        cls.driver = WgpuRenderer()

    @classmethod
    def tearDownClass(cls):
        cls.driver.close()

    def frame(self, scene, nets, cache=None, wire=None):
        from maniml.web.generated_geometry import serialize_generated_frame
        from maniml.web.geometry import GeometryCache, parse_geometry_message
        from maniml.web.triangle_scene import TriangleMeshCache, prepare_triangle_frame
        frame = prepare_triangle_frame(scene, self.tessellator, mesh_cache=cache or TriangleMeshCache(),
                                       fill_borders=True, gpu_borders=True, net_surfaces=nets)
        frame.samples, frame.supersample = 4, 2
        header, payload = parse_geometry_message(
            serialize_generated_frame(frame, scene.camera.uniforms, wire or GeometryCache()))
        return header, payload, frame

    def render(self, scene, nets, **kwargs):
        header, payload, frame = self.frame(scene, nets, **kwargs)
        return np.asarray(self.driver.render(header, payload), dtype=int), header, payload, frame

    def test_port_surfaces_scene_matches_the_cpu_grid(self):
        from tests.test_wgpu_port import build_surfaces_scene
        grid, _, _, _ = self.render(build_surfaces_scene(), False)
        net, header, payload, _ = self.render(build_surfaces_scene(), True)
        self.assertEqual([batch["pipeline"] for batch in header["batches"]], ["surface_depth", "texsurface_depth"])
        self.assertTrue(all("net" in batch for batch in header["batches"]))
        self.assertLess(len(payload), 500_000, "the nets and one texture, not two evaluated grids")
        diff = np.abs(grid - net)
        self.assertLessEqual((diff.max(axis=2) > 24).mean(), .005)
        self.assertLessEqual(diff.max(), 8)

    def test_zoomed_sphere_has_no_facets(self):
        """Looking at the sphere's silhouette: at 16x the default sphere's
        grid shows its facets against a four times finer reference, the
        net evaluated at screen density shows far fewer, and at 64x none;
        at the normal view the net is the grid."""
        from tests.renderer_fixtures import build_scene

        def scene(resolution, zoom):
            scene = build_scene(Sphere(radius=1.0, resolution=resolution), resolution=(960, 540), samples=4)
            scene.camera.frame.scale(1 / zoom).move_to([1.0, 0, 0])
            scene.camera.refresh_uniforms()
            return scene

        grid, _, _, _ = self.render(scene((101, 51), 1), False)
        net, header, _, _ = self.render(scene((101, 51), 1), True)
        self.assertLessEqual(np.abs(grid - net).max(), 4, "at the normal view the net is the sample grid")
        for zoom, worst_grid, ratio in ((16, .0005, 2), (64, .001, 10)):
            with self.subTest(zoom=zoom):
                grid, _, _, _ = self.render(scene((101, 51), zoom), False)
                net, header, _, _ = self.render(scene((101, 51), zoom), True)
                fine, _, _, _ = self.render(scene((401, 201), zoom), False)
                facets = (np.abs(grid - fine).max(axis=2) > 24).mean()
                smooth = (np.abs(net - fine).max(axis=2) > 24).mean()
                self.assertGreater(facets, worst_grid, "the reference must expose the grid's facets")
                self.assertLess(smooth, facets / ratio)
                self.assertLessEqual(smooth, .005)
                self.assertGreater(header["batches"][0]["net"]["capacity"], 4)

    def test_every_surface_fixture_is_no_further_from_the_true_surface_as_nets(self):
        """The nets gate since B5.9 (docs/phase_b4_plan.md, "The flips";
        Taylor, 2026-09-29): every Surface fixture drawn from nets is no
        further from the true surface than drawn from Phase A's grids, by
        the pixels over 24/255 from a reference of the same frame (each
        surface's uv_func within 1/32 of a pixel, 16 times the samples per
        pixel, in each stack's order of a surface's triangles). Nets
        against grids, B5.4's gate, is reported and not judged: a net is
        drawn rounder than its grid, so it measured sameness to the old
        look."""
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.surface_fixtures import SURFACE_FIXTURES, against_reference

        nets, reference = WgpuRenderer(), WgpuRenderer()
        try:
            for name in SURFACE_FIXTURES:
                with self.subTest(fixture=name):
                    result = against_reference(SURFACE_FIXTURES[name](), self.driver, nets, reference)
                    self.assertGreater(result["grid_batches"], 0)
                    self.assertGreater(result["net_batches"], 0)
                    self.assertTrue(result["reference"]["within_tolerance"], result["reference"])
                    self.assertEqual(result["reference"]["net_defined"], 0, "each surface is its function's")
                    self.assertLessEqual(result["nets"]["pixels_rgb_over24"], result["grids"]["pixels_rgb_over24"],
                                         {key: result[key] for key in ("grids", "nets", "nets_vs_grids")})
        finally:
            nets.close()
            reference.close()

    def test_the_reference_is_the_true_surface_and_puts_the_scene_back(self):
        """The reference's own proof (tests/surface_fixtures.py): drawn
        supersampled through the clip transform's tiles, a frame is the
        frame the driver draws, to its edges' antialiasing; with the
        surfaces true it shows the facets a grid has at a zoom and it
        converges (a quarter of the tolerance moves no pixel over 24/255);
        the order of a surface's triangles moves the translucent fixture's
        picture and not an opaque one's; and the scene is put back as it
        was."""
        from unittest.mock import patch
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests import surface_fixtures as fixtures

        reference = WgpuRenderer()
        try:
            for name in ("orbs", "orbit_demo"):
                scene = fixtures.SURFACE_FIXTURES[name]()
                with patch.dict(os.environ, fixtures.PHASE_A):
                    header, payload = parse_geometry_message(
                        serialize_scene(scene, GeometryCache(), renderer="phase_a"))
                plain = np.asarray(self.driver.render(header, payload), dtype=float)
                tiled = fixtures.supersampled(reference, header, payload)
                with self.subTest(fixture=name, check="tiles"):
                    self.assertLess(fixtures.difference(tiled, plain)["fraction_pixels_rgb_over24"], 5e-5)
                    self.assertLess(fixtures.difference(tiled, plain)["mean_rgb"], .1)
            scene = fixtures.SURFACE_FIXTURES["orbs"]()
            surfaces = fixtures.surfaces_of(scene)
            before = [(surface._data, surface._data.tobytes(), surface.resolution, surface.revision)
                      for surface in surfaces]
            grids, header = fixtures.draw(scene, self.driver, "phase_a", fixtures.PHASE_A)
            coarse, records = fixtures.reference_frames(scene, reference, header["camera"], header["resolution"])
            fine, fine_records = fixtures.reference_frames(scene, reference, header["camera"], header["resolution"],
                                                           tolerance=fixtures.REFERENCE_TOLERANCE / 4)
            self.assertGreater(sum(r["triangles"] for r in fine_records), 3 * sum(r["triangles"] for r in records))
            self.assertEqual(fixtures.difference(fine["grid"], coarse["grid"])["pixels_rgb_over24"], 0)
            self.assertEqual(fixtures.difference(coarse["grid"], coarse["net"])["pixels_rgb_over24"], 0,
                             "opaque: the order moves nothing")
            self.assertGreater(fixtures.difference(coarse["grid"], grids)["pixels_rgb_over24"], 1000,
                               "the grids' facets")
            for surface, (rows, data, shape, revision) in zip(surfaces, before):
                self.assertIs(surface._data, rows)
                self.assertEqual(surface._data.tobytes(), data)
                self.assertEqual(surface.resolution, shape)
                self.assertNotIn("get_shader_data", surface.__dict__)
                self.assertGreater(surface.revision, revision)
            again, _ = fixtures.draw(scene, self.driver, "phase_a", fixtures.PHASE_A)
            self.assertTrue(np.array_equal(again, grids))
            scene = fixtures.SURFACE_FIXTURES["translucent"]()
            _, header = fixtures.draw(scene, self.driver, "phase_a", fixtures.PHASE_A)
            orders, _ = fixtures.reference_frames(scene, reference, header["camera"], header["resolution"])
            self.assertGreater(fixtures.difference(orders["grid"], orders["net"])["pixels_rgb_over24"], 100,
                               "where a translucent surface overlaps itself, the order decides what shows")
            # Faces sorted back to front (always_sort_to_camera's updater):
            # grids draw the triangle indices' new order and the grid-order
            # reference follows it (0 pixels over 24/255 from grids here,
            # 8,036 from a reference in the cells' order); a net draws its
            # own order, and its reference does not move.
            for surface in fixtures.surfaces_of(scene):
                surface.sort_faces_back_to_front(scene.camera.get_location() - surface.get_center())
            sorted_grids, header = fixtures.draw(scene, self.driver, "phase_a", fixtures.PHASE_A)
            resorted, records = fixtures.reference_frames(scene, reference, header["camera"], header["resolution"])
            self.assertEqual([record["grid_order"] for record in records], ["sorted", "sorted"])
            self.assertGreater(fixtures.difference(orders["grid"], resorted["grid"])["pixels_rgb_over24"], 1000)
            self.assertEqual(fixtures.difference(orders["net"], resorted["net"])["pixels_rgb_over24"], 0)
            self.assertLess(fixtures.difference(resorted["grid"], sorted_grids)["pixels_rgb_over24"], 50)
        finally:
            reference.close()

    def test_one_dispatch_evaluates_what_changed_and_a_small_zoom_nothing(self):
        """B5.5: every changed net of a frame in one dispatch, gathered and
        copied out, pixel for pixel what evaluating each alone in place
        draws; a pan or a zoom that moves no step count evaluates nothing,
        and a driver that kept its outputs across the moves draws what a
        fresh driver draws."""
        from unittest.mock import patch
        from maniml.web import gpu_net_geometry
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.surface_fixtures import NETS, orbs

        scene, drivers = orbs(), [WgpuRenderer(), WgpuRenderer(), WgpuRenderer()]
        caches = {id(driver): GeometryCache() for driver in drivers}
        evaluated = [[], [], []]
        for driver, calls in zip(drivers, evaluated):
            original = driver._evaluate_nets

            def counting(changed, *args, original=original, calls=calls, **kwargs):
                calls.append(len(gpu_net_geometry.plan_evaluation(
                    [(id(net["source"]), net["source_bytes"], net["size"], net["patches"]) for net in changed],
                    min(gpu_net_geometry.NET_SCRATCH_BUDGET, args[2]))))
                return original(changed, *args, **kwargs)
            driver._evaluate_nets = counting

        def draw(driver, budget=None):
            with patch.dict(os.environ, NETS):
                header, payload = parse_geometry_message(serialize_scene(scene, caches[id(driver)],
                                                                         renderer="triangles"))
            with patch.object(gpu_net_geometry, "NET_SCRATCH_BUDGET", budget or gpu_net_geometry.NET_SCRATCH_BUDGET):
                return np.asarray(driver.render(header, payload)), header

        try:
            gathered, header = draw(drivers[0])
            alone, _ = draw(drivers[1], budget=1)
            # A budget of a few nets: several dispatches reuse one scratch.
            several, _ = draw(drivers[2], budget=400_000)
            # The seventy nets are one run (B5.7), evaluated net by net.
            self.assertEqual([len(batch["net"]) for batch in header["batches"] if "net" in batch], [70])
            self.assertEqual(evaluated[:2], [[1], [70]], "one dispatch; seventy when none may share")
            self.assertGreater(evaluated[2][0], 5)
            self.assertTrue(np.array_equal(gathered, alone), "gathered and copied out, or evaluated in place")
            self.assertTrue(np.array_equal(gathered, several), "in one dispatch or in several")
            for move, evaluates in (("pan", False), (.98, False), (1 / .98, False), (.5, True), (2.2, True)):
                with self.subTest(move=move):
                    if move == "pan":
                        scene.camera.frame.shift([.2, -.1, 0])
                    else:
                        scene.camera.frame.scale(move)
                    scene.camera.refresh_uniforms()
                    before = [len(calls) for calls in evaluated]
                    kept, _ = draw(drivers[0])
                    self.assertEqual(len(evaluated[0]) > before[0], evaluates)
                    fresh_driver = WgpuRenderer()
                    try:
                        with patch.dict(os.environ, NETS):
                            header, payload = parse_geometry_message(
                                serialize_scene(scene, GeometryCache(), renderer="triangles"))
                        fresh = np.asarray(fresh_driver.render(header, payload))
                    finally:
                        fresh_driver.close()
                    # After the zoom out a fresh cache reserves for this
                    # zoom alone and the kept one keeps its larger
                    # reservation: the same steps, the same pixels.
                    self.assertTrue(np.array_equal(kept, fresh), "the kept outputs are what a fresh driver draws")
            self.assertTrue(all(count == 1 for count in evaluated[0]), "each evaluating frame is one dispatch")
        finally:
            for driver in drivers:
                driver.close()

    def test_net_runs_draw_what_each_net_draws(self):
        """B5.7: the orbs' seventy nets are one batch drawn in one draw with
        the index pattern of each member's steps, and draw pixel for pixel
        what seventy batches (MANIML_NET_RUNS=0) and the capacity's pattern
        (zero-area triangles past the steps) draw, through a zoom walk and a
        play where some members move; the kept driver evaluates only the
        members that moved or whose steps did, and draws what a fresh one
        draws."""
        from unittest.mock import patch
        from maniml.web import gpu_net_geometry
        from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene
        from maniml.web.wgpu_renderer import WgpuRenderer
        from tests.surface_fixtures import NETS, orbs

        scene = orbs()
        movers = [mob for index, mob in enumerate(scene.mobjects) if index % 3 == 0 and hasattr(mob, "resolution")]
        drivers = {name: WgpuRenderer() for name in ("runs", "each", "capacity")}
        caches = {name: GeometryCache() for name in drivers}
        evaluated, drawn = [], []
        original = drivers["runs"]._evaluate_nets

        def counting(changed, *args, **kwargs):
            evaluated.append(len(changed))
            return original(changed, *args, **kwargs)
        drivers["runs"]._evaluate_nets = counting
        pattern = drivers["runs"]._net_pattern

        def patterns(members):
            drawn.append(members)
            return pattern(members)
        drivers["runs"]._net_pattern = patterns
        indices, count = gpu_net_geometry.run_indices, gpu_net_geometry.run_count

        def at_capacity(rule):
            return lambda members: rule([(patches, capacity, capacity) for patches, capacity, _ in members])

        def draw(name, cache=None, driver=None):
            with patch.dict(os.environ, {**NETS, "MANIML_NET_RUNS": "0" if name == "each" else "1"}):
                header, payload = parse_geometry_message(serialize_scene(
                    scene, caches[name] if cache is None else cache, renderer="triangles"))
            # "capacity" evaluates at the steps and draws the capacity's
            # pattern, as B5.5's driver did.
            with patch.object(gpu_net_geometry, "run_indices", at_capacity(indices) if name == "capacity" else indices), \
                    patch.object(gpu_net_geometry, "run_count", at_capacity(count) if name == "capacity" else count):
                return np.asarray((driver or drivers[name]).render(header, payload)), header

        try:
            moves = [None, .98, .5, .5, 1 / .98, 4, "play", "play", "play"]
            for index, move in enumerate(moves):
                with self.subTest(frame=index, move=move):
                    if move == "play":
                        for mob in movers:
                            mob.shift([.03, .02, 0])
                    elif move is not None:
                        scene.camera.frame.scale(move)
                        scene.camera.refresh_uniforms()
                    before = len(evaluated)
                    runs, header = draw("runs")
                    each, each_header = draw("each")
                    capacity, _ = draw("capacity")
                    fresh_driver = WgpuRenderer()
                    try:
                        fresh, _ = draw("runs", GeometryCache(), fresh_driver)
                    finally:
                        fresh_driver.close()
                    self.assertEqual([len(batch["net"]) for batch in header["batches"]], [70])
                    self.assertEqual(sum("net" in batch for batch in each_header["batches"]), 70)
                    self.assertTrue(np.array_equal(runs, each), "one run draws what seventy batches draw")
                    self.assertTrue(np.array_equal(runs, capacity), "the steps' pattern draws what the capacity's draws")
                    self.assertTrue(np.array_equal(runs, fresh), "the kept run draws what a fresh driver draws")
                    members = drawn[-1]
                    self.assertEqual(len(members), 70)
                    self.assertLess(gpu_net_geometry.run_count(members),
                                    sum(p * gpu_net_geometry.indices_per_patch(c) for p, c, _ in members))
                    if move == "play":
                        self.assertEqual(evaluated[before:], [len(movers)], "only the members that moved")
                    elif move == .98:
                        self.assertEqual(evaluated[before:], [], "a zoom that moves no step count evaluates nothing")
        finally:
            for driver in drivers.values():
                driver.close()

    def test_camera_changes_resend_nothing_and_a_zoom_grows_the_reservation(self):
        from maniml.web.geometry import GeometryCache
        from maniml.web.triangle_scene import TriangleMeshCache
        from tests.renderer_fixtures import build_scene
        scene = build_scene(Sphere(radius=1.0), resolution=(480, 270), samples=4)
        cache, wire = TriangleMeshCache(), GeometryCache()
        first, payload, frame = self.frame(scene, True, cache=cache, wire=wire)
        self.driver.render(first, payload)
        self.assertTrue(first["net_data"])
        capacity = first["batches"][0]["net"]["capacity"]
        for step in range(4):
            scene.camera.frame.scale(.5).shift([.01, 0, 0])
            scene.camera.refresh_uniforms()
            header, payload, frame = self.frame(scene, True, cache=cache, wire=wire)
            self.driver.render(header, payload)
            self.assertEqual(payload, b"")
            self.assertEqual(header["net_data"], {})
            self.assertTrue(header["batches"][0]["cached"])
            self.assertEqual(frame.mesh_cache_stats["gpu_net_updates"], 1)
        self.assertGreater(header["batches"][0]["net"]["capacity"], capacity)
        self.assertGreater(header["batches"][0]["count"], first["batches"][0]["count"])
        # A moved surface is a new net.
        scene.mobjects[0].shift([0.2, 0, 0])
        header, payload, frame = self.frame(scene, True, cache=cache, wire=wire)
        self.assertTrue(payload)
        self.assertTrue(header["net_data"])
        self.assertEqual(frame.mesh_cache_stats["gpu_net_updates"], 2)
