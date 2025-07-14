"""
Rate functions - re-export from GL.
"""

from manim.utils.rate_functions import *

# CE has some additional rate functions we can define
def ease_in_sine(t):
    """CE compatibility."""
    import numpy as np
    return 1 - np.cos((t * np.pi) / 2)

def ease_out_sine(t):
    """CE compatibility."""
    import numpy as np
    return np.sin((t * np.pi) / 2)

def ease_in_out_sine(t):
    """CE compatibility."""
    import numpy as np
    return -(np.cos(np.pi * t) - 1) / 2

def ease_in_quad(t):
    """CE compatibility."""
    return t * t

def ease_out_quad(t):
    """CE compatibility."""
    return 1 - (1 - t) * (1 - t)

def ease_in_out_quad(t):
    """CE compatibility."""
    return 2 * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 2) / 2

def ease_in_cubic(t):
    """CE compatibility."""
    return t * t * t

def ease_out_cubic(t):
    """CE compatibility."""
    return 1 - pow(1 - t, 3)

def ease_in_out_cubic(t):
    """CE compatibility."""
    return 4 * t * t * t if t < 0.5 else 1 - pow(-2 * t + 2, 3) / 2