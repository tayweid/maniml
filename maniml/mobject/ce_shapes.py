"""CE-compatible mobjects with no direct ManimGL ancestor.

Small, faithful-enough implementations of ManimCE classes that GL never
had: Star, RegularPolygram, Angle/RightAngle, DoubleArrow, LabeledDot,
Title, Paragraph, VDict.
"""
from __future__ import annotations

import numpy as np

from maniml.constants import (
    BLACK, DOWN, FRAME_WIDTH, LEFT, MED_SMALL_BUFF, ORIGIN, RIGHT, TAU, UP,
)
from maniml.mobject.geometry import Arc, Dot, Line, Polygon
from maniml.mobject.types.vectorized_mobject import VGroup, VMobject
from maniml.utils.space_ops import angle_of_vector, line_intersection, normalize


class Star(Polygon):
    def __init__(
        self,
        n: int = 5,
        outer_radius: float = 1.0,
        inner_radius: float | None = None,
        density: int = 2,
        start_angle: float = TAU / 4,
        **kwargs,
    ):
        if inner_radius is None:
            # Inner radius of the regular star polygon {n/density}
            inner_radius = outer_radius * (
                np.cos(np.pi * density / n) / np.cos(np.pi * (density - 1) / n)
            )
        vertices = []
        for i in range(2 * n):
            radius = outer_radius if i % 2 == 0 else inner_radius
            angle = start_angle + i * TAU / (2 * n)
            vertices.append(radius * np.array([np.cos(angle), np.sin(angle), 0.0]))
        super().__init__(*vertices, **kwargs)


class RegularPolygram(Polygon):
    def __init__(
        self,
        num_vertices: int = 5,
        density: int = 2,
        radius: float = 1.0,
        start_angle: float = TAU / 4,
        **kwargs,
    ):
        angles = [
            start_angle + TAU * ((i * density) % num_vertices) / num_vertices
            for i in range(num_vertices)
        ]
        vertices = [
            radius * np.array([np.cos(a), np.sin(a), 0.0]) for a in angles
        ]
        super().__init__(*vertices, **kwargs)


class Angle(Arc):
    """Arc marking the angle between two lines, at their intersection."""

    def __init__(
        self,
        line1: Line,
        line2: Line,
        radius: float = 0.5,
        quadrant=(1, 1),
        other_angle: bool = False,
        **kwargs,
    ):
        intersection = line_intersection(
            [line1.get_start(), line1.get_end()],
            [line2.get_start(), line2.get_end()],
        )
        angle_1 = angle_of_vector(quadrant[0] * (line1.get_end() - line1.get_start()))
        angle_2 = angle_of_vector(quadrant[1] * (line2.get_end() - line2.get_start()))
        if other_angle:
            angle_1, angle_2 = angle_2, angle_1
        delta = (angle_2 - angle_1) % TAU
        super().__init__(
            start_angle=angle_1,
            angle=delta,
            radius=radius,
            arc_center=intersection,
            **kwargs,
        )
        self.angle_value = delta

    def get_value(self, degrees: bool = False) -> float:
        return self.angle_value * (360 / TAU if degrees else 1)


class RightAngle(VMobject):
    """Elbow marking the right angle between two lines."""

    def __init__(
        self,
        line1: Line,
        line2: Line,
        length: float = 0.5,
        quadrant=(1, 1),
        **kwargs,
    ):
        intersection = line_intersection(
            [line1.get_start(), line1.get_end()],
            [line2.get_start(), line2.get_end()],
        )
        d1 = normalize(quadrant[0] * (line1.get_end() - line1.get_start()))
        d2 = normalize(quadrant[1] * (line2.get_end() - line2.get_start()))
        super().__init__(**kwargs)
        self.set_points_as_corners([
            intersection + d1 * length,
            intersection + (d1 + d2) * length,
            intersection + d2 * length,
        ])


class DoubleArrow(Line):
    def __init__(self, start=LEFT, end=RIGHT, **kwargs):
        super().__init__(start, end, **kwargs)
        self.add_tip()
        self.add_tip(at_start=True)


class LabeledDot(VGroup):
    """Dot sized to fit a label. A VGroup of (dot, label) rather than a
    Dot subclass: on the GL backend a filled submobject nested inside
    another filled mobject's family does not composite reliably."""

    def __init__(self, label, point=ORIGIN, radius: float | None = None, **kwargs):
        if isinstance(label, str):
            from maniml.mobject.svg.tex_mobject import MathTex
            label = MathTex(label, color=BLACK)
        if radius is None:
            radius = 0.1 + max(label.get_width(), label.get_height()) / 2
        dot = Dot(point=point, radius=radius, **kwargs)
        label.move_to(dot.get_center())
        super().__init__(dot, label)
        self.dot = dot
        self.label = label


class Title(VGroup):
    def __init__(
        self,
        *text_parts: str,
        include_underline: bool = True,
        underline_buff: float = MED_SMALL_BUFF,
        match_underline_width_to_text: bool = False,
        underline_stroke_width: float = 2.0,
        **kwargs,
    ):
        from maniml.mobject.svg.tex_mobject import Tex
        title = Tex(*text_parts, **kwargs)
        super().__init__(title)
        self.title = title
        title.to_edge(UP)
        if include_underline:
            underline = Line(LEFT, RIGHT, stroke_width=underline_stroke_width)
            underline.next_to(title, DOWN, buff=underline_buff)
            if match_underline_width_to_text:
                underline.match_width(title)
            else:
                underline.set_width(FRAME_WIDTH - 2)
            self.add(underline)
            self.underline = underline


class Paragraph(VGroup):
    def __init__(
        self,
        *text: str,
        line_spacing: float = 0.3,
        alignment: str = "left",
        **kwargs,
    ):
        from maniml.mobject.svg.text_mobject import Text
        lines = [Text(line, **kwargs) for line in text]
        super().__init__(*lines)
        edge = {"left": LEFT, "right": RIGHT}.get(alignment)
        if edge is not None:
            self.arrange(DOWN, buff=line_spacing, aligned_edge=edge)
        else:
            self.arrange(DOWN, buff=line_spacing)


class VDict(VMobject):
    """Dict-like VMobject container (CE compatibility)."""

    def __init__(self, mapping_or_iterable=(), show_keys: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.show_keys = show_keys
        self.submob_dict: dict = {}
        self.add(mapping_or_iterable)

    def add(self, mapping_or_iterable):
        items = (mapping_or_iterable.items()
                 if isinstance(mapping_or_iterable, dict)
                 else mapping_or_iterable)
        for key, value in items:
            self.add_key_value_pair(key, value)
        return self

    def add_key_value_pair(self, key, value) -> None:
        self.submob_dict[key] = value
        super().add(value)

    def remove(self, key):
        submob = self.submob_dict.pop(key)
        super().remove(submob)
        return self

    def __getitem__(self, key):
        return self.submob_dict[key]

    def __setitem__(self, key, value) -> None:
        if key in self.submob_dict:
            self.remove(key)
        self.add_key_value_pair(key, value)

    def __contains__(self, key) -> bool:
        return key in self.submob_dict

    def get_all_submobjects(self) -> list:
        return list(self.submob_dict.values())
