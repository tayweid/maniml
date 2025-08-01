from __future__ import annotations

import math

import numpy as np

from manim.constants import DL, DOWN, DR, LEFT, ORIGIN, OUT, RIGHT, UL, UP, UR
from manim.constants import RED, BLACK, DEFAULT_MOBJECT_COLOR, DEFAULT_LIGHT_COLOR
from manim.constants import MED_SMALL_BUFF, SMALL_BUFF
from manim.constants import DEG, PI, TAU
from manim.mobject.mobject import Mobject
from manim.mobject.types.vectorized_mobject import DashedVMobject
from manim.mobject.types.vectorized_mobject import VGroup
from manim.mobject.types.vectorized_mobject import VMobject
from manim.utils.bezier import quadratic_bezier_points_for_arc
from manim.utils.iterables import adjacent_n_tuples
from manim.utils.iterables import adjacent_pairs
from manim.utils.simple_functions import clip
from manim.utils.simple_functions import fdiv
from manim.utils.space_ops import angle_between_vectors
from manim.utils.space_ops import angle_of_vector
from manim.utils.space_ops import cross2d
from manim.utils.space_ops import compass_directions
from manim.utils.space_ops import find_intersection
from manim.utils.space_ops import get_norm
from manim.utils.space_ops import normalize
from manim.utils.space_ops import rotate_vector
from manim.utils.space_ops import rotation_matrix_transpose
from manim.utils.space_ops import rotation_between_vectors

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Iterable, Optional
    from manim.typing import ManimColor, Vect3, Vect3Array, Self


DEFAULT_DOT_RADIUS = 0.08
DEFAULT_SMALL_DOT_RADIUS = 0.04
DEFAULT_DASH_LENGTH = 0.05
DEFAULT_ARROW_TIP_LENGTH = 0.35
DEFAULT_ARROW_TIP_WIDTH = 0.35


# Deprecate?
class TipableVMobject(VMobject):
    """
    Meant for shared functionality between Arc and Line.
    Functionality can be classified broadly into these groups:

        * Adding, Creating, Modifying tips
            - add_tip calls create_tip, before pushing the new tip
                into the TipableVMobject's list of submobjects
            - stylistic and positional configuration

        * Checking for tips
            - Boolean checks for whether the TipableVMobject has a tip
                and a starting tip

        * Getters
            - Straightforward accessors, returning information pertaining
                to the TipableVMobject instance's tip(s), its length etc
    """
    tip_config: dict = dict(
        fill_opacity=1.0,
        stroke_width=0.0,
        tip_style=0.0,  # triangle=0, inner_smooth=1, dot=2
    )

    # Adding, Creating, Modifying tips
    def add_tip(self, at_start: bool = False, **kwargs) -> Self:
        """
        Adds a tip to the TipableVMobject instance, recognising
        that the endpoints might need to be switched if it's
        a 'starting tip' or not.
        """
        tip = self.create_tip(at_start, **kwargs)
        self.reset_endpoints_based_on_tip(tip, at_start)
        self.asign_tip_attr(tip, at_start)
        tip.set_color(self.get_stroke_color())
        self.add(tip)
        return self

    def create_tip(self, at_start: bool = False, **kwargs) -> ArrowTip:
        """
        Stylises the tip, positions it spacially, and returns
        the newly instantiated tip to the caller.
        """
        tip = self.get_unpositioned_tip(**kwargs)
        self.position_tip(tip, at_start)
        return tip

    def get_unpositioned_tip(self, **kwargs) -> ArrowTip:
        """
        Returns a tip that has been stylistically configured,
        but has not yet been given a position in space.
        """
        config = dict()
        config.update(self.tip_config)
        config.update(kwargs)
        return ArrowTip(**config)

    def position_tip(self, tip: ArrowTip, at_start: bool = False) -> ArrowTip:
        # Last two control points, defining both
        # the end, and the tangency direction
        if at_start:
            anchor = self.get_start()
            handle = self.get_first_handle()
        else:
            handle = self.get_last_handle()
            anchor = self.get_end()
        tip.rotate(angle_of_vector(handle - anchor) - PI - tip.get_angle())
        tip.shift(anchor - tip.get_tip_point())
        return tip

    def reset_endpoints_based_on_tip(self, tip: ArrowTip, at_start: bool) -> Self:
        if self.get_length() == 0:
            # Zero length, put_start_and_end_on wouldn't
            # work
            return self

        if at_start:
            start = tip.get_base()
            end = self.get_end()
        else:
            start = self.get_start()
            end = tip.get_base()
        self.put_start_and_end_on(start, end)
        return self

    def asign_tip_attr(self, tip: ArrowTip, at_start: bool) -> Self:
        if at_start:
            self.start_tip = tip
        else:
            self.tip = tip
        return self

    # Checking for tips
    def has_tip(self) -> bool:
        return hasattr(self, "tip") and self.tip in self

    def has_start_tip(self) -> bool:
        return hasattr(self, "start_tip") and self.start_tip in self

    # Getters
    def pop_tips(self) -> VGroup:
        start, end = self.get_start_and_end()
        result = VGroup()
        if self.has_tip():
            result.add(self.tip)
            self.remove(self.tip)
        if self.has_start_tip():
            result.add(self.start_tip)
            self.remove(self.start_tip)
        self.put_start_and_end_on(start, end)
        return result

    def get_tips(self) -> VGroup:
        """
        Returns a VGroup (collection of VMobjects) containing
        the TipableVMObject instance's tips.
        """
        result = VGroup()
        if hasattr(self, "tip"):
            result.add(self.tip)
        if hasattr(self, "start_tip"):
            result.add(self.start_tip)
        return result

    def get_tip(self) -> ArrowTip:
        """Returns the TipableVMobject instance's (first) tip,
        otherwise throws an exception."""
        tips = self.get_tips()
        if len(tips) == 0:
            raise Exception("tip not found")
        else:
            return tips[0]

    def get_default_tip_length(self) -> float:
        return self.tip_length

    def get_first_handle(self) -> Vect3:
        return self.get_points()[1]

    def get_last_handle(self) -> Vect3:
        return self.get_points()[-2]

    def get_end(self) -> Vect3:
        if self.has_tip():
            return self.tip.get_start()
        else:
            return VMobject.get_end(self)

    def get_start(self) -> Vect3:
        if self.has_start_tip():
            return self.start_tip.get_start()
        else:
            return VMobject.get_start(self)

    def get_length(self) -> float:
        start, end = self.get_start_and_end()
        return get_norm(start - end)


class Arc(TipableVMobject):
    '''
    Creates an arc.
    Parameters
    -----
    start_angle : float
        Starting angle of the arc in radians. (Angles are measured counter-clockwise)
    angle : float
        Angle subtended by the arc at its center in radians. (Angles are measured counter-clockwise)
    radius : float
        Radius of the arc
    arc_center : array_like
        Center of the arc
    Examples :
            arc = Arc(start_angle=TAU/4, angle=TAU/2, radius=3, arc_center=ORIGIN)
            arc = Arc(angle=TAU/4, radius=4.5, arc_center=(1,2,0), color=BLUE)
    Returns
    -----
    out : Arc object
        An Arc object satisfying the specified parameters
    '''

    def __init__(
        self,
        start_angle: float = 0,
        angle: float = TAU / 4,
        radius: float = 1.0,
        n_components: Optional[int] = None,
        arc_center: Vect3 = ORIGIN,
        **kwargs
    ):
        super().__init__(**kwargs)

        if n_components is None:
            # 16 components for a full circle
            n_components = int(15 * (abs(angle) / TAU)) + 1

        self.set_points(quadratic_bezier_points_for_arc(angle, n_components))
        self.rotate(start_angle, about_point=ORIGIN)
        self.scale(radius, about_point=ORIGIN)
        self.shift(arc_center)

    def get_arc_center(self) -> Vect3:
        """
        Looks at the normals to the first two
        anchors, and finds their intersection points
        """
        # First two anchors and handles
        a1, h, a2 = self.get_points()[:3]
        # Tangent vectors
        t1 = h - a1
        t2 = h - a2
        # Normals
        n1 = rotate_vector(t1, TAU / 4)
        n2 = rotate_vector(t2, TAU / 4)
        return find_intersection(a1, n1, a2, n2)

    def get_start_angle(self) -> float:
        angle = angle_of_vector(self.get_start() - self.get_arc_center())
        return angle % TAU

    def get_stop_angle(self) -> float:
        angle = angle_of_vector(self.get_end() - self.get_arc_center())
        return angle % TAU

    def move_arc_center_to(self, point: Vect3) -> Self:
        self.shift(point - self.get_arc_center())
        return self


class ArcBetweenPoints(Arc):
    '''
    Creates an arc passing through the specified points with "angle" as the
    angle subtended at its center.
    Parameters
    -----
    start : array_like
        Starting point of the arc
    end : array_like
        Ending point of the arc
    angle : float
        Angle subtended by the arc at its center in radians. (Angles are measured counter-clockwise)
    Examples :
            arc = ArcBetweenPoints(start=(0, 0, 0), end=(1, 2, 0), angle=TAU / 2)
            arc = ArcBetweenPoints(start=(-2, 3, 0), end=(1, 2, 0), angle=-TAU / 12, color=BLUE)
    Returns
    -----
    out : ArcBetweenPoints object
        An ArcBetweenPoints object satisfying the specified parameters
    '''

    def __init__(
        self,
        start: Vect3,
        end: Vect3,
        angle: float = TAU / 4,
        **kwargs
    ):
        super().__init__(angle=angle, **kwargs)
        if angle == 0:
            self.set_points_as_corners([LEFT, RIGHT])
        self.put_start_and_end_on(start, end)


class CurvedArrow(ArcBetweenPoints):
    '''
    Creates a curved arrow passing through the specified points with "angle" as the
    angle subtended at its center.
    Parameters
    -----
    start_point : array_like
        Starting point of the curved arrow
    end_point : array_like
        Ending point of the curved arrow
    angle : float
        Angle subtended by the curved arrow at its center in radians. (Angles are measured counter-clockwise)
    Examples :
            curvedArrow = CurvedArrow(start_point=(0, 0, 0), end_point=(1, 2, 0), angle=TAU/2)
            curvedArrow = CurvedArrow(start_point=(-2, 3, 0), end_point=(1, 2, 0), angle=-TAU/12, color=BLUE)
    Returns
    -----
    out : CurvedArrow object
        A CurvedArrow object satisfying the specified parameters
    '''

    def __init__(
        self,
        start_point: Vect3,
        end_point: Vect3,
        **kwargs
    ):
        super().__init__(start_point, end_point, **kwargs)
        self.add_tip()


class CurvedDoubleArrow(CurvedArrow):
    '''
    Creates a curved double arrow passing through the specified points with "angle" as the
    angle subtended at its center.
    Parameters
    -----
    start_point : array_like
        Starting point of the curved double arrow
    end_point : array_like
        Ending point of the curved double arrow
    angle : float
        Angle subtended by the curved double arrow at its center in radians. (Angles are measured counter-clockwise)
    Examples :
            curvedDoubleArrow = CurvedDoubleArrow(start_point = (0, 0, 0), end_point = (1, 2, 0), angle = TAU/2)
            curvedDoubleArrow = CurvedDoubleArrow(start_point = (-2, 3, 0), end_point = (1, 2, 0), angle = -TAU/12, color = BLUE)
    Returns
    -----
    out : CurvedDoubleArrow object
        A CurvedDoubleArrow object satisfying the specified parameters
    '''

    def __init__(
        self,
        start_point: Vect3,
        end_point: Vect3,
        **kwargs
    ):
        super().__init__(start_point, end_point, **kwargs)
        self.add_tip(at_start=True)


class Circle(Arc):
    '''
    Creates a circle.
    Parameters
    -----
    radius : float
        Radius of the circle
    arc_center : array_like
        Center of the circle
    Examples :
            circle = Circle(radius=2, arc_center=(1,2,0))
            circle = Circle(radius=3.14, arc_center=2 * LEFT + UP, color=DARK_BLUE)
    Returns
    -----
    out : Circle object
        A Circle object satisfying the specified parameters
    '''

    def __init__(
        self,
        start_angle: float = 0,
        stroke_color: ManimColor = RED,
        **kwargs
    ):
        super().__init__(
            start_angle, TAU,
            stroke_color=stroke_color,
            **kwargs
        )

    def surround(
        self,
        mobject: Mobject,
        dim_to_match: int = 0,
        stretch: bool = False,
        buff: float = MED_SMALL_BUFF
    ) -> Self:
        self.replace(mobject, dim_to_match, stretch)
        self.stretch((self.get_width() + 2 * buff) / self.get_width(), 0)
        self.stretch((self.get_height() + 2 * buff) / self.get_height(), 1)
        return self

    def point_at_angle(self, angle: float) -> Vect3:
        start_angle = self.get_start_angle()
        return self.point_from_proportion(
            ((angle - start_angle) % TAU) / TAU
        )

    def get_radius(self) -> float:
        return get_norm(self.get_start() - self.get_center())


class Dot(Circle):
    '''
    Creates a dot. Dot is a filled white circle with no bounary and DEFAULT_DOT_RADIUS.
    Parameters
    -----
    point : array_like
        Coordinates of center of the dot.
    Examples :
            dot = Dot(point=(1, 2, 0))

    Returns
    -----
    out : Dot object
        A Dot object satisfying the specified parameters
    '''

    def __init__(
        self,
        point: Vect3 = ORIGIN,
        radius: float = DEFAULT_DOT_RADIUS,
        stroke_color: ManimColor = BLACK,
        stroke_width: float = 0.0,
        fill_opacity: float = 1.0,
        fill_color: ManimColor = DEFAULT_MOBJECT_COLOR,
        **kwargs
    ):
        super().__init__(
            arc_center=point,
            radius=radius,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            fill_opacity=fill_opacity,
            fill_color=fill_color,
            **kwargs
        )


class SmallDot(Dot):
    '''
    Creates a small dot. Small dot is a filled white circle with no bounary and DEFAULT_SMALL_DOT_RADIUS.
    Parameters
    -----
    point : array_like
        Coordinates of center of the small dot.
    Examples :
            smallDot = SmallDot(point=(1, 2, 0))

    Returns
    -----
    out : SmallDot object
        A SmallDot object satisfying the specified parameters
    '''

    def __init__(
        self,
        point: Vect3 = ORIGIN,
        radius: float = DEFAULT_SMALL_DOT_RADIUS,
        **kwargs
    ):
        super().__init__(point, radius=radius, **kwargs)


class Ellipse(Circle):
    '''
    Creates an ellipse.
    Parameters
    -----
    width : float
        Width of the ellipse
    height : float
        Height of the ellipse
    arc_center : array_like
        Coordinates of center of the ellipse
    Examples :
            ellipse = Ellipse(width=4, height=1, arc_center=(3, 3, 0))
            ellipse = Ellipse(width=2, height=5, arc_center=ORIGIN, color=BLUE)
    Returns
    -----
    out : Ellipse object
        An Ellipse object satisfying the specified parameters
    '''

    def __init__(
        self,
        width: float = 2.0,
        height: float = 1.0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.set_width(width, stretch=True)
        self.set_height(height, stretch=True)


class AnnularSector(VMobject):
    '''
    Creates an annular sector.
    Parameters
    -----
    inner_radius : float
        Inner radius of the annular sector
    outer_radius : float
        Outer radius of the annular sector
    start_angle : float
        Starting angle of the annular sector (Angles are measured counter-clockwise)
    angle : float
        Angle subtended at the center of the annular sector (Angles are measured counter-clockwise)
    arc_center : array_like
        Coordinates of center of the annular sector
    Examples :
            annularSector = AnnularSector(inner_radius=1, outer_radius=2, angle=TAU/2, start_angle=TAU*3/4, arc_center=(1,-2,0))
    Returns
    -----
    out : AnnularSector object
        An AnnularSector object satisfying the specified parameters
    '''

    def __init__(
        self,
        angle: float = TAU / 4,
        start_angle: float = 0.0,
        inner_radius: float = 1.0,
        outer_radius: float = 2.0,
        arc_center: Vect3 = ORIGIN,
        fill_color: ManimColor = DEFAULT_LIGHT_COLOR,
        fill_opacity: float = 1.0,
        stroke_width: float = 0.0,
        **kwargs,
    ):
        super().__init__(
            fill_color=fill_color,
            fill_opacity=fill_opacity,
            stroke_width=stroke_width,
            **kwargs,
        )

        # Initialize points
        inner_arc, outer_arc = [
            Arc(
                start_angle=start_angle,
                angle=angle,
                radius=radius,
                arc_center=arc_center,
            )
            for radius in (inner_radius, outer_radius)
        ]
        self.set_points(inner_arc.get_points()[::-1])  # Reverse
        self.add_line_to(outer_arc.get_points()[0])
        self.add_subpath(outer_arc.get_points())
        self.add_line_to(inner_arc.get_points()[-1])


class Sector(AnnularSector):
    '''
    Creates a sector.
    Parameters
    -----
    outer_radius : float
        Radius of the sector
    start_angle : float
        Starting angle of the sector in radians. (Angles are measured counter-clockwise)
    angle : float
        Angle subtended by the sector at its center in radians. (Angles are measured counter-clockwise)
    arc_center : array_like
        Coordinates of center of the sector
    Examples :
            sector = Sector(outer_radius=1, start_angle=TAU/3, angle=TAU/2, arc_center=[0,3,0])
            sector = Sector(outer_radius=3, start_angle=TAU/4, angle=TAU/4, arc_center=ORIGIN, color=PINK)
    Returns
    -----
    out : Sector object
        An Sector object satisfying the specified parameters
    '''

    def __init__(
        self,
        angle: float = TAU / 4,
        radius: float = 1.0,
        **kwargs
    ):
        super().__init__(
            angle,
            inner_radius=0,
            outer_radius=radius,
            **kwargs
        )


class Annulus(VMobject):
    '''
    Creates an annulus.
    Parameters
    -----
    inner_radius : float
        Inner radius of the annulus
    outer_radius : float
        Outer radius of the annulus
    arc_center : array_like
        Coordinates of center of the annulus
    Examples :
            annulus = Annulus(inner_radius=2, outer_radius=3, arc_center=(1, -1, 0))
            annulus = Annulus(inner_radius=2, outer_radius=3, stroke_width=20, stroke_color=RED, fill_color=BLUE, arc_center=ORIGIN)
    Returns
    -----
    out : Annulus object
        An Annulus object satisfying the specified parameters
    '''

    def __init__(
        self,
        inner_radius: float = 1.0,
        outer_radius: float = 2.0,
        fill_opacity: float = 1.0,
        stroke_width: float = 0.0,
        fill_color: ManimColor = DEFAULT_LIGHT_COLOR,
        center: Vect3 = ORIGIN,
        **kwargs,
    ):
        super().__init__(
            fill_color=fill_color,
            fill_opacity=fill_opacity,
            stroke_width=stroke_width,
            **kwargs,
        )

        self.radius = outer_radius
        outer_path = outer_radius * quadratic_bezier_points_for_arc(TAU)
        inner_path = inner_radius * quadratic_bezier_points_for_arc(-TAU)
        self.add_subpath(outer_path)
        self.add_subpath(inner_path)
        self.shift(center)


class Line(TipableVMobject):
    '''
    Creates a line joining the points "start" and "end".
    Parameters
    -----
    start : array_like
        Starting point of the line
    end : array_like
        Ending point of the line
    Examples :
            line = Line((0, 0, 0), (3, 0, 0))
            line = Line((1, 2, 0), (-2, -3, 0), color=BLUE)
    Returns
    -----
    out : Line object
        A Line object satisfying the specified parameters
    '''

    def __init__(
        self,
        start: Vect3 | Mobject = LEFT,
        end: Vect3 | Mobject = RIGHT,
        buff: float = 0.0,
        path_arc: float = 0.0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.path_arc = path_arc
        self.buff = buff
        self.set_start_and_end_attrs(start, end)
        self.set_points_by_ends(self.start, self.end, buff, path_arc)

    def set_points_by_ends(
        self,
        start: Vect3,
        end: Vect3,
        buff: float = 0,
        path_arc: float = 0
    ) -> Self:
        self.clear_points()
        self.start_new_path(start)
        self.add_arc_to(end, path_arc)

        # Apply buffer
        if buff > 0:
            length = self.get_arc_length()
            alpha = min(buff / length, 0.5)
            self.pointwise_become_partial(self, alpha, 1 - alpha)
        return self

    def set_path_arc(self, new_value: float) -> Self:
        self.path_arc = new_value
        self.init_points()
        return self

    def set_start_and_end_attrs(self, start: Vect3 | Mobject, end: Vect3 | Mobject):
        # If either start or end are Mobjects, this
        # gives their centers
        rough_start = self.pointify(start)
        rough_end = self.pointify(end)
        vect = normalize(rough_end - rough_start)
        # Now that we know the direction between them,
        # we can find the appropriate boundary point from
        # start and end, if they're mobjects
        self.start = self.pointify(start, vect)
        self.end = self.pointify(end, -vect)

    def pointify(
        self,
        mob_or_point: Mobject | Vect3,
        direction: Vect3 | None = None
    ) -> Vect3:
        """
        Take an argument passed into Line (or subclass) and turn
        it into a 3d point.
        """
        if isinstance(mob_or_point, Mobject):
            mob = mob_or_point
            if direction is None:
                return mob.get_center()
            else:
                return mob.get_continuous_bounding_box_point(direction)
        else:
            point = mob_or_point
            result = np.zeros(self.dim)
            result[:len(point)] = point
            return result

    def put_start_and_end_on(self, start: Vect3, end: Vect3) -> Self:
        curr_start, curr_end = self.get_start_and_end()
        if np.isclose(curr_start, curr_end).all():
            # Handle null lines more gracefully
            self.set_points_by_ends(start, end, buff=0, path_arc=self.path_arc)
            return self
        return super().put_start_and_end_on(start, end)

    def get_vector(self) -> Vect3:
        return self.get_end() - self.get_start()

    def get_unit_vector(self) -> Vect3:
        return normalize(self.get_vector())

    def get_angle(self) -> float:
        return angle_of_vector(self.get_vector())

    def get_projection(self, point: Vect3) -> Vect3:
        """
        Return projection of a point onto the line
        """
        unit_vect = self.get_unit_vector()
        start = self.get_start()
        return start + np.dot(point - start, unit_vect) * unit_vect

    def get_slope(self) -> float:
        return np.tan(self.get_angle())

    def set_angle(self, angle: float, about_point: Optional[Vect3] = None) -> Self:
        if about_point is None:
            about_point = self.get_start()
        self.rotate(
            angle - self.get_angle(),
            about_point=about_point,
        )
        return self

    def set_length(self, length: float, **kwargs):
        self.scale(length / self.get_length(), **kwargs)
        return self

    def get_arc_length(self) -> float:
        arc_len = get_norm(self.get_vector())
        if self.path_arc > 0:
            arc_len *= self.path_arc / (2 * math.sin(self.path_arc / 2))
        return arc_len


class DashedLine(Line):
    '''
    Creates a dashed line joining the points "start" and "end".
    Parameters
    -----
    start : array_like
        Starting point of the dashed line
    end : array_like
        Ending point of the dashed line
    dash_length : float
        length of each dash
    Examples :
            line = DashedLine((0, 0, 0), (3, 0, 0))
            line = DashedLine((1, 2, 3), (4, 5, 6), dash_length=0.01)
    Returns
    -----
    out : DashedLine object
        A DashedLine object satisfying the specified parameters
    '''

    def __init__(
        self,
        start: Vect3 = LEFT,
        end: Vect3 = RIGHT,
        dash_length: float = DEFAULT_DASH_LENGTH,
        positive_space_ratio: float = 0.5,
        **kwargs
    ):
        super().__init__(start, end, **kwargs)

        num_dashes = self.calculate_num_dashes(dash_length, positive_space_ratio)
        dashes = DashedVMobject(
            self,
            num_dashes=num_dashes,
            positive_space_ratio=positive_space_ratio
        )
        self.clear_points()
        self.add(*dashes)

    def calculate_num_dashes(self, dash_length: float, positive_space_ratio: float) -> int:
        try:
            full_length = dash_length / positive_space_ratio
            return int(np.ceil(self.get_length() / full_length))
        except ZeroDivisionError:
            return 1

    def get_start(self) -> Vect3:
        if len(self.submobjects) > 0:
            return self.submobjects[0].get_start()
        else:
            return Line.get_start(self)

    def get_end(self) -> Vect3:
        if len(self.submobjects) > 0:
            return self.submobjects[-1].get_end()
        else:
            return Line.get_end(self)

    def get_start_and_end(self) -> Tuple[Vect3, Vect3]:
        return self.get_start(), self.get_end()

    def get_first_handle(self) -> Vect3:
        return self.submobjects[0].get_points()[1]

    def get_last_handle(self) -> Vect3:
        return self.submobjects[-1].get_points()[-2]


class TangentLine(Line):
    '''
    Creates a tangent line to the specified vectorized math object.
    Parameters
    -----
    vmob : VMobject object
        Vectorized math object which the line will be tangent to
    alpha : float
        Point on the perimeter of the vectorized math object. It takes value between 0 and 1
        both inclusive.
    length : float
        Length of the tangent line
    Examples :
            circle = Circle(arc_center=ORIGIN, radius=3, color=GREEN)
            tangentLine = TangentLine(vmob=circle, alpha=1/3, length=6, color=BLUE)
    Returns
    -----
    out : TangentLine object
        A TangentLine object satisfying the specified parameters
    '''

    def __init__(
        self,
        vmob: VMobject,
        alpha: float,
        length: float = 2,
        d_alpha: float = 1e-6,
        **kwargs
    ):
        a1 = clip(alpha - d_alpha, 0, 1)
        a2 = clip(alpha + d_alpha, 0, 1)
        super().__init__(vmob.pfp(a1), vmob.pfp(a2), **kwargs)
        self.scale(length / self.get_length())


class Elbow(VMobject):
    '''
    Creates an elbow. Elbow is an L-shaped shaped object.
    Parameters
    -----
    width : float
        Width of the elbow
    angle : float
        Angle of the elbow in radians with the horizontal. (Angles are measured counter-clockwise)
    Examples :
            line = Elbow(width=2, angle=TAU/16)
    Returns
    -----
    out : Elbow object
        A Elbow object satisfying the specified parameters
    '''

    def __init__(
        self,
        width: float = 0.2,
        angle: float = 0,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.set_points_as_corners([UP, UR, RIGHT])
        self.set_width(width, about_point=ORIGIN)
        self.rotate(angle, about_point=ORIGIN)


class StrokeArrow(Line):
    def __init__(
        self,
        start: Vect3 | Mobject,
        end: Vect3 | Mobject,
        stroke_color: ManimColor = DEFAULT_LIGHT_COLOR,
        stroke_width: float = 5,
        buff: float = 0.25,
        tip_width_ratio: float = 5,
        tip_len_to_width: float = 0.0075,
        max_tip_length_to_length_ratio: float = 0.3,
        max_width_to_length_ratio: float = 8.0,
        **kwargs,
    ):
        self.tip_width_ratio = tip_width_ratio
        self.tip_len_to_width = tip_len_to_width
        self.max_tip_length_to_length_ratio = max_tip_length_to_length_ratio
        self.max_width_to_length_ratio = max_width_to_length_ratio
        self.n_tip_points = 3
        self.original_stroke_width = stroke_width
        super().__init__(
            start, end,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            buff=buff,
            **kwargs
        )

    def set_points_by_ends(
        self,
        start: Vect3,
        end: Vect3,
        buff: float = 0,
        path_arc: float = 0
    ) -> Self:
        super().set_points_by_ends(start, end, buff, path_arc)
        self.insert_tip_anchor()
        self.create_tip_with_stroke_width()
        return self

    def insert_tip_anchor(self) -> Self:
        prev_end = self.get_end()
        arc_len = self.get_arc_length()
        tip_len = self.get_stroke_width() * self.tip_width_ratio * self.tip_len_to_width
        if tip_len >= self.max_tip_length_to_length_ratio * arc_len or arc_len == 0:
            alpha = self.max_tip_length_to_length_ratio
        else:
            alpha = tip_len / arc_len

        if self.path_arc > 0 and self.buff > 0:
            self.insert_n_curves(10)  # Is this needed?
        self.pointwise_become_partial(self, 0.0, 1.0 - alpha)
        self.add_line_to(self.get_end())
        self.add_line_to(prev_end)
        self.n_tip_points = 3
        return self

    @Mobject.affects_data
    def create_tip_with_stroke_width(self) -> Self:
        if self.get_num_points() < 3:
            return self
        stroke_width = min(
            self.original_stroke_width,
            self.max_width_to_length_ratio * self.get_length(),
        )
        tip_width = self.tip_width_ratio * stroke_width
        ntp = self.n_tip_points
        self.data['stroke_width'][:-ntp] = self.data['stroke_width'][0]
        self.data['stroke_width'][-ntp:, 0] = tip_width * np.linspace(1, 0, ntp)
        return self

    def reset_tip(self) -> Self:
        self.set_points_by_ends(
            self.get_start(), self.get_end(),
            path_arc=self.path_arc
        )
        return self

    def set_stroke(
        self,
        color: ManimColor | Iterable[ManimColor] | None = None,
        width: float | Iterable[float] | None = None,
        *args, **kwargs
    ) -> Self:
        super().set_stroke(color=color, width=width, *args, **kwargs)
        self.original_stroke_width = self.get_stroke_width()
        if self.has_points():
            self.reset_tip()
        return self

    def _handle_scale_side_effects(self, scale_factor: float) -> Self:
        if scale_factor != 1.0:
            self.reset_tip()
        return self


class Arrow(Line):
    '''
    Creates an arrow.

    Parameters
    ----------
    start : array_like
        Starting point of the arrow
    end : array_like
        Ending point of the arrow 
    buff : float, optional
        Buffer distance from the start and end points. Default is MED_SMALL_BUFF.
    path_arc : float, optional
        If set to a non-zero value, the arrow will be curved to subtend a circle by this angle.
        Default is 0 (straight arrow).
    thickness : float, optional
        How wide should the base of the arrow be. This affects the shaft width. Default is 3.0.
    tip_width_ratio : float, optional
        Ratio of the tip width to the shaft width. Default is 5.
    tip_angle : float, optional
        Angle of the arrow tip in radians. Default is PI/3 (60 degrees).
    max_tip_length_to_length_ratio : float, optional
        Maximum ratio of tip length to total arrow length. Prevents tips from being too large
        relative to the arrow. Default is 0.5.
    max_width_to_length_ratio : float, optional
        Maximum ratio of arrow width to total arrow length. Prevents arrows from being too wide
        relative to their length. Default is 0.1.
    **kwargs
        Additional keyword arguments passed to the parent Line class.

    Examples
    --------
    >>> arrow = Arrow((0, 0, 0), (3, 0, 0))
    >>> curved_arrow = Arrow(LEFT, RIGHT, path_arc=PI/4)
    >>> thick_arrow = Arrow(UP, DOWN, thickness=5.0, tip_width_ratio=3)

    Returns
    -------
    Arrow
        An Arrow object satisfying the specified parameters.
    '''

    tickness_multiplier = 0.015

    def __init__(
        self,
        start: Vect3 | Mobject = LEFT,
        end: Vect3 | Mobject = LEFT,
        buff: float = MED_SMALL_BUFF,
        path_arc: float = 0,
        fill_color: ManimColor = DEFAULT_LIGHT_COLOR,
        fill_opacity: float = 1.0,
        stroke_width: float = 0.0,
        thickness: float = 3.0,
        tip_width_ratio: float = 5,
        tip_angle: float = PI / 3,
        max_tip_length_to_length_ratio: float = 0.5,
        max_width_to_length_ratio: float = 0.1,
        **kwargs,
    ):
        self.thickness = thickness
        self.tip_width_ratio = tip_width_ratio
        self.tip_angle = tip_angle
        self.max_tip_length_to_length_ratio = max_tip_length_to_length_ratio
        self.max_width_to_length_ratio = max_width_to_length_ratio
        super().__init__(
            start, end,
            fill_color=fill_color,
            fill_opacity=fill_opacity,
            stroke_width=stroke_width,
            buff=buff,
            path_arc=path_arc,
            **kwargs
        )

    def get_key_dimensions(self, length):
        width = self.thickness * self.tickness_multiplier
        w_ratio = fdiv(self.max_width_to_length_ratio, fdiv(width, length))
        if w_ratio < 1:
            width *= w_ratio

        tip_width = self.tip_width_ratio * width
        tip_length = tip_width / (2 * np.tan(self.tip_angle / 2))
        t_ratio = fdiv(self.max_tip_length_to_length_ratio, fdiv(tip_length, length))
        if t_ratio < 1:
            tip_length *= t_ratio
            tip_width *= t_ratio

        return width, tip_width, tip_length

    def set_points_by_ends(
        self,
        start: Vect3,
        end: Vect3,
        buff: float = 0,
        path_arc: float = 0
    ) -> Self:
        vect = end - start
        length = max(get_norm(vect), 1e-8)  # More systematic min?
        unit_vect = normalize(vect)

        # Find the right tip length and thickness
        width, tip_width, tip_length = self.get_key_dimensions(length - buff)

        # Adjust start and end based on buff
        if path_arc == 0:
            start = start + buff * unit_vect
            end = end - buff * unit_vect
        else:
            R = length / 2 / math.sin(path_arc / 2)
            midpoint = 0.5 * (start + end)
            center = midpoint + rotate_vector(0.5 * vect, PI / 2) / math.tan(path_arc / 2)
            sign = 1
            start = center + rotate_vector(start - center, buff / R)
            end = center + rotate_vector(end - center, -buff / R)
            path_arc -= (2 * buff + tip_length) / R
        vect = end - start
        length = get_norm(vect)

        # Find points for the stem, imagining an arrow pointed to the left
        if path_arc == 0:
            points1 = (length - tip_length) * np.array([RIGHT, 0.5 * RIGHT, ORIGIN])
            points1 += width * UP / 2
            points2 = points1[::-1] + width * DOWN
        else:
            # Find arc points
            points1 = quadratic_bezier_points_for_arc(path_arc)
            points2 = np.array(points1[::-1])
            points1 *= (R + width / 2)
            points2 *= (R - width / 2)
            rot_T = rotation_matrix_transpose(PI / 2 - path_arc, OUT)
            for points in points1, points2:
                points[:] = np.dot(points, rot_T)
                points += R * DOWN

        self.set_points(points1)
        # Tip
        self.add_line_to(tip_width * UP / 2)
        self.add_line_to(tip_length * LEFT)
        self.tip_index = len(self.get_points()) - 1
        self.add_line_to(tip_width * DOWN / 2)
        self.add_line_to(points2[0])
        # Close it out
        self.add_subpath(points2)
        self.add_line_to(points1[0])

        # Reposition to match proper start and end
        self.rotate(angle_of_vector(vect) - self.get_angle())
        self.rotate(
            PI / 2 - np.arccos(normalize(vect)[2]),
            axis=rotate_vector(self.get_unit_vector(), -PI / 2),
        )
        self.shift(start - self.get_start())
        return self

    def reset_points_around_ends(self) -> Self:
        self.set_points_by_ends(
            self.get_start().copy(),
            self.get_end().copy(),
            path_arc=self.path_arc
        )
        return self

    def get_start(self) -> Vect3:
        points = self.get_points()
        return 0.5 * (points[0] + points[-3])

    def get_end(self) -> Vect3:
        return self.get_points()[self.tip_index]

    def get_start_and_end(self):
        return (self.get_start(), self.get_end())

    def put_start_and_end_on(self, start: Vect3, end: Vect3) -> Self:
        self.set_points_by_ends(start, end, buff=0, path_arc=self.path_arc)
        return self

    def scale(self, *args, **kwargs) -> Self:
        super().scale(*args, **kwargs)
        self.reset_points_around_ends()
        return self

    def set_thickness(self, thickness: float) -> Self:
        self.thickness = thickness
        self.reset_points_around_ends()
        return self

    def set_path_arc(self, path_arc: float) -> Self:
        self.path_arc = path_arc
        self.reset_points_around_ends()
        return self

    def set_perpendicular_to_camera(self, camera_frame):
        to_cam = camera_frame.get_implied_camera_location() - self.get_center()
        normal = self.get_unit_normal()
        axis = normalize(self.get_vector())
        # Project to be perpendicular to axis
        trg_normal = to_cam - np.dot(to_cam, axis) * axis
        mat = rotation_between_vectors(normal, trg_normal)
        self.apply_matrix(mat, about_point=self.get_start())
        return self


class Vector(Arrow):
    '''
    Creates a vector. Vector is an arrow with start point as ORIGIN
    Parameters
    -----
    direction : array_like
        Coordinates of direction of the arrow
    Examples :
            arrow = Vector(direction=LEFT)
    Returns
    -----
    out : Vector object
        A Vector object satisfying the specified parameters
    '''

    def __init__(
        self,
        direction: Vect3 = RIGHT,
        buff: float = 0.0,
        **kwargs
    ):
        if len(direction) == 2:
            direction = np.hstack([direction, 0])
        super().__init__(ORIGIN, direction, buff=buff, **kwargs)


class CubicBezier(VMobject):
    '''
    Creates a cubic Bézier curve.

    A cubic Bézier curve is defined by four control points: two anchor points (start and end)
    and two handle points that control the curvature. The curve starts at the first anchor
    point, is "pulled" toward the handle points, and ends at the second anchor point.

    Parameters
    ----------
    a0 : array_like
        First anchor point (starting point of the curve).
    h0 : array_like
        First handle point (controls the initial direction and curvature from a0).
    h1 : array_like
        Second handle point (controls the final direction and curvature toward a1).
    a1 : array_like
        Second anchor point (ending point of the curve).
    **kwargs
        Additional keyword arguments passed to the parent VMobject class, such as
        stroke_color, stroke_width, fill_color, fill_opacity, etc.
    Returns
    -------
    CubicBezier
        A CubicBezier object representing the specified cubic Bézier curve.

    '''

    def __init__(
        self,
        a0: Vect3,
        h0: Vect3,
        h1: Vect3,
        a1: Vect3,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.add_cubic_bezier_curve(a0, h0, h1, a1)


class Polygon(VMobject):
    '''
    Creates a polygon by joining the specified vertices.
    Parameters
    -----
    *vertices : array_like
        Vertex of the polygon
    Examples :
            triangle = Polygon((-3,0,0), (3,0,0), (0,3,0))
    Returns
    -----
    out : Polygon object
        A Polygon object satisfying the specified parameters
    '''

    def __init__(
        self,
        *vertices: Vect3,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.set_points_as_corners([*vertices, vertices[0]])

    def get_vertices(self) -> Vect3Array:
        return self.get_start_anchors()

    def round_corners(self, radius: Optional[float] = None) -> Self:
        if radius is None:
            verts = self.get_vertices()
            min_edge_length = min(
                get_norm(v1 - v2)
                for v1, v2 in zip(verts, verts[1:])
                if not np.isclose(v1, v2).all()
            )
            radius = 0.25 * min_edge_length
        vertices = self.get_vertices()
        arcs = []
        for v1, v2, v3 in adjacent_n_tuples(vertices, 3):
            vect1 = normalize(v2 - v1)
            vect2 = normalize(v3 - v2)
            angle = angle_between_vectors(vect1, vect2)
            # Distance between vertex and start of the arc
            cut_off_length = radius * np.tan(angle / 2)
            # Negative radius gives concave curves
            sign = float(np.sign(radius * cross2d(vect1, vect2)))
            arc = ArcBetweenPoints(
                v2 - vect1 * cut_off_length,
                v2 + vect2 * cut_off_length,
                angle=sign * angle,
                n_components=2,
            )
            arcs.append(arc)

        self.clear_points()
        # To ensure that we loop through starting with last
        arcs = [arcs[-1], *arcs[:-1]]
        for arc1, arc2 in adjacent_pairs(arcs):
            self.add_subpath(arc1.get_points())
            self.add_line_to(arc2.get_start())
        return self


class Polyline(VMobject):
    def __init__(
        self,
        *vertices: Vect3,
        **kwargs
    ):
        super().__init__(**kwargs)
        self.set_points_as_corners(vertices)


class RegularPolygon(Polygon):
    '''
    Creates a regular polygon of edge length 1 at the center of the screen.
    Parameters
    -----
    n : int
        Number of vertices of the regular polygon
    start_angle : float
        Starting angle of the regular polygon in radians. (Angles are measured counter-clockwise)
    Examples :
            pentagon = RegularPolygon(n=5, start_angle=30 * DEGREES)
    Returns
    -----
    out : RegularPolygon object
        A RegularPolygon object satisfying the specified parameters
    '''

    def __init__(
        self,
        n: int = 6,
        radius: float = 1.0,
        start_angle: float | None = None,
        **kwargs
    ):
        # Defaults to 0 for odd, 90 for even
        if start_angle is None:
            start_angle = (n % 2) * 90 * DEG
        start_vect = rotate_vector(radius * RIGHT, start_angle)
        vertices = compass_directions(n, start_vect)
        super().__init__(*vertices, **kwargs)


class Triangle(RegularPolygon):
    '''
    Creates a triangle of edge length 1 at the center of the screen.
    Parameters
    -----
    start_angle : float
        Starting angle of the triangle in radians. (Angles are measured counter-clockwise)
    Examples :
            triangle = Triangle(start_angle=45 * DEGREES)
    Returns
    -----
    out : Triangle object
        A Triangle object satisfying the specified parameters
    '''

    def __init__(self, **kwargs):
        super().__init__(n=3, **kwargs)


class ArrowTip(Triangle):
    def __init__(
        self,
        angle: float = 0,
        width: float = DEFAULT_ARROW_TIP_WIDTH,
        length: float = DEFAULT_ARROW_TIP_LENGTH,
        fill_opacity: float = 1.0,
        fill_color: ManimColor = DEFAULT_MOBJECT_COLOR,
        stroke_width: float = 0.0,
        tip_style: int = 0,  # triangle=0, inner_smooth=1, dot=2
        **kwargs
    ):
        super().__init__(
            start_angle=0,
            fill_opacity=fill_opacity,
            fill_color=fill_color,
            stroke_width=stroke_width,
            **kwargs
        )
        self.set_height(width)
        self.set_width(length, stretch=True)
        if tip_style == 1:
            self.set_height(length * 0.9, stretch=True)
            self.data["point"][4] += np.array([0.6 * length, 0, 0])
        elif tip_style == 2:
            h = length / 2
            self.set_points(Dot().set_width(h).get_points())
        self.rotate(angle)

    def get_base(self) -> Vect3:
        return self.point_from_proportion(0.5)

    def get_tip_point(self) -> Vect3:
        return self.get_points()[0]

    def get_vector(self) -> Vect3:
        return self.get_tip_point() - self.get_base()

    def get_angle(self) -> float:
        return angle_of_vector(self.get_vector())

    def get_length(self) -> float:
        return get_norm(self.get_vector())


class Rectangle(Polygon):
    '''
    Creates a rectangle at the center of the screen.
    Parameters
    -----
    width : float
        Width of the rectangle
    height : float
        Height of the rectangle
    Examples :
            rectangle = Rectangle(width=3, height=4, color=BLUE)
    Returns
    -----
    out : Rectangle object
        A Rectangle object satisfying the specified parameters
    '''

    def __init__(
        self,
        width: float = 4.0,
        height: float = 2.0,
        **kwargs
    ):
        super().__init__(UR, UL, DL, DR, **kwargs)
        self.set_width(width, stretch=True)
        self.set_height(height, stretch=True)

    def surround(self, mobject, buff=SMALL_BUFF) -> Self:
        target_shape = np.array(mobject.get_shape()) + 2 * buff
        self.set_shape(*target_shape)
        self.move_to(mobject)
        return self


class Square(Rectangle):
    '''
    Creates a square at the center of the screen.
    Parameters
    -----
    side_length : float
        Edge length of the square
    Examples :
            square = Square(side_length=5, color=PINK)
    Returns
    -----
    out : Square object
        A Square object satisfying the specified parameters
    '''

    def __init__(self, side_length: float = 2.0, **kwargs):
        super().__init__(side_length, side_length, **kwargs)


class Squircle(VMobject):
    '''
    Creates a squircle (superellipse) - a shape between a rectangle and ellipse.
    
    The squircle is defined by the equation:
    |x/a|^n + |y/b|^n = 1
    
    Parameters
    ----------
    width : float
        Width of the bounding rectangle (2*a)
    height : float
        Height of the bounding rectangle (2*b)
    squareness : float
        Parameter controlling the shape (2 = ellipse, >2 = more rectangular, typically 4)
    arc_center : Vect3Array
        Center point of the squircle
    **kwargs
        Additional keyword arguments to pass to VMobject
        
    Examples
    --------
        squircle = Squircle(width=2, height=2, squareness=4)  # Square squircle
        squircle = Squircle(width=3, height=2, squareness=4)  # Rectangular squircle
        squircle = Squircle(width=3, height=2, squareness=3, color=BLUE)
        
    Returns
    -------
    out : Squircle object
        A Squircle object satisfying the specified parameters
    '''
    
    def __init__(
        self,
        width: float = 2.0,
        height: float = None,
        side_length: float = None,  # For backwards compatibility
        squareness: float = 4.0,
        arc_center: Vect3Array = ORIGIN,
        **kwargs
    ):
        # Handle backwards compatibility
        if side_length is not None:
            width = side_length
            height = side_length
        elif height is None:
            height = width
            
        self.width = width
        self.height = height
        self.squareness = squareness
        self.arc_center = arc_center
        super().__init__(**kwargs)
        
    def init_points(self) -> None:
        # Generate points for the squircle using parametric equations
        n_points = 100
        t = np.linspace(0, TAU, n_points)
        a = self.width / 2   # Semi-width
        b = self.height / 2  # Semi-height
        
        # Parametric equations for superellipse
        # Using the fact that for |x|^n + |y|^n = 1:
        # x = sign(cos(t)) * |cos(t)|^(2/n)
        # y = sign(sin(t)) * |sin(t)|^(2/n)
        n = self.squareness
        exponent = 2.0 / n
        
        cos_t = np.cos(t)
        sin_t = np.sin(t)
        
        x = a * np.sign(cos_t) * np.abs(cos_t) ** exponent
        y = b * np.sign(sin_t) * np.abs(sin_t) ** exponent
        z = np.zeros_like(x)
        
        points = np.column_stack([x, y, z])
        points += self.arc_center
        
        # Close the path
        points = np.append(points, [points[0]], axis=0)
        
        # Set points using quadratic bezier curves
        # We'll create the shape by connecting the points
        self.set_points_as_corners(points)
        self.close_path()


class RoundedRectangle(Rectangle):
    '''
    Creates a rectangle with round edges at the center of the screen.
    Parameters
    -----
    width : float
        Width of the rounded rectangle
    height : float
        Height of the rounded rectangle
    corner_radius : float
        Corner radius of the rectangle
    Examples :
            rRectangle = RoundedRectangle(width=3, height=4, corner_radius=1, color=BLUE)
    Returns
    -----
    out : RoundedRectangle object
        A RoundedRectangle object satisfying the specified parameters
    '''

    def __init__(
        self,
        width: float = 4.0,
        height: float = 2.0,
        corner_radius: float = 0.5,
        **kwargs
    ):
        super().__init__(width, height, **kwargs)
        self.round_corners(corner_radius)
