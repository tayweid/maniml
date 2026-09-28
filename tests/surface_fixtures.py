"""Scenes that draw a Surface, for the nets flip's pixel gate
(docs/phase_b4_plan.md, "The flips"): each fixture's frame drawn from grids
(Phase A) and from nets must differ by at most 0.5% of pixels over 24/255.

The renderer and quality fixtures draw no Surface. These collect the
surfaces the tests and the course draw: the port's surfaces scene, the
default sphere at the zooms test_surface_net checks for facets, the CE
spelling's saddle, a textured flat surface, the orbs of the B3 and B4
episodes, the orbit demo, F1's plotted surfaces, a textured sphere zoomed
in, and translucent surfaces. Every build returns fresh source objects on
the fixture camera (tests.renderer_fixtures.build_scene).
"""

import os
import tempfile

import numpy as np

from maniml.constants import BLUE, BLUE_D, DEGREES, GREEN, LEFT, OUT, RED, RIGHT, YELLOW
from maniml.mobject.coordinate_systems import ThreeDAxes
from maniml.mobject.three_dimensions import Cube, Sphere, Torus
from maniml.mobject.types.surface import Surface, TexturedSurface
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
# The gate: the share of pixels more than 24/255 off in any channel.
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
    measures of the nets image against the grids one."""
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
