"""Source-scene fixtures shared by renderer experiments and fidelity tests.

These builders allocate no graphics context and do not serialize geometry.
They use the production camera's coordinate/uniform behavior with only its
framebuffer allocation replaced. Every build returns fresh source objects.
Fixture expectations describe visible coverage, never batch or pass counts.
"""

from dataclasses import dataclass
from functools import partial
from types import SimpleNamespace
from typing import Callable

import numpy as np

from maniml.camera.camera import Camera
from maniml.camera.camera_frame import CameraFrame
from maniml.constants import BLUE, GREEN, RED, WHITE, YELLOW
from maniml.mobject.geometry import Annulus, Circle, Square
from maniml.mobject.mobject import Group, Mobject, Point
from maniml.mobject.types.vectorized_mobject import VMobject


@dataclass
class FixtureScene:
    camera: Camera
    mobjects: list[Mobject]
    render_groups: list[Group]


@dataclass(frozen=True)
class CoverageProbe:
    """World-xy interior coverage of a fixture's single opaque flat path.

    Probes deliberately avoid boundaries. They are geometric expectations,
    not antialiasing or color thresholds; they apply to the cases carrying
    them, whose cameras are untransformed and whose strokes/borders are zero.
    """

    point: tuple[float, float]
    covered: bool


@dataclass(frozen=True)
class RendererFixture:
    name: str
    build: Callable[[], FixtureScene]
    features: tuple[str, ...]
    probes: tuple[CoverageProbe, ...] = ()


def build_scene(*mobjects, resolution=(384, 216), samples=0,
                background=(0.08, 0.11, 0.14, 1.0)) -> FixtureScene:
    """Make a source snapshot without starting a Scene or graphics device."""
    camera = Camera.__new__(Camera)
    camera.frame = CameraFrame()
    camera.light_source = Point(np.array([-10.0, 10.0, 10.0]))
    camera.uniforms = {}
    camera.fbo = camera.draw_fbo = SimpleNamespace(size=tuple(resolution))
    camera.background_rgba = list(background)
    camera.samples = samples
    return FixtureScene(camera, list(mobjects), [Group(*mobjects)])


def closed_contours(*contours, **style) -> VMobject:
    """Build one compound path, preserving each supplied contour direction."""
    path = VMobject(fill_color=WHITE, fill_opacity=1.0, stroke_width=0,
                    fill_border_width=0)
    for contour in contours:
        points = np.asarray(contour, dtype=float)
        if points.shape[1] == 2:
            points = np.column_stack((points, np.zeros(len(points))))
        path.start_new_path(points[0])
        path.add_points_as_corners(points[1:])
        path.close_path()
    if style:
        path.set_style(**style)
    return path


def concave_quad(alpha: float) -> VMobject:
    """The same four path vertices pass through a required diagonal flip.

    In the unshifted example B moves (4, 0) -> (1, 3), with A=(0, 0),
    C=(4, 4), D=(0, 4). The AC diagonal ceases to be valid at alpha=2/3.
    Centering the path keeps all four corners inside the test viewport.
    """
    return closed_contours([
        (-2, -2), (2 - 3 * alpha, -2 + 3 * alpha), (2, 2), (-2, 2),
    ])


def _annulus():
    return build_scene(Annulus(inner_radius=0.55, outer_radius=1.2,
                               color=WHITE, fill_opacity=1, stroke_width=0,
                               fill_border_width=0))


def _nested_contours():
    return build_scene(closed_contours(
        [(-2, -2), (2, -2), (2, 2), (-2, 2)],
        [(-1.2, -1.2), (-1.2, 1.2), (1.2, 1.2), (1.2, -1.2)],
        [(-0.45, -0.45), (0.45, -0.45), (0.45, 0.45), (-0.45, 0.45)],
    ))


def _winding(repeat=1, reverse=False):
    corners = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    if reverse:
        corners.reverse()
    # One continuous contour, rather than several independently painted shapes.
    return build_scene(closed_contours(corners * repeat))


def _curved_fill():
    return build_scene(Circle(radius=1.2, color=WHITE, fill_opacity=1,
                               stroke_width=0, fill_border_width=0))


def _uniform(color=BLUE, opacity=1.0, transparent=False):
    background = (0, 0, 0, 0) if transparent else (0.08, 0.11, 0.14, 1)
    return build_scene(Square(side_length=2, color=color, fill_opacity=opacity,
                               stroke_width=0, fill_border_width=0),
                       background=background)


def _gradient_curve():
    curve = Circle(radius=1.2, stroke_width=0, fill_border_width=0)
    curve.set_fill(color=[RED, GREEN, BLUE], opacity=[0.2, 0.6, 0.9])
    return build_scene(curve)


def _border(width=None):
    options = {} if width is None else {"fill_border_width": width}
    return build_scene(Circle(radius=1.2, color=BLUE, fill_opacity=0.55,
                               stroke_width=0, **options))


def _translucent_overlaps():
    return build_scene(
        Circle(radius=1.2, color=RED, fill_opacity=0.5, stroke_width=0,
               fill_border_width=0).shift([-0.6, 0, 0]),
        Circle(radius=1.2, color=BLUE, fill_opacity=0.5, stroke_width=0,
               fill_border_width=0).shift([0.6, 0, 0]),
    )


def _stroke_behind():
    return build_scene(
        Square(side_length=2, fill_color=BLUE, fill_opacity=0.7,
               stroke_color=RED, stroke_width=24, stroke_behind=True),
        Circle(radius=0.7, fill_color=GREEN, fill_opacity=0.65,
               stroke_color=YELLOW, stroke_width=12).shift([0.8, -0.2, 0]),
    )


def _tapered_stroke():
    path = VMobject(fill_opacity=0, joint_type="miter")
    path.start_new_path([-2, -1, 0])
    path.add_quadratic_bezier_curve_to([0, 2, 0], [1, -0.5, 0])
    path.add_line_to([2, 1, 0])
    path.set_stroke(color=[RED, GREEN, BLUE], width=[2, 22, 5],
                    opacity=[0.25, 0.8, 0.45])
    return build_scene(path)


def _rotated_plane():
    path = Square(side_length=2.4, color=BLUE, fill_opacity=1, stroke_width=0,
                  fill_border_width=0)
    path.rotate(np.pi / 3, axis=np.array([1.0, 1.0, 0.0]))
    # Painter-mode path keeps its real 3D coordinates and camera projection.
    return build_scene(path)


def _mixed_depth():
    front = Square(side_length=2.8, color=BLUE, fill_opacity=1, stroke_width=0,
                   use_triangulated_fill=True, depth_test=True)
    crossing = Square(side_length=2.8, color=RED, fill_opacity=1, stroke_width=0,
                      use_triangulated_fill=True, depth_test=True)
    crossing.rotate(np.pi / 3, axis=np.array([0.0, 1.0, 0.0]))
    overlay = Circle(radius=0.35, color=YELLOW, fill_opacity=0.7,
                     stroke_width=0, fill_border_width=0).shift([-0.8, 0.8, 0])
    overlay.fix_in_frame()
    scene = build_scene(front, crossing, overlay, samples=4)
    scene.camera.frame.reorient(15, 25, 0)
    return scene


def renderer_cases() -> tuple[RendererFixture, ...]:
    """Return source fixtures, including independent nonzero-coverage probes."""
    quad_inside = CoverageProbe((-1.5, 1.5), True)
    quad_outside = CoverageProbe((2.5, 0), False)
    winding_probes = (CoverageProbe((0, 0), True), CoverageProbe((1.5, 0), False))
    return (
        RendererFixture("annulus_hole", _annulus, ("curves", "holes"),
                        (CoverageProbe((0, 0), False),
                         CoverageProbe((0.9, 0), True),
                         CoverageProbe((1.5, 0), False))),
        RendererFixture("nested_contours", _nested_contours, ("holes", "winding"),
                        (CoverageProbe((0, 0), True),
                         CoverageProbe((0.8, 0), False),
                         CoverageProbe((1.6, 0), True),
                         CoverageProbe((2.4, 0), False))),
        RendererFixture("quad_convex", lambda: build_scene(concave_quad(0)),
                        ("morph", "topology"),
                        (quad_inside, quad_outside, CoverageProbe((-1 / 3, 1 / 3), True))),
        RendererFixture("quad_before_flip", lambda: build_scene(concave_quad(2 / 3 - 0.001)),
                        ("morph", "topology", "near_degenerate")),
        RendererFixture("quad_after_flip", lambda: build_scene(concave_quad(2 / 3 + 0.001)),
                        ("morph", "topology", "near_degenerate")),
        RendererFixture("quad_concave", lambda: build_scene(concave_quad(1)),
                        ("morph", "topology"),
                        (quad_inside, quad_outside, CoverageProbe((-1 / 3, 1 / 3), False))),
        RendererFixture("repeated_winding", partial(_winding, repeat=2),
                        ("winding", "coincident_edges"), winding_probes),
        RendererFixture("reversed_winding", partial(_winding, reverse=True),
                        ("winding",), winding_probes),
        RendererFixture("curved_fill", _curved_fill, ("curves", "border_control"),
                        (CoverageProbe((0, 0), True), CoverageProbe((1.5, 0), False))),
        RendererFixture("uniform_color", _uniform, ("color", "border_control")),
        RendererFixture("uniform_opacity", partial(_uniform, opacity=0.5),
                        ("alpha", "border_control")),
        RendererFixture("transparent_target", partial(_uniform, opacity=0.5, transparent=True),
                        ("alpha", "transparent_target", "border_control")),
        RendererFixture("gradient_curve", _gradient_curve, ("curves", "gradient", "alpha")),
        RendererFixture("fill_border_default", _border, ("fill_border", "alpha")),
        RendererFixture("fill_border_wide", partial(_border, width=4),
                        ("fill_border", "alpha")),
        RendererFixture("translucent_overlaps", _translucent_overlaps,
                        ("alpha", "draw_order")),
        RendererFixture("stroke_behind_overlap", _stroke_behind,
                        ("alpha", "draw_order", "stroke_behind")),
        RendererFixture("tapered_stroke", _tapered_stroke,
                        ("stroke", "curves", "gradient", "alpha", "joints")),
        RendererFixture("rotated_plane", _rotated_plane, ("camera", "planar_3d", "painter")),
        RendererFixture("mixed_depth", _mixed_depth,
                        ("camera", "depth", "fixed_frame", "alpha")),
    )


def get_fixture(name: str) -> RendererFixture:
    for case in renderer_cases():
        if case.name == name:
            return case
    raise KeyError(name)
