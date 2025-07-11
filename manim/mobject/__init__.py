"""
maniml Mobjects - CE-compatible mobjects using GL backend.
"""

# Base classes
from manim.renderer.opengl.mobject.mobject import Mobject
from manim.renderer.opengl.mobject.types.vectorized_mobject import VMobject, VGroup

# Import our wrapped versions
from .text.text_mobject import Text, MarkupText, Paragraph
from .text.tex_mobject import Tex, MathTex, SingleStringMathTex, TexTemplate
from .text.code_mobject import Code
from .geometry import (
    Circle, Dot, Ellipse, 
    Rectangle, Square, RoundedRectangle,
    Triangle, RegularPolygon, Star, Polygon,
    Line, DashedLine, Arrow, DoubleArrow, Vector,
    Arc, ArcBetweenPoints, CurvedArrow, CurvedDoubleArrow,
    Angle, RightAngle, Elbow
)
from .boolean_ops import Union, Intersection, Difference, Exclusion
from .labeled import LabeledLine, LabeledArrow, LabeledDot
from .svg_mobject import SVGMobject, ImageMobject
from .number_line import NumberLine, UnitInterval
from .coordinate_systems import Axes, ThreeDAxes, NumberPlane, PolarPlane
from .three_d import (
    Sphere, Cube, Cylinder, Cone, Torus,
    Box3D, Prism, Surface, ParametricSurface,
    Line3D, Arrow3D, Dot3D, ThreeDVMobject,
    Tetrahedron, Octahedron, Icosahedron, Dodecahedron
)
from .value_tracker import ValueTracker, ComplexValueTracker
from .graph import Graph
from .graphing import BarChart

# Direct imports from GL (these are already compatible)
from manim.renderer.opengl.mobject.geometry import (
    Annulus, AnnularSector, Sector,
    CubicBezier, Polyline
)
from manim.renderer.opengl.mobject.svg.brace import Brace, BraceLabel
from manim.renderer.opengl.mobject.numbers import DecimalNumber, Integer
from manim.renderer.opengl.mobject.matrix import Matrix, DecimalMatrix, IntegerMatrix
from manim.renderer.opengl.mobject.interactive import (
    MotionMobject, Button, Checkbox, LinearNumberSlider,
    ColorSliders, Textbox, ControlPanel
)
# Table mobjects
from .table import Table, MathTable, MobjectTable, IntegerTable, DecimalTable

__all__ = [
    # Base classes
    "Mobject", "VMobject", "VGroup",
    
    # Text
    "Text", "MarkupText", "Paragraph", "Code",
    
    # TeX
    "Tex", "MathTex", "SingleStringMathTex", "TexTemplate",
    
    # 2D Geometry
    "Circle", "Dot", "Ellipse",
    "Rectangle", "Square", "RoundedRectangle",
    "Triangle", "RegularPolygon", "Star", "Polygon",
    "Line", "DashedLine", "Arrow", "DoubleArrow", "Vector",
    "Arc", "ArcBetweenPoints", "CurvedArrow", "CurvedDoubleArrow",
    "Angle", "RightAngle", "Elbow",
    "Annulus", "AnnularSector", "Sector",
    "CubicBezier", "Polyline",
    
    # Boolean operations
    "Union", "Intersection", "Difference", "Exclusion",
    
    # Labeled geometry
    "LabeledLine", "LabeledArrow", "LabeledDot",
    
    # SVG and Images
    "SVGMobject", "ImageMobject",
    
    # Coordinate systems
    "NumberLine", "UnitInterval", "DecimalNumber", "Integer",
    "Axes", "ThreeDAxes", "NumberPlane", "PolarPlane",
    
    # 3D Geometry
    "Sphere", "Cube", "Cylinder", "Cone", "Torus",
    "Box3D", "Prism", "Surface", "ParametricSurface",
    "Line3D", "Arrow3D", "Dot3D", "ThreeDVMobject",
    "Tetrahedron", "Octahedron", "Icosahedron", "Dodecahedron",
    
    # Utilities
    "ValueTracker", "ComplexValueTracker",
    "Brace", "BraceLabel", "BraceBetweenPoints",
    "Matrix", "DecimalMatrix", "IntegerMatrix",
    "Table", "MathTable", "MobjectTable", "IntegerTable", "DecimalTable",
    
    # Interactive
    "MotionMobject", "Button", "Checkbox", "LinearNumberSlider",
    "ColorSliders", "Textbox", "ControlPanel",
    
    # Graph theory
    "Graph",
    
    # Charts
    "BarChart",
]


# CE compatibility functions
from manim.renderer.opengl.constants import DEGREES

def BraceBetweenPoints(point1, point2, direction=None, **kwargs):
    """CE-compatible BraceBetweenPoints."""
    from .geometry import Line
    line = Line(point1, point2)
    if direction is None:
        direction = line.copy().rotate(90 * DEGREES).get_unit_vector()
    return Brace(line, direction=direction, **kwargs)