"""
Fading animations with CE compatibility.
"""

import manim.renderer.opengl
from manim.renderer.opengl.animation.fading import (
    FadeIn as GLFadeIn,
    FadeOut as GLFadeOut,
    FadeInFromPoint as GLFadeInFromPoint,
    FadeOutToPoint as GLFadeOutToPoint,
    FadeTransform as GLFadeTransform,
    FadeTransformPieces as GLFadeTransformPieces,
)
from manim.renderer.opengl.constants import *
import warnings


class FadeIn(GLFadeIn):
    """CE-compatible FadeIn with shift parameter."""
    
    def __init__(self, mobject, shift=None, target_position=None, scale=1, **kwargs):
        # GL FadeIn already supports shift and scale!
        # Just need to handle target_position warning
        if target_position is not None:
            warnings.warn(
                "maniml: target_position not supported in FadeIn. Use shift.",
                UserWarning
            )
        
        # Convert shift to numpy array if needed
        if shift is not None:
            import numpy as np
            shift = np.array(shift)
        else:
            import numpy as np
            shift = np.array([0., 0., 0.])
            
        super().__init__(mobject, shift=shift, scale=scale, **kwargs)


class FadeOut(GLFadeOut):
    """CE-compatible FadeOut with shift parameter."""
    
    def __init__(self, mobject, shift=None, target_position=None, scale=1, **kwargs):
        # GL FadeOut already supports shift!
        if target_position is not None:
            warnings.warn(
                "maniml: target_position not supported in FadeOut. Use shift.",
                UserWarning
            )
        
        # Convert shift to numpy array if needed
        if shift is not None:
            import numpy as np
            shift = np.array(shift)
        else:
            import numpy as np
            shift = np.array([0., 0., 0.])
        
        # Note: GL FadeOut doesn't have scale parameter
        if scale != 1:
            warnings.warn(
                "maniml: scale parameter not supported in FadeOut.",
                UserWarning
            )
            
        super().__init__(mobject, shift=shift, **kwargs)


# Aliases for CE compatibility
class FadeInFrom(FadeIn):
    """CE compatibility - FadeInFrom is same as FadeIn with direction."""
    
    def __init__(self, mobject, direction=DOWN, **kwargs):
        super().__init__(mobject, shift=direction, **kwargs)


class FadeOutAndShift(FadeOut):
    """CE compatibility - FadeOutAndShift is same as FadeOut with direction."""
    
    def __init__(self, mobject, direction=DOWN, **kwargs):
        super().__init__(mobject, shift=direction, **kwargs)


# Direct mappings
FadeInFromPoint = GLFadeInFromPoint
FadeOutToPoint = GLFadeOutToPoint
FadeTransform = GLFadeTransform

# FadeInFromLarge doesn't exist in GL, create it
class FadeInFromLarge(GLFadeIn):
    """CE-compatible FadeInFromLarge - fade in with scaling."""
    
    def __init__(self, mobject, scale_factor=2, **kwargs):
        # Start larger
        mobject.scale(scale_factor)
        super().__init__(mobject, **kwargs)
        # Store target size
        self.target_scale = 1.0 / scale_factor


# Direct mapping
FadeTransformPieces = GLFadeTransformPieces