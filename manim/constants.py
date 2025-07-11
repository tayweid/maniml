"""
Constants compatible with ManimCE but using ManimGL values.
"""

# Import all constants from ManimGL
from manim.renderer.opengl.constants import *

# Add any CE-specific constants that don't exist in GL
# Most constants are the same between CE and GL

# Ensure CE color names work
BLUE_A = BLUE_A if 'BLUE_A' in globals() else BLUE
BLUE_B = BLUE_B if 'BLUE_B' in globals() else DARK_BLUE  
BLUE_C = BLUE_C if 'BLUE_C' in globals() else DARK_BLUE
BLUE_D = BLUE_D if 'BLUE_D' in globals() else DARK_BLUE
BLUE_E = BLUE_E if 'BLUE_E' in globals() else DARK_BLUE

# Add more color variants as needed
RED_A = RED_A if 'RED_A' in globals() else RED
RED_B = RED_B if 'RED_B' in globals() else RED
RED_C = RED_C if 'RED_C' in globals() else RED
RED_D = RED_D if 'RED_D' in globals() else RED
RED_E = RED_E if 'RED_E' in globals() else RED

# Add aliases for American spelling
GRAY = GREY

# Add aliases for CE colors that don't exist in GL
LIGHT_GREY = GREY_A
LIGHT_GRAY = GREY_A
DARK_GREY = GREY_D
DARK_GRAY = GREY_D

# Add light/dark variants that CE expects but GL doesn't have
LIGHT_RED = RED
LIGHT_GREEN = GREEN  
LIGHT_BLUE = BLUE
DARK_RED = RED
DARK_GREEN = GREEN
DARK_BLUE = BLUE

# Typography constants
try:
    NORMAL
    ITALIC
    OBLIQUE
    BOLD
except NameError:
    # Define if not in GL
    NORMAL = "NORMAL"
    ITALIC = "ITALIC"
    OBLIQUE = "OBLIQUE"
    BOLD = "BOLD"

# Frame dimensions - use GL defaults if available
try:
    FRAME_HEIGHT
    FRAME_WIDTH
    FRAME_X_RADIUS
    FRAME_Y_RADIUS
except NameError:
    FRAME_HEIGHT = 8.0
    FRAME_WIDTH = 14.222222222222221
    FRAME_X_RADIUS = FRAME_WIDTH / 2
    FRAME_Y_RADIUS = FRAME_HEIGHT / 2