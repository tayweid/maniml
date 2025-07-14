"""
Scene with CE compatibility using GL backend.
"""

import manim
from manim.scene.scene import Scene as GLScene
from manim.scene.scene import ThreeDScene as GLThreeDScene
from manim.scene.scene import SceneState, EndScene
import warnings
import time
import sys
import inspect
import pyperclip
from pyglet.window import key as PygletWindowKeys
import difflib

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


class Scene(GLScene):
    """
    CE-compatible Scene using GL backend.
    
    Provides CE's API while using GL's fast rendering.
    """
    
    def __init__(self, **kwargs):
        # CE compatibility attributes
        self.renderer = self  # CE code often references scene.renderer
        self.animations = []  # Track animations for CE compatibility
        
        # Checkpoint management
        self.checkpoint_states = {}  # key -> SceneState
        self.animation_count = 0
        self.animation_checkpoints = []  # List of (line_number, state) tuples
        self.current_animation_index = -1
        
        # Auto-reload setup
        self.file_watcher = None
        self.auto_reload_enabled = kwargs.pop('auto_reload', True)  # Enable by default
        self._scene_filepath = None
        self._original_content = None
        self._file_changed_flag = False  # Thread-safe flag
        
        super().__init__(**kwargs)
        
        # Enable auto-reload if requested
        if self.auto_reload_enabled:
            self.setup_auto_reload()
    
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
    
    def play(self, *animations, **kwargs):
        """
        CE-style play with multiple animations and lag_ratio support.
        """
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
                from manim.animation.composition import LaggedStart
                super().play(LaggedStart(*animations, lag_ratio=lag_ratio), **kwargs)
            else:
                from manim.animation.composition import AnimationGroup
                super().play(AnimationGroup(*animations), **kwargs)
        
        return self
    
    def wait(self, duration=1.0, stop_condition=None, frozen_frame=None):
        """CE-style wait with proper event handling."""
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
    
    def on_resize(self, width, height):
        """Handle window resize events with crop and zoom to maintain edge positions."""
        # Call parent implementation
        super().on_resize(width, height)
        
        if hasattr(self, 'camera'):
            # Store initial dimensions if not already stored
            if not hasattr(self, '_initial_window_width'):
                self._initial_window_width = width
                self._initial_window_height = height
                self._initial_frame_width = self.camera.frame.get_width()
                self._initial_frame_height = self.camera.frame.get_height()
                # Calculate initial visible width (what's actually shown after any cropping)
                window_aspect = width / height
                frame_aspect = self._initial_frame_width / self._initial_frame_height
                if window_aspect < frame_aspect:
                    # Window is taller - we see less width due to cropping
                    self._initial_visible_width = self._initial_frame_height * window_aspect
                else:
                    # Window is wider or same - we see full width
                    self._initial_visible_width = self._initial_frame_width
            
            # Calculate current aspect ratios
            window_aspect = width / height
            frame_aspect = 16 / 9  # Standard frame aspect ratio
            
            # Calculate frame dimensions to maintain visible edges
            if window_aspect < frame_aspect:
                # Window is taller - crops left/right
                # We want visible width to stay constant at initial value
                # visible_width = frame_height * window_aspect
                # So: frame_height = initial_visible_width / window_aspect
                new_frame_height = self._initial_visible_width / window_aspect
                new_frame_width = new_frame_height * frame_aspect
            else:
                # Window is wider - crops top/bottom
                # Scale based on window width to maintain edges
                zoom_factor = width / self._initial_window_width
                new_frame_width = self._initial_frame_width * zoom_factor
                new_frame_height = new_frame_width / frame_aspect
            
            # Apply the calculated dimensions
            self.camera.frame.set_width(new_frame_width, stretch=True)
            self.camera.frame.set_height(new_frame_height, stretch=True)
            
            # Apply cropping viewport
            if hasattr(self.camera, 'ctx'):
                if window_aspect > frame_aspect:
                    # Window is wider - crop top/bottom
                    viewport_width = width
                    viewport_height = int(width / frame_aspect)
                    viewport_x = 0
                    viewport_y = -(viewport_height - height) // 2
                else:
                    # Window is taller - crop left/right
                    viewport_height = height
                    viewport_width = int(height * frame_aspect)
                    viewport_x = -(viewport_width - width) // 2
                    viewport_y = 0
                
                # Set the OpenGL viewport
                self.camera.ctx.viewport = (viewport_x, viewport_y, viewport_width, viewport_height)
    
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
                print(f"↑ Jump to animation {self.current_animation_index + 1}/{len(self.animation_checkpoints)}")
                self.restore_state(checkpoint[2])
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
                print(f"↓ Jump to animation {self.current_animation_index + 1}/{len(self.animation_checkpoints)}")
                self.restore_state(checkpoint[2])
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
                    print(f"← Reverse to animation {self.current_animation_index + 1}/{len(self.animation_checkpoints)}")
                    self.restore_state(prev_checkpoint[2])
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
            
            if hasattr(self, '_file_watcher') and self._file_watcher and hasattr(self, '_scene_filepath'):
                # We need to extract and run the code for the next animation
                if self.current_animation_index < len(self.animation_checkpoints) - 1:
                    # Set flag to prevent re-entry
                    self._processing_key = True
                    
                    next_index = self.current_animation_index + 1
                    next_checkpoint = self.animation_checkpoints[next_index]
                    
                    # Get the line numbers
                    current_line = self.animation_checkpoints[self.current_animation_index][1] if self.current_animation_index >= 0 else 0
                    next_line = next_checkpoint[1]
                    
                    print(f"→ Playing animation {next_index + 1}/{len(self.animation_checkpoints)}")
                    
                    # Read the file and extract the code between checkpoints
                    try:
                        with open(self._scene_filepath, 'r') as f:
                            lines = f.readlines()
                        
                        # Extract code between current and next checkpoint
                        code_lines = []
                        in_construct = False
                        base_indent = None
                        
                        for i, line in enumerate(lines):
                            line_no = i + 1
                            
                            if 'def construct(self):' in line:
                                in_construct = True
                                base_indent = len(line) - len(line.lstrip())
                                continue
                            
                            if in_construct and current_line < line_no <= next_line:
                                if line.strip() and 'interactive_embed' not in line:
                                    # Remove the base indentation
                                    dedented = line[base_indent + 4:]  # +4 for method body indent
                                    code_lines.append(dedented)
                        
                        code_to_run = ''.join(code_lines)
                        
                        # Execute the animation code
                        self._navigating_animations = True  # Prevent checkpoint creation
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
                            
                            # Only update index if we completed successfully
                            self.current_animation_index = next_index
                        finally:
                            self._navigating_animations = False  # Re-enable checkpoint creation
                        
                    except Exception as e:
                        print(f"Error playing animation: {e}")
                        
                        # If we get a NameError, try rebuilding the construct namespace
                        if "name" in str(e) and "is not defined" in str(e):
                            print("Rebuilding namespace from current file...")
                            try:
                                # Read current file and extract full construct body
                                with open(self._scene_filepath, 'r') as f:
                                    current_content = f.readlines()
                                
                                # Get all code up to the current line
                                setup_code = self._extract_code_up_to_line(next_line, current_content)
                                
                                # Execute setup code to define variables
                                namespace = self._construct_namespace.copy() if hasattr(self, '_construct_namespace') else {}
                                exec("from manim import *", namespace)
                                namespace['self'] = self
                                exec(setup_code, namespace)
                                
                                # Now try the animation code again
                                exec(code_to_run, namespace)
                                self.current_animation_index = next_index
                                return
                            except Exception as e2:
                                print(f"Still failed after namespace rebuild: {e2}")
                        
                        # Fall back to jump
                        self.current_animation_index = next_index
                        self.restore_state(next_checkpoint[2])
                        self.update_frame(dt=0, force_draw=True)
                    finally:
                        # Clear the flag
                        self._processing_key = False
                else:
                    print("Already at last animation")
            else:
                # Fallback to jumping if we can't play animations
                if self.current_animation_index < len(self.animation_checkpoints) - 1:
                    self.current_animation_index += 1
                    checkpoint = self.animation_checkpoints[self.current_animation_index]
                    print(f"→ Jump to animation {self.current_animation_index + 1}/{len(self.animation_checkpoints)}")
                    self.restore_state(checkpoint[2])
                    self.update_frame(dt=0, force_draw=True)
                else:
                    print("Already at last animation")
    
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
    
    
    
    def jump_to_animation(self, index):
        """Jump instantly to a specific animation checkpoint."""
        if index < 0 or index >= len(self.animation_checkpoints):
            print(f"Invalid index. Available checkpoints: 0-{len(self.animation_checkpoints)-1}")
            return
            
        checkpoint = self.animation_checkpoints[index]
        print(f"Jumping to animation #{index + 1}")
        
        # Restore the state
        self.restore_state(checkpoint[2])
        self.current_animation_index = index
        
        # Update frame
        self.update_frame(force_draw=True)
    
    def list_checkpoints(self):
        """List all available animation checkpoints."""
        print(f"\nAvailable checkpoints ({len(self.animation_checkpoints)} total):")
        for i, (idx, line_no, _) in enumerate(self.animation_checkpoints):
            print(f"  {i}: Animation at line {line_no}")
        print(f"\nUse jump_to(index) to jump to any checkpoint.")
    
    def play(self, *animations, **kwargs):
        """Play animations with checkpoint support."""
        # Don't save checkpoints if we're navigating with arrow keys
        if hasattr(self, '_navigating_animations') and self._navigating_animations:
            return super().play(*animations, **kwargs)
        
        # Get the line number where this play was called
        frame = inspect.currentframe().f_back
        line_no = frame.f_lineno
        
        # Play the animation first
        result = super().play(*animations, **kwargs)
        
        # Save checkpoint AFTER animation completes
        self.current_animation_index += 1
        state = self.get_state()
        self.animation_checkpoints.append((self.current_animation_index, line_no, state))
        
        # Keep only last 50 checkpoints to avoid memory issues
        if len(self.animation_checkpoints) > 50:
            self.animation_checkpoints.pop(0)
            
        return result
    
    def wait(self, duration=1.0, stop_condition=None, frozen_frame=None):
        """Wait with checkpoint support."""
        # Don't save checkpoints if we're navigating with arrow keys
        if hasattr(self, '_navigating_animations') and self._navigating_animations:
            return super().wait(duration, stop_condition, frozen_frame)
            
        # Get the line number
        frame = inspect.currentframe().f_back
        line_no = frame.f_lineno
        
        # Execute the wait first
        result = super().wait(duration, stop_condition, frozen_frame)
        
        # Save checkpoint AFTER wait completes
        self.current_animation_index += 1
        state = self.get_state()
        self.animation_checkpoints.append((self.current_animation_index, line_no, state))
        
        # Keep only last 50 checkpoints
        if len(self.animation_checkpoints) > 50:
            self.animation_checkpoints.pop(0)
            
        return result
    
    
    def tear_down(self):
        """Clean up file watcher on scene end."""
        if hasattr(self, '_file_watcher') and self._file_watcher:
            self._file_watcher.stop()
        super().tear_down()


class ThreeDScene(GLThreeDScene):
    """CE-compatible ThreeDScene using GL backend."""
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Add CE compatibility methods
        self.renderer = self
    
    # Inherit CE compatibility methods from Scene
    add = Scene.add
    remove = Scene.remove
    play = Scene.play
    wait = Scene.wait
    bring_to_front = Scene.bring_to_front
    bring_to_back = Scene.bring_to_back
    clear = Scene.clear
    on_key_press = Scene.on_key_press
    checkpoint_paste = Scene.checkpoint_paste
    clear_checkpoints = Scene.clear_checkpoints
    
    def set_camera_orientation(self, phi=None, theta=None, gamma=None, **kwargs):
        """CE compatibility wrapper."""
        if phi is not None:
            kwargs['phi'] = phi
        if theta is not None:
            kwargs['theta'] = theta
        if gamma is not None:
            kwargs['gamma'] = gamma
            
        super().set_camera_orientation(**kwargs)
        return self
    
    def move_camera(self, phi=None, theta=None, gamma=None, **kwargs):
        """CE compatibility wrapper."""
        if phi is not None:
            kwargs['phi'] = phi
        if theta is not None:
            kwargs['theta'] = theta  
        if gamma is not None:
            kwargs['gamma'] = gamma
            
        super().move_camera(**kwargs)
        return self


# Alias for CE compatibility
SpecialThreeDScene = ThreeDScene