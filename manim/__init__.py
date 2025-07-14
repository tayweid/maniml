"""
maniml - ManimCE-compatible animations with OpenGL performance
"""

# Import all constants first
from .constants import *

# Import essential scene classes
from .scene.scene import Scene, ThreeDScene

# Import basic mobjects directly
from .mobject.mobject import Mobject, Group
from .mobject.geometry import Circle, Dot, Line, Rectangle, Square, Arrow, Vector
from .mobject.types.vectorized_mobject import VMobject, VGroup
from .mobject.svg.tex_mobject import Tex
from .mobject.svg.text_mobject import Text
from .mobject.numbers import DecimalNumber

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

# For convenience, make everything available at package level
__all__ = [
    # Scenes
    'Scene', 'ThreeDScene',
    # Basic Mobjects
    'Mobject', 'Group', 'VMobject', 'VGroup',
    # Shapes
    'Circle', 'Dot', 'Line', 'Rectangle', 'Square', 'Arrow', 'Vector',
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
]