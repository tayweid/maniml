"""Small, deterministic source scenes for the A0 text/edge quality gate.

No renderer or GPU device is created here. TeX means actual production TeX
paths; missing compiler tools are an explicit error, never a font substitute.
ROI boxes use final-output pixels with a top-left origin and exclusive right
and bottom edges, matching PIL's crop convention. They include control hulls
and a small AA margin, not just a mostly empty full-frame average.
"""

from dataclasses import dataclass
from functools import partial
import hashlib
import math
import shutil
from typing import Callable, Iterator

import numpy as np

from maniml.constants import BLUE, FRAME_HEIGHT, FRAME_WIDTH, RED, WHITE, YELLOW
from maniml.mobject.geometry import Annulus, Circle, Line, Rectangle
from maniml.mobject.mobject import Group
from maniml.mobject.svg.tex_mobject import MathTex, Tex
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.utils.tex_file_writing import get_tex_config
from tests.renderer_fixtures import FixtureScene, build_scene


RESOLUTION = (960, 540)
BACKGROUND = (0.08, 0.11, 0.14, 1.0)
TEX_TEMPLATE = "default"
PARAGRAPH_LINES = (
    r"Smooth curves stay clear as the camera moves.",
    r"Tiny counters in $a,e,o,8$ must remain open.",
)
MATH_SOURCE = r"\int_0^1 x^2\,dx=\frac13,\quad e^{i\pi}+1=0,\quad \sqrt{a^2+b^2}"
PERSPECTIVE_SOURCE = r"O8"
BORDER_POLICIES = ("production_default", "zero_for_aa")


class QualityFixtureUnavailable(RuntimeError):
    """Required real-source tools are missing; this fixture was not built."""


@dataclass(frozen=True)
class QualityROI:
    name: str
    box: tuple[int, int, int, int]


@dataclass
class QualityFrame:
    name: str
    scene: FixtureScene
    rois: tuple[QualityROI, ...]
    metadata: dict
    diagnostic_limitations: tuple[str, ...]


@dataclass(frozen=True)
class QualityFixture:
    name: str
    build: Callable[[], QualityFrame]
    features: tuple[str, ...]
    border_policy: str


def require_tex_tools() -> dict[str, str]:
    compiler, _ = get_tex_config(TEX_TEMPLATE)
    paths = {name: shutil.which(name) for name in (compiler, "dvisvgm")}
    missing = [name for name, path in paths.items() if path is None]
    if missing:
        raise QualityFixtureUnavailable(
            "A0 real-TeX quality fixtures require " + ", ".join(missing)
            + " on PATH; no replacement font or synthetic glyph is used."
        )
    return paths


def _tex_content():
    require_tex_tools()
    first = Tex(PARAGRAPH_LINES[0], font_size=18, template=TEX_TEMPLATE,
                color=WHITE).move_to([0, 0.8, 0])
    second = Tex(PARAGRAPH_LINES[1], font_size=18, template=TEX_TEMPLATE,
                 color=WHITE).move_to([0, 0.35, 0])
    math = MathTex(MATH_SOURCE, font_size=22, template=TEX_TEMPLATE,
                   color=WHITE).move_to([0, -0.5, 0])
    return [first, second, math], {
        "paragraph": Group(first, second), "small_math": math,
    }


def _hairline_content():
    # Widths are source style units, deliberately unchanged by camera motion.
    # At this normal view, a width of 1 is approximately 0.675 output pixels.
    strokes = []
    for index, width in enumerate((0.5, 1.0, 2.0)):
        y = 0.9 - 0.6 * index
        strokes.append(Line([-2.4, y, 0], [-0.4, y + 0.2, 0],
                            color=WHITE, stroke_width=width))
        curve = VMobject(color=WHITE, fill_opacity=0, stroke_width=width)
        curve.start_new_path([0.4, y, 0])
        curve.add_quadratic_bezier_curve_to([1.4, y + 0.45, 0], [2.4, y, 0])
        strokes.append(curve)
    holes = [
        Annulus(inner_radius=radius, outer_radius=0.13, color=WHITE,
                fill_opacity=1, stroke_width=0).shift([x, -1.1, 0])
        for x, radius in zip((-0.9, 0, 0.9), (0.009, 0.018, 0.035))
    ]
    return [*strokes, *holes], {
        "thin_strokes": Group(*strokes),
        **{f"hole_{index}": hole for index, hole in enumerate(holes)},
    }


def _perspective_content():
    require_tex_tools()
    objects = []
    regions = {}
    # Identical source glyph and curve sizes, different camera distances.
    # These remain painter-mode paths: this isolates perspective quality from
    # depth-buffer order and the current renderer's separate 3D fill policy.
    for name, x, z, angle in (
        ("far", -2.0, -1.5, 0), ("near", 2.0, 1.5, 0),
        ("tilted", 0, 0, np.pi / 3),
    ):
        glyph = MathTex(PERSPECTIVE_SOURCE, font_size=22, template=TEX_TEMPLATE,
                        color=WHITE).move_to([0, -0.5, 0])
        curve = Circle(radius=0.45, color=WHITE, fill_opacity=1,
                       stroke_width=1).shift([0, 0.4, 0])
        group = Group(glyph, curve)
        group.rotate(angle, axis=np.array([0., 1., 0.]), about_point=np.zeros(3))
        group.shift([x, 0, z])
        objects.append(group)
        regions[name] = group
    return objects, regions


def _region_box(left, bottom, right, top):
    """Unrendered source-space crop marker, not extra scene geometry."""
    return VMobject().set_points_as_corners([
        [left, bottom, 0], [right, bottom, 0],
        [right, top, 0], [left, top, 0],
    ])


def _border_content():
    underlay_left = Rectangle(width=1.8, height=2.4, color=BLUE,
                             fill_opacity=1, stroke_width=0).shift([-0.9, 0, 0])
    underlay_right = Rectangle(width=1.8, height=2.4, color=RED,
                              fill_opacity=1, stroke_width=0).shift([0.9, 0, 0])
    fill = Circle(radius=0.8, color=YELLOW, fill_opacity=0.4, stroke_width=0,
                  fill_border_width=12)
    return [underlay_left, underlay_right, fill], {
        "border_arc_left": _region_box(-1.02, -0.32, -0.65, 0.32),
        "border_arc_right": _region_box(0.65, -0.32, 1.02, 0.32),
        "interior_left": _region_box(-0.42, -0.12, -0.18, 0.12),
        "interior_right": _region_box(0.18, -0.12, 0.42, 0.12),
        "outside_right": _region_box(1.22, -0.12, 1.46, 0.12),
    }


def _points(mobject):
    arrays = [mob.get_points() for mob in mobject.get_family() if mob.has_points()]
    return np.concatenate(arrays) if arrays else np.empty((0, 3))


def _project(points, camera):
    """Project source control hulls for crop bounds; no generated mesh needed."""
    camera.refresh_uniforms()
    view = np.asarray(camera.uniforms["view"]).reshape(4, 4).T
    camera_points = points @ view[:3, :3].T + view[:3, 3]
    projected = camera_points * camera.uniforms["frame_rescale_factors"]
    w = 1 - projected[:, 2]
    if np.any(w <= 0):
        raise ValueError("quality ROI crosses the camera projection singularity")
    ndc = projected[:, :2] / w[:, None]
    return (ndc * [1, -1] + 1) * np.asarray(RESOLUTION) / 2


def _rois(regions, camera):
    result = []
    for name, obj in regions.items():
        pixels = _project(_points(obj), camera)
        low = np.floor(pixels.min(axis=0) - 4).astype(int)
        high = np.ceil(pixels.max(axis=0) + 4).astype(int)
        low = np.maximum(low, 0)
        high = np.minimum(high, RESOLUTION)
        if np.any(high <= low):
            raise ValueError(f"quality ROI {name!r} is outside the output frame")
        result.append(QualityROI(name, (int(low[0]), int(low[1]),
                                       int(high[0]), int(high[1]))))
    return tuple(result)


def _source_digest(objects):
    digest = hashlib.sha256()
    for obj in objects:
        for mob in obj.get_family():
            if isinstance(mob, VMobject) and mob.has_points():
                # Only source geometry/paint, not renderer-computed normals.
                for name in ("point", "fill_rgba", "fill_border_width",
                             "stroke_rgba", "stroke_width"):
                    array = np.asarray(mob.data[name], dtype="<f4")
                    digest.update(np.asarray(array.shape, dtype="<u4").tobytes())
                    digest.update(array.tobytes())
    return digest.hexdigest()


def _configure_camera(scene, zoom, pixel_offset):
    scene.camera.frame.set_shape(FRAME_WIDTH / zoom, FRAME_HEIGHT / zoom)
    # A camera pan giving this exact image displacement for the z=0 plane.
    # Under perspective, depths correctly move by different amounts.
    dx, dy = pixel_offset
    scene.camera.frame.move_to(np.array([
        -dx * FRAME_WIDTH / RESOLUTION[0] / zoom,
        dy * FRAME_HEIGHT / RESOLUTION[1] / zoom, 0,
    ]))


def build_quality_frame(content="tex", view="normal",
                        border_policy="production_default", pixel_offset=(0., 0.)):
    """Build fresh source objects with a fixed output/style contract.

    `production_default` leaves the authored style intact (class defaults,
    notably TeX's 0.5, except the border stress case's explicit width of 12).
    `zero_for_aa` explicitly zeros only the fill border; it is a separate
    diagnostic control and does not claim default-style fidelity.
    """
    if border_policy not in BORDER_POLICIES:
        raise ValueError(f"unknown border policy: {border_policy}")
    if view not in ("normal", "zoom"):
        raise ValueError(f"unknown view: {view}")
    if len(pixel_offset) != 2 or not np.isfinite(pixel_offset).all():
        raise ValueError("pixel_offset must contain two finite numbers")
    builders = {"tex": _tex_content, "hairlines": _hairline_content,
                "perspective": _perspective_content, "border": _border_content}
    if content not in builders:
        raise ValueError(f"unknown content: {content}")
    objects, regions = builders[content]()
    if border_policy == "zero_for_aa":
        for obj in objects:
            for mob in obj.get_family():
                if isinstance(mob, VMobject):
                    mob.set_fill(border_width=0, recurse=False)
    scene = build_scene(*objects, resolution=RESOLUTION, samples=0,
                        background=BACKGROUND)
    if content == "border":
        # Keep the backdrop outside this paint's winding/coverage operation.
        # Otherwise current batching may MAX the border against the backdrop's
        # already-opaque scratch coverage, obscuring the border under test.
        scene.render_groups = [Group(*objects[:2]), Group(objects[2])]
    zoom = 1.0 if view == "normal" else 2.0
    _configure_camera(scene, zoom, pixel_offset)
    has_border = any(np.any(mob.data["fill_border_width"] > 0)
                     for obj in objects for mob in obj.get_family()
                     if isinstance(mob, VMobject) and mob.has_points())
    limitations = (("flattened triangle prototype omits requested fill borders",)
                   if has_border else ())
    uses_tex = content in ("tex", "perspective")
    compiler, preamble = get_tex_config(TEX_TEMPLATE) if uses_tex else (None, None)
    metadata = {
        "content": content, "view": view, "border_policy": border_policy,
        "zoom": zoom, "pixel_offset": list(pixel_offset),
        "resolution": list(RESOLUTION), "samples": 0,
        "background": list(BACKGROUND), "color_space": "unorm attachment values",
        "source_sha256": _source_digest(objects),
        "tex_template": TEX_TEMPLATE if uses_tex else None,
        "tex_compiler": compiler,
        "tex_template_sha256": hashlib.sha256(preamble.encode()).hexdigest()
        if uses_tex else None,
        "tex_sources": list(PARAGRAPH_LINES) + [MATH_SOURCE] if content == "tex"
        else [PERSPECTIVE_SOURCE] if content == "perspective" else [],
        "roi_coordinates": "output pixels; top-left origin; right/bottom exclusive",
        "scene_semantics": "painter order; real xyz perspective; no depth testing",
    }
    if content == "border":
        metadata["authored_fill_border_width"] = 12
        metadata["fill_opacity"] = 0.4
        metadata["semantic_controls"] = {
            "interior_left": "Single translucent fill over opaque blue underlay; border toggle must not alter this region.",
            "interior_right": "Single translucent fill over opaque red underlay; border toggle must not alter this region.",
            "outside_right": "Opaque red underlay only; outside the fill and wide border.",
            "border_arc_left": "Fill and border combine coverage before one composite over blue; not two independent source-over layers.",
            "border_arc_right": "Fill and border combine coverage before one composite over red; not two independent source-over layers.",
            "alpha": "Opaque underlay/background requires output alpha 1 throughout; current winding opacity adjustment is separate from this invariant.",
        }
    name = f"{content}_{view}_{border_policy}"
    result = QualityFrame(name, scene, _rois(regions, scene.camera), metadata, limitations)
    # Private source references support camera-only temporal sequences.
    result._regions = regions
    return result


def quality_cases() -> tuple[QualityFixture, ...]:
    return tuple(
        QualityFixture(f"{content}_{view}_{policy}",
                       partial(build_quality_frame, content, view, policy),
                       features, policy)
        for content, view, features in (
            ("tex", "normal", ("real_tex", "small_text", "tiny_holes")),
            ("tex", "zoom", ("real_tex", "camera_zoom", "small_math")),
            ("hairlines", "normal", ("thin_strokes", "tiny_holes", "curves")),
            ("perspective", "normal", ("real_tex", "perspective", "tilted_plane")),
            ("border", "normal", ("fill_border", "alpha", "coverage_combination")),
        )
        for policy in BORDER_POLICIES
    )


def quality_sequence(content="tex", border_policy="zero_for_aa",
                     motion="zoom", steps=9, *, max_zoom=2.0) -> Iterator[QualityFrame]:
    """Yield camera-only frames, preserving source and scene identities.

    Render each yielded frame before advancing: the next item mutates this
    same scene's camera. Metadata and crop tuples are frame-specific snapshots.
    Zoom is smooth in/out over one cycle; translation crosses one pixel in
    quarter-pixel horizontal increments with the default nine frames (two
    horizontal pixels and one vertical pixel total).
    """
    if motion not in ("zoom", "fractional_translation"):
        raise ValueError(f"unknown camera motion: {motion}")
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 3:
        raise ValueError("steps must be an integer of at least three")
    if not math.isfinite(max_zoom) or max_zoom < 1:
        raise ValueError("max_zoom must be finite and at least one")
    base = build_quality_frame(content, border_policy=border_policy)
    for index in range(steps):
        phase = index / (steps - 1)
        zoom = 1.0 + 0.5 * (max_zoom - 1) * (1 - math.cos(2 * math.pi * phase)) if motion == "zoom" else 1.0
        offset = (0., 0.) if motion == "zoom" else (2 * phase, phase)
        _configure_camera(base.scene, zoom, offset)
        metadata = dict(base.metadata, sequence=motion, frame_index=index,
                        frame_count=steps, phase=phase, zoom=zoom,
                        pixel_offset=list(offset))
        yield QualityFrame(f"{content}_{border_policy}_{motion}_{index:03d}",
                           base.scene, _rois(base._regions, base.scene.camera),
                           metadata, base.diagnostic_limitations)
