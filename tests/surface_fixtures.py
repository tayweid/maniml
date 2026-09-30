"""Scenes that draw a Surface, for the nets flip's pixel gate
(docs/phase_b4_plan.md, "The flips"), and the accuracy measure that gate
reads since B5.9: each fixture's frame drawn from grids (Phase A) and from
nets, each measured against a reference of the same frame drawn from the
true surface (``against_reference``), and nets must be no further from it
than grids. The old measure, nets against grids (``nets_against_grids``,
B5.4's 0.5% of pixels over 24/255), is reported beside it as a diagnostic.

The renderer and quality fixtures draw no Surface. These collect the
surfaces the tests and the course draw: the port's surfaces scene, the
default sphere at the zooms test_surface_net checks for facets, the CE
spelling's saddle, a textured flat surface, the orbs of the B3 and B4
episodes, the orbit demo, F1's plotted surfaces, a textured sphere zoomed
in, and translucent surfaces. Every build returns fresh source objects on
the fixture camera (tests.renderer_fixtures.build_scene).
"""

from contextlib import contextmanager
import os
import tempfile

import numpy as np

from maniml.constants import BLUE, BLUE_D, DEGREES, GREEN, LEFT, OUT, RED, RIGHT, YELLOW
from maniml.mobject.coordinate_systems import ThreeDAxes
from maniml.mobject.three_dimensions import Cube, Sphere, Torus
from maniml.mobject.types.surface import Surface, TexturedSurface
from maniml.utils import bezier_net
from tests.renderer_fixtures import build_scene


def image_path():
    """A 64x64 gradient, test_wgpu_port's texture."""
    from PIL import Image

    path = os.path.join(tempfile.gettempdir(), "maniml_wgpu_port_tex.png")
    if not os.path.exists(path):
        image = Image.new("RGB", (64, 64))
        for x in range(64):
            for y in range(64):
                image.putpixel((x, y), (4 * x, 4 * y, 255 - 2 * x))
        image.save(path)
    return path


def viewed(*mobjects, phi=70, theta=-60, zoom=1.0, center=None, resolution=(960, 540)):
    scene = build_scene(*mobjects, resolution=resolution, samples=4)
    scene.camera.frame.set_phi(phi * DEGREES)
    scene.camera.frame.set_theta(theta * DEGREES)
    if zoom != 1.0:
        scene.camera.frame.scale(1 / zoom)
    if center is not None:
        scene.camera.frame.move_to(center)
    scene.camera.refresh_uniforms()
    return scene


def port_surfaces():
    """test_wgpu_port's surfaces scene on the fixture camera: a sphere and
    a textured sphere at 1920x1080."""
    return viewed(Sphere(radius=1.4).shift(LEFT * 2.2), TexturedSurface(Sphere(radius=1.4), image_path()).shift(RIGHT * 2.2),
                  phi=60, theta=20, resolution=(1920, 1080))


def sphere_at(zoom):
    """test_surface_net's no-facets scene: the default sphere's silhouette."""
    scene = build_scene(Sphere(radius=1.0), resolution=(960, 540), samples=4)
    scene.camera.frame.scale(1 / zoom).move_to([1.0, 0, 0])
    scene.camera.refresh_uniforms()
    return scene


def ce_saddle():
    """The CE spelling's checkerboard saddle, stroked."""
    surface = Surface(lambda u, v: np.array([u, v, u * v]), u_range=(-1, 1), v_range=(-1, 1), resolution=8,
                      fill_color=RED, fill_opacity=0.5, checkerboard_colors=[RED, BLUE_D], stroke_width=0.5)
    return viewed(surface.scale(2), phi=65, theta=-40)


def textured_flat():
    """test_native_camera's flat textured surface."""
    surface = Surface(u_range=(-1, 1), v_range=(-1, 1), resolution=(2, 2), color="#55CC99")
    return viewed(TexturedSurface(surface, image_path()).scale(2), phi=50, theta=-70)


def orbs():
    """The B3 and B4 episodes' agents: many small spheres, tilted."""
    colors = (BLUE, RED, GREEN, YELLOW)
    spheres = [Sphere(radius=.23, color=colors[(i + j) % 4], resolution=(16, 10)).move_to([i * .7 - 3, j * .7 - 1.4, .3])
               for i in range(10) for j in range(5)]
    small = [Sphere(radius=.065, color=colors[i % 4], resolution=(12, 8)).move_to([i * .3 - 3, 2.2, .16])
             for i in range(20)]
    return viewed(*spheres, *small, phi=60, theta=-80)


def orbit_demo():
    """dogfood/orbit_demo.py's frame: axes, a torus and a cube."""
    cube = Cube(side_length=1.2).set_color(YELLOW).shift(OUT * 1.5)
    return viewed(ThreeDAxes(), Torus(r1=2, r2=.6, color=BLUE), cube, phi=70, theta=-45)


def cobb_douglas():
    """F1's utility surface over its axes."""
    plane = Surface(lambda u, v: np.array([u - 5, v - 5, u ** .5 + v ** .5 - 3]), resolution=(10, 10),
                    fill_color="#29ABCA", v_range=[.5, 10], u_range=[.5, 10])
    axes = ThreeDAxes(x_range=(0, 10, 1), y_range=(0, 10, 1), z_range=(0, 1, 1))
    return viewed(axes, plane, phi=75, theta=180, zoom=.6)


def fill_by_value():
    """F1's surface coloured by height."""
    axes = ThreeDAxes(x_range=(0, 5, 1), y_range=(0, 5, 1), z_range=(-1, 1, .5))
    plane = Surface(lambda u, v: axes.c2p(u, v, (u + v) / 5 - 1), resolution=(10, 10), v_range=[0, 5], u_range=[0, 5])

    def rgba(points):
        z = np.clip(points[:, 2], -.5, .5)
        return np.column_stack([.5 + z, np.full_like(z, .8), .5 - z, np.ones_like(z)])

    plane.set_color_by_rgba_func(rgba)
    return viewed(axes, plane, phi=75, theta=-160, zoom=.7)


def textured_zoom():
    """A textured sphere four times zoomed, off centre."""
    return viewed(TexturedSurface(Sphere(radius=1.4), image_path()), phi=60, theta=20, zoom=4, center=[.8, .6, .5])


def translucent():
    """A sphere and a torus at partial opacity, overlapping."""
    return viewed(Sphere(radius=1.2).set_opacity(.5).shift(LEFT * 1.5),
                  Torus(r1=1.2, r2=.4, color=GREEN).set_opacity(.6), phi=65, theta=-30)


SURFACE_FIXTURES = {
    "port_surfaces": port_surfaces,
    "sphere_1x": lambda: sphere_at(1), "sphere_4x": lambda: sphere_at(4),
    "sphere_16x": lambda: sphere_at(16), "sphere_64x": lambda: sphere_at(64),
    "ce_saddle": ce_saddle, "textured_flat": textured_flat, "orbs": orbs, "orbit_demo": orbit_demo,
    "cobb_douglas": cobb_douglas, "fill_by_value": fill_by_value, "textured_zoom": textured_zoom,
    "translucent": translucent,
}

# The nets flip's stack, the default renderer under these switches, as
# benchmarks.browser_frames' phase_a_nets and episode_frames' nets draw it.
NETS = {"MANIML_FILL": "meshes", "MANIML_SURFACE": "nets", "MANIML_PROGRAMS": "off", "MANIML_BORDER_GENERATOR": "gpu"}
# Phase A forced reads only these of the stack's switches: stated so that a
# caller's environment cannot move the reference.
PHASE_A = {"MANIML_BORDER_GENERATOR": "gpu"}
# B5.4's gate, nets against grids, a diagnostic since B5.9: the share of
# pixels more than 24/255 off in any channel.
PIXEL_LIMIT = .005


def draw(scene, driver, renderer, environment):
    """The scene serialized through a fresh cache under ``environment`` and
    drawn by ``driver``: (straight RGBA as an int array, header)."""
    from unittest.mock import patch

    from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene

    with patch.dict(os.environ, environment):
        message = serialize_scene(scene, GeometryCache(), renderer=renderer)
    header, payload = parse_geometry_message(message)
    return np.asarray(driver.render(header, payload), dtype=int), header


def nets_against_grids(name, grids_driver, nets_driver):
    """Fixture ``name`` drawn from Phase A's grids ("phase_a") and from nets
    (the default renderer under NETS), each by a driver of its own: the
    surface batches of each, and benchmarks.paint_retention.difference's
    measures of the nets image against the grids one (B5.4's measure;
    accuracy reports it beside the gate as ``nets_vs_grids``)."""
    grids, grid_header = draw(SURFACE_FIXTURES[name](), grids_driver, "phase_a", PHASE_A)
    nets, net_header = draw(SURFACE_FIXTURES[name](), nets_driver, "triangles", NETS)
    delta = np.abs(grids - nets)
    return {"resolution": net_header["resolution"],
            "grid_batches": sum(batch["pipeline"].startswith(("surface", "texsurface")) and "net" not in batch
                                for batch in grid_header["batches"]),
            "net_batches": sum("net" in batch for batch in net_header["batches"]),
            "mean_rgb": float(delta[..., :3].mean()),
            "fraction_pixels_rgb_over24": float((delta[..., :3].max(axis=-1) > 24).mean()),
            "max_rgba": float(delta.max()), "mean_alpha": float(delta[..., 3].mean())}



# The accuracy measure (B5.9, docs/phase_b4_plan.md, "The flips"). A net is
# drawn rounder than its grid, so a gate that measures nets against grids
# fails a net for being the more accurate (B5.7's lattice). The reference
# is the frame drawn from the true surface instead: every Surface's
# uv_func evaluated so densely that its facets are a small fraction of a
# pixel from it (REFERENCE_TOLERANCE), drawn as Phase A draws a grid (the
# surface pipeline from CPU vertices: no net is evaluated), with
# REFERENCE_SUPERSAMPLE² times the samples of the frame per pixel. Each
# stack is measured against it, and the gate is that nets are no further
# from it than grids.

# Each axis of the reference is drawn at this many times the frame's
# pixels, box-filtered to the frame (16 times the samples per pixel, over
# the driver's own 4x MSAA and 2x2 resolve), in tiles of the frame's size
# placed by the uniforms' clip transform (common.wgsl, emit_gl_position).
REFERENCE_SUPERSAMPLE = 4
# The reference's own error bound, in output pixels: the largest deviation
# of one of its facets from the surface, estimated from its projected
# samples (facet_error), a third of it along each parameter and a third
# for the twist.
REFERENCE_TOLERANCE = 1 / 32
# The most a patch's samples are multiplied by along a parameter.
REFERENCE_MAX_FACTOR = 1024
# A facet counts toward the error only if its samples are past the near
# plane (w, in focal distances: emit_gl_position's depth clips w < 1/11)
# and its bounds meet the frame (NDC within this).
_W_MIN, _FRAME = 1 / 11, 1.05


def project(points, camera, resolution, fixed=False):
    """Output pixel positions (x right, y down) of world ``points`` as
    emit_gl_position places them under the frame's ``camera`` uniforms,
    and each point's w and NDC."""
    points = np.asarray(points, dtype=float).reshape(-1, 3)
    if not fixed:
        view = np.asarray(camera["view"], dtype=float).reshape(4, 4).T  # the uniform is column-major
        points = points @ view[:3, :3].T + view[:3, 3]
    scaled = points * np.asarray(camera["frame_rescale_factors"], dtype=float)
    w = 1.0 - scaled[:, 2]
    ndc = scaled[:, :2] / np.where(np.abs(w) > 1e-12, w, 1e-12)[:, None]
    width, height = resolution
    return np.stack([(ndc[:, 0] + 1) * width / 2, (1 - ndc[:, 1]) * height / 2], axis=1), w, ndc


def facet_error(points, camera, resolution, fixed=False):
    """How far a grid of samples ``(nu, nv, 3)`` drawn as facets is from the
    surface it samples, in output pixels, estimated from the projected
    samples: an eighth of the largest second difference along u and along
    v (the sagitta of a chord) and a quarter of the largest twist (how far
    a quad's centre is from the diagonal its two triangles share), over
    the facets in front of the eye whose bounds meet the frame. Returns
    (along u, along v, twist)."""
    nu, nv = points.shape[:2]
    pixels, w, ndc = project(points, camera, resolution, fixed)
    usable = ((w > _W_MIN) & np.isfinite(pixels).all(axis=1)).reshape(nu, nv)
    pixels, ndc = pixels.reshape(nu, nv, 2), ndc.reshape(nu, nv, 2)

    def largest(delta, corners, divisor):
        keep = np.logical_and.reduce([usable[c] for c in corners])
        low = np.minimum.reduce([ndc[c] for c in corners])
        high = np.maximum.reduce([ndc[c] for c in corners])
        keep &= (low <= _FRAME).all(axis=-1) & (high >= -_FRAME).all(axis=-1)
        return float(np.linalg.norm(delta, axis=-1)[keep].max()) / divisor if keep.any() else 0.0

    along_u = along_v = twist = 0.0
    if nu >= 3:
        corners = (np.s_[:-2], np.s_[1:-1], np.s_[2:])
        along_u = largest(pixels[:-2] - 2 * pixels[1:-1] + pixels[2:], corners, 8)
    if nv >= 3:
        corners = (np.s_[:, :-2], np.s_[:, 1:-1], np.s_[:, 2:])
        along_v = largest(pixels[:, :-2] - 2 * pixels[:, 1:-1] + pixels[:, 2:], corners, 8)
    if nu >= 2 and nv >= 2:
        corners = (np.s_[1:, 1:], np.s_[1:, :-1], np.s_[:-1, 1:], np.s_[:-1, :-1])
        along_uv = pixels[1:, 1:] - pixels[1:, :-1] - pixels[:-1, 1:] + pixels[:-1, :-1]
        twist = largest(along_uv, corners, 4)
    return along_u, along_v, twist


def uv_samples(function, u_range, v_range, nu, nv):
    """``function`` on the ``(nu, nv)`` grid of the ranges, as
    Surface.init_points samples it: ``(nu, nv, 3)``. One call over arrays
    where the function takes them and agrees with its pointwise values,
    else point by point."""
    us, vs = np.linspace(*u_range, nu), np.linspace(*v_range, nv)
    try:
        grid = np.asarray(function(*np.meshgrid(us, vs, indexing="ij")), dtype=float)
    except Exception:
        grid = None
    if grid is not None and grid.shape == (3, nu, nv):
        grid = np.moveaxis(grid, 0, -1)
        probes = {(0, 0), (nu - 1, nv - 1), (nu // 2, nv // 3), (nu // 3, nv - 1)}
        if all(np.array_equal(grid[i, j], np.asarray(function(us[i], vs[j]), dtype=float)) for i, j in probes):
            return grid
    return np.array([[function(u, v) for v in vs] for u in us], dtype=float)


def _columns(dtype, name):
    """The float32 columns of field ``name`` in a surface's data rows."""
    offset = dtype.fields[name][1] // 4
    return slice(offset, offset + int(np.prod(dtype.fields[name][0].shape or (1,))))


def _true_normals(positions, theirs):
    """Unit normals of a sample grid ``(m, n, 3)`` from its derivatives,
    oriented as ``theirs`` (the surface's own normal vectors there), which
    stand where the derivatives' cross product vanishes (a pole)."""
    tangent_u = np.gradient(positions, axis=0, edge_order=2)
    tangent_v = np.gradient(positions, axis=1, edge_order=2)
    normals = np.cross(tangent_u, tangent_v)
    lengths = np.linalg.norm(normals, axis=-1)
    scale = np.linalg.norm(tangent_u, axis=-1) * np.linalg.norm(tangent_v, axis=-1)
    defined = np.isfinite(lengths) & (scale > 0) & (lengths > 1e-9 * scale)
    unit = normals / np.where(defined, lengths, 1)[..., None]
    unit *= np.where((unit * theirs).sum(axis=-1) < 0, -1.0, 1.0)[..., None]
    their_lengths = np.linalg.norm(theirs, axis=-1)
    fallback = theirs / np.where(their_lengths > 0, their_lengths, 1)[..., None]
    return np.where(defined[..., None], unit, fallback)


def _grow(ku, kv, along_u, along_v, twist, budget):
    """A patch's factors for the next try: each direction's own error
    falls with the square of its factor, and the twist with their product,
    so what the twist still needs goes to the direction whose own error is
    the larger (a sphere seen close to the eye curves one way)."""
    grown = [k if error <= budget else k * np.sqrt(error / budget)
             for k, error in ((ku, along_u), (kv, along_v))]
    left = twist * ku * kv / (np.ceil(grown[0]) * np.ceil(grown[1]))
    if left > budget:
        grown[0 if along_u >= along_v else 1] *= left / budget
    return tuple(min(REFERENCE_MAX_FACTOR, int(np.ceil(k))) for k in grown)


def grid_ranks(surface):
    """Where each triangle of ``surface``'s grid comes in the order grids
    draw them: Surface.get_shader_data reads the grid through
    get_triangle_indices, which compute_triangle_indices makes cell by
    cell, row by row, two triangles a cell (top left, bottom left, top
    right; then top right, bottom left, bottom right), and which
    sort_faces_back_to_front (always_sort_to_camera's updater) reorders in
    place. Returns each triangle's rank, indexed by its place in
    compute_triangle_indices' order (2 × cell + which half), and "cells"
    where the order is that one or "sorted" where it is another; indices
    that are no order of those triangles raise."""
    nu, nv = surface.resolution
    grid = np.arange(nu * nv).reshape(nu, nv)
    top_left, bottom_left = grid[:-1, :-1].reshape(-1), grid[1:, :-1].reshape(-1)
    top_right, bottom_right = grid[:-1, 1:].reshape(-1), grid[1:, 1:].reshape(-1)
    natural = np.stack([np.stack([top_left, bottom_left, top_right], axis=1),
                        np.stack([top_right, bottom_left, bottom_right], axis=1)], axis=1).reshape(-1, 3)
    drawn = np.asarray(surface.get_triangle_indices()).reshape(-1, 3)
    if drawn.shape == natural.shape and np.array_equal(drawn, natural):
        return np.arange(len(natural)), "cells"
    size = np.int64(nu * nv)
    key = lambda triangles: (triangles[:, 0].astype(np.int64) * size + triangles[:, 1]) * size + triangles[:, 2]
    natural_keys, drawn_keys = key(natural), key(drawn)
    sorter = np.argsort(natural_keys)
    found = sorter[np.clip(np.searchsorted(natural_keys, drawn_keys, sorter=sorter), 0, len(sorter) - 1)]
    if (drawn.shape != natural.shape or not np.array_equal(natural_keys[found], drawn_keys)
            or len(np.unique(found)) != len(found)):
        raise ValueError(f"{type(surface).__name__}'s triangle indices are no order of its grid's triangles")
    ranks = np.empty(len(natural), dtype=np.int64)
    ranks[found] = np.arange(len(found))
    return ranks, "sorted"


def true_patches(surface, camera, resolution, tolerance=REFERENCE_TOLERANCE, samples_cache=None):
    """The reference's samples of ``surface`` in the frame, patch by patch:
    each patch of its net a grid of ``factors`` times its samples along
    each parameter, grown until facet_error is within ``tolerance`` or a
    factor reaches REFERENCE_MAX_FACTOR (a patch off the frame keeps its
    own samples). Returns the samples as data rows, their triangles
    (``(count, 3)`` into the rows), each triangle's place in the order a
    stack draws it (``orders``: "grid", the order of the grid triangle it
    refines in the surface's own triangle indices (grid_ranks: cell by
    cell, row by row, unless its faces were sorted); "net", patch by
    patch, whatever the indices, as a net draws) and a record.

    The samples' positions are the surface's uv_func, carried into the
    frame by the affine map that takes the construction's samples of it to
    the surface's own (fitted, and required to fit to float32 rounding), so
    a surface shifted, scaled, rotated or faded is its function's; their
    normals the true surface's (the cross product of its derivatives,
    oriented as the surface's own, which stands where it vanishes, as at
    a sphere's poles). Every other field (colour, opacity, image
    coordinates) is the surface's net evaluated there, which is how a
    surface defines it. A surface that is not an affine image of its
    function (a morph, a partial surface) is its own net evaluated densely
    instead (``net_defined``).

    ``samples_cache``, a dict kept across calls, shares the function's
    samples between surfaces of one function: the same code (a bound
    method's function) giving the same construction samples, bit for bit,
    as a lattice's spheres of one radius do."""
    nu, nv = surface.resolution
    patches_u, patches_v = (nu - 1) // 2, (nv - 1) // 2
    dtype = surface._data.dtype
    point, normal = _columns(dtype, "point"), _columns(dtype, "d_normal_point")
    net = surface.get_net()
    fixed = bool(surface.uniforms.get("is_fixed_in_frame", 0))
    own = bezier_net.evaluate(net, 2, 2)
    # A TexturedSurface keeps its uv_surface's function and ranges.
    origin = getattr(surface, "uv_surface", surface)
    function = getattr(surface, "uv_func", None)
    u_range, v_range = tuple(origin.u_range[:2]), tuple(origin.v_range[:2])
    mapping, residual, identity = None, None, None
    if callable(function):
        source = uv_samples(function, u_range, v_range, nu, nv).reshape(-1, 3)
        identity = (getattr(function, "__func__", None) or id(function), u_range, v_range, nu, nv, source.tobytes())
        design = np.concatenate([source, np.ones((len(source), 1))], axis=1)
        target = own[..., point].reshape(-1, 3)
        if np.isfinite(design).all():
            mapping = np.linalg.lstsq(design, target, rcond=None)[0]
            residual = float(np.abs(design @ mapping - target).max())
            if not residual <= 1e-5 * max(1.0, float(np.abs(target).max())):
                mapping = None
    us, vs = np.linspace(*u_range, nu), np.linspace(*v_range, nv)
    ranks, grid_order = grid_ranks(surface)
    budget = tolerance / 3
    rows, triangles, grid_keys, net_keys, factors, worst, worst_patch, base = [], [], [], [], [], 0.0, None, 0
    culled = 0

    def samples(block, i, j, ku, kv):
        fields = bezier_net.evaluate(block, 2 * ku, 2 * kv)
        if mapping is None:
            return fields, fields[..., point]
        key = (identity, i, j, ku, kv)
        grid = None if samples_cache is None else samples_cache.get(key)
        if grid is None:
            grid = uv_samples(function, (us[2 * i], us[2 * i + 2]), (vs[2 * j], vs[2 * j + 2]), 2 * ku + 1, 2 * kv + 1)
            if samples_cache is not None:
                samples_cache[key] = grid
        return fields, grid @ mapping[:3] + mapping[3]

    for i in range(patches_u):
        for j in range(patches_v):
            block = net[2 * i:2 * i + 3, 2 * j:2 * j + 3]
            ku = kv = 1
            fields, positions = samples(block, i, j, ku, kv)
            _, w, _ = project(positions, camera, resolution, fixed)
            if (w <= _W_MIN).any() and (w > _W_MIN).any():
                # Across the eye's plane: measure it finer from the start.
                ku = kv = 4
                fields, positions = samples(block, i, j, ku, kv)
            for attempt in range(9):
                along_u, along_v, twist = facet_error(positions, camera, resolution, fixed)
                grown = _grow(ku, kv, along_u, along_v, twist, budget)
                if grown == (ku, kv) or attempt == 8:
                    break  # the errors are the samples' kept
                ku, kv = grown
                fields, positions = samples(block, i, j, ku, kv)
            if along_u + along_v + twist >= worst:
                worst, worst_patch = along_u + along_v + twist, [i, j, ku, kv]
            factors.append((ku, kv))
            if mapping is not None:
                theirs = fields[..., normal] - fields[..., point]
                lengths = np.linalg.norm(theirs, axis=-1)
                nudge = float(np.median(lengths[lengths > 0])) if (lengths > 0).any() else surface.normal_nudge
                fields[..., point] = positions
                fields[..., normal] = positions + nudge * _true_normals(positions, theirs)
            side = 2 * kv + 1
            a, b = np.meshgrid(np.arange(2 * ku), np.arange(2 * kv), indexing="ij")
            a, b = a.reshape(-1), b.reshape(-1)
            corner = a * side + b
            # Surface.compute_triangle_indices' two triangles a quad.
            patch = np.stack([corner, corner + side, corner + 1, corner + 1, corner + side,
                              corner + side + 1], axis=1).reshape(-1, 3)
            # Grids draw the grid's triangles in the surface's index order
            # (two cells a patch each way, two triangles a cell): each of
            # these triangles takes the rank of the grid triangle its
            # centroid lies in (the cell's first, s + t <= 1 in the cell's
            # own parameters, or its second). Nets draw patch by patch,
            # each by its rows.
            half = np.tile([1 / 3, 2 / 3], len(a))
            s = (np.repeat(a % ku, 2) + half) / ku
            t = (np.repeat(b % kv, 2) + half) / kv
            cells = np.repeat((2 * i + a // ku) * (nv - 1) + 2 * j + b // kv, 2)
            cell = np.stack([ranks[2 * cells + (s + t > 1)], np.repeat(a % ku, 2), np.repeat(b % kv, 2)], axis=1)
            place = np.repeat(np.stack([np.full_like(a, i * patches_v + j), a, b], axis=1), 2, axis=0)
            # A triangle that draws no pixel is left out: one wholly past
            # the near plane, or in front of the eye and off the frame.
            _, w, ndc = project(fields[..., point], camera, resolution, fixed)
            w, ndc = w[patch], ndc[patch]
            ahead = (w > 0).all(axis=1)
            drawn = ~(ahead & (w < _W_MIN).all(axis=1))
            drawn &= ~ahead | ((ndc.min(axis=1) <= _FRAME).all(axis=1) & (ndc.max(axis=1) >= -_FRAME).all(axis=1))
            used = np.unique(patch[drawn])
            renumber = np.full(fields.shape[0] * fields.shape[1], -1)
            renumber[used] = np.arange(len(used)) + base
            rows.append(fields.reshape(-1, fields.shape[-1])[used])
            triangles.append(renumber[patch[drawn]])
            grid_keys.append(cell[drawn])
            net_keys.append(place[drawn])
            culled += int((~drawn).sum())
            base += len(used)
    rows = np.ascontiguousarray(np.concatenate(rows).astype(np.float32)).view(dtype).reshape(-1)
    triangles = np.concatenate(triangles)
    orders = {}
    for name, keys in (("grid", np.concatenate(grid_keys)), ("net", np.concatenate(net_keys))):
        # Two triangles a quad keep their order (lexsort is stable).
        orders[name] = np.lexsort(keys.T[::-1])
    counts = np.array(factors)
    return rows, triangles, orders, {
        "surface": type(surface).__name__, "resolution": [nu, nv], "patches": len(factors),
        "factors_max": [int(counts[:, 0].max()), int(counts[:, 1].max())],
        "patches_refined": int(((counts[:, 0] > 1) | (counts[:, 1] > 1)).sum()),
        "triangles": len(triangles), "culled": culled, "error_px": worst, "worst_patch": worst_patch,
        "within_tolerance": worst <= tolerance, "grid_order": grid_order,
        "net_defined": mapping is None, "fit_residual": residual}


def surfaces_of(scene):
    """The scene's Surface leaves that draw a net, each once."""
    seen, found = set(), []
    for mob in scene.mobjects:
        for member in mob.get_family():
            if (id(member) not in seen and isinstance(member, Surface) and getattr(member, "net", False)
                    and member.has_points()):
                seen.add(id(member))
                found.append(member)
    return found


class TrueSurfaces:
    """Every Surface of a scene drawn as its true_patches while this holds
    (``order`` picks whose triangle order), each through a get_shader_data
    of its own, as Phase A's grid path reads a surface; ``restore`` takes
    the getters away. The surfaces' rows and nets are untouched, and each
    change moves their revision."""

    def __init__(self, scene, camera, resolution, tolerance=REFERENCE_TOLERANCE, samples_cache=None):
        self.entries, self.records = [], []
        for surface in surfaces_of(scene):
            rows, triangles, orders, record = true_patches(surface, camera, resolution, tolerance, samples_cache)
            self.entries.append((surface, rows, triangles, orders))
            self.records.append(record)

    def order(self, name):
        for surface, rows, triangles, orders in self.entries:
            vertices = rows[triangles[orders[name]].reshape(-1)]
            surface.get_shader_data = lambda vertices=vertices: vertices
            surface._bump_revision()

    def restore(self):
        for surface, *_ in self.entries:
            surface.__dict__.pop("get_shader_data", None)
            surface._bump_revision()


@contextmanager
def true_surfaces(scene, camera, resolution, tolerance=REFERENCE_TOLERANCE, samples_cache=None):
    """TrueSurfaces for the frame (``camera`` and ``resolution``, a
    header's), in the grids' order, restored on exit."""
    surfaces = TrueSurfaces(scene, camera, resolution, tolerance, samples_cache)
    try:
        surfaces.order("grid")
        yield surfaces
    finally:
        surfaces.restore()


def supersampled(driver, header, payload, factor=REFERENCE_SUPERSAMPLE):
    """The frame of ``header`` drawn at ``factor`` times its pixels along
    each axis and box-filtered back to its size: ``factor``² tiles of the
    frame's own size, each the frame's uniforms with a clip transform
    that magnifies its part of the frame onto the whole target. A float
    array of the driver's output (premultiplied RGBA, 0-255)."""
    width, height = header["resolution"]
    if width % factor or height % factor:
        raise ValueError(f"a {width}x{height} frame does not divide into {factor}x{factor} tiles")
    if any("clip_transform" in (batch.get("uniforms") or {}) for batch in header["batches"]):
        raise ValueError("a batch sets its own clip transform")
    tile_w, tile_h = width // factor, height // factor
    image = np.zeros((height, width, 4))
    for row in range(factor):
        for column in range(factor):
            # This tile's centre in NDC (x right, y up), moved to the target's.
            cx, cy = -1 + (2 * column + 1) / factor, 1 - (2 * row + 1) / factor
            tile = {**header, "camera": {**header["camera"],
                                         "clip_transform": [factor, factor, -factor * cx, -factor * cy]}}
            pixels = np.asarray(driver.render(tile, payload), dtype=float)
            image[row * tile_h:(row + 1) * tile_h, column * tile_w:(column + 1) * tile_w] = (
                pixels.reshape(tile_h, factor, tile_w, factor, 4).mean(axis=(1, 3)))
    return image


def reference_frames(scene, driver, camera, resolution, tolerance=REFERENCE_TOLERANCE, samples_cache=None):
    """The references of ``scene``'s frame: its surfaces made true
    (true_surfaces, for the frame's ``camera`` and ``resolution``),
    serialized as Phase A forced and drawn supersampled by ``driver``, once
    in each stack's order of a surface's triangles. Returns ({order: float
    image}, per-surface records)."""
    from unittest.mock import patch

    from maniml.web.geometry import GeometryCache, parse_geometry_message, serialize_scene

    images = {}
    with true_surfaces(scene, camera, resolution, tolerance, samples_cache) as surfaces:
        for order in ("grid", "net"):
            surfaces.order(order)
            with patch.dict(os.environ, PHASE_A):
                header, payload = parse_geometry_message(serialize_scene(scene, GeometryCache(), renderer="phase_a"))
            images[order] = supersampled(driver, header, payload)
    return images, surfaces.records


def difference(reference, image):
    """benchmarks.paint_retention.difference, with the pixel count."""
    delta = np.abs(np.asarray(reference, dtype=float) - np.asarray(image, dtype=float))
    over = delta[..., :3].max(axis=-1) > 24
    return {"mean_rgb": float(delta[..., :3].mean()), "fraction_pixels_rgb_over24": float(over.mean()),
            "pixels_rgb_over24": int(over.sum()), "max_rgba": float(delta.max()),
            "mean_alpha": float(delta[..., 3].mean())}


def accuracy(grids, nets, references):
    """Each stack against the reference drawn in its order (``references``,
    reference_frames'), the gate's measure; nets against grids, B5.4's
    measure, and nets against the reference in the grids' order, as
    diagnostics; how far apart the order alone puts the two references
    (where a translucent surface overlaps itself, which of its triangles is
    drawn first decides what shows); and, where grids and nets differ by
    more than 24/255, which of the two is the nearer its reference.
    ``passes`` is the gate: nets no further from the true surface than
    grids, by the pixels over 24/255. A frame whose grids and nets are
    nowhere more than 24/255 apart is a ``tie``, one picture by the gate's
    own threshold, whatever their counts against their references: those
    differ there by pixels at the threshold's edge (the orbit demo's frame
    mid-play, 596 against 589 where the stacks and the references agree
    within 24/255 everywhere), noise below what the gate can tell."""
    grids, nets = np.asarray(grids, dtype=float), np.asarray(nets, dtype=float)
    result = {"grids": difference(references["grid"], grids), "nets": difference(references["net"], nets),
              "nets_vs_grids": difference(grids, nets),
              "nets_vs_grid_order_reference": difference(references["grid"], nets),
              "reference_orders": difference(references["grid"], references["net"])}
    differ = np.abs(grids - nets)[..., :3].max(axis=-1) > 24
    grid_off = np.abs(grids - references["grid"])[..., :3].max(axis=-1)[differ]
    net_off = np.abs(nets - references["net"])[..., :3].max(axis=-1)[differ]
    result["where_they_differ"] = {"pixels": int(differ.sum()), "nets_nearer": int((net_off < grid_off).sum()),
                                   "grids_nearer": int((grid_off < net_off).sum()),
                                   "equal": int((grid_off == net_off).sum())}
    result["tie"] = result["nets_vs_grids"]["pixels_rgb_over24"] == 0
    result["passes"] = result["tie"] or result["nets"]["pixels_rgb_over24"] <= result["grids"]["pixels_rgb_over24"]
    return result


def reference_summary(records, tolerance=REFERENCE_TOLERANCE):
    """What the references of a frame were made of."""
    return {"supersample": REFERENCE_SUPERSAMPLE, "tolerance_px": tolerance, "surfaces": len(records),
            "net_defined": sum(record["net_defined"] for record in records),
            "error_px": max((record["error_px"] for record in records), default=0.0),
            "within_tolerance": all(record["within_tolerance"] for record in records),
            "sorted_surfaces": sum(record["grid_order"] == "sorted" for record in records),
            "factors_max": [max((record["factors_max"][axis] for record in records), default=1) for axis in (0, 1)],
            "triangles": sum(record["triangles"] for record in records)}


def against_reference(scene, grids_driver, nets_driver, reference_driver, tolerance=REFERENCE_TOLERANCE,
                      samples_cache=None):
    """``scene``'s frame drawn from Phase A's grids and from nets (the
    default renderer under NETS), each by a driver of its own, and its
    references (reference_frames, by a third): accuracy's measures, the
    surface batches of each stack and what the references were made of."""
    grids, grid_header = draw(scene, grids_driver, "phase_a", PHASE_A)
    nets, net_header = draw(scene, nets_driver, "triangles", NETS)
    references, records = reference_frames(scene, reference_driver, grid_header["camera"],
                                           grid_header["resolution"], tolerance, samples_cache)
    return {"resolution": grid_header["resolution"],
            "grid_batches": sum(batch["pipeline"].startswith(("surface", "texsurface")) and "net" not in batch
                                for batch in grid_header["batches"]),
            "net_batches": sum("net" in batch for batch in net_header["batches"]),
            **accuracy(grids, nets, references), "reference": reference_summary(records, tolerance)}
