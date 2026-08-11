"""
Window utilities for maniml to handle cursor and event issues.
"""

import time
import threading


class WindowEventHandler:
    """Helper class to manage window events and cursor state."""
    
    @staticmethod
    def start_event_processor(scene):
        """Start a background thread to process window events."""
        def process_events():
            while getattr(scene, '_window_active', True):
                try:
                    if hasattr(scene, 'window') and scene.window:
                        import glfw
                        if glfw._glfw:
                            glfw.poll_events()
                except:
                    pass
                time.sleep(0.1)  # Process events every 100ms
        
        # Start event processor in background
        event_thread = threading.Thread(target=process_events, daemon=True)
        event_thread.start()
        return event_thread
    
    @staticmethod 
    def ensure_normal_cursor(window):
        """Ensure the cursor is in normal state."""
        try:
            import glfw
            if glfw._glfw and window:
                # Reset cursor to normal
                glfw.set_input_mode(window.window, glfw.CURSOR, glfw.CURSOR_NORMAL)
                # Process any pending events
                glfw.poll_events()
        except:
            pass


def fix_spinning_cursor(scene_class):
    """Decorator to fix spinning cursor issue in scenes."""
    
    original_run = scene_class.run
    original_play = scene_class.play
    original_wait = scene_class.wait
    
    def new_run(self):
        """Enhanced run with cursor fix."""
        self._window_active = True
        # Start event processor
        self._event_thread = WindowEventHandler.start_event_processor(self)
        
        try:
            # Run original scene
            original_run(self)
        finally:
            # Stop event processor
            self._window_active = False
            # Ensure cursor is normal
            if hasattr(self, 'window') and self.window:
                WindowEventHandler.ensure_normal_cursor(self.window)
    
    def new_play(self, *args, **kwargs):
        """Enhanced play with event processing."""
        result = original_play(self, *args, **kwargs)
        # Quick event poll after animation
        try:
            import glfw
            if hasattr(self, 'window') and self.window and glfw._glfw:
                glfw.poll_events()
        except:
            pass
        return result
    
    def new_wait(self, *args, **kwargs):
        """Enhanced wait with event processing."""
        result = original_wait(self, *args, **kwargs)
        # Process events during wait
        try:
            import glfw
            if hasattr(self, 'window') and self.window and glfw._glfw:
                glfw.poll_events()
        except:
            pass
        return result
    
    # Replace methods
    scene_class.run = new_run
    scene_class.play = new_play
    scene_class.wait = new_wait
    
    return scene_class