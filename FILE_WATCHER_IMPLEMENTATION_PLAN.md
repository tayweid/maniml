# File Watcher Implementation Plan for maniml

## Executive Summary

This document outlines the plan to implement file watching functionality in the main `maniml` codebase, based on the working implementation in `maniml_local`. The goal is to enable automatic animation updates when the source file is edited and saved.

## Current State Analysis

### maniml_local (Working Implementation)
- Uses `SimpleFileWatcher` with polling-based file monitoring
- Integrates with checkpoint system via `on_edit()` method
- Handles line-level change detection using difflib
- Successfully restores to safe checkpoints and re-executes affected code

### maniml backup (Non-working Implementation)
- Has both simple and advanced implementations
- Advanced version uses watchdog library
- Preserves namespace in checkpoints (similar to current maniml)
- Implementation exists but doesn't work properly

### maniml (Current State)
- Has robust checkpoint system with namespace preservation
- No file watcher implementation
- `--autoreload` flag only affects IPython embed mode
- Already has most necessary infrastructure for integration

## Implementation Strategy

### Phase 1: Port SimpleFileWatcher
1. **Copy `file_watcher.py` from maniml_local**
   - Brings in `SimpleFileWatcher` class (polling-based)
   - Includes `AnimationTracker` for AST parsing
   - No external dependencies needed

2. **Integration Points in `scene.py`**
   - Add `_file_watcher` attribute
   - Add `_file_changed_flag` for thread-safe communication
   - Add `auto_reload_enabled` configuration option

### Phase 2: Adapt Change Detection Logic
1. **Port `on_edit()` method**
   - Adapt to maniml's checkpoint structure
   - Use existing `animation_checkpoints` list
   - Leverage existing `restore_checkpoint()` method

2. **Modify for maniml's checkpoint format**
   ```python
   # maniml checkpoint structure
   {
       'index': int,
       'line_number': int,
       'state': SceneState,
       'namespace': dict
   }
   ```

### Phase 3: Integration with Existing Navigation

1. **Enhance `interact()` method**
   ```python
   def interact(self):
       if self.auto_reload_enabled:
           self._setup_file_watcher()
       # ... existing code ...
   ```

2. **Add file change handling to render loop**
   ```python
   # In the main interaction loop
   if self._file_changed_flag:
       self._file_changed_flag = False
       self._handle_file_change()
   ```

### Phase 4: Key Implementation Details

1. **File Change Handler**
   ```python
   def _handle_file_change(self):
       try:
           new_content = self._read_file_content()
           if not self._check_syntax(new_content):
               return
           self.on_edit(new_content)
       except Exception as e:
           logger.error(f"Error handling file change: {e}")
   ```

2. **Checkpoint Restoration Logic**
   ```python
   def on_edit(self, new_content):
       # Find changed lines
       changed_lines = self._find_changed_line_ranges(self.old_content, new_content)
       if not changed_lines:
           return
       
       # Find earliest change
       earliest_change = min(changed_lines)
       
       # Find last safe checkpoint
       safe_checkpoint_idx = self._find_safe_checkpoint(earliest_change)
       
       # Truncate future checkpoints
       if safe_checkpoint_idx >= 0:
           self.animation_checkpoints = self.animation_checkpoints[:safe_checkpoint_idx + 1]
           self.restore_checkpoint(safe_checkpoint_idx)
       else:
           # Clear everything and restart
           self.clear()
           self.animation_checkpoints = []
           self.current_animation_index = 0
       
       # Re-execute from checkpoint
       self._reexecute_from_checkpoint(safe_checkpoint_idx)
   ```

3. **Line Number Tracking Enhancement**
   - Leverage existing `_get_caller_line_number()` method
   - Ensure accurate line number recording for each checkpoint

## Compatibility Considerations

1. **Preserve Existing Behavior**
   - File watching should be opt-in (disabled by default initially)
   - Existing checkpoint navigation must continue working
   - No breaking changes to public API

2. **Thread Safety**
   - Use simple flag mechanism like maniml_local
   - Avoid complex synchronization
   - Handle file operations in main thread

3. **Error Handling**
   - Graceful handling of syntax errors
   - Clear error messages for debugging
   - Fallback to manual restart if needed

## Testing Strategy

1. **Unit Tests**
   - Test file watcher detection
   - Test line change detection
   - Test checkpoint truncation logic

2. **Integration Tests**
   - Test full reload flow
   - Test interaction with arrow key navigation
   - Test edge cases (edits before first animation, etc.)

3. **Manual Testing Scenarios**
   - Edit and save while animation is running
   - Multiple rapid edits
   - Syntax errors and recovery
   - Large file changes

## Implementation Timeline

1. **Week 1**: Port SimpleFileWatcher and basic integration
2. **Week 2**: Adapt change detection and checkpoint handling
3. **Week 3**: Testing and edge case handling
4. **Week 4**: Documentation and polish

## Configuration Options

Add to maniml configuration:
```python
# In config
auto_reload_enabled = False  # Default off for stability
auto_reload_check_interval = 1.0  # Seconds between file checks
auto_reload_max_checkpoints = 50  # Limit memory usage
```

## Potential Enhancements (Future)

1. **Watchdog Integration**: Replace polling with filesystem events
2. **Partial Re-execution**: Only re-run affected animations
3. **Multi-file Support**: Watch imported modules
4. **Smart Diffing**: Better understanding of semantic changes
5. **Preview Mode**: Show changes without full re-execution

## Risks and Mitigations

1. **Risk**: Performance impact from polling
   - **Mitigation**: Configurable check interval, disable by default

2. **Risk**: Memory usage from checkpoints
   - **Mitigation**: Checkpoint limit, cleanup old checkpoints

3. **Risk**: Complex edge cases
   - **Mitigation**: Extensive testing, gradual rollout

4. **Risk**: Thread synchronization issues
   - **Mitigation**: Simple flag-based approach, minimize shared state

## Success Criteria

1. File changes trigger automatic reload
2. Animations resume from appropriate checkpoint
3. No regression in existing functionality
4. Performance impact < 5% when enabled
5. Clear documentation and examples

## Next Steps

1. Create feature branch for implementation
2. Port SimpleFileWatcher as first PR
3. Implement core functionality incrementally
4. Gather feedback from early testers
5. Refine based on real-world usage