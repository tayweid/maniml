"""
Scene with CE compatibility using GL backend.
"""

import manim.renderer.opengl
from manim.renderer.opengl.scene.scene import Scene as GLScene
from manim.renderer.opengl.scene.scene import ThreeDScene as GLThreeDScene
from manim.renderer.opengl.scene.scene import SceneState, EndScene
import warnings
import time
import sys
import inspect
import pyperclip
from pyglet.window import key as PygletWindowKeys
import difflib
import itertools as it
import numpy as np

# Import event system - use ManimGL's since that's what the mobjects use
from manim.renderer.opengl.event_handler import EVENT_DISPATCHER
from manim.renderer.opengl.event_handler.event_listner import EventListener
from manim.renderer.opengl.event_handler.event_type import EventType
from manim.scene.scene_utils import deepcopy_namespace

# Import mobject types for selection
from manim.renderer.opengl.mobject.mobject import Group
from manim.renderer.opengl.mobject.mobject import Mobject
from manim.renderer.opengl.mobject.mobject import Point
from manim.renderer.opengl.mobject.types.vectorized_mobject import VGroup
from manim.renderer.opengl.mobject.types.vectorized_mobject import VMobject
from manim.renderer.opengl.mobject.types.vectorized_mobject import VHighlight
from manim.renderer.opengl.mobject.types.dot_cloud import DotCloud
from manim.renderer.opengl.mobject.geometry import Rectangle
from manim.renderer.opengl.mobject.geometry import Square
from manim.renderer.opengl.mobject.numbers import DecimalNumber
from manim.renderer.opengl.mobject.svg.tex_mobject import Tex
from manim.renderer.opengl.mobject.svg.text_mobject import Text

# Import animation for pasting
from manim.renderer.opengl.animation.fading import FadeIn

# Import constants
from manim.renderer.opengl.constants import DL, DOWN, DR, LEFT, ORIGIN, RIGHT, UL, UP, UR
from manim.renderer.opengl.constants import FRAME_WIDTH, FRAME_HEIGHT, SMALL_BUFF
from manim.renderer.opengl.constants import PI, DEG
from manim.renderer.opengl.constants import MANIM_COLORS, WHITE, GREY_A, GREY_C

# Import utilities
from manim.renderer.opengl.utils.family_ops import extract_mobject_family_members
from manim.renderer.opengl.utils.space_ops import get_norm
from manim.renderer.opengl.utils.tex_file_writing import LatexError

try:
    from manim.scene.file_watcher import SimpleFileWatcher, AnimationTracker
except ImportError:
    SimpleFileWatcher = None
    AnimationTracker = None

# Dummy AutoReloadMixin since we're not using the complex version
class AutoReloadMixin:
    def setup_auto_reload(self):
        pass

# Fix spinning cursor issue - disable debug GL in pyglet
try:
    import pyglet
    pyglet.options['debug_gl'] = False
except ImportError:
    pass

# Key bindings for interactive mode (from ManimGL)
# These would normally come from manim_config but we'll use defaults
SELECT_KEY = 's'
UNSELECT_KEY = 'u'
GRAB_KEY = 'g'
X_GRAB_KEY = 'h'
Y_GRAB_KEY = 'v'
GRAB_KEYS = [GRAB_KEY, X_GRAB_KEY, Y_GRAB_KEY]
RESIZE_KEY = 't'
COLOR_KEY = 'c'
INFORMATION_KEY = 'i'
CURSOR_KEY = ';'

# For keyboard interactions
ARROW_SYMBOLS = [
    PygletWindowKeys.LEFT,
    PygletWindowKeys.UP,
    PygletWindowKeys.RIGHT,
    PygletWindowKeys.DOWN,
]

ALL_MODIFIERS = PygletWindowKeys.MOD_CTRL | PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_SHIFT


class Scene(GLScene):
    """
    CE-compatible Scene using GL backend with InteractiveScene functionality.
    
    Provides CE's API while using GL's fast rendering.
    Includes ManimGL's mouse interaction features.
    """
    
    # Interaction settings
    scroll_sensitivity = 20  # From ManimGL's default
    drag_to_pan = False  # Disable by default, use Cmd/Ctrl + drag instead
    
    # InteractiveScene configuration
    corner_dot_config = dict(
        color=WHITE,
        radius=0.05,
        glow_factor=2.0,
    )
    selection_rectangle_stroke_color = WHITE
    selection_rectangle_stroke_width = 1.0
    palette_colors = MANIM_COLORS
    selection_nudge_size = 0.05
    cursor_location_config = dict(
        font_size=24,
        fill_color=GREY_C,
        num_decimal_places=3,
    )
    time_label_config = dict(
        font_size=24,
        fill_color=GREY_C,
        num_decimal_places=1,
    )
    crosshair_width = 0.2
    crosshair_style = dict(
        stroke_color=GREY_A,
        stroke_width=[3, 0, 3],
    )
    
    def __init__(self, **kwargs):
        # CE compatibility attributes
        self.renderer = self  # CE code often references scene.renderer
        self.animations = []  # Track animations for CE compatibility
        
        # Checkpoint management
        self.checkpoint_states = {}  # key -> SceneState
        self.animation_count = 0
        self.animation_checkpoints = []  # List of dicts with {index, line_number, state, namespace}
        self.current_animation_index = -1
        
        # Auto-reload setup
        self.file_watcher = None
        self.auto_reload_enabled = kwargs.pop('auto_reload', True)  # Enable by default
        self._scene_filepath = None
        self._original_content = None
        self._file_changed_flag = False  # Thread-safe flag
        
        # Animation control for playing only first animation
        self._animations_to_play = 1  # Default to play only first animation
        self._animations_played = 0   # Counter for animations played
        
        # InteractiveScene attributes
        self.selection = Group()
        self.selection_highlight = None  # Will be initialized in setup()
        self.selection_rectangle = None  # Will be initialized in setup()
        self.crosshair = None  # Will be initialized in setup()
        self.information_label = None  # Will be initialized in setup()
        self.color_palette = None  # Will be initialized in setup()
        self.unselectables = []  # Will be populated in setup()
        self.select_top_level_mobs = True
        self.selection_search_set = []
        
        self.is_selecting = False
        self.is_grabbing = False
        
        # Mouse interaction state
        self.mouse_to_selection = None
        self.scale_about_point = None
        self.scale_ref_vect = None
        self.scale_ref_width = None
        self.scale_ref_height = None
        
        super().__init__(**kwargs)
        
        # Enable auto-reload if requested
        if self.auto_reload_enabled:
            self.setup_auto_reload()
            
        # Setup interactive elements
        self.setup_interactive_elements()
    
    def initialize_checkpoint_zero(self):
        """Create the initial checkpoint with baseline Python namespace."""
        import sys
        
        # Create baseline namespace
        baseline_namespace = {}
        
        # Add built-ins
        baseline_namespace.update(__builtins__)
        
        # Add manim imports
        exec("from manim import *", baseline_namespace)
        
        # Add self reference
        baseline_namespace['self'] = self
        
        # Add empty state to namespace
        baseline_namespace['__checkpoint_state__'] = self.get_state()
        
        # Deep copy (though not much to copy yet)
        checkpoint_namespace = deepcopy_namespace(baseline_namespace)
        checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')
        
        # Create checkpoint 0
        checkpoint_zero = {
            'index': 0,
            'line_number': 0,
            'state': checkpoint_state,
            'namespace': checkpoint_namespace
        }
        
        self.animation_checkpoints.append(checkpoint_zero)
        self.current_animation_index = 0
    
    def setup_interactive_elements(self):
        """Initialize interactive elements like selection highlight, crosshair, etc."""
        self.selection_highlight = self.get_selection_highlight()
        self.selection_rectangle = self.get_selection_rectangle()
        self.crosshair = self.get_crosshair()
        self.information_label = self.get_information_label()
        self.color_palette = self.get_color_palette()
        self.unselectables = [
            self.selection,
            self.selection_highlight,
            self.selection_rectangle,
            self.crosshair,
            self.information_label,
            self.camera.frame
        ]
        self.regenerate_selection_search_set()
        self.add(self.selection_highlight)
    
    def setup(self):
        """Called before construct - initialize checkpoint 0."""
        super().setup()
        
        # Get the scene file path from the call stack
        frame = inspect.currentframe()
        while frame:
            filepath = frame.f_globals.get('__file__')
            if filepath and not filepath.endswith('scene.py'):
                self._scene_filepath = filepath
                break
            frame = frame.f_back
        
        # Setup file watching if enabled and we have a file path
        if SimpleFileWatcher and self.auto_reload_enabled and self._scene_filepath:
            try:
                # Store the original file content
                with open(self._scene_filepath, 'r') as f:
                    self._original_content = f.readlines()
                
                # Create file watcher that sets a flag
                self._file_watcher = SimpleFileWatcher(
                    self._scene_filepath,
                    lambda: setattr(self, '_file_changed_flag', True)
                )
                self._file_watcher.start()
                print(f"[AUTO-RELOAD] Watching for changes in: {self._scene_filepath}")
            except Exception as e:
                print(f"[AUTO-RELOAD] Failed to setup file watcher: {e}")
        
        # Initialize checkpoint 0 - baseline state
        self.initialize_checkpoint_zero()
        
        # Reset animation counter to ensure we start fresh
        self._animations_played = 0
    
    def update_frame(self, dt=0, force_draw=False):
        """Override update_frame to check for file changes."""
        # Check file change flag
        if hasattr(self, '_file_changed_flag') and self._file_changed_flag:
            self._file_changed_flag = False  # Reset flag
            self._handle_file_change()
        
        # Call parent update_frame
        return super().update_frame(dt, force_draw)
    
    def add(self, *mobjects):
        """CE-style add method that returns self for chaining."""
        super().add(*mobjects)
        return self
    
    def remove(self, *mobjects):
        """CE-style remove method that returns self for chaining."""
        super().remove(*mobjects)
        return self
    
    def play_old(self, *animations, **kwargs):
        """
        DEPRECATED - This method is overridden later in the file.
        CE-style play with multiple animations and lag_ratio support.
        """
        # Check if we should skip animations (for playing only first animation)
        if hasattr(self, '_animations_to_play') and hasattr(self, '_animations_played'):
            # Count this animation BEFORE checking if we should skip
            self._animations_played += 1
            
            if self._animations_played > self._animations_to_play:
                # Skip but still need to add mobjects to scene
                from manim.renderer.opengl.animation.animation import prepare_animation
                from manim.renderer.opengl.mobject.mobject import _AnimationBuilder
                
                # Convert any animation builders to actual animations
                prepared_animations = []
                for proto in animations:
                    if isinstance(proto, _AnimationBuilder):
                        proto = proto.build()
                    anim = prepare_animation(proto)
                    prepared_animations.append(anim)
                
                # Add mobjects to scene (similar to how GL scene does it)
                all_mobjects = set(self.get_mobject_family_members())
                for anim in prepared_animations:
                    anim.begin()
                    if anim.mobject not in all_mobjects:
                        self.add(anim.mobject)
                        all_mobjects = all_mobjects.union(anim.mobject.get_family())
                
                return animations[0] if animations else None
        
        # Extract CE-specific kwargs
        run_time = kwargs.pop('run_time', None)
        lag_ratio = kwargs.pop('lag_ratio', 0)
        rate_func = kwargs.pop('rate_func', None)
        
        # Handle run_time
        if run_time is not None:
            for anim in animations:
                if hasattr(anim, 'run_time'):
                    anim.run_time = run_time
        
        # Handle rate_func
        if rate_func is not None:
            for anim in animations:
                if hasattr(anim, 'rate_func'):
                    anim.rate_func = rate_func
        
        # Handle multiple animations
        if len(animations) == 1:
            super().play(animations[0], **kwargs)
        else:
            # Multiple animations
            if lag_ratio > 0:
                from manim.renderer.opengl.animation.composition import LaggedStart
                super().play(LaggedStart(*animations, lag_ratio=lag_ratio), **kwargs)
            else:
                from manim.renderer.opengl.animation.composition import AnimationGroup
                super().play(AnimationGroup(*animations), **kwargs)
        
        return self
    
    def wait(self, duration=1.0, stop_condition=None, frozen_frame=None):
        """CE-style wait with proper event handling."""
        # Check if we should skip animations (for playing only first animation)
        if hasattr(self, '_animations_to_play') and hasattr(self, '_animations_played'):
            # Count this animation BEFORE checking if we should skip
            self._animations_played += 1
            
            if self._animations_played > self._animations_to_play:
                # Skip the wait
                return self
        
        super().wait(duration=duration, stop_condition=stop_condition)
        return self
    
    
    def next_section(self, name="", type="default", skip_animations=False):
        """CE compatibility - sections not supported in GL."""
        warnings.warn(
            "maniml: Sections not supported. Use comments for organization.",
            UserWarning
        )
        return self
    
    def add_subcaption(self, text, duration=None, offset=0):
        """CE compatibility - subcaptions not supported in GL."""
        warnings.warn(
            "maniml: Subcaptions not supported. Use Text objects instead.",
            UserWarning
        )
        return self
    
    def bring_to_front(self, *mobjects):
        """CE compatibility method."""
        for mob in mobjects:
            self.remove(mob)
            self.add(mob)
        return self
    
    def bring_to_back(self, *mobjects):
        """CE compatibility method."""
        for mob in mobjects:
            self.remove(mob)
            # Add at the beginning
            self.mobjects.insert(0, mob)
        return self
    
    def clear(self):
        """CE compatibility - clear the scene."""
        self.remove(*self.mobjects)
        return self
    
    def get_top(self):
        """CE compatibility - get top of frame."""
        return self.camera.frame_shape[1] / 2
    
    def get_bottom(self):
        """CE compatibility - get bottom of frame."""
        return -self.camera.frame_shape[1] / 2
    
    def get_left(self):
        """CE compatibility - get left edge of frame."""
        return -self.camera.frame_shape[0] / 2
    
    def get_right(self):
        """CE compatibility - get right edge of frame."""
        return self.camera.frame_shape[0] / 2
    
    def interactive_embed(self, terminal=True, **kwargs):
        """
        CE compatibility - optionally open an interactive IPython terminal.
        
        Similar to checkpoint_paste in ManimGL and interactive mode in ManimCE.
        Provides access to self and all scene objects in the terminal.
        
        Args:
            terminal: If True (default), launch IPython terminal. If False, just show window.
        """
        # Setup file watching if available
        if SimpleFileWatcher and self.auto_reload_enabled:
            # Get the scene file path
            frame = inspect.currentframe()
            while frame:
                filepath = frame.f_globals.get('__file__')
                if filepath and not filepath.endswith('scene.py'):
                    # Store the filepath for later use
                    self._scene_filepath = filepath
                    
                    # Store the original file content
                    with open(filepath, 'r') as f:
                        self._original_content = f.readlines()
                    
                    # Store the construct method's namespace for later use
                    self._construct_namespace = frame.f_locals.copy()
                    
                    # Create file watcher that sets a flag
                    self._file_watcher = SimpleFileWatcher(
                        filepath,
                        lambda: setattr(self, '_file_changed_flag', True)
                    )
                    self._file_watcher.start()
                    print(f"Auto-reload enabled for: {filepath}")
                    break
                frame = frame.f_back
        
        # If terminal=False, just print instructions and return
        if not terminal:
            print("\nWindow controls:")
            print("  ↑/↓     : Jump between animations")
            print("  ←/→     : Navigate animations (→ plays forward)")
            print("  ESC     : Quit")
            print("\nAuto-reload is enabled - file changes will reload automatically.")
            return
        
        # Skip IPython completely - just print instructions
        print("\nWindow controls:")
        print("  ↑/↓     : Jump between animations")
        print("  ←/→     : Navigate animations (→ plays forward)")
        print("  ESC     : Quit")
        if self._file_watcher:
            print("\nAuto-reload is enabled - file changes will reload automatically.")
    
    # Let ManimGL handle resize naturally - it prevents squishing automatically
    # by using OpenGL viewport management
    
    def setup_interactive(self):
        """Override to suppress the tips message."""
        # Skip the log.info message from parent
        self.skip_animations = False
        while not self.is_window_closing():
            self.update_frame(1 / self.camera.fps)
    
    def on_key_press(self, symbol, modifiers):
        """Handle key press events for navigation and control."""
        # Call parent implementation first
        super().on_key_press(symbol, modifiers)
        
        # Handle ESC key to quit (always process, regardless of other flags)
        if symbol == PygletWindowKeys.ESCAPE:
            self.quit_interaction = True
            
            # Clear any processing flags
            if hasattr(self, '_processing_key'):
                self._processing_key = False
            
            # Stop file watcher
            if hasattr(self, '_file_watcher') and self._file_watcher:
                self._file_watcher.stop()
            
            # Close the window gracefully
            if hasattr(self, 'window') and self.window:
                self.window.close()
            
            # Set a flag to exit the main loop
            self.done = True
        
        # Handle UP arrow - jump to previous animation
        elif symbol == PygletWindowKeys.UP:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
            
            # If animation is playing, skip to end first
            if hasattr(self, 'playing') and self.playing:
                self.skip_animations = True
                return  # Let animation finish, then user can press UP again
                
            if self.current_animation_index > 0:
                self.current_animation_index -= 1
                checkpoint = self.animation_checkpoints[self.current_animation_index]
                print(f"↑ Jump to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                self.restore_state(checkpoint['state'])
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at first animation")
        
        # Handle DOWN arrow - jump to next animation
        elif symbol == PygletWindowKeys.DOWN:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
            
            # If animation is playing, skip to end first
            if hasattr(self, 'playing') and self.playing:
                self.skip_animations = True
                return  # Let animation finish, then user can press DOWN again
                
            if self.current_animation_index < len(self.animation_checkpoints) - 1:
                self.current_animation_index += 1
                checkpoint = self.animation_checkpoints[self.current_animation_index]
                print(f"↓ Jump to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                self.restore_state(checkpoint['state'])
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at last animation")
        
        # Handle LEFT arrow - play animation in reverse
        elif symbol == PygletWindowKeys.LEFT:
            # Prevent handling if we're already processing a key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
                
            if self.current_animation_index > 0:
                # Set flag to prevent re-entry
                self._processing_key = True
                try:
                    # Get the current checkpoint and the previous one
                    current_checkpoint = self.animation_checkpoints[self.current_animation_index]
                    prev_checkpoint = self.animation_checkpoints[self.current_animation_index - 1]
                    
                    # We need to reverse the animation from current to previous state
                    # This is tricky - for now just jump back
                    self.current_animation_index -= 1
                    print(f"← Reverse to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                    self.restore_state(prev_checkpoint['state'])
                    self.update_frame(dt=0, force_draw=True)
                    # TODO: Implement actual reverse animation playback
                finally:
                    # Clear the flag
                    self._processing_key = False
            else:
                print("Already at first animation")
        
        # Handle RIGHT arrow - play next animation forward
        elif symbol == PygletWindowKeys.RIGHT:
            # Prevent handling if we're already processing a key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
            
            # Set flag to prevent re-entry
            self._processing_key = True
            try:
                self.run_next_animation()
            finally:
                self._processing_key = False
        
        # InteractiveScene key handlers
        char = chr(symbol) if symbol < 256 else ''
        
        # Handle event dispatcher first
        event_data = {"symbol": symbol, "modifiers": modifiers}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.KeyPressEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return
        
        # Selection controls
        if char == SELECT_KEY and (modifiers & ALL_MODIFIERS) == 0:
            self.enable_selection()
        elif char == UNSELECT_KEY:
            self.clear_selection()
        elif char in GRAB_KEYS and (modifiers & ALL_MODIFIERS) == 0:
            self.prepare_grab()
        elif char == RESIZE_KEY and (modifiers & PygletWindowKeys.MOD_SHIFT):
            self.prepare_resizing(about_corner=((modifiers & PygletWindowKeys.MOD_SHIFT) > 0))
        elif symbol == PygletWindowKeys.LSHIFT:
            if self.window.is_key_pressed(ord("t")):
                self.prepare_resizing(about_corner=True)
        elif char == COLOR_KEY and (modifiers & ALL_MODIFIERS) == 0:
            self.toggle_color_palette()
        elif char == INFORMATION_KEY and (modifiers & ALL_MODIFIERS) == 0:
            self.display_information()
        elif char == "c" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
            self.copy_selection()
        elif char == "v" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
            self.paste_selection()
        elif char == "x" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
            self.copy_selection()
            self.delete_selection()
        elif symbol == PygletWindowKeys.BACKSPACE:
            self.delete_selection()
        elif char == "a" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
            self.clear_selection()
            self.add_to_selection(*self.mobjects)
        elif char == "g" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
            self.group_selection()
        elif char == "g" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL | PygletWindowKeys.MOD_SHIFT)):
            self.ungroup_selection()
        elif char == "t" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
            self.toggle_selection_mode()
        elif char == "d" and (modifiers & PygletWindowKeys.MOD_SHIFT):
            self.copy_frame_positioning()
        elif char == "c" and (modifiers & PygletWindowKeys.MOD_SHIFT):
            self.copy_cursor_position()
        elif symbol in ARROW_SYMBOLS and self.selection:
            # Only nudge if we have a selection and not using arrows for navigation
            self.nudge_selection(
                vect=[LEFT, UP, RIGHT, DOWN][ARROW_SYMBOLS.index(symbol)],
                large=(modifiers & PygletWindowKeys.MOD_SHIFT),
            )
        
        # Adding crosshair
        if char == CURSOR_KEY:
            if self.crosshair in self.mobjects:
                self.remove(self.crosshair)
            else:
                self.add(self.crosshair)
        if char == SELECT_KEY:
            self.add(self.crosshair)

        # Conditions for saving state
        if char in [GRAB_KEY, X_GRAB_KEY, Y_GRAB_KEY, RESIZE_KEY]:
            self.save_state()
    
    def on_key_release(self, symbol, modifiers):
        """Handle key release events."""
        super().on_key_release(symbol, modifiers)
        
        # Handle event dispatcher
        event_data = {"symbol": symbol, "modifiers": modifiers}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.KeyReleaseEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return
            
        char = chr(symbol) if symbol < 256 else ''
        if char == SELECT_KEY:
            self.gather_new_selection()
        if char in GRAB_KEYS:
            self.is_grabbing = False
        elif char == INFORMATION_KEY:
            self.display_information(False)
        elif symbol == PygletWindowKeys.LSHIFT and self.window.is_key_pressed(ord(RESIZE_KEY)):
            self.prepare_resizing(about_corner=False)
    
    def on_mouse_motion(self, point, d_point):
        """Handle mouse motion events."""
        super().on_mouse_motion(point, d_point)
        
        # Only move crosshair if it exists and is in the scene
        if hasattr(self, 'crosshair') and self.crosshair and self.crosshair in self.mobjects:
            self.crosshair.move_to(self.frame.to_fixed_frame_point(point))
        
        event_data = {"point": point, "d_point": d_point}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseMotionEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return
            
        if self.is_grabbing:
            self.handle_grabbing(point)
        elif self.window.is_key_pressed(ord(RESIZE_KEY)):
            self.handle_resizing(point)
        elif self.window.is_key_pressed(ord(SELECT_KEY)) and self.window.is_key_pressed(PygletWindowKeys.LSHIFT):
            self.handle_sweeping_selection(point)
    
    def on_mouse_drag(self, point, d_point, buttons, modifiers):
        """Handle mouse drag events with proper event order."""
        # IMPORTANT: Update mouse position first
        self.mouse_drag_point.move_to(point)
        
        # Then dispatch to event handlers BEFORE any panning
        event_data = {"point": point, "d_point": d_point, "buttons": buttons, "modifiers": modifiers}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseDragEvent, **event_data)
        
        # If an object handled the drag, don't pan
        if propagate_event is False:
            return
        
        # Only pan if Cmd/Ctrl is held (and no object handled the event)
        if modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL):
            # Pan the scene
            self.frame.shift(-d_point)
        
        # Update crosshair position if it exists
        if hasattr(self, 'crosshair') and self.crosshair and self.crosshair in self.mobjects:
            self.crosshair.move_to(self.frame.to_fixed_frame_point(point))
    
    def on_mouse_press(self, point, button, mods):
        """Handle mouse press events."""
        self.mouse_drag_point.move_to(point)
        event_data = {"point": point, "button": button, "mods": mods}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MousePressEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return
    
    def on_mouse_release(self, point, button, mods):
        """Handle mouse release events."""
        event_data = {"point": point, "button": button, "mods": mods}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseReleaseEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return
            
        if self.color_palette in self.mobjects:
            self.choose_color(point)
        else:
            self.clear_selection()
    
    def on_mouse_scroll(self, point, offset, x_pixel_offset, y_pixel_offset):
        """Handle mouse scroll events - only zoom with Cmd/Ctrl held."""
        event_data = {"point": point, "offset": offset}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseScrollEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return
        
        # Only zoom if Cmd/Ctrl is held
        if self.window.is_key_pressed(PygletWindowKeys.LCOMMAND) or \
           self.window.is_key_pressed(PygletWindowKeys.RCOMMAND) or \
           self.window.is_key_pressed(PygletWindowKeys.LCTRL) or \
           self.window.is_key_pressed(PygletWindowKeys.RCTRL):
            # Use parent's zoom behavior
            rel_offset = y_pixel_offset / self.camera.get_pixel_height()
            self.frame.scale(
                1 - self.scroll_sensitivity * rel_offset,
                about_point=point
            )
    
    def setup_auto_reload(self):
        """Setup automatic file watching and reloading."""
        # Skip auto-reload setup here, we'll do it in interactive_embed
        pass
    
    def checkpoint_paste(self, skip=False, record=False, progress_bar=True):
        """
        Run code from clipboard, with automatic checkpointing.
        
        If the code starts with a comment, it will be used as a checkpoint key.
        Running the same checkpoint again will restore to that state first.
        """
        code_string = pyperclip.paste()
        lines = code_string.strip().split('\n')
        
        # Check for checkpoint comment
        checkpoint_key = None
        if lines and lines[0].strip().startswith('#'):
            checkpoint_key = lines[0].strip()
        
        # Handle checkpoint
        if checkpoint_key:
            if checkpoint_key in self.checkpoint_states:
                # Restore to checkpoint
                print(f"Restoring to checkpoint: {checkpoint_key}")
                self.restore_state(self.checkpoint_states[checkpoint_key])
                # Clear later checkpoints
                keys_to_remove = []
                found = False
                for key in self.checkpoint_states:
                    if found:
                        keys_to_remove.append(key)
                    if key == checkpoint_key:
                        found = True
                for key in keys_to_remove:
                    del self.checkpoint_states[key]
            else:
                # Save new checkpoint
                print(f"Creating checkpoint: {checkpoint_key}")
                self.checkpoint_states[checkpoint_key] = self.get_state()
        
        # Execute the code
        with self.temp_config_change(skip=skip, record=record, progress_bar=progress_bar):
            # Get the calling frame's namespace
            frame = inspect.currentframe().f_back
            namespace = frame.f_locals.copy()
            namespace.update(frame.f_globals)
            namespace['self'] = self
            
            try:
                exec(code_string, namespace)
            except Exception as e:
                print(f"Error executing code: {e}")
                import traceback
                traceback.print_exc()
    
    def clear_checkpoints(self):
        """Clear all saved checkpoints."""
        self.checkpoint_states.clear()
        print("All checkpoints cleared")
    
    def reload_scene(self):
        """Reload the scene file and re-run from the beginning."""
        print("Reloading scene...")
        # This will exit the embed and trigger a reload in ManimGL
        if hasattr(self, '_shell'):
            self._shell.run_line_magic("exit_raise", "")
        else:
            raise EndScene()
    
    def _handle_file_change(self):
        """Handle file change by reloading from the appropriate checkpoint."""
        print("\nFile changed! Auto-reloading...")
        
        try:
            # Read the new content
            with open(self._scene_filepath, 'r') as f:
                new_content = f.readlines()
            
            # Check for syntax errors
            try:
                compile(''.join(new_content), self._scene_filepath, 'exec')
            except SyntaxError as e:
                print(f"Syntax error at line {e.lineno}: {e.msg}")
                return
            
            # Find what line changed
            changed_line = self._find_first_changed_line(new_content)
            
            if changed_line:
                print(f"Change detected at line {changed_line}")
                
                # Find the checkpoint before this line
                checkpoint_index = -1
                print(f"Available checkpoints:")
                for i, (_, line_no, _) in enumerate(self.animation_checkpoints):
                    print(f"  Checkpoint {i}: line {line_no}")
                    if line_no < changed_line:
                        checkpoint_index = i
                    else:
                        break
                print(f"Selected checkpoint index: {checkpoint_index}")
                
                if checkpoint_index >= 0:
                    # Restore to checkpoint
                    checkpoint = self.animation_checkpoints[checkpoint_index]
                    print(f"Restoring to checkpoint {checkpoint_index + 1} (line {checkpoint[1]})")
                    print(f"Current mobjects before restore: {[m.name if hasattr(m, 'name') else str(m) for m in self.mobjects]}")
                    self.restore_state(checkpoint[2])
                    print(f"Current mobjects after restore: {[m.name if hasattr(m, 'name') else str(m) for m in self.mobjects]}")
                    
                    # Extract code after the checkpoint line
                    code_to_run = self._extract_code_after_line(checkpoint[1], new_content)
                    
                    if code_to_run:
                        print("Running updated code...")
                        print(f"Code to run:\n{code_to_run}")
                        
                        # Set flag to prevent checkpoint creation during reload
                        self._navigating_animations = True
                        
                        try:
                            # Use exec with comprehensive namespace
                            import sys
                            
                            # Start with the construct method's namespace if available
                            if hasattr(self, '_construct_namespace'):
                                namespace = self._construct_namespace.copy()
                            else:
                                namespace = {}
                            
                            # Add module namespace
                            module_name = self.__class__.__module__
                            if module_name in sys.modules:
                                module = sys.modules[module_name]
                                namespace.update(vars(module))
                            
                            # Import all maniml objects if not already there
                            if 'Circle' not in namespace:
                                exec("from manim import *", namespace)
                            
                            # Update with current self and scene methods
                            namespace.update({
                                'self': self,
                                'scene': self,
                                'play': self.play,
                                'wait': self.wait,
                                'add': self.add,
                                'remove': self.remove,
                                'camera': self.camera,
                            })
                            
                            # Add all current mobjects by name
                            for mob in self.mobjects:
                                if hasattr(mob, 'name') and mob.name:
                                    namespace[mob.name] = mob
                            
                            # Execute the code
                            exec(code_to_run, namespace)
                            print("Code executed successfully!")
                        except Exception as e:
                            print(f"Error executing updated code: {e}")
                            import traceback
                            traceback.print_exc()
                        finally:
                            # Clear the flag
                            self._navigating_animations = False
                else:
                    print("No checkpoint before change, running from start...")
                    self.clear()
                    code_to_run = self._extract_construct_body(new_content)
                    if code_to_run:
                        # Set flag to prevent checkpoint creation during reload
                        self._navigating_animations = True
                        
                        try:
                            # Use exec with comprehensive namespace
                            import sys
                            
                            # Start with the module's namespace
                            module_name = self.__class__.__module__
                            if module_name in sys.modules:
                                module = sys.modules[module_name]
                                namespace = vars(module).copy()
                            else:
                                namespace = {}
                            
                            # Import all maniml objects if not already there
                            if 'Circle' not in namespace:
                                exec("from manim import *", namespace)
                            
                            # Add self and scene methods
                            namespace.update({
                                'self': self,
                                'scene': self,
                                'play': self.play,
                                'wait': self.wait,
                                'add': self.add,
                                'remove': self.remove,
                                'camera': self.camera,
                            })
                            
                            # Execute the code
                            exec(code_to_run, namespace)
                            print("Code executed successfully from start!")
                        except Exception as e:
                            print(f"Error executing code from start: {e}")
                            import traceback
                            traceback.print_exc()
                        finally:
                            # Clear the flag
                            self._navigating_animations = False
                
                print("Reload complete!")
                
                # Force an immediate redraw
                self.update_frame(dt=0, force_draw=True)
            
            # Update stored content
            self._original_content = new_content
            
        except Exception as e:
            print(f"Error during reload: {e}")
            import traceback
            traceback.print_exc()
    
    def _find_first_changed_line(self, new_content):
        """Find the first line that changed."""
        for i, (old_line, new_line) in enumerate(zip(self._original_content, new_content)):
            if old_line != new_line:
                return i + 1  # Line numbers are 1-based
        
        # Check for added lines at the end
        if len(new_content) > len(self._original_content):
            return len(self._original_content) + 1
        
        return None
    
    def _extract_construct_body(self, content):
        """Extract the body of the construct method as executable code."""
        in_construct = False
        code_lines = []
        base_indent = None
        
        for line in content:
            if 'def construct(self):' in line:
                in_construct = True
                base_indent = len(line) - len(line.lstrip())
                continue
            
            if in_construct:
                # Check if we've exited construct
                if line.strip() and not line[base_indent:].startswith(' '):
                    break
                
                # Skip interactive_embed calls
                if line.strip() and 'interactive_embed' not in line:
                    # Remove the base indentation
                    dedented = line[base_indent + 4:]  # +4 for method body indent
                    code_lines.append(dedented)
        
        return ''.join(code_lines)
    
    def _extract_code_up_to_line(self, end_line, content):
        """Extract code from the construct method up to the given line."""
        in_construct = False
        code_lines = []
        base_indent = None
        
        for i, line in enumerate(content):
            line_no = i + 1
            
            if 'def construct(self):' in line:
                in_construct = True
                base_indent = len(line) - len(line.lstrip())
                continue
            
            if in_construct:
                # Check if we've exited construct
                if line.strip() and not line[base_indent:].startswith(' '):
                    break
                
                # Include all lines up to end_line
                if line_no <= end_line and line.strip() and 'interactive_embed' not in line:
                    # Remove the base indentation
                    dedented = line[base_indent + 4:]  # +4 for method body indent
                    code_lines.append(dedented)
        
        return ''.join(code_lines)
    
    def _extract_code_between_lines(self, start_line, end_line, content):
        """Extract code from the construct method between the given lines."""
        in_construct = False
        code_lines = []
        base_indent = None
        
        for i, line in enumerate(content):
            line_no = i + 1
            
            if 'def construct(self):' in line:
                in_construct = True
                base_indent = len(line) - len(line.lstrip())
                continue
            
            if in_construct:
                # Check if we've exited construct
                if line.strip() and not line[base_indent:].startswith(' '):
                    break
                
                # Only include lines between start_line and end_line
                if start_line < line_no <= end_line and line.strip() and 'interactive_embed' not in line:
                    # Remove the base indentation
                    dedented = line[base_indent + 4:]  # +4 for method body indent
                    code_lines.append(dedented)
        
        return ''.join(code_lines)
    
    def _extract_code_after_line(self, start_line, content):
        """Extract code from the construct method after the given line."""
        in_construct = False
        code_lines = []
        base_indent = None
        
        for i, line in enumerate(content):
            line_no = i + 1
            
            if 'def construct(self):' in line:
                in_construct = True
                base_indent = len(line) - len(line.lstrip())
                continue
            
            if in_construct:
                # Check if we've exited construct
                if line.strip() and not line[base_indent:].startswith(' '):
                    break
                
                # Only include lines after start_line
                if line_no > start_line and line.strip() and 'interactive_embed' not in line:
                    # Remove the base indentation
                    dedented = line[base_indent + 4:]  # +4 for method body indent
                    code_lines.append(dedented)
        
        return ''.join(code_lines)
    
    def run_next_animation(self):
        """Run the next animation using checkpoint_temporary workflow."""
        if self.current_animation_index >= len(self.animation_checkpoints) - 1:
            print("Already at last animation")
            return
            
        # Create checkpoint_temporary
        #checkpoint_temporary = {}
        
        # Get current checkpoint
        current_checkpoint = self.animation_checkpoints[self.current_animation_index]
        next_index = self.current_animation_index + 1
        
        # Deep copy namespace from current checkpoint
        #OLD checkpoint_temporary['namespace'] = deepcopy_namespace(current_checkpoint['namespace'])
        checkpoint_temporary = deepcopy_namespace(current_checkpoint) #NEW
        
        # Clear the window
        self.clear()
        
        # Restore state from current checkpoint
        # This adds all the mobjects to the scene
        self.restore_state(checkpoint_temporary['state']) #NEW

        # Get the code to run
        if hasattr(self, '_scene_filepath') and self._scene_filepath:
            try:
                with open(self._scene_filepath, 'r') as f:
                    lines = f.readlines()
                
                # Extract code from current checkpoint to next play() call
                current_line = current_checkpoint['line_number']
                code_lines = []
                in_construct = False
                base_indent = None
                found_next_play = False
                next_line_number = 0
                
                for i, line in enumerate(lines):
                    line_no = i + 1
                    
                    if 'def construct(self):' in line:
                        in_construct = True
                        base_indent = len(line) - len(line.lstrip())
                        continue
                    
                    if in_construct:
                        # Check if we've exited construct
                        if line.strip() and not line[base_indent:].startswith(' '):
                            break
                        
                        # Only include lines after current checkpoint
                        if line_no > current_line:
                            if line.strip() and 'interactive_embed' not in line:
                                # Remove the base indentation
                                dedented = line[base_indent + 4:]  # +4 for method body indent
                                code_lines.append(dedented)
                                
                                # Check if this line contains play()
                                if 'self.play(' in line or '.play(' in line:
                                    found_next_play = True
                                    next_line_number = line_no
                                    # For multiline play calls, continue until we find the closing parenthesis
                                    if line.count('(') > line.count(')'):
                                        paren_count = line.count('(') - line.count(')')
                                        j = i + 1
                                        while j < len(lines) and paren_count > 0:
                                            next_line = lines[j]
                                            code_lines.append(next_line[base_indent + 4:])
                                            paren_count += next_line.count('(') - next_line.count(')')
                                            next_line_number = j + 1
                                            j += 1
                                    break
                
                if not found_next_play:
                    print("No more animations found")
                    return
                    
                code_to_run = ''.join(code_lines)
                
                # Set flag to prevent checkpoint creation during navigation
                self._navigating_animations = True
                
                try:
                    # Update self reference to point to current scene
                    checkpoint_temporary['namespace']['self'] = self
                    
                    # Execute the code
                    exec(code_to_run, checkpoint_temporary['namespace'])
                    
                    # Animation completed, now finalize the checkpoint
                    self.current_animation_index = next_index
                    
                    # Add state to namespace for deepcopy
                    checkpoint_temporary['namespace']['__checkpoint_state__'] = self.get_state()
                    
                    # Deep copy for final storage
                    final_checkpoint = deepcopy_namespace(checkpoint_temporary['namespace'])
                    final_state = final_checkpoint.pop('__checkpoint_state__')
                    
                    # Create final checkpoint
                    checkpoint = {
                        'index': next_index,
                        'line_number': next_line_number,
                        'state': final_state,
                        'namespace': final_checkpoint
                    }
                    
                    # Add or update checkpoint
                    if next_index < len(self.animation_checkpoints):
                        self.animation_checkpoints[next_index] = checkpoint
                    else:
                        self.animation_checkpoints.append(checkpoint)
                    
                    print(f"→ Played animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                    
                finally:
                    self._navigating_animations = False
                    
            except Exception as e:
                print(f"Error running animation: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("No file path available for code extraction")
    
    def jump_to_animation(self, index):
        """Jump instantly to a specific animation checkpoint."""
        if index < 0 or index >= len(self.animation_checkpoints):
            print(f"Invalid index. Available checkpoints: 0-{len(self.animation_checkpoints)-1}")
            return
            
        checkpoint = self.animation_checkpoints[index]
        print(f"Jumping to animation #{index + 1}")
        
        # Restore the state
        self.restore_state(checkpoint['state'])
        self.current_animation_index = index
        
        # Update frame
        self.update_frame(force_draw=True)
    
    def list_checkpoints(self):
        """List all available animation checkpoints."""
        print(f"\nAvailable checkpoints ({len(self.animation_checkpoints)} total):")
        for i, checkpoint in enumerate(self.animation_checkpoints):
            print(f"  {i}: Animation at line {checkpoint['line_number']}")
        print(f"\nUse jump_to(index) to jump to any checkpoint.")
    
    def play(self, *animations, **kwargs):
        """Play animations with checkpoint support."""
        # Check if we should skip animations (for playing only first animation)
        should_skip = False
        if hasattr(self, '_animations_to_play') and hasattr(self, '_animations_played'):
            self._animations_played += 1
            
            if self._animations_played > self._animations_to_play:
                # Enable skip mode for animations beyond the limit
                should_skip = True
                prev_skip = self.skip_animations
                self.skip_animations = True
        
        # Don't save checkpoints if we're navigating with arrow keys
        if hasattr(self, '_navigating_animations') and self._navigating_animations:
            return super().play(*animations, **kwargs)
        
        # Get the line number where this play was called
        frame = inspect.currentframe().f_back
        line_no = frame.f_lineno
        
        # Play the animation first
        result = super().play(*animations, **kwargs)
        
        # Restore skip_animations if we changed it
        if should_skip:
            self.skip_animations = prev_skip
        
        # Capture the namespace AFTER animation completes
        # This includes all variables defined up to this point
        namespace = frame.f_locals.copy()
        
        # Also include globals from the calling module
        namespace.update(frame.f_globals)
        
        # Add current state to namespace BEFORE deepcopy
        namespace['__checkpoint_state__'] = self.get_state()
        
        # Deep copy everything together - references are preserved!
        checkpoint_namespace = deepcopy_namespace(namespace)
        
        # Extract state from deepcopied namespace
        checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')
        
        # Save checkpoint AFTER animation completes
        self.current_animation_index += 1
        
        checkpoint = {
            'index': self.current_animation_index,
            'line_number': line_no,
            'state': checkpoint_state,  # References deepcopied mobjects
            'namespace': checkpoint_namespace  # Contains same mobjects
        }
        
        self.animation_checkpoints.append(checkpoint)
        
        # Keep only last 50 checkpoints to avoid memory issues
        if len(self.animation_checkpoints) > 50:
            self.animation_checkpoints.pop(0)
            
        return result
    
    def wait(self, duration=1.0, stop_condition=None, frozen_frame=None):
        """CE-style wait without checkpoint creation."""
        # Check if we should skip this wait (for playing only first animation)
        if hasattr(self, '_animations_to_play') and hasattr(self, '_animations_played'):
            self._animations_played += 1
            
            if self._animations_played > self._animations_to_play:
                # Skip the wait by setting duration to 0
                duration = 0
        
        # Simply execute the wait without creating checkpoints
        result = super().wait(duration, stop_condition, frozen_frame)
        return result
    
    
    def tear_down(self):
        """Clean up file watcher on scene end."""
        if hasattr(self, '_file_watcher') and self._file_watcher:
            self._file_watcher.stop()
        super().tear_down()
    
    # InteractiveScene methods (ported from ManimGL)
    
    def get_selection_rectangle(self):
        rect = Rectangle(
            stroke_color=self.selection_rectangle_stroke_color,
            stroke_width=self.selection_rectangle_stroke_width,
        )
        rect.fix_in_frame()
        rect.fixed_corner = ORIGIN
        rect.add_updater(self.update_selection_rectangle)
        return rect

    def update_selection_rectangle(self, rect):
        p1 = rect.fixed_corner
        p2 = self.frame.to_fixed_frame_point(self.mouse_point.get_center())
        rect.set_points_as_corners([
            p1, np.array([p2[0], p1[1], 0]),
            p2, np.array([p1[0], p2[1], 0]),
            p1,
        ])
        return rect

    def get_selection_highlight(self):
        result = Group()
        result.tracked_mobjects = []
        result.add_updater(self.update_selection_highlight)
        return result

    def update_selection_highlight(self, highlight):
        if set(highlight.tracked_mobjects) == set(self.selection):
            return

        # Otherwise, refresh contents of highlight
        highlight.tracked_mobjects = list(self.selection)
        highlight.set_submobjects([
            self.get_highlight(mob)
            for mob in self.selection
        ])
        try:
            index = min((
                i for i, mob in enumerate(self.mobjects)
                for sm in self.selection
                if sm in mob.get_family()
            ))
            self.mobjects.remove(highlight)
            self.mobjects.insert(index - 1, highlight)
        except ValueError:
            pass

    def get_crosshair(self):
        lines = VMobject().replicate(2)
        lines[0].set_points([LEFT, ORIGIN, RIGHT])
        lines[1].set_points([UP, ORIGIN, DOWN])
        crosshair = VGroup(*lines)

        crosshair.set_width(self.crosshair_width)
        crosshair.set_style(**self.crosshair_style)
        crosshair.set_animating_status(True)
        crosshair.fix_in_frame()
        return crosshair

    def get_color_palette(self):
        palette = VGroup(*(
            Square(fill_color=color, fill_opacity=1, side_length=1)
            for color in self.palette_colors
        ))
        palette.set_stroke(width=0)
        palette.arrange(RIGHT, buff=0.5)
        palette.set_width(FRAME_WIDTH - 0.5)
        palette.to_edge(DOWN, buff=SMALL_BUFF)
        palette.fix_in_frame()
        return palette

    def get_information_label(self):
        loc_label = VGroup(*(
            DecimalNumber(**self.cursor_location_config)
            for n in range(3)
        ))

        def update_coords(loc_label):
            for mob, coord in zip(loc_label, self.mouse_point.get_location()):
                mob.set_value(coord)
            loc_label.arrange(RIGHT, buff=loc_label.get_height())
            loc_label.to_corner(DR, buff=SMALL_BUFF)
            loc_label.fix_in_frame()
            return loc_label

        loc_label.add_updater(update_coords)

        time_label = DecimalNumber(0, **self.time_label_config)
        time_label.to_corner(DL, buff=SMALL_BUFF)
        time_label.fix_in_frame()
        time_label.add_updater(lambda m, dt: m.increment_value(dt))

        return VGroup(loc_label, time_label)

    # Selection management

    def toggle_selection_mode(self):
        self.select_top_level_mobs = not self.select_top_level_mobs
        self.refresh_selection_scope()
        self.regenerate_selection_search_set()

    def get_selection_search_set(self):
        return self.selection_search_set

    def regenerate_selection_search_set(self):
        selectable = list(filter(
            lambda m: m not in self.unselectables,
            self.mobjects
        ))
        if self.select_top_level_mobs:
            self.selection_search_set = selectable
        else:
            self.selection_search_set = [
                submob
                for mob in selectable
                for submob in mob.family_members_with_points()
            ]

    def refresh_selection_scope(self):
        curr = list(self.selection)
        if self.select_top_level_mobs:
            self.selection.set_submobjects([
                mob
                for mob in self.mobjects
                if any(sm in mob.get_family() for sm in curr)
            ])
            self.selection.refresh_bounding_box(recurse_down=True)
        else:
            self.selection.set_submobjects(
                extract_mobject_family_members(
                    curr, exclude_pointless=True,
                )
            )

    def get_corner_dots(self, mobject):
        dots = DotCloud(**self.corner_dot_config)
        radius = float(self.corner_dot_config["radius"])
        if mobject.get_depth() < 1e-2:
            vects = [DL, UL, UR, DR]
        else:
            vects = np.array(list(it.product(*3 * [[-1, 1]])))
        dots.add_updater(lambda d: d.set_points([
            mobject.get_corner(v) + v * radius
            for v in vects
        ]))
        return dots

    def get_highlight(self, mobject):
        if isinstance(mobject, VMobject) and mobject.has_points() and not self.select_top_level_mobs:
            length = max([mobject.get_height(), mobject.get_width()])
            result = VHighlight(
                mobject,
                max_stroke_addition=min([50 * length, 10]),
            )
            result.add_updater(lambda m: m.replace(mobject, stretch=True))
            return result
        elif isinstance(mobject, DotCloud):
            return Mobject()
        else:
            return self.get_corner_dots(mobject)

    def add_to_selection(self, *mobjects):
        mobs = list(filter(
            lambda m: m not in self.unselectables and m not in self.selection,
            mobjects
        ))
        if len(mobs) == 0:
            return
        self.selection.add(*mobs)
        for mob in mobs:
            mob.set_animating_status(True)

    def toggle_from_selection(self, *mobjects):
        for mob in mobjects:
            if mob in self.selection:
                self.selection.remove(mob)
                mob.set_animating_status(False)
                mob.refresh_bounding_box()
            else:
                self.add_to_selection(mob)

    def clear_selection(self):
        for mob in self.selection:
            mob.set_animating_status(False)
            mob.refresh_bounding_box()
        self.selection.set_submobjects([])

    def disable_interaction(self, *mobjects):
        for mob in mobjects:
            for sm in mob.get_family():
                self.unselectables.append(sm)
        self.regenerate_selection_search_set()

    def enable_interaction(self, *mobjects):
        for mob in mobjects:
            for sm in mob.get_family():
                if sm in self.unselectables:
                    self.unselectables.remove(sm)

    # Keyboard action methods

    def copy_selection(self):
        # Simplified version without IPython
        names = [str(id(mob)) for mob in self.selection]
        pyperclip.copy(", ".join(names))

    def paste_selection(self):
        clipboard_str = pyperclip.paste()
        # Try pasting a mobject
        try:
            ids = map(int, clipboard_str.split(","))
            mobs = map(self.id_to_mobject, ids)
            mob_copies = [m.copy() for m in mobs if m is not None]
            self.clear_selection()
            self.play(*(
                FadeIn(mc, run_time=0.5, scale=1.5)
                for mc in mob_copies
            ))
            self.add_to_selection(*mob_copies)
            return
        except ValueError:
            pass
        # Otherwise, treat as tex or text
        if set("\\^=+").intersection(clipboard_str):  # Proxy to text for LaTeX
            try:
                new_mob = Tex(clipboard_str)
            except LatexError:
                return
        else:
            new_mob = Text(clipboard_str)
        self.clear_selection()
        self.add(new_mob)
        self.add_to_selection(new_mob)

    def delete_selection(self):
        self.remove(*self.selection)
        self.clear_selection()

    def enable_selection(self):
        self.is_selecting = True
        self.add(self.selection_rectangle)
        self.selection_rectangle.fixed_corner = self.frame.to_fixed_frame_point(
            self.mouse_point.get_center()
        )

    def gather_new_selection(self):
        self.is_selecting = False
        if self.selection_rectangle in self.mobjects:
            self.remove(self.selection_rectangle)
            additions = []
            for mob in reversed(self.get_selection_search_set()):
                if self.selection_rectangle.is_touching(mob):
                    additions.append(mob)
                    if self.selection_rectangle.get_arc_length() < 1e-2:
                        break
            self.toggle_from_selection(*additions)

    def prepare_grab(self):
        mp = self.mouse_point.get_center()
        self.mouse_to_selection = mp - self.selection.get_center()
        self.is_grabbing = True

    def prepare_resizing(self, about_corner=False):
        center = self.selection.get_center()
        mp = self.mouse_point.get_center()
        if about_corner:
            self.scale_about_point = self.selection.get_corner(center - mp)
        else:
            self.scale_about_point = center
        self.scale_ref_vect = mp - self.scale_about_point
        self.scale_ref_width = self.selection.get_width()
        self.scale_ref_height = self.selection.get_height()

    def toggle_color_palette(self):
        if len(self.selection) == 0:
            return
        if self.color_palette not in self.mobjects:
            self.save_state()
            self.add(self.color_palette)
        else:
            self.remove(self.color_palette)

    def display_information(self, show=True):
        if show:
            self.add(self.information_label)
        else:
            self.remove(self.information_label)

    def group_selection(self):
        group = self.get_group(*self.selection)
        self.add(group)
        self.clear_selection()
        self.add_to_selection(group)

    def ungroup_selection(self):
        pieces = []
        for mob in list(self.selection):
            self.remove(mob)
            pieces.extend(list(mob))
        self.clear_selection()
        self.add(*pieces)
        self.add_to_selection(*pieces)

    def nudge_selection(self, vect, large=False):
        nudge = self.selection_nudge_size
        if large:
            nudge *= 10
        self.selection.shift(nudge * vect)

    # Mouse event handlers

    def handle_grabbing(self, point):
        diff = point - self.mouse_to_selection
        if self.window.is_key_pressed(ord(GRAB_KEY)):
            self.selection.move_to(diff)
        elif self.window.is_key_pressed(ord(X_GRAB_KEY)):
            self.selection.set_x(diff[0])
        elif self.window.is_key_pressed(ord(Y_GRAB_KEY)):
            self.selection.set_y(diff[1])

    def handle_resizing(self, point):
        if not hasattr(self, "scale_about_point") or self.scale_about_point is None:
            return
        vect = point - self.scale_about_point
        if self.window.is_key_pressed(PygletWindowKeys.LCTRL):
            for i in (0, 1):
                scalar = vect[i] / self.scale_ref_vect[i]
                self.selection.rescale_to_fit(
                    scalar * [self.scale_ref_width, self.scale_ref_height][i],
                    dim=i,
                    about_point=self.scale_about_point,
                    stretch=True,
                )
        else:
            scalar = get_norm(vect) / get_norm(self.scale_ref_vect)
            self.selection.set_width(
                scalar * self.scale_ref_width,
                about_point=self.scale_about_point
            )

    def handle_sweeping_selection(self, point):
        mob = self.point_to_mobject(
            point,
            search_set=self.get_selection_search_set(),
            buff=SMALL_BUFF
        )
        if mob is not None:
            self.add_to_selection(mob)

    def choose_color(self, point):
        # Search through all mobject on the screen, not just the palette
        to_search = [
            sm
            for mobject in self.mobjects
            for sm in mobject.family_members_with_points()
            if mobject not in self.unselectables
        ]
        mob = self.point_to_mobject(point, to_search)
        if mob is not None:
            self.selection.set_color(mob.get_color())
        self.remove(self.color_palette)

    # Override add/remove to maintain selection search set
    
    def add(self, *mobjects):
        super().add(*mobjects)
        self.regenerate_selection_search_set()
        return self

    def remove(self, *mobjects):
        super().remove(*mobjects)
        self.regenerate_selection_search_set()
        return self

    def remove_all_except(self, *mobjects_to_keep):
        super().remove_all_except(*mobjects_to_keep)
        self.regenerate_selection_search_set()

    # Override get_state to ignore interactive elements
    
    def get_state(self):
        return SceneState(self, ignore=[
            self.selection_highlight,
            self.selection_rectangle,
            self.crosshair,
        ])

    def restore_state(self, scene_state):
        super().restore_state(scene_state)
        if hasattr(self, 'selection_highlight') and self.selection_highlight:
            self.mobjects.insert(0, self.selection_highlight)

    # Copy positioning helpers
    
    def copy_frame_positioning(self):
        frame = self.frame
        center = frame.get_center()
        height = frame.get_height()
        angles = frame.get_euler_angles()

        call = f"reorient("
        theta, phi, gamma = (angles / DEG).astype(int)
        call += f"{theta}, {phi}, {gamma}"
        if any(center != 0):
            call += f", {tuple(np.round(center, 2))}"
        if height != FRAME_HEIGHT:
            call += ", {:.2f}".format(height)
        call += ")"
        pyperclip.copy(call)

    def copy_cursor_position(self):
        pyperclip.copy(str(tuple(self.mouse_point.get_center().round(2))))


class ThreeDScene(GLThreeDScene):
    """CE-compatible ThreeDScene using GL backend."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Add CE compatibility methods
        self.renderer = self
        # Disable drag-to-pan by default since we use Cmd/Ctrl + drag
        self.drag_to_pan = False
    
    # Override methods to add CE compatibility
    def add(self, *mobjects):
        """CE-style add method that returns self for chaining."""
        GLThreeDScene.add(self, *mobjects)
        return self
    
    def remove(self, *mobjects):
        """CE-style remove method that returns self for chaining."""
        GLThreeDScene.remove(self, *mobjects)
        return self
    
    def play(self, *animations, **kwargs):
        """CE-style play with multiple animations and lag_ratio support."""
        # Extract CE-specific kwargs
        run_time = kwargs.pop('run_time', None)
        lag_ratio = kwargs.pop('lag_ratio', 0)
        rate_func = kwargs.pop('rate_func', None)
        
        # Handle run_time
        if run_time is not None:
            for anim in animations:
                if hasattr(anim, 'run_time'):
                    anim.run_time = run_time
        
        # Handle rate_func
        if rate_func is not None:
            for anim in animations:
                if hasattr(anim, 'rate_func'):
                    anim.rate_func = rate_func
        
        # Handle multiple animations
        if len(animations) == 1:
            GLThreeDScene.play(self, animations[0], **kwargs)
        else:
            # Multiple animations
            if lag_ratio > 0:
                from manim.renderer.opengl.animation.composition import LaggedStart
                GLThreeDScene.play(self, LaggedStart(*animations, lag_ratio=lag_ratio), **kwargs)
            else:
                from manim.renderer.opengl.animation.composition import AnimationGroup
                GLThreeDScene.play(self, AnimationGroup(*animations), **kwargs)
    
    def wait(self, duration=None, stop_condition=None, note=None, ignore_presenter_mode=False):
        """CE-style wait method."""
        # Call parent's wait directly
        if duration is None:
            duration = 1.0  # Default wait time
        GLThreeDScene.wait(self, duration, stop_condition, note, ignore_presenter_mode)
    
    def bring_to_front(self, *mobjects):
        """CE-style bring_to_front."""
        GLThreeDScene.bring_to_front(self, *mobjects)
        return self
    
    def bring_to_back(self, *mobjects):
        """CE-style bring_to_back."""
        GLThreeDScene.bring_to_back(self, *mobjects)
        return self
    
    def clear(self):
        """CE-style clear."""
        GLThreeDScene.clear(self)
        return self
    
    # Interactive methods from Scene
    def on_key_press(self, symbol, modifiers):
        """Handle key press with Scene's interactive features."""
        # First call parent's on_key_press
        GLThreeDScene.on_key_press(self, symbol, modifiers)
        # Then add our interactive features if Scene has them
        if hasattr(Scene, 'on_key_press') and hasattr(Scene, 'gather_new_selection'):
            # Call specific interactive methods we need
            pass
    
    def checkpoint_paste(self):
        """Interactive checkpoint paste."""
        if hasattr(Scene, 'checkpoint_paste'):
            return Scene.checkpoint_paste(self)
    
    def clear_checkpoints(self):
        """Clear checkpoints."""
        if hasattr(Scene, 'clear_checkpoints'):
            return Scene.clear_checkpoints(self)
    
    def set_camera_orientation(self, phi=None, theta=None, gamma=None, **kwargs):
        """CE compatibility wrapper for camera orientation."""
        # Convert CE-style angles (in radians) to degrees for reorient
        if phi is not None or theta is not None or gamma is not None:
            # Get current angles if not specified
            current_theta = self.frame.get_theta() if theta is None else theta
            current_phi = self.frame.get_phi() if phi is None else phi
            current_gamma = self.frame.get_gamma() if gamma is None else gamma
            
            # Convert radians to degrees
            theta_deg = current_theta * 180 / PI
            phi_deg = current_phi * 180 / PI
            gamma_deg = current_gamma * 180 / PI
            
            # Use reorient which expects degrees
            self.frame.reorient(theta_deg, phi_deg, gamma_deg)
        
        return self
    
    def move_camera(self, phi=None, theta=None, gamma=None, **kwargs):
        """CE compatibility wrapper for animating camera movement."""
        # For animated camera movements
        animations = []
        
        if theta is not None:
            animations.append(self.frame.animate.set_theta(theta))
        if phi is not None:
            animations.append(self.frame.animate.set_phi(phi))
        if gamma is not None:
            animations.append(self.frame.animate.set_gamma(gamma))
        
        if animations:
            self.play(*animations, **kwargs)
        
        return self


# Alias for CE compatibility
SpecialThreeDScene = ThreeDScene