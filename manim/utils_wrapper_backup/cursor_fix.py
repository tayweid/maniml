"""
Fix for the spinning cursor issue in ManimGL/maniml.

The spinning cursor is caused by the window event loop not processing
events properly during waits and animations.
"""

import threading
import time


def fix_window_cursor(scene_class):
    """
    Decorator to fix the spinning cursor issue.
    
    Works by ensuring window events are processed regularly.
    """
    original_wait = scene_class.wait
    original_play = scene_class.play
    
    def enhanced_wait(self, duration=1.0, stop_condition=None, frozen_frame=None):
        """Wait that processes window events."""
        # Run original wait in a way that allows event processing
        start_time = time.time()
        
        # Split wait into small chunks to process events
        chunk_duration = 0.05  # 50ms chunks
        
        while time.time() - start_time < duration:
            # Wait for a small chunk
            remaining = duration - (time.time() - start_time)
            chunk = min(chunk_duration, remaining)
            
            if chunk > 0:
                # Call parent's wait for the chunk
                original_wait(self, chunk, stop_condition=stop_condition, frozen_frame=frozen_frame)
            
            # Process window events if window exists
            if hasattr(self, 'window') and self.window:
                try:
                    # Ensure events are processed
                    if hasattr(self.window, '_window'):
                        # Pyglet window
                        window = self.window._window
                        if hasattr(window, 'dispatch_events'):
                            window.dispatch_events()
                        # Also try to update display
                        if hasattr(window, 'flip'):
                            window.flip()
                except:
                    pass
            
            # Check stop condition
            if stop_condition and stop_condition():
                break
                
        return self
    
    def enhanced_play(self, *animations, **kwargs):
        """Play that ensures cursor stays normal."""
        result = original_play(self, *animations, **kwargs)
        
        # Process events after animation
        if hasattr(self, 'window') and self.window:
            try:
                if hasattr(self.window, '_window'):
                    self.window._window.dispatch_events()
            except:
                pass
                
        return result
    
    # Replace methods
    scene_class.wait = enhanced_wait
    scene_class.play = enhanced_play
    
    return scene_class


class CursorFixMixin:
    """
    Mixin class that can be added to any Scene to fix cursor issues.
    
    Usage:
        class MyScene(CursorFixMixin, Scene):
            def construct(self):
                # Your scene code
                pass
    """
    
    def wait(self, duration=1.0, stop_condition=None, frozen_frame=None):
        """Enhanced wait with event processing."""
        # Use the fixed wait implementation
        scene_with_fix = fix_window_cursor(self.__class__)
        return scene_with_fix.wait(self, duration, stop_condition, frozen_frame)
    
    def play(self, *animations, **kwargs):
        """Enhanced play with event processing."""
        scene_with_fix = fix_window_cursor(self.__class__)
        return scene_with_fix.play(self, *animations, **kwargs)