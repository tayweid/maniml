"""
Movement animations with CE compatibility.
"""

import manim
from manim.animation.animation import Animation as GLAnimation
from manim.animation.movement import (
    Homotopy as GLHomotopy,
    ComplexHomotopy as GLComplexHomotopy,
    PhaseFlow as GLPhaseFlow,
    MoveAlongPath as GLMoveAlongPath,
)
from manim.animation.rotation import (
    Rotate as GLRotate,
    Rotating as GLRotating,
)
from manim.animation.transform import ApplyMethod
from manim.constants import *
import warnings
import numpy as np

# Import OUT for default rotation axis
try:
    from manim.constants import OUT
except ImportError:
    OUT = np.array([0., 0., 1.])


# Direct mappings
Homotopy = GLHomotopy
ComplexHomotopy = GLComplexHomotopy
PhaseFlow = GLPhaseFlow
MoveAlongPath = GLMoveAlongPath
Rotate = GLRotate


class RotateInPlace(GLRotate):
    """CE compatibility - RotateInPlace is just Rotate about center."""
    
    def __init__(self, mobject, angle=2*3.14159, **kwargs):
        # Ensure rotation is about the mobject's center
        kwargs['about_point'] = mobject.get_center()
        super().__init__(mobject, angle=angle, **kwargs)


# In CE, Shift/MoveTo/Scale are animations, in GL they're mobject methods
class Shift(ApplyMethod):
    """CE-compatible Shift animation."""
    
    def __init__(self, mobject, direction, **kwargs):
        super().__init__(mobject.shift, direction, **kwargs)


class MoveTo(ApplyMethod):
    """CE-compatible MoveTo animation."""
    
    def __init__(self, mobject, point_or_mobject, aligned_edge=ORIGIN, **kwargs):
        if hasattr(point_or_mobject, 'get_center'):
            # It's a mobject
            target = point_or_mobject.get_center()
        else:
            # It's a point
            target = point_or_mobject
        
        # mobject.move_to accepts aligned_edge as parameter
        import numpy as np
        if not np.array_equal(aligned_edge, ORIGIN):
            super().__init__(mobject.move_to, target, aligned_edge, **kwargs)
        else:
            super().__init__(mobject.move_to, target, **kwargs)


class Scale(GLAnimation):
    """CE-compatible Scale animation."""
    
    def __init__(self, mobject, scale_factor, about_edge=None, about_point=None, **kwargs):
        self.scale_factor = scale_factor
        self.about_edge = about_edge
        self.about_point = about_point
        
        # Store original scale
        self.original_points = mobject.get_points().copy()
        self.original_center = mobject.get_center()
        
        super().__init__(mobject, **kwargs)
        
    def interpolate_mobject(self, alpha):
        # Reset to original state
        self.mobject.set_points(self.original_points)
        self.mobject.move_to(self.original_center)
        
        # Apply scale with interpolation
        scale = 1 + (self.scale_factor - 1) * alpha
        
        scale_kwargs = {}
        if self.about_edge is not None:
            scale_kwargs['about_edge'] = self.about_edge
        if self.about_point is not None:
            scale_kwargs['about_point'] = self.about_point
            
        self.mobject.scale(scale, **scale_kwargs)


class Rotating(GLRotating):
    """CE-compatible Rotating - continuous rotation."""
    
    def __init__(self, mobject, radians=2*PI, axis=None, **kwargs):
        # CE uses 'radians', GL uses 'angle'
        angle = kwargs.pop('radians', radians)
        # Default axis if not specified
        if axis is None:
            axis = OUT  # [0, 0, 1] - rotate around z-axis
        super().__init__(mobject, angle=angle, axis=axis, **kwargs)