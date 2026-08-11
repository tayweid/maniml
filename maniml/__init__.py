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

# CE's MovingCameraScene is redundant on the GL backend: every scene's
# camera frame is a mobject you can animate. Alias for compatibility.
MovingCameraScene = Scene

# Import basic mobjects directly
from .mobject.mobject import Mobject, Group
from .mobject.geometry import (
    TipableVMobject,
    Arc, ArcBetweenPoints, CurvedArrow, CurvedDoubleArrow,
    Circle, Dot, SmallDot, Ellipse,
    AnnularSector, Sector, Annulus,
    Line, DashedLine, TangentLine, Elbow, StrokeArrow, Arrow, Vector,
    CubicBezier,
    Polygon, Polyline, RegularPolygon, Triangle, ArrowTip,
    Rectangle, Square, Squircle, RoundedRectangle
)
from .mobject.types.vectorized_mobject import VMobject, VGroup
from .mobject.svg.tex_mobject import Tex, MathTex, TexText
from .mobject.svg.text_mobject import Text, MarkupText
from .mobject.numbers import DecimalNumber

# Import 3D-related classes
from .mobject.types.surface import Surface, SGroup
from .mobject.types.vmobject_3d import VMobject3D, Circle3D, Text as Text3D
from .mobject.three_dimensions import (
    Sphere, Cube, Torus, Cylinder, Cone,
    Line3D, Disk3D, Square3D, Rectangle3D, Prism, Squircle3D
)
from .mobject.coordinate_systems import Axes, ThreeDAxes, NumberPlane
from .mobject.shape_matchers import SurroundingRectangle
from .mobject.mobject_update_utils import always, f_always

# Import core animations directly
from .animation.animation import Animation
from .animation.creation import (
    ShowCreation, Uncreate, DrawBorderThenFill, Write, Unwrite,
    ShowIncreasingSubsets, ShowSubmobjectsOneByOne, AddTextWordByWord,
    ShowPassingFlash as ShowPassingFlashCreation
)
from .animation.transform import (
    Transform, ReplacementTransform, TransformFromCopy,
    MoveToTarget, ApplyMethod, ApplyPointwiseFunction, ApplyPointwiseFunctionToCenter,
    ApplyFunction, ApplyMatrix, ApplyComplexFunction,
    FadeToColor, ScaleInPlace, ShrinkToCenter, Restore, Swap, CyclicReplace
)
from .animation.fading import (
    Fade, FadeIn, FadeOut, FadeInFromPoint, FadeOutToPoint,
    FadeTransform, FadeTransformPieces, VFadeIn, VFadeOut, VFadeInThenOut
)
from .animation.composition import AnimationGroup, Succession, LaggedStart, LaggedStartMap
from .animation.growing import GrowFromPoint, GrowFromCenter, GrowFromEdge, GrowArrow
from .animation.movement import Homotopy, SmoothedVectorizedHomotopy, ComplexHomotopy, PhaseFlow, MoveAlongPath
from .animation.indication import (
    FocusOn, Indicate, Flash, CircleIndicate, ShowPassingFlash,
    VShowPassingFlash, FlashAround, FlashUnder,
    ShowCreationThenDestruction, ShowCreationThenFadeOut,
    AnimationOnSurroundingRectangle, ShowPassingFlashAround,
    ShowCreationThenDestructionAround, ShowCreationThenFadeAround,
    ApplyWave, WiggleOutThenIn, TurnInsideOut, FlashyFadeIn
)
from .animation.rotation import Rotating, Rotate
from .animation.update import UpdateFromFunc, UpdateFromAlphaFunc, MaintainPositionRelativeTo

# Import CE compatibility layer
from .compatibility import (
    # Creation animations
    Create, Uncreate, Write, Unwrite,
    # Movement animations
    Shift, MoveTo, Scale, Rotate,
    # Special animations
    Wait,
)

# Import rate functions
from .utils.rate_functions import (
    linear, smooth, there_and_back, there_and_back_with_pause,
    rush_into, rush_from, slow_into, double_smooth
)

# CE-compatible config object (module-level assignments like
# config.background_color take effect; unsupported settings warn).
# Bound LAST so no later submodule import can rebind manim.config back
# to the config module; `from maniml.config import manim_config` still
# resolves via sys.modules and keeps working.
from .ce_config import config

# For convenience, make everything available at package level
__all__ = [
    # Configuration
    'config',
    # Scenes
    'Scene', 'ThreeDScene', 'MovingCameraScene',
    # Basic Mobjects
    'Mobject', 'Group', 'VMobject', 'VGroup',
    # Shapes
    'TipableVMobject',
    'Arc', 'ArcBetweenPoints', 'CurvedArrow', 'CurvedDoubleArrow',
    'Circle', 'Dot', 'SmallDot', 'Ellipse',
    'AnnularSector', 'Sector', 'Annulus',
    'Line', 'DashedLine', 'TangentLine', 'Elbow', 'StrokeArrow', 'Arrow', 'Vector',
    'CubicBezier',
    'Polygon', 'Polyline', 'RegularPolygon', 'Triangle', 'ArrowTip',
    'Rectangle', 'Square', 'Squircle', 'RoundedRectangle',
    # 3D Shapes
    'Surface', 'SGroup', 'Sphere', 'Cube', 'Torus', 'Cylinder', 'Cone',
    'Line3D', 'Disk3D', 'Square3D', 'Rectangle3D', 'Prism', 'Squircle3D',
    'VMobject3D', 'Circle3D', 'Text3D',
    # Coordinate Systems
    'Axes', 'ThreeDAxes', 'NumberPlane',
    # Helpers
    'SurroundingRectangle', 'always', 'f_always',
    # Text
    'Text', 'MarkupText', 'Tex', 'MathTex', 'DecimalNumber',
    # Creation Animations
    'Animation', 'ShowCreation', 'Uncreate', 'DrawBorderThenFill', 'Write', 'Unwrite',
    'ShowIncreasingSubsets', 'ShowSubmobjectsOneByOne', 'AddTextWordByWord',
    # Transform Animations
    'Transform', 'ReplacementTransform', 'TransformFromCopy',
    'MoveToTarget', 'ApplyMethod', 'ApplyPointwiseFunction', 'ApplyPointwiseFunctionToCenter',
    'ApplyFunction', 'ApplyMatrix', 'ApplyComplexFunction',
    'FadeToColor', 'ScaleInPlace', 'ShrinkToCenter', 'Restore', 'Swap', 'CyclicReplace',
    # Fade Animations
    'Fade', 'FadeIn', 'FadeOut', 'FadeInFromPoint', 'FadeOutToPoint',
    'FadeTransform', 'FadeTransformPieces', 'VFadeIn', 'VFadeOut', 'VFadeInThenOut',
    # Composition
    'AnimationGroup', 'Succession', 'LaggedStart', 'LaggedStartMap',
    # Growing Animations
    'GrowFromPoint', 'GrowFromCenter', 'GrowFromEdge', 'GrowArrow',
    # Movement Animations
    'Homotopy', 'SmoothedVectorizedHomotopy', 'ComplexHomotopy', 'PhaseFlow', 'MoveAlongPath',
    # Indication Animations
    'FocusOn', 'Indicate', 'Flash', 'CircleIndicate', 'ShowPassingFlash',
    'VShowPassingFlash', 'FlashAround', 'FlashUnder',
    'ShowCreationThenDestruction', 'ShowCreationThenFadeOut',
    'AnimationOnSurroundingRectangle', 'ShowPassingFlashAround',
    'ShowCreationThenDestructionAround', 'ShowCreationThenFadeAround',
    'ApplyWave', 'WiggleOutThenIn', 'TurnInsideOut', 'FlashyFadeIn',
    # Rotation Animations
    'Rotating', 'Rotate',
    # Update Animations
    'UpdateFromFunc', 'UpdateFromAlphaFunc', 'MaintainPositionRelativeTo',
    # CE-Compatible Animations
    'Create', 'Shift', 'MoveTo', 'Scale', 'Wait',
    # Rate functions
    'linear', 'smooth', 'there_and_back', 'there_and_back_with_pause',
    'rush_into', 'rush_from', 'slow_into', 'double_smooth',
]

# Also star-export every ALL_CAPS constant (colors, directions, frame
# dimensions, ...) so plain `from maniml import *` scene files see them
from . import constants as _constants
__all__ += [
    _name for _name in dir(_constants)
    if _name.isupper() and _name not in __all__
]