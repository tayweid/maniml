"""
Geometric mobjects with CE defaults and compatibility.
"""

import manim
from manim.constants import *

# Most shapes are directly compatible, we just need to ensure CE defaults

def Circle(radius=1.0, color=WHITE, **kwargs):
    """Circle with CE default radius of 1.0."""
    return manim.renderer.opengl.mobject.geometry.Circle(radius=radius, color=color, **kwargs)


def Dot(point=ORIGIN, radius=0.08, stroke_width=0, fill_opacity=1.0, color=WHITE, **kwargs):
    """Dot with CE defaults."""
    dot = manim.renderer.opengl.mobject.geometry.Dot(point=point, radius=radius, color=color, **kwargs)
    dot.set_stroke(width=stroke_width)
    dot.set_fill(opacity=fill_opacity)
    return dot


def Ellipse(width=2, height=1, color=WHITE, **kwargs):
    """Ellipse with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.Circle(color=color, **kwargs).stretch(width / 2, 0).stretch(height / 2, 1)


def Rectangle(width=4.0, height=2.0, color=WHITE, **kwargs):
    """Rectangle with CE default dimensions."""
    return manim.renderer.opengl.mobject.geometry.Rectangle(width=width, height=height, color=color, **kwargs)


def Square(side_length=2.0, color=WHITE, **kwargs):
    """Square with CE default side length of 2.0."""
    return manim.renderer.opengl.mobject.geometry.Square(side_length=side_length, color=color, **kwargs)


def RoundedRectangle(width=4.0, height=2.0, corner_radius=0.5, color=WHITE, **kwargs):
    """RoundedRectangle with CE defaults."""
    # GL might not have RoundedRectangle, so we approximate
    if hasattr(manim.renderer.opengl.mobject.geometry, 'RoundedRectangle'):
        return manim.renderer.opengl.mobject.geometry.RoundedRectangle(width=width, height=height, corner_radius=corner_radius, color=color, **kwargs)
    else:
        # Fallback to regular rectangle
        import warnings
        warnings.warn("maniml: RoundedRectangle not available, using Rectangle", UserWarning)
        return Rectangle(width=width, height=height, color=color, **kwargs)


def Triangle(color=WHITE, **kwargs):
    """Triangle with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.Triangle(color=color, **kwargs)


def RegularPolygon(n=6, color=WHITE, **kwargs):
    """RegularPolygon with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.RegularPolygon(n=n, color=color, **kwargs)


def Star(n=5, outer_radius=1, inner_radius=0.5, color=WHITE, **kwargs):
    """Star shape with CE defaults."""
    import numpy as np
    # Create star vertices alternating between outer and inner radius
    vertices = []
    for i in range(2 * n):
        angle = i * TAU / (2 * n) - TAU / 4  # Start at top
        radius = outer_radius if i % 2 == 0 else inner_radius
        vertices.append(radius * np.array([np.cos(angle), np.sin(angle), 0]))
    return Polygon(*vertices, color=color, **kwargs)


def Polygon(*vertices, color=WHITE, **kwargs):
    """Polygon with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.Polygon(*vertices, color=color, **kwargs)


def Line(start=LEFT, end=RIGHT, buff=0, color=WHITE, **kwargs):
    """Line with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.Line(start=start, end=end, buff=buff, color=color, **kwargs)


def DashedLine(start=LEFT, end=RIGHT, dash_length=0.05, dashed_ratio=0.5, color=WHITE, **kwargs):
    """DashedLine with CE defaults."""
    # GL doesn't support dashed_ratio parameter
    kwargs.pop('dashed_ratio', None)
    
    if hasattr(manim.renderer.opengl.mobject.geometry, 'DashedLine'):
        return manim.renderer.opengl.mobject.geometry.DashedLine(
            start=start, end=end, dash_length=dash_length, 
            color=color, **kwargs
        )
    else:
        # Create dashed effect manually
        line = Line(start=start, end=end, color=color, **kwargs)
        # This is a simplified version
        return line


def Arrow(start=LEFT, end=RIGHT, buff=0, max_tip_length_to_length_ratio=0.25, 
          max_stroke_width_to_length_ratio=5, color=WHITE, **kwargs):
    """Arrow with CE defaults."""
    # GL Arrow is simpler, ignore some CE parameters
    return manim.renderer.opengl.mobject.geometry.Arrow(start=start, end=end, buff=buff, color=color, **kwargs)


def DoubleArrow(start=LEFT, end=RIGHT, buff=0, color=WHITE, **kwargs):
    """DoubleArrow with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.DoubleArrow(start=start, end=end, buff=buff, color=color, **kwargs)


def Vector(direction=RIGHT, buff=0, color=WHITE, **kwargs):
    """Vector (arrow from origin) with CE defaults."""
    return Arrow(start=ORIGIN, end=direction, buff=buff, color=color, **kwargs)


def Arc(radius=1.0, start_angle=0, angle=TAU / 4, color=WHITE, **kwargs):
    """Arc with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.Arc(radius=radius, start_angle=start_angle, angle=angle, color=color, **kwargs)


def ArcBetweenPoints(start, end, angle=TAU / 4, color=WHITE, **kwargs):
    """ArcBetweenPoints with CE defaults."""
    return manim.renderer.opengl.mobject.geometry.ArcBetweenPoints(start, end, angle=angle, color=color, **kwargs)


def CurvedArrow(start_point, end_point, color=WHITE, **kwargs):
    """CurvedArrow with CE defaults."""
    if hasattr(manim.renderer.opengl.mobject.geometry, 'CurvedArrow'):
        return manim.renderer.opengl.mobject.geometry.CurvedArrow(start_point, end_point, color=color, **kwargs)
    else:
        # Approximate with ArcBetweenPoints + arrow tip
        arc = ArcBetweenPoints(start_point, end_point, color=color, **kwargs)
        # Add arrow tip manually if needed
        return arc


def CurvedDoubleArrow(start_point, end_point, color=WHITE, **kwargs):
    """CurvedDoubleArrow with CE defaults."""
    if hasattr(manim.renderer.opengl.mobject.geometry, 'CurvedDoubleArrow'):
        return manim.renderer.opengl.mobject.geometry.CurvedDoubleArrow(start_point, end_point, color=color, **kwargs)
    else:
        # Approximate
        arc = ArcBetweenPoints(start_point, end_point, color=color, **kwargs)
        return arc


def Angle(line1, line2, radius=0.5, quadrant=(1, 1), other_angle=False, color=WHITE, **kwargs):
    """Angle marker with CE defaults."""
    if hasattr(manim.renderer.opengl.mobject.geometry, 'Angle'):
        return manim.renderer.opengl.mobject.geometry.Angle(line1, line2, radius=radius, quadrant=quadrant, 
                           other_angle=other_angle, color=color, **kwargs)
    else:
        # Simple approximation with an arc
        import warnings
        warnings.warn("maniml: Angle not available, using Arc approximation", UserWarning)
        return Arc(radius=radius, color=color, **kwargs)


def RightAngle(line1, line2, length=0.5, color=WHITE, **kwargs):
    """Right angle marker with CE defaults."""
    if hasattr(manim.renderer.opengl.mobject.geometry, 'RightAngle'):
        return manim.renderer.opengl.mobject.geometry.RightAngle(line1, line2, length=length, color=color, **kwargs)
    else:
        # Create with lines
        import warnings
        warnings.warn("maniml: RightAngle not available, using line approximation", UserWarning)
        from manim.mobject.types.vectorized_mobject import VGroup
        corner = line1.get_end()
        v1 = line1.get_unit_vector() * length
        v2 = line2.get_unit_vector() * length
        
        l1 = Line(corner, corner + v1, color=color, **kwargs)
        l2 = Line(corner, corner + v2, color=color, **kwargs)
        l3 = Line(corner + v1, corner + v1 + v2, color=color, **kwargs)
        l4 = Line(corner + v2, corner + v1 + v2, color=color, **kwargs)
        
        return VGroup(l1, l2, l3, l4)


def Elbow(width=0.2, angle=0, color=WHITE, **kwargs):
    """Elbow (right angle) shape with CE defaults."""
    if hasattr(manim.renderer.opengl.mobject.geometry, 'Elbow'):
        return manim.renderer.opengl.mobject.geometry.Elbow(width=width, angle=angle, color=color, **kwargs)
    else:
        # Create with lines
        from manim.mobject.types.vectorized_mobject import VGroup
        l1 = Line(ORIGIN, RIGHT * width, color=color, **kwargs)
        l2 = Line(ORIGIN, UP * width, color=color, **kwargs)
        elbow = VGroup(l1, l2)
        elbow.rotate(angle)
        return elbow