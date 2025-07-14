#!/usr/bin/env python
"""Debug file watcher."""

import sys
import os

# Add maniml to path
sys.path.insert(0, os.path.dirname(__file__))

from manim import *

class WatcherDebug(Scene):
    def construct(self):
        print("\n=== WatcherDebug Starting ===")
        print(f"Scene filepath: {getattr(self, '_scene_filepath', 'NOT SET')}")
        print(f"Auto reload enabled: {getattr(self, 'auto_reload_enabled', 'NOT SET')}")
        print(f"File watcher: {getattr(self, 'file_watcher', 'NOT SET')}")
        print(f"Has _file_watcher: {hasattr(self, '_file_watcher')}")
        if hasattr(self, '_file_watcher'):
            print(f"File watcher object: {self._file_watcher}")
        
        # Animation 1
        circle = Circle(color=BLUE, radius=1)
        self.play(Create(circle))
        
        # Keep it running to test file changes
        print("\nScene setup complete. Modify this file to test auto-reload.")
        print("Add a comment on the next line to trigger a change.")
        # CHANGE ME
        
        # Wait for a bit to allow testing
        self.wait(10)