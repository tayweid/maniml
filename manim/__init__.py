"""
maniml - ManimCE-compatible animations with OpenGL performance
"""

# Import all constants first
from .constants import *
# Explicitly import commonly used constants for better IDE support
from .constants import (
    PI, TAU, DEGREES, DEG,
    UP, DOWN, LEFT, RIGHT, IN, OUT,
    UL, UR, DL, DR,
    ORIGIN,
    BLUE, RED, GREEN, YELLOW, WHITE, BLACK,
    FRAME_WIDTH, FRAME_HEIGHT
)

# Import essential scene classes
from .scene.scene import Scene, ThreeDScene

# Import basic mobjects directly
from .mobject.mobject import Mobject, Group
from .mobject.geometry import Circle, Dot, Line, Rectangle, Square, Arrow, Vector
from .mobject.types.vectorized_mobject import VMobject, VGroup
from .mobject.svg.tex_mobject import Tex
from .mobject.svg.text_mobject import Text
from .mobject.numbers import DecimalNumber

# Import 3D-related classes
from .mobject.types.surface import Surface, SGroup
from .mobject.types.vmobject_3d import VMobject3D, Circle3D, Text3D
from .mobject.three_dimensions import (
    Sphere, Cube, Torus, Cylinder, Cone,
    Line3D, Disk3D, Square3D, Rectangle3D, Prism
)
from .mobject.coordinate_systems import ThreeDAxes

# Import core animations directly
from .animation.animation import Animation
from .animation.creation import ShowCreation
from .animation.transform import Transform, ReplacementTransform
from .animation.fading import FadeIn, FadeOut
from .animation.composition import AnimationGroup, Succession, LaggedStart

# Import CE compatibility layer
from .compatibility import (
    # Creation animations
    Create, Uncreate, Write, Unwrite,
    # Movement animations
    Shift, MoveTo, Scale, Rotate,
    # Special animations
    Wait,
    # Aliases
    MathTex,
)

# Import rate functions
from .utils.rate_functions import (
    linear, smooth, there_and_back, there_and_back_with_pause,
    rush_into, rush_from, slow_into, double_smooth
)

# For convenience, make everything available at package level
__all__ = [
    # Scenes
    'Scene', 'ThreeDScene',
    # Basic Mobjects
    'Mobject', 'Group', 'VMobject', 'VGroup',
    # Shapes
    'Circle', 'Dot', 'Line', 'Rectangle', 'Square', 'Arrow', 'Vector',
    # 3D Shapes
    'Surface', 'SGroup', 'Sphere', 'Cube', 'Torus', 'Cylinder', 'Cone',
    'Line3D', 'Disk3D', 'Square3D', 'Rectangle3D', 'Prism',
    'VMobject3D', 'Circle3D', 'Text3D',
    # Coordinate Systems
    'ThreeDAxes',
    # Text
    'Text', 'Tex', 'MathTex', 'DecimalNumber',
    # Core Animations
    'Animation', 'ShowCreation',
    # Transform Animations
    'Transform', 'ReplacementTransform',
    # Fade Animations
    'FadeIn', 'FadeOut',
    # Composition
    'AnimationGroup', 'Succession', 'LaggedStart',
    # CE-Compatible Animations
    'Create', 'Uncreate', 'Write', 'Unwrite',
    'Shift', 'MoveTo', 'Scale', 'Rotate',
    'Wait',
    # Rate functions
    'linear', 'smooth', 'there_and_back', 'there_and_back_with_pause',
    'rush_into', 'rush_from', 'slow_into', 'double_smooth',
]