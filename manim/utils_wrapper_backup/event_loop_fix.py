"""
Event loop fix for ManimGL/maniml to prevent spinning cursor.

The key insight from ManimCE's GL mode is that the pyglet event loop
needs to run in a separate thread to keep the window responsive.
"""

import threading
import time
import atexit


class EventLoopManager:
    """Manages a separate thread for the pyglet event loop."""
    
    _instance = None
    _event_loop_thread = None
    _event_loop_running = False
    _initialized = False
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def ensure_event_loop(self):
        """Ensure the pyglet event loop is running in a separate thread."""
        if not self._initialized:
            self._initialized = True
            self._start_event_loop()
            # Register cleanup
            atexit.register(self._stop_event_loop)
    
    def _start_event_loop(self):
        """Start the pyglet event loop in a separate thread."""
        if not self._event_loop_running:
            self._event_loop_running = True
            self._event_loop_thread = threading.Thread(
                target=self._run_event_loop,
                daemon=True,
                name="PygletEventLoop"
            )
            self._event_loop_thread.start()
            # Give it a moment to start
            time.sleep(0.1)
    
    def _run_event_loop(self):
        """Run the pyglet event loop."""
        try:
            import pyglet
            # This will run until pyglet.app.exit() is called
            pyglet.app.run()
        except Exception:
            pass  # Event loop stopped
        finally:
            self._event_loop_running = False
    
    def _stop_event_loop(self):
        """Stop the pyglet event loop."""
        if self._event_loop_running:
            try:
                import pyglet
                pyglet.app.exit()
            except:
                pass
            self._event_loop_running = False


# Global instance
_event_loop_manager = EventLoopManager()


def ensure_event_loop():
    """Ensure the pyglet event loop is running."""
    _event_loop_manager.ensure_event_loop()


def start_event_loop_for_scene(scene):
    """
    Start event loop for a scene if it has a window.
    
    This should be called when a scene starts running.
    """
    if hasattr(scene, 'window') and scene.window:
        ensure_event_loop()
        # Also ensure window events are being processed
        if hasattr(scene.window, '_window'):
            # Schedule regular event dispatching
            import pyglet
            def dispatch_events(dt):
                if hasattr(scene.window, '_window') and scene.window._window:
                    try:
                        scene.window._window.dispatch_events()
                    except:
                        pass
            
            # Schedule event dispatch every 50ms
            pyglet.clock.schedule_interval(dispatch_events, 0.05)