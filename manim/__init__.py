"""
maniml - Standalone Manim without external dependencies
"""

# Import all constants first
from .constants import *

# Import essential scene classes
from .scene.scene import Scene, ThreeDScene

# Import basic mobjects
from .mobject.mobject import Mobject, Group
from .mobject.geometry import Circle, Dot, Line, Rectangle, Square, Arrow, Vector
from .mobject.types.vectorized_mobject import VMobject, VGroup
from .mobject.svg.tex_mobject import Tex
from .mobject.svg.text_mobject import Text
from .mobject.numbers import DecimalNumber

# Import core animations
from .animation.animation import Animation
from .animation.creation import ShowCreation, Create, Write
from .animation.transform import Transform, ReplacementTransform
from .animation.fading import FadeIn, FadeOut
from .animation.composition import AnimationGroup, Succession, LaggedStart

# Wait is a special case - it's a method on Scene, not an animation
def Wait(duration=1.0, **kwargs):
    """Create a Wait animation."""
    from .animation.animation import Animation
    class _Wait(Animation):
        def __init__(self, duration=1.0, **kwargs):
            super().__init__(None, run_time=duration, **kwargs)
    return _Wait(duration, **kwargs)

# CE compatibility aliases
MathTex = Tex
Uncreate = lambda mob, **kwargs: ShowCreation(mob, rate_func=lambda t: 1-t, **kwargs)

# Simple movement animations
from .animation.transform import Transform as _Transform

class Shift(_Transform):
    """Shift animation."""
    def __init__(self, mobject, direction, **kwargs):
        target = mobject.copy().shift(direction)
        super().__init__(mobject, target, **kwargs)

class MoveTo(_Transform):
    """MoveTo animation."""
    def __init__(self, mobject, point_or_mobject, **kwargs):
        target = mobject.copy()
        if hasattr(point_or_mobject, "get_center"):
            target.move_to(point_or_mobject.get_center())
        else:
            target.move_to(point_or_mobject)
        super().__init__(mobject, target, **kwargs)

class Scale(_Transform):
    """Scale animation."""
    def __init__(self, mobject, scale_factor, **kwargs):
        target = mobject.copy().scale(scale_factor)
        super().__init__(mobject, target, **kwargs)

class Rotate(_Transform):
    """Rotate animation."""
    def __init__(self, mobject, angle, **kwargs):
        target = mobject.copy().rotate(angle)
        super().__init__(mobject, target, **kwargs)