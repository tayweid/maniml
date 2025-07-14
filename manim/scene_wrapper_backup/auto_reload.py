"""
Auto-reload system for maniml that watches for file changes
and reloads from the last unchanged animation.
"""

import os
import time
import threading
import ast
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Set, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


class CodeAnalyzer:
    """Analyzes Python code to track animation calls and their locations."""
    
    def __init__(self):
        self.animations: List[Tuple[int, int, str]] = []  # (start_line, end_line, code_hash)
        
    def analyze_file(self, filepath: str) -> None:
        """Parse file and extract animation calls with their line numbers."""
        self.animations.clear()
        
        try:
            with open(filepath, 'r') as f:
                content = f.read()
                
            tree = ast.parse(content)
            
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    # Check if this is a play() or wait() call
                    if (isinstance(node.func, ast.Attribute) and 
                        node.func.attr in ['play', 'wait', 'add', 'remove']):
                        
                        # Get the line range for this call
                        start_line = node.lineno
                        end_line = node.end_lineno or start_line
                        
                        # Extract the code for this animation
                        lines = content.split('\n')
                        animation_code = '\n'.join(lines[start_line-1:end_line])
                        code_hash = hashlib.md5(animation_code.encode()).hexdigest()
                        
                        self.animations.append((start_line, end_line, code_hash))
                        
        except Exception as e:
            print(f"Error analyzing file: {e}")
            
    def find_first_changed_animation(self, other: 'CodeAnalyzer') -> Optional[int]:
        """
        Compare with another analyzer to find the index of the first changed animation.
        Returns the index of the first animation that differs, or None if no changes.
        """
        # Compare animations
        for i, (start1, end1, hash1) in enumerate(self.animations):
            if i >= len(other.animations):
                # New animations added
                return i
                
            start2, end2, hash2 = other.animations[i]
            
            if hash1 != hash2:
                # This animation changed
                return i
                
        # Check if animations were removed
        if len(self.animations) < len(other.animations):
            return len(self.animations)
            
        return None


class SceneFileWatcher(FileSystemEventHandler):
    """Watches the scene file for changes and triggers reloads."""
    
    def __init__(self, scene, filepath: str):
        self.scene = scene
        self.filepath = Path(filepath).resolve()
        self.analyzer = CodeAnalyzer()
        self.analyzer.analyze_file(str(self.filepath))
        
        # Track animation checkpoints
        self.checkpoints: Dict[int, Any] = {}  # animation_index -> scene_state
        self.current_animation_index = -1
        
        # Setup file watching
        self.observer = Observer()
        self.observer.schedule(self, str(self.filepath.parent), recursive=False)
        self.observer.start()
        
        # Flag to prevent recursive reloads
        self.is_reloading = False
        
    def on_modified(self, event):
        """Handle file modification events."""
        if isinstance(event, FileModifiedEvent):
            if Path(event.src_path).resolve() == self.filepath:
                if not self.is_reloading:
                    self.handle_file_change()
                    
    def handle_file_change(self):
        """Analyze changes and reload from appropriate checkpoint."""
        print(f"\nFile changed: {self.filepath.name}")
        
        # Create new analyzer for the modified file
        new_analyzer = CodeAnalyzer()
        new_analyzer.analyze_file(str(self.filepath))
        
        # Find the first changed animation
        changed_index = self.analyzer.find_first_changed_animation(new_analyzer)
        
        if changed_index is not None:
            print(f"First change detected at animation #{changed_index}")
            
            # Find the checkpoint to reload from
            reload_index = changed_index - 1
            
            if reload_index >= 0 and reload_index in self.checkpoints:
                print(f"Reloading from checkpoint before animation #{reload_index + 1}")
                self.is_reloading = True
                
                # Restore the scene state
                self.scene.restore_state(self.checkpoints[reload_index])
                self.current_animation_index = reload_index
                
                # Update analyzer
                self.analyzer = new_analyzer
                
                # Trigger scene reload
                self.reload_from_current_position()
                
                self.is_reloading = False
            else:
                print("No suitable checkpoint found, full reload required")
                self.request_full_reload()
        else:
            print("No animation changes detected")
            
    def save_checkpoint(self, animation_index: int):
        """Save a checkpoint after an animation completes."""
        if animation_index != self.current_animation_index:
            self.current_animation_index = animation_index
            self.checkpoints[animation_index] = self.scene.get_state()
            
    def reload_from_current_position(self):
        """Request the scene to reload from current position."""
        # Set a flag that the scene can check
        if hasattr(self.scene, 'request_reload'):
            self.scene.request_reload = True
            self.scene.reload_from_index = self.current_animation_index + 1
            
    def request_full_reload(self):
        """Request a full scene reload."""
        if hasattr(self.scene, 'request_reload'):
            self.scene.request_reload = True
            self.scene.reload_from_index = 0
            
    def stop(self):
        """Stop watching the file."""
        self.observer.stop()
        self.observer.join()


class AutoReloadMixin:
    """Mixin to add auto-reload capabilities to a Scene."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_watcher = None
        self.request_reload = False
        self.reload_from_index = 0
        self._play_count = 0
        
    def enable_auto_reload(self):
        """Enable automatic reloading when the scene file changes."""
        # Get the file path of the scene
        import inspect
        frame = inspect.currentframe()
        while frame:
            if 'self' in frame.f_locals and isinstance(frame.f_locals['self'], self.__class__):
                filepath = frame.f_globals.get('__file__')
                if filepath:
                    print(f"Watching file: {filepath}")
                    self.file_watcher = SceneFileWatcher(self, filepath)
                    break
            frame = frame.f_back
            
    def play(self, *animations, **kwargs):
        """Override play to track checkpoints."""
        # Check for reload request before playing
        if self.request_reload:
            if self._play_count < self.reload_from_index:
                # Skip this animation
                self._play_count += 1
                return self
            else:
                # We've reached the reload point
                self.request_reload = False
                
        # Call parent play
        result = super().play(*animations, **kwargs)
        
        # Save checkpoint after animation
        if self.file_watcher:
            self.file_watcher.save_checkpoint(self._play_count)
            
        self._play_count += 1
        return result
        
    def wait(self, *args, **kwargs):
        """Override wait to track checkpoints."""
        # Similar logic as play
        if self.request_reload:
            if self._play_count < self.reload_from_index:
                self._play_count += 1
                return self
            else:
                self.request_reload = False
                
        result = super().wait(*args, **kwargs)
        
        if self.file_watcher:
            self.file_watcher.save_checkpoint(self._play_count)
            
        self._play_count += 1
        return result
        
    def tear_down(self):
        """Stop file watching on tear down."""
        if self.file_watcher:
            self.file_watcher.stop()
        super().tear_down()