"""File watching functionality for automatic scene reloading."""

import difflib
import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)
# Set to WARNING to suppress INFO and DEBUG messages
logger.setLevel(logging.WARNING)



class CodeDiffer:
    """Handles diff operations between code versions."""
    
    @staticmethod
    def find_changed_line_ranges(old_content: str, new_content: str) -> List[Tuple[int, int]]:
        """Find ranges of changed lines between two versions of code.
        
        Returns a list of (start_line, end_line) tuples for changed regions.
        Line numbers are 1-based.
        """
        old_lines = old_content.splitlines()
        new_lines = new_content.splitlines()
        
        # Use a simpler line-by-line comparison
        changed_lines = []
        max_lines = max(len(old_lines), len(new_lines))
        
        for i in range(max_lines):
            old_line = old_lines[i] if i < len(old_lines) else None
            new_line = new_lines[i] if i < len(new_lines) else None
            
            if old_line != new_line:
                changed_lines.append(i + 1)  # 1-based line numbers
        
        # Group consecutive changed lines into ranges
        if not changed_lines:
            return []
        
        ranges = []
        start = changed_lines[0]
        end = changed_lines[0]
        
        for line_num in changed_lines[1:]:
            if line_num == end + 1:
                end = line_num
            else:
                ranges.append((start, end))
                start = line_num
                end = line_num
        
        ranges.append((start, end))
        return ranges
    
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
                        
                        # Debug: Show actual diff
                        old_lines = self._last_content.splitlines()
                        new_lines = new_content.splitlines()
                        for i, (old, new) in enumerate(zip(old_lines, new_lines), 1):
                            if old != new:
                                logger.debug(f"[FileWatcher] Line {i} changed: '{old}' -> '{new}'")
                        
                        # Get changed ranges for logging
                        changed_ranges = CodeDiffer.find_changed_line_ranges(self._last_content, new_content)
                        logger.debug(f"[FileWatcher] Changed ranges: {changed_ranges}")
                        
                        # Notify callback with change information
                        logger.info(f"[FileWatcher] Calling callback with change info")
                        self.callback({
                            'earliest_changed_line': earliest_change,
                            'new_content': new_content,
                            'changed_ranges': changed_ranges
                        })
                        
                        # Update our records
                        self._last_content = new_content
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
        logger.info(f"[FileWatcher] Starting file watcher for {self.filepath}")
        self.watcher = SimpleFileWatcher(str(self.filepath), callback, self.check_interval)
        self.watcher.start()
    
    def stop(self):
        """Stop watching the file."""
        if self.watcher:
            self.watcher.stop()
            self.watcher = None