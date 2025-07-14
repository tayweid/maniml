"""
Growing animations with CE compatibility.
"""

import manim
from manim.animation.growing import (
    GrowFromPoint as GLGrowFromPoint,
    GrowFromCenter as GLGrowFromCenter,
    GrowFromEdge as GLGrowFromEdge,
    GrowArrow as GLGrowArrow,
)
from manim.constants import *
import warnings


# Direct mappings
GrowFromPoint = GLGrowFromPoint
GrowFromCenter = GLGrowFromCenter
GrowFromEdge = GLGrowFromEdge
GrowArrow = GLGrowArrow


# SpinInFromNothing doesn't exist in GL, create it
class SpinInFromNothing(GLGrowFromCenter):
    """CE-compatible SpinInFromNothing - grow from center with rotation."""
    
    def __init__(self, mobject, angle=2*PI, **kwargs):
        # Store initial state
        self.angle = angle
        mobject.scale(0)
        mobject.rotate(-angle)
        super().__init__(mobject, **kwargs)
        
    def interpolate_mobject(self, alpha):
        super().interpolate_mobject(alpha)
        # Add rotation
        self.mobject.rotate(self.angle * alpha / self.run_time / self.rate_func(1))


# ShrinkToCenter doesn't exist in GL, create it
class ShrinkToCenter(GLGrowFromCenter):
    """CE-compatible ShrinkToCenter - reverse of GrowFromCenter."""
    
    def __init__(self, mobject, **kwargs):
        # Reverse the rate function
        original_rate_func = kwargs.get('rate_func', lambda t: t)
        kwargs['rate_func'] = lambda t: original_rate_func(1 - t)
        super().__init__(mobject, **kwargs)