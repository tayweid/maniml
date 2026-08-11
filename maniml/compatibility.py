"""
ManimCE Compatibility Layer for Maniml

This module provides mappings from ManimCE API to ManimGL implementation,
allowing CE code to run on the GL backend with minimal changes.
"""

from .animation.transform import Transform as _Transform
from .animation.creation import ShowCreation
from .animation.animation import Animation


# Animation Aliases
def Create(mobject, **kwargs):
    """CE-compatible alias for ShowCreation."""
    return ShowCreation(mobject, **kwargs)


def Uncreate(mobject, **kwargs):
    """CE-compatible reverse of Create."""
    return ShowCreation(mobject, rate_func=lambda t: 1-t, **kwargs)


def Write(mobject, **kwargs):
    """CE-compatible alias for ShowCreation (for text)."""
    return ShowCreation(mobject, **kwargs)


def Unwrite(mobject, **kwargs):
    """CE-compatible reverse of Write."""
    return ShowCreation(mobject, rate_func=lambda t: 1-t, **kwargs)


# Movement Animations
class Shift(_Transform):
    """Shift animation - moves mobject by a vector."""
    def __init__(self, mobject, direction, **kwargs):
        target = mobject.copy().shift(direction)
        super().__init__(mobject, target, **kwargs)


class MoveTo(_Transform):
    """MoveTo animation - moves mobject to a point or another mobject's position."""
    def __init__(self, mobject, point_or_mobject, **kwargs):
        target = mobject.copy()
        if hasattr(point_or_mobject, "get_center"):
            target.move_to(point_or_mobject.get_center())
        else:
            target.move_to(point_or_mobject)
        super().__init__(mobject, target, **kwargs)


class Scale(_Transform):
    """Scale animation - scales mobject by a factor."""
    def __init__(self, mobject, scale_factor, **kwargs):
        target = mobject.copy().scale(scale_factor)
        super().__init__(mobject, target, **kwargs)


class Rotate(_Transform):
    """Rotate animation - rotates mobject by an angle."""
    def __init__(self, mobject, angle, axis=None, about_point=None, **kwargs):
        import numpy as np
        from .constants import OUT
        
        # Default axis is OUT (z-axis)
        if axis is None:
            axis = OUT
            
        # Extract axis from kwargs if passed there (for compatibility)
        axis = kwargs.pop('axis', axis)
        about_point = kwargs.pop('about_point', about_point)
        
        # Create target with rotation
        target = mobject.copy()
        if about_point is not None:
            target.rotate(angle, axis=axis, about_point=about_point)
        else:
            target.rotate(angle, axis=axis)
            
        super().__init__(mobject, target, **kwargs)


# Special Animations
class Wait(Animation):
    """Wait animation - pauses for a duration."""
    def __init__(self, duration=1.0, **kwargs):
        super().__init__(None, run_time=duration, **kwargs)


def Circumscribe(mobject, shape=None, time_width=0.3, buff=None,
                 color=None, stroke_width=3, run_time=1, **kwargs):
    """CE-compatible flash around a mobject.

    Backed by GL's FlashAround; the `shape` argument is accepted for
    signature compatibility but the flash outline is always the
    surrounding rectangle.
    """
    from .animation.indication import FlashAround
    from .constants import SMALL_BUFF, YELLOW
    kwargs.pop('fade_in', None)
    kwargs.pop('fade_out', None)
    return FlashAround(
        mobject,
        time_width=time_width,
        buff=SMALL_BUFF if buff is None else buff,
        color=YELLOW if color is None else color,
        stroke_width=stroke_width,
        run_time=run_time,
        **kwargs,
    )


def Wiggle(mobject, scale_value=1.1, rotation_angle=None, n_wiggles=6, **kwargs):
    """CE-compatible wiggle (GL: WiggleOutThenIn, same semantics)."""
    from .animation.indication import WiggleOutThenIn
    from .constants import TAU
    return WiggleOutThenIn(
        mobject,
        scale_value=scale_value,
        rotation_angle=0.01 * TAU if rotation_angle is None else rotation_angle,
        n_wiggles=n_wiggles,
        **kwargs,
    )


class SpinInFromNothing(Animation):
    """CE-compatible grow-with-spin entrance."""
    def __new__(cls, mobject, angle=None, **kwargs):
        from .animation.growing import GrowFromCenter
        from .constants import PI
        return GrowFromCenter(
            mobject, path_arc=PI / 2 if angle is None else angle, **kwargs)


class Broadcast(Animation):
    """CE-compatible broadcast: ripples of `mobject` from a focal point."""
    def __new__(cls, mobject, focal_point=None, n_mobs=5, initial_opacity=1.0,
                final_opacity=0.0, initial_width=0.0, remover=True,
                lag_ratio=0.2, run_time=3, **kwargs):
        from .animation.composition import LaggedStart
        from .animation.transform import Transform
        from .constants import ORIGIN
        focal_point = ORIGIN if focal_point is None else focal_point
        anims = []
        for _ in range(n_mobs):
            start = mobject.copy()
            start.set_width(max(initial_width, 1e-3))
            start.move_to(focal_point)
            start.set_opacity(initial_opacity)
            target = mobject.copy().move_to(focal_point)
            target.set_opacity(final_opacity)
            anims.append(Transform(start, target, remover=remover))
        return LaggedStart(*anims, lag_ratio=lag_ratio,
                           run_time=run_time, **kwargs)


# Text/Math Aliases
def MathTex(*args, **kwargs):
    """CE-compatible math-mode Tex."""
    from .mobject.svg.tex_mobject import MathTex as _MathTex
    return _MathTex(*args, **kwargs)


def Tex(*args, **kwargs):
    """Import Tex from the correct location."""
    from .mobject.svg.tex_mobject import Tex as _Tex
    return _Tex(*args, **kwargs)


def Text(*args, **kwargs):
    """Import Text from the correct location."""
    from .mobject.svg.text_mobject import Text as _Text
    return _Text(*args, **kwargs)


# Shape Aliases
def Circle(**kwargs):
    """Import Circle from the correct location."""
    from .mobject.geometry import Circle as _Circle
    return _Circle(**kwargs)


def Square(**kwargs):
    """Import Square from the correct location."""
    from .mobject.geometry import Square as _Square
    return _Square(**kwargs)


def Rectangle(**kwargs):
    """Import Rectangle from the correct location."""
    from .mobject.geometry import Rectangle as _Rectangle
    return _Rectangle(**kwargs)


def Dot(**kwargs):
    """Import Dot from the correct location."""
    from .mobject.geometry import Dot as _Dot
    return _Dot(**kwargs)


def Line(*args, **kwargs):
    """Import Line from the correct location."""
    from .mobject.geometry import Line as _Line
    return _Line(*args, **kwargs)


def Arrow(*args, **kwargs):
    """Import Arrow from the correct location."""
    from .mobject.geometry import Arrow as _Arrow
    return _Arrow(*args, **kwargs)


def Vector(*args, **kwargs):
    """Import Vector from the correct location."""
    from .mobject.geometry import Vector as _Vector
    return _Vector(*args, **kwargs)


# Group Aliases
def VGroup(*mobjects, **kwargs):
    """Import VGroup from the correct location."""
    from .mobject.types.vectorized_mobject import VGroup as _VGroup
    return _VGroup(*mobjects, **kwargs)


def Group(*mobjects, **kwargs):
    """Import Group from the correct location."""
    from .mobject.mobject import Group as _Group
    return _Group(*mobjects, **kwargs)


# Animation Imports
def FadeIn(*args, **kwargs):
    """Import FadeIn from the correct location."""
    from .animation.fading import FadeIn as _FadeIn
    return _FadeIn(*args, **kwargs)


def FadeOut(*args, **kwargs):
    """Import FadeOut from the correct location."""
    from .animation.fading import FadeOut as _FadeOut
    return _FadeOut(*args, **kwargs)


def Transform(*args, **kwargs):
    """Import Transform from the correct location."""
    from .animation.transform import Transform as _Transform
    return _Transform(*args, **kwargs)


def ReplacementTransform(*args, **kwargs):
    """Import ReplacementTransform from the correct location."""
    from .animation.transform import ReplacementTransform as _ReplacementTransform
    return _ReplacementTransform(*args, **kwargs)


# Composition Animations
def AnimationGroup(*animations, **kwargs):
    """Import AnimationGroup from the correct location."""
    from .animation.composition import AnimationGroup as _AnimationGroup
    return _AnimationGroup(*animations, **kwargs)


def Succession(*animations, **kwargs):
    """Import Succession from the correct location."""
    from .animation.composition import Succession as _Succession
    return _Succession(*animations, **kwargs)


def LaggedStart(*animations, **kwargs):
    """Import LaggedStart from the correct location."""
    from .animation.composition import LaggedStart as _LaggedStart
    return _LaggedStart(*animations, **kwargs)


# All CE-compatible exports
__all__ = [
    # Creation
    'Create', 'Uncreate', 'Write', 'Unwrite',
    # Movement
    'Shift', 'MoveTo', 'Scale', 'Rotate',
    # Special
    'Wait',
    # Text/Math
    'MathTex', 'Tex', 'Text',
    # Shapes
    'Circle', 'Square', 'Rectangle', 'Dot', 'Line', 'Arrow', 'Vector',
    # Groups
    'VGroup', 'Group',
    # Animations
    'FadeIn', 'FadeOut', 'Transform', 'ReplacementTransform',
    # Composition
    'AnimationGroup', 'Succession', 'LaggedStart',
]