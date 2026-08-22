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
    FadeTransform, FadeTransformPieces, FlickerIn,
    VFadeIn, VFadeOut, VFadeInThenOut
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


# CE-compatible names that were implemented but unexported
# (surfaced by tests/ce_conformance)
from .animation.creation import (
    ShowPartial
)
from .camera.camera import (
    Camera, ThreeDCamera
)
from .mobject.coordinate_systems import (
    ComplexPlane, CoordinateSystem
)
from .mobject.frame import (
    FullScreenRectangle, ScreenRectangle
)
from .mobject.functions import (
    FunctionGraph, ImplicitFunction
)
from .mobject.matrix import (
    DecimalMatrix, IntegerMatrix, Matrix, MobjectMatrix
)
from .mobject.mobject import (
    Point, override_animate
)
from .mobject.mobject_update_utils import (
    always_redraw, always_rotate, always_shift, assert_is_mobject_method,
    cycle_animation, turn_animation_into_updater
)
from .mobject.number_line import (
    NumberLine, UnitInterval
)
from .mobject.numbers import (
    Integer
)
from .mobject.shape_matchers import (
    BackgroundRectangle, Cross, Underline
)
from .mobject.svg.brace import (
    Brace, BraceLabel, BraceText
)
from .mobject.svg.svg_mobject import (
    SVGMobject, VMobjectFromSVGPath
)
from .mobject.svg.text_mobject import (
    Code, register_font
)
from .mobject.table import (
    Table, MathTable
)
from .mobject.three_dimensions import (
    Dodecahedron
)
from .mobject.types.dot_cloud import (
    DotCloud, TrueDot
)
from .mobject.types.image_mobject import (
    ImageMobject
)
from .mobject.types.point_cloud_mobject import (
    PGroup, PMobject
)
from .mobject.types.vectorized_mobject import (
    CurvesAsSubmobjects, DashedVMobject, VectorizedPoint
)
from .mobject.value_tracker import (
    ComplexValueTracker, ValueTracker
)
from .rendering.shader_wrapper import (
    ShaderWrapper
)
from .rendering.window import (
    Window
)
from .scene.scene_file_writer import (
    SceneFileWriter
)
from .utils.bezier import (
    bezier, get_smooth_cubic_bezier_handle_points, integer_interpolate,
    interpolate, inverse_interpolate, is_closed, match_interpolate, mid,
    partial_bezier_points
)
from .utils.color import (
    average_color, color_gradient, color_to_int_rgb, color_to_int_rgba,
    color_to_rgb, color_to_rgba, hex_to_rgb, interpolate_color, invert_color,
    random_bright_color, random_color, rgb_to_color, rgb_to_hex,
    rgba_to_color
)
from .utils.dict_ops import (
    merge_dicts_recursively
)
from .utils.family_ops import (
    extract_mobject_family_members
)
from .utils.file_ops import (
    guarantee_existence
)
from .utils.images import (
    get_full_raster_image_path, invert_image
)
from .utils.iterables import (
    adjacent_n_tuples, adjacent_pairs, list_difference_update, list_update,
    listify, make_even, remove_list_redundancies
)
from .utils.paths import (
    clockwise_path, counterclockwise_path, path_along_arc, straight_path
)
from .utils.rate_functions import (
    exponential_decay, lingering, not_quite_there, running_start,
    squish_rate_func, wiggle
)
from .utils.simple_functions import (
    binary_search, choose, clip, sigmoid
)
from .utils.sounds import (
    get_full_sound_file_path
)
from .utils.space_ops import (
    R3_to_complex, angle_axis_from_quaternion, angle_between_vectors,
    angle_of_vector, center_of_mass, compass_directions,
    complex_func_to_R3_func, complex_to_R3, cross2d, earclip_triangulation,
    find_intersection, get_unit_normal, get_winding_number,
    line_intersection, midpoint, normalize, quaternion_conjugate,
    quaternion_from_angle_axis, quaternion_mult, rotate_vector,
    rotation_about_z, rotation_matrix, thick_diagonal, z_to_vector
)

from .animation.transform_matching_parts import (
    TransformMatchingParts, TransformMatchingShapes,
    TransformMatchingStrings, TransformMatchingTex,
)

# CE shims implemented for compatibility (no GL ancestor)
from .mobject.ce_shapes import (
    Angle, DoubleArrow, LabeledDot, Paragraph, RegularPolygram, RightAngle,
    Star, Title, VDict,
)
from .compatibility import Broadcast, Circumscribe, SpinInFromNothing, Wiggle
from .utils.rate_functions import smootherstep
from .utils.color import ManimColor

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

__all__ += [
    'ShowPartial', 'Camera', 'ThreeDCamera', 'ComplexPlane',
    'CoordinateSystem', 'FullScreenRectangle', 'ScreenRectangle',
    'FunctionGraph', 'ImplicitFunction', 'DecimalMatrix', 'IntegerMatrix',
    'Matrix', 'MobjectMatrix', 'Point', 'override_animate', 'always_redraw',
    'always_rotate', 'always_shift', 'assert_is_mobject_method',
    'cycle_animation', 'turn_animation_into_updater', 'NumberLine',
    'UnitInterval', 'Integer', 'BackgroundRectangle', 'Cross', 'Underline',
    'Brace', 'BraceLabel', 'BraceText', 'SVGMobject', 'VMobjectFromSVGPath',
    'Code', 'register_font', 'Table', 'MathTable', 'Dodecahedron', 'DotCloud', 'TrueDot',
    'ImageMobject', 'PGroup', 'PMobject', 'CurvesAsSubmobjects',
    'DashedVMobject', 'VectorizedPoint', 'ComplexValueTracker',
    'ValueTracker', 'ShaderWrapper', 'Window', 'SceneFileWriter', 'bezier',
    'get_smooth_cubic_bezier_handle_points', 'integer_interpolate',
    'interpolate', 'inverse_interpolate', 'is_closed', 'match_interpolate',
    'mid', 'partial_bezier_points', 'average_color', 'color_gradient',
    'color_to_int_rgb', 'color_to_int_rgba', 'color_to_rgb', 'color_to_rgba',
    'hex_to_rgb', 'interpolate_color', 'invert_color', 'random_bright_color',
    'random_color', 'rgb_to_color', 'rgb_to_hex', 'rgba_to_color',
    'merge_dicts_recursively', 'extract_mobject_family_members',
    'guarantee_existence', 'get_full_raster_image_path', 'invert_image',
    'adjacent_n_tuples', 'adjacent_pairs', 'list_difference_update',
    'list_update', 'listify', 'make_even', 'remove_list_redundancies',
    'clockwise_path', 'counterclockwise_path', 'path_along_arc',
    'straight_path', 'exponential_decay', 'lingering', 'not_quite_there',
    'running_start', 'squish_rate_func', 'wiggle', 'binary_search', 'choose',
    'clip', 'sigmoid', 'get_full_sound_file_path', 'R3_to_complex',
    'angle_axis_from_quaternion', 'angle_between_vectors', 'angle_of_vector',
    'center_of_mass', 'compass_directions', 'complex_func_to_R3_func',
    'complex_to_R3', 'cross2d', 'earclip_triangulation', 'find_intersection',
    'get_unit_normal', 'get_winding_number', 'line_intersection', 'midpoint',
    'normalize', 'quaternion_conjugate', 'quaternion_from_angle_axis',
    'quaternion_mult', 'rotate_vector', 'rotation_about_z',
    'rotation_matrix', 'thick_diagonal', 'z_to_vector'
]

__all__ += [
    'Angle', 'DoubleArrow', 'LabeledDot', 'Paragraph', 'RegularPolygram', 'RightAngle', 'Star', 'Title', 'VDict', 'Broadcast', 'Circumscribe', 'SpinInFromNothing', 'Wiggle', 'smootherstep', 'ManimColor',
]

__all__ += [
    'TransformMatchingParts', 'TransformMatchingShapes',
    'TransformMatchingStrings', 'TransformMatchingTex',
]
