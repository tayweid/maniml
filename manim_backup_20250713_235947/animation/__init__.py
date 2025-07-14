"""
maniml Animations - CE-compatible animations using GL backend.
"""

# Import our wrapped versions
from .creation import (
    Create, Uncreate, DrawBorderThenFill, Write, Unwrite,
    ShowCreation, ShowPassingFlash, ShowPartial,
    AddTextLetterByLetter, AddTextWordByWord
)

from .transform import (
    Transform, ReplacementTransform, TransformFromCopy,
    ClockwiseTransform, CounterclockwiseTransform,
    MoveToTarget, ApplyMethod, ApplyPointwiseFunction,
    ApplyMatrix, Swap, Restore, TransformMatchingShapes,
    TransformMatchingTex
)

from .fading import (
    FadeIn, FadeOut, FadeInFrom, FadeOutAndShift,
    FadeInFromPoint, FadeOutToPoint, FadeInFromLarge,
    FadeTransform, FadeTransformPieces
)

from .growing import (
    GrowFromPoint, GrowFromCenter, GrowFromEdge,
    GrowArrow, SpinInFromNothing, ShrinkToCenter
)

from .movement import (
    Homotopy, ComplexHomotopy, PhaseFlow, MoveAlongPath,
    Shift, MoveTo, Scale, Rotate, Rotating, RotateInPlace
)

from .indication import (
    FocusOn, Indicate, Flash, CircleIndicate, ShowPassingFlashAround,
    ShowCreationThenDestruction, ShowCreationThenFadeOut,
    Wiggle, Circumscribe
)

from .composition import (
    AnimationGroup, Succession, LaggedStart, LaggedStartMap,
    Wait, EmptyAnimation
)

from .changing import (
    AnimatedBoundary, TracedPath
)

from .numbers import (
    ChangingDecimal, ChangeDecimalToValue
)

from .specialized import (
    Broadcast
)

# Direct imports from GL (already compatible)
from manim.animation.update import UpdateFromFunc, UpdateFromAlphaFunc

# Rate functions
from manim.utils.rate_functions import (
    linear, smooth, rush_into, rush_from, slow_into,
    double_smooth, there_and_back, there_and_back_with_pause,
    running_start, not_quite_there, wiggle, squish_rate_func,
    lingering, exponential_decay
)

__all__ = [
    # Creation
    "Create", "Uncreate", "DrawBorderThenFill", "Write", "Unwrite",
    "ShowCreation", "ShowPassingFlash", "ShowPartial",
    "AddTextLetterByLetter", "AddTextWordByWord",
    
    # Transform
    "Transform", "ReplacementTransform", "TransformFromCopy",
    "ClockwiseTransform", "CounterclockwiseTransform",
    "MoveToTarget", "ApplyMethod", "ApplyPointwiseFunction",
    "ApplyMatrix", "Swap", "Restore", "TransformMatchingShapes",
    "TransformMatchingTex",
    
    # Fading
    "FadeIn", "FadeOut", "FadeInFrom", "FadeOutAndShift",
    "FadeInFromPoint", "FadeOutToPoint", "FadeInFromLarge",
    "FadeTransform", "FadeTransformPieces",
    
    # Growing
    "GrowFromPoint", "GrowFromCenter", "GrowFromEdge",
    "GrowArrow", "SpinInFromNothing", "ShrinkToCenter",
    
    # Movement
    "Shift", "MoveTo", "Scale", "Rotate", "Rotating", "RotateInPlace",
    "Homotopy", "ComplexHomotopy", "PhaseFlow", "MoveAlongPath",
    
    # Indication
    "FocusOn", "Indicate", "Flash", "CircleIndicate",
    "ShowPassingFlashAround", "ShowCreationThenDestruction",
    "ShowCreationThenFadeOut", "Wiggle", "Circumscribe",
    
    # Composition
    "AnimationGroup", "Succession", "LaggedStart", "LaggedStartMap",
    "Wait", "EmptyAnimation",
    
    # Update
    "UpdateFromFunc", "UpdateFromAlphaFunc",
    
    # Changing
    "AnimatedBoundary", "TracedPath",
    
    # Numbers
    "ChangingDecimal", "ChangeDecimalToValue",
    
    # Specialized
    "Broadcast",
    
    # Rate functions
    "linear", "smooth", "rush_into", "rush_from", "slow_into",
    "double_smooth", "there_and_back", "there_and_back_with_pause",
    "running_start", "not_quite_there", "wiggle", "squish_rate_func",
    "lingering", "exponential_decay",
]