"""
ManimGL Core - Standalone copy of essential ManimGL components for maniml
"""

# Import all constants
from .constants import *

# Import essential classes
from .mobject.mobject import Mobject
from .animation.animation import Animation
from .scene.scene import Scene

# Import utilities
from . import utils

# Import event system
from .event_handler import EVENT_DISPATCHER