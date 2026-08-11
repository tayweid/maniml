"""
Indication animations with CE compatibility.
"""

import manim.renderer.opengl
from manim.renderer.opengl.animation.indication import (
    FocusOn as GLFocusOn,
    Indicate as GLIndicate,
    Flash as GLFlash,
    CircleIndicate as GLCircleIndicate,
    ShowPassingFlashAround as GLShowPassingFlashAround,
    WiggleOutThenIn as GLWiggleOutThenIn,
    ShowCreationThenDestruction as GLShowCreationThenDestruction,
    ShowCreationThenFadeOut as GLShowCreationThenFadeOut,
)
from manim.renderer.opengl.constants import *
import warnings


# Direct mappings
FocusOn = GLFocusOn
Indicate = GLIndicate
Flash = GLFlash
CircleIndicate = GLCircleIndicate
ShowPassingFlashAround = GLShowPassingFlashAround
ShowCreationThenDestruction = GLShowCreationThenDestruction
ShowCreationThenFadeOut = GLShowCreationThenFadeOut

# Wiggle maps to WiggleOutThenIn in GL
Wiggle = GLWiggleOutThenIn


# Circumscribe doesn't exist in GL, create it
from manim.renderer.opengl.animation.creation import ShowCreation as GLShowCreation

class Circumscribe(GLShowCreation):
    """CE-compatible Circumscribe - draws shape around object."""
    
    def __init__(self, mobject, shape=None, color=YELLOW, buff=0.1, **kwargs):
        if shape is None:
            from manim.renderer.opengl.mobject.geometry import Rectangle
            shape = Rectangle(color=color)
            shape.surround(mobject, buff=buff)
        
        # Initialize with the shape
        super().__init__(shape, **kwargs)