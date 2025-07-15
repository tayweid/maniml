"""File watching functionality for automatic scene reloading."""

import ast
import difflib
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)
# Set to DEBUG for testing
logger.setLevel(logging.DEBUG)


class AnimationTracker:
    """Tracks animation calls in a Python file using AST parsing."""
    
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.animation_lines: List[int] = []
        self.animation_methods = {'play', 'wait', 'add', 'remove'}
        self._parse_file()
    
    def _parse_file(self):
        """Parse the file and find all animation method calls."""
        try:
            content = self.filepath.read_text()
            tree = ast.parse(content)
            
            class AnimationVisitor(ast.NodeVisitor):
                def __init__(self, tracker):
                    self.tracker = tracker
                
                def visit_Call(self, node):
                    # Check for self.play(), self.wait(), etc.
                    if (isinstance(node.func, ast.Attribute) and
                        isinstance(node.func.value, ast.Name) and
                        node.func.value.id == 'self' and
                        node.func.attr in self.tracker.animation_methods):
                        self.tracker.animation_lines.append(node.lineno)
                    self.generic_visit(node)
            
            visitor = AnimationVisitor(self)
            visitor.visit(tree)
            self.animation_lines.sort()
            logger.debug(f"[AnimationTracker] Found {len(self.animation_lines)} animations at lines: {self.animation_lines}")
            
        except Exception as e:
            logger.warning(f"[AnimationTracker] Failed to parse file {self.filepath}: {e}")
    
    def get_animation_index_for_line(self, line_number: int) -> Optional[int]:
        """Get the animation index for a given line number.
        
        Returns the index of the last animation before the given line,
        or None if the line is before any animations.
        """
        for i, anim_line in enumerate(self.animation_lines):
            if anim_line >= line_number:
                return i - 1 if i > 0 else None
        return len(self.animation_lines) - 1 if self.animation_lines else None


class CodeDiffer:
    """Handles diff operations between code versions."""
    
    @staticmethod
    def find_changed_line_ranges(old_content: str, new_content: str) -> List[Tuple[int, int]]:
        """Find ranges of changed lines between two versions of code.
        
        Returns a list of (start_line, end_line) tuples for changed regions.
        Line numbers are 1-based.
        """
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        
        differ = difflib.unified_diff(old_lines, new_lines, lineterm='')
        
        changed_ranges = []
        current_range_start = None
        
        # Parse unified diff output
        for i, line in enumerate(differ):
            if line.startswith('@@'):
                # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
                parts = line.split()
                if len(parts) >= 3:
                    new_range = parts[2]  # Format: +new_start,new_count
                    if ',' in new_range:
                        start, count = new_range[1:].split(',')
                        start_line = int(start)
                        end_line = start_line + int(count) - 1
                    else:
                        start_line = int(new_range[1:])
                        end_line = start_line
                    
                    changed_ranges.append((start_line, end_line))
        
        return changed_ranges
    
    @staticmethod
    def get_earliest_changed_line(old_content: str, new_content: str) -> Optional[int]:
        """Get the earliest (smallest) line number that changed."""
        changed_ranges = CodeDiffer.find_changed_line_ranges(old_content, new_content)
        if changed_ranges:
            return min(start for start, _ in changed_ranges)
        return None


class SimpleFileWatcher:
    """Simple polling-based file watcher."""
    
    def __init__(self, filepath: str, callback: Callable[[Dict], None], check_interval: float = 1.0):
        self.filepath = Path(filepath).resolve()
        self.callback = callback
        self.check_interval = check_interval
        self._stop_event = threading.Event()
        self._thread = None
        self._last_mtime = None
        self._last_content = self._read_file()
        self.animation_tracker = AnimationTracker(str(self.filepath))
        
    def _read_file(self) -> str:
        """Read the current file content."""
        try:
            return self.filepath.read_text()
        except Exception as e:
            logger.error(f"Failed to read file {self.filepath}: {e}")
            return ""
        
    def _watch_loop(self):
        """Main watching loop."""
        logger.debug(f"[FileWatcher] Starting watch loop for {self.filepath}")
        while not self._stop_event.is_set():
            try:
                current_mtime = self.filepath.stat().st_mtime
                
                if self._last_mtime is None:
                    self._last_mtime = current_mtime
                    logger.debug(f"[FileWatcher] Initial mtime: {self._last_mtime}")
                elif current_mtime != self._last_mtime:
                    logger.info(f"[FileWatcher] File changed! Old mtime: {self._last_mtime}, New mtime: {current_mtime}")
                    self._last_mtime = current_mtime
                    
                    # Read new content and check for changes
                    new_content = self._read_file()
                    logger.debug(f"[FileWatcher] Read {len(new_content)} characters from file")
                    
                    # Find what changed
                    earliest_change = CodeDiffer.get_earliest_changed_line(self._last_content, new_content)
                    
                    if earliest_change is not None:
                        logger.info(f"[FileWatcher] Earliest change at line {earliest_change}")
                        
                        # Find the last animation before the change
                        safe_animation_index = self.animation_tracker.get_animation_index_for_line(earliest_change)
                        logger.info(f"[FileWatcher] Safe animation index: {safe_animation_index}")
                        
                        # Get changed ranges for logging
                        changed_ranges = CodeDiffer.find_changed_line_ranges(self._last_content, new_content)
                        logger.debug(f"[FileWatcher] Changed ranges: {changed_ranges}")
                        
                        # Notify callback with change information
                        logger.info(f"[FileWatcher] Calling callback with change info")
                        self.callback({
                            'earliest_changed_line': earliest_change,
                            'safe_animation_index': safe_animation_index,
                            'new_content': new_content,
                            'changed_ranges': changed_ranges
                        })
                        
                        # Update our records
                        self._last_content = new_content
                        self.animation_tracker = AnimationTracker(str(self.filepath))
                    else:
                        logger.debug(f"[FileWatcher] File changed but no line changes detected (maybe just whitespace?)")
                    
            except Exception as e:
                logger.error(f"[FileWatcher] Error in file watcher: {e}", exc_info=True)
            
            self._stop_event.wait(self.check_interval)
    
    def start(self):
        """Start watching."""
        self._thread = threading.Thread(target=self._watch_loop, daemon=True)
        self._thread.start()
        logger.info(f"[FileWatcher] Started watching file: {self.filepath}")
        logger.debug(f"[FileWatcher] Thread started: {self._thread.is_alive()}")
    
    def stop(self):
        """Stop watching."""
        self._stop_event.set()
        if self._thread:
            self._thread.join()
        logger.info(f"Stopped watching file: {self.filepath}")


# Main FileWatcher class that provides the primary interface
class FileWatcher:
    """Main interface for file watching functionality."""
    
    def __init__(self, filepath: str, check_interval: float = 1.0):
        self.filepath = Path(filepath).resolve()
        self.check_interval = check_interval
        self.watcher: Optional[SimpleFileWatcher] = None
        
    def start(self, callback: Callable[[Dict], None]):
        """Start watching the file."""
        logger.info(f"[FileWatcher Main] Starting file watcher for {self.filepath}")
        self.watcher = SimpleFileWatcher(str(self.filepath), callback, self.check_interval)
        self.watcher.start()
    
    def stop(self):
        """Stop watching the file."""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None