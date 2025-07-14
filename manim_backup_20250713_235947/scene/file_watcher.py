"""
Simple file watcher for auto-reloading scenes.
"""

import os
import time
import threading
import ast
from pathlib import Path


class SimpleFileWatcher:
    """Watches a file and executes a callback when it changes."""
    
    def __init__(self, filepath, callback, check_interval=1.0):
        self.filepath = Path(filepath)
        self.callback = callback
        self.check_interval = check_interval
        self.last_modified = self.filepath.stat().st_mtime
        self.running = False
        self.thread = None
        
    def start(self):
        """Start watching the file."""
        if self.running:
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._watch_loop, daemon=True)
        self.thread.start()
        print(f"Watching for changes in: {self.filepath.name}")
        
    def stop(self):
        """Stop watching the file."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
            
    def _watch_loop(self):
        """Main watch loop that runs in a separate thread."""
        while self.running:
            try:
                current_mtime = self.filepath.stat().st_mtime
                if current_mtime > self.last_modified:
                    print(f"\nFile changed: {self.filepath.name}")
                    self.last_modified = current_mtime
                    self.callback()
            except Exception as e:
                print(f"Error watching file: {e}")
                
            time.sleep(self.check_interval)


class AnimationTracker:
    """Tracks animation calls in the source code."""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.animations = []  # List of (line_no, code_snippet)
        
    def analyze_file(self):
        """Parse the file and find all animation calls."""
        self.animations.clear()
        
        try:
            with open(self.filepath, 'r') as f:
                content = f.read()
                
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Check if this is a play() or wait() call
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr in ['play', 'wait', 'add', 'remove']:
                            self.animations.append((node.lineno, node.func.attr))
                            
        except Exception as e:
            print(f"Error analyzing file: {e}")
            
    def find_changed_animation_index(self, error_line=None):
        """Find which animation index corresponds to a line number."""
        if error_line:
            # Find the animation that contains this line
            for i, (line_no, _) in enumerate(self.animations):
                if line_no >= error_line:
                    return max(0, i - 1)  # Return the animation before the error
        return len(self.animations) - 1