"""
Creation animations with CE compatibility.
"""

import manim
from manim.animation.creation import (
    ShowCreation as GLShowCreation,
    Write as GLWrite,
    DrawBorderThenFill as GLDrawBorderThenFill,
    ShowIncreasingSubsets as GLShowIncreasingSubsets,
    ShowSubmobjectsOneByOne as GLShowSubmobjectsOneByOne
)

# ShowPassingFlash might be in a different module or not exist
try:
    from manim.animation.indication import ShowPassingFlash as GLShowPassingFlash
except ImportError:
    GLShowPassingFlash = None
from manim.animation.fading import FadeIn
import warnings


# CE name mappings
Create = GLShowCreation
ShowCreation = GLShowCreation


class Uncreate(GLShowCreation):
    """CE-compatible Uncreate - reverse of Create."""
    
    def __init__(self, mobject, reverse_rate_func=True, **kwargs):
        super().__init__(mobject, rate_func=lambda t: 1 - t, **kwargs)


# Direct mappings
Write = GLWrite
DrawBorderThenFill = GLDrawBorderThenFill

# ShowPassingFlash with fallback
if GLShowPassingFlash:
    ShowPassingFlash = GLShowPassingFlash
else:
    # Create a simple fallback
    class ShowPassingFlash(GLShowCreation):
        """Simplified ShowPassingFlash."""
        def __init__(self, mobject, **kwargs):
            warnings.warn("maniml: ShowPassingFlash simplified to ShowCreation", UserWarning)
            super().__init__(mobject, **kwargs)


class Unwrite(GLWrite):
    """CE-compatible Unwrite - reverse of Write."""
    
    def __init__(self, mobject, reverse=True, **kwargs):
        if hasattr(manimlib, 'Unwrite'):
            # If GL has Unwrite, use it
            super().__init__(mobject, **kwargs)
        else:
            # Otherwise reverse Write
            kwargs['rate_func'] = lambda t: 1 - t
            super().__init__(mobject, **kwargs)


class ShowPartial(GLShowCreation):
    """CE-compatible ShowPartial - show part of a mobject."""
    
    def __init__(self, mobject, partial_ratio=0.5, **kwargs):
        warnings.warn(
            "maniml: ShowPartial simplified. Shows first portion only.",
            UserWarning
        )
        # Simplified version
        kwargs['rate_func'] = lambda t: t * partial_ratio
        super().__init__(mobject, **kwargs)


class AddTextLetterByLetter(GLShowIncreasingSubsets):
    """CE-compatible AddTextLetterByLetter."""
    
    def __init__(self, text, time_per_char=0.1, **kwargs):
        if 'run_time' not in kwargs:
            # Calculate run time based on text length
            if hasattr(text, 'text'):
                kwargs['run_time'] = len(text.text) * time_per_char
            elif hasattr(text, '__len__'):
                kwargs['run_time'] = len(text) * time_per_char
                
        super().__init__(text, **kwargs)


class AddTextWordByWord(GLShowSubmobjectsOneByOne):
    """CE-compatible AddTextWordByWord - simplified version."""
    
    def __init__(self, text_mobject, time_per_word=0.5, **kwargs):
        warnings.warn(
            "maniml: AddTextWordByWord shows submobjects, not actual words.",
            UserWarning
        )
        if 'run_time' not in kwargs and hasattr(text_mobject, 'submobjects'):
            kwargs['run_time'] = len(text_mobject.submobjects) * time_per_word
            
        super().__init__(text_mobject, **kwargs)