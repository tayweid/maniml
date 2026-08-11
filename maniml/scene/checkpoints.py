"""Checkpoint system for maniml scenes.

Saving/restoring deep-copied (state, namespace) snapshots around each
play() call, re-executing animation units from source, and replaying
after file-watcher edits. The copy discipline lives here: state and
namespace are deep-copied *together* so variable-to-mobject references
survive (see deepcopy_namespace at the bottom).
"""
from __future__ import annotations

import inspect
import os
import traceback
from contextlib import contextmanager

from maniml.logger import log
from maniml.mobject.mobject import Mobject
from maniml.scene.file_watcher import FileWatcher
from maniml.scene.source_map import SourceMapError
from maniml.scene.source_map import build_units
from maniml.scene.source_map import next_play_unit
from maniml.scene.source_map import unit_for_line


class CheckpointMixin:
    def _create_checkpoint_zero(self, namespace: dict | None = None) -> None:
        """
        Create checkpoint 0 with the full namespace from the scene file.
        Called right before the first animation to capture all imports.
        Pass an explicit namespace (e.g. from a freshly reloaded module)
        to skip the module discovery.
        """
        import sys

        namespace = dict(namespace) if namespace else {}

        # If we have the scene filepath, use it to find the module
        if not namespace and hasattr(self, '_scene_filepath') and self._scene_filepath:
            # Find the module in sys.modules that matches our scene file
            for module_name, module in sys.modules.items():
                if hasattr(module, '__file__') and module.__file__ == self._scene_filepath:
                    namespace.update(vars(module))
                    break
        
        # If we didn't find it that way, try __main__
        if not namespace and '__main__' in sys.modules:
            main_module = sys.modules['__main__']
            if hasattr(main_module, self.__class__.__name__):
                namespace.update(vars(main_module))
        
        # Last resort: get from frame
        if not namespace:
            frame = inspect.currentframe()
            while frame:
                if frame.f_code.co_filename.endswith('.py') and 'manim' not in frame.f_code.co_filename:
                    namespace.update(frame.f_globals)
                    break
                frame = frame.f_back
        
        # Ensure we have manim imports
        if 'Circle' not in namespace:
            exec("from maniml import *", namespace)
        
        # Explicitly import constants if BLUE is missing
        if 'BLUE' not in namespace:
            import maniml
            # Get all color constants from maniml.constants
            for name in dir(maniml.constants):
                if not name.startswith('_'):
                    namespace[name] = getattr(maniml.constants, name)
        
        # Add self reference
        namespace['self'] = self
        
        # Add current (empty) state to namespace
        namespace['__checkpoint_state__'] = self.get_state()
        
        # Deep copy to create checkpoint
        checkpoint_namespace = deepcopy_namespace(namespace)
        checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')
        
        # Create checkpoint 0
        checkpoint_zero = {
            'index': 0,
            'line_number': 0,  # No specific line for initial state
            'unit_index': -1,  # Before the first animation unit
            'state': checkpoint_state,  # Empty scene state
            'namespace': checkpoint_namespace
        }
        
        self.animation_checkpoints.append(checkpoint_zero)
        self.current_animation_index = 0


    def _setup_file_watcher(self) -> None:
        """Setup the file watcher for auto-reload functionality."""
        if hasattr(self, '_scene_filepath') and self._scene_filepath:
            # log.info(f"Setting up file watcher for: {self._scene_filepath}")
            self._file_watcher = FileWatcher(self._scene_filepath)
            self._file_watcher.start(self._on_file_changed)
        else:
            log.warning("No scene filepath available, file watching disabled")
    
    def _on_file_changed(self, change_info: dict) -> None:
        """Callback when file changes are detected.

        Runs on the watcher thread: store the payload before raising the
        flag, since the main loop clears the flag and reads the payload.
        """
        log.info(f"File change detected: Line {change_info['earliest_changed_line']}")
        self._pending_change_info = change_info
        self._file_changed_flag = True

    def _handle_file_change(self) -> None:
        """Handle a file save in the main thread.

        Checkpoints are re-anchored against the freshly parsed source:
        the ones from units before the edited unit are kept (the source
        above the edit is identical, so their unit indices still hold),
        everything from the edited unit on is discarded and replayed —
        fast-forwarded with animations skipped, except the edited unit
        itself, which plays at real speed. Edits outside construct()
        (imports, constants, helpers, other methods) rebuild the whole
        scene from a freshly reloaded module.
        """
        change_info = self._pending_change_info
        if change_info is None:
            return
        self._pending_change_info = None
        earliest_change = change_info['earliest_changed_line']
        log.info(f"Handling file change at line {earliest_change}")

        self._source_units_cache = None
        units = self._get_source_units()
        if units is None:
            print("Scene file has errors; fix them and save again")
            return

        if not (units and units[0].start_line <= earliest_change <= units[-1].end_line):
            print("Change outside construct(): rebuilding scene")
            self._restart_from_source()
            return

        # First unit whose code reaches the edit; everything before it
        # is untouched source
        affected = next(u for u in units if u.end_line >= earliest_change)

        # Keep only checkpoints created by units before the affected one
        safe_idx = 0
        for checkpoint in self.animation_checkpoints[1:]:
            unit_index = checkpoint.get('unit_index')
            if unit_index is not None and unit_index < affected.index:
                safe_idx = checkpoint['index']
            else:
                break
        self.animation_checkpoints = self.animation_checkpoints[:safe_idx + 1]

        if self.current_animation_index != safe_idx:
            self.current_animation_index = safe_idx
            self.restore_state(self.animation_checkpoints[safe_idx]['state'])
            self.update_frame(dt=0, force_draw=True)
        log.info(f"Replaying from checkpoint {safe_idx} to unit {affected.index}")

        self._replay_to_unit(affected.index)

    def _replay_to_unit(self, target_unit_index: int) -> None:
        """Re-run units up to and including target_unit_index.

        Units before the target are fast-forwarded (animations skipped,
        so each costs only its state evaluation); the target unit itself
        plays at real speed.
        """
        for _ in range(10000):  # bound against non-advancing loops
            units = self._get_source_units()
            if units is None:
                return
            current = self.animation_checkpoints[self.current_animation_index]
            current_unit = current.get('unit_index')
            if current_unit is None:
                current_unit = -1
            if current_unit >= target_unit_index:
                return
            last_index = self.current_animation_index
            next_unit = next_play_unit(units, after_unit_index=current_unit)
            if next_unit is None or next_unit.index >= target_unit_index:
                # The edited unit itself (or a trailing no-play unit):
                # play at real speed and stop
                self.run_next_animation()
                return
            with self.temp_skip():
                self.run_next_animation()
            if self.current_animation_index == last_index:
                return  # no progress (error or nothing left)

    def _restart_from_source(self) -> None:
        """Reload the scene module and rebuild all checkpoints.

        Used when an edit falls outside construct(): checkpoint
        namespaces may hold stale copies of module-level objects, so
        replaying from any existing checkpoint would use the old code.
        Fast-forwards back to the unit the user was on.
        """
        if not getattr(self, '_scene_filepath', None):
            return

        previous_unit = None
        if self.animation_checkpoints:
            previous_unit = self.animation_checkpoints[self.current_animation_index].get('unit_index')

        from maniml.__main__ import load_scene_module
        try:
            module = load_scene_module(self._scene_filepath)
        except Exception as e:
            print(f"Error reloading scene file: {e}")
            traceback.print_exc()
            return

        self.animation_checkpoints = []
        self.current_animation_index = -1
        self._source_units_cache = None
        self.clear()
        self._create_checkpoint_zero(namespace=vars(module))
        self.update_frame(dt=0, force_draw=True)

        units = self._get_source_units()
        if units and previous_unit is not None and previous_unit >= 0:
            self._replay_to_unit(min(previous_unit, units[-1].index))

    # Run modes

    def _run_all_units(self) -> None:
        """Run every remaining animation unit, stopping when no progress
        is made (end of scene or an error already reported)."""
        while True:
            last_index = self.current_animation_index
            self.run_next_animation()
            if self.current_animation_index == last_index:
                break

    def _restore_checkpoint_for_display(self, index: int) -> None:
        """Put a copy of the checkpoint at `index` on screen and keep its
        namespace as the live one (for click-to-inspect). State and
        namespace are copied together so names still point at the
        on-screen objects."""
        self.current_animation_index = index
        temp = deepcopy_namespace(self.animation_checkpoints[index])
        self.restore_state(temp['state'])
        namespace = temp['namespace']
        namespace['self'] = self
        self._live_namespace = namespace

    def _find_animation_anchor(self) -> tuple[int | None, int | None]:
        """Locate the source anchor (end line and unit index) of the play()
        call currently on the stack.

        When run_next_animation execs a unit it plants
        __animation_line_number__ / __animation_unit_index__ in the exec
        namespace. Otherwise (e.g. construct() called directly) fall back
        to the deepest stack frame in the user's scene file, mapped
        through the source map.
        """
        frame = inspect.currentframe()
        while frame:
            for scope in (frame.f_locals, frame.f_globals):
                if '__animation_line_number__' in scope:
                    return (
                        scope['__animation_line_number__'],
                        scope.get('__animation_unit_index__'),
                    )
            frame = frame.f_back

        # The deepest user-file frame is the END line of a multi-line play call
        line_no = None
        for frame_info in traceback.extract_stack():
            if '/maniml/' not in frame_info.filename and frame_info.filename.endswith('.py'):
                line_no = frame_info.lineno

        unit_index = None
        if line_no is not None:
            units = self._get_source_units()
            if units:
                unit = unit_for_line(units, line_no)
                if unit is not None:
                    unit_index = unit.index
        return line_no, unit_index

    def _capture_caller_namespace(self) -> dict:
        """Copy the variables of the frame that triggered this play call:
        either a construct() frame or a unit exec'd by run_next_animation."""
        frame = inspect.currentframe()
        while frame:
            if frame.f_code.co_name == 'construct' and 'self' in frame.f_locals:
                namespace = frame.f_locals.copy()
                namespace.update(frame.f_globals)
                return namespace
            if '__animation_line_number__' in frame.f_globals:
                # A unit exec'd by run_next_animation
                namespace = frame.f_globals.copy()
                namespace.update(frame.f_locals)
                return namespace
            frame = frame.f_back

        # Fallback: the direct caller of play()
        frame = inspect.currentframe()
        while frame and frame.f_code.co_name != 'play':
            frame = frame.f_back
        if frame is not None and frame.f_back is not None:
            caller = frame.f_back
            namespace = caller.f_locals.copy()
            namespace.update(caller.f_globals)
            return namespace
        return {}

    def _save_checkpoint(self, line_no: int, unit_index: int | None, namespace: dict) -> None:
        """Deep-copy the namespace and scene state into the checkpoint at
        current_animation_index + 1, replacing any existing one there."""
        namespace = dict(namespace)
        namespace.pop('__animation_line_number__', None)
        namespace.pop('__animation_unit_index__', None)

        # Deep copy state and namespace together so references between
        # namespace variables and on-screen mobjects are preserved
        namespace['__checkpoint_state__'] = self.get_state()
        checkpoint_namespace = deepcopy_namespace(namespace)
        checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')

        self.current_animation_index += 1
        checkpoint = {
            'index': self.current_animation_index,
            'line_number': line_no,
            'unit_index': unit_index,
            'state': checkpoint_state,
            'namespace': checkpoint_namespace,
        }
        if self.current_animation_index < len(self.animation_checkpoints):
            # Re-running an existing animation: replace its checkpoint
            self.animation_checkpoints[self.current_animation_index] = checkpoint
        else:
            self.animation_checkpoints.append(checkpoint)

    def _remember_scene_filepath(self) -> None:
        """Record the user's scene file path from the stack if not yet known."""
        if getattr(self, '_scene_filepath', None):
            return
        for frame_info in traceback.extract_stack():
            filename = frame_info.filename
            if '/maniml/' not in filename and filename.endswith('.py'):
                self._scene_filepath = filename
                break

    def _get_source_units(self):
        """Parse the scene file into animation units, cached by mtime.

        Returns None (with a warning) if the file is missing, unparseable,
        or has no matching construct().
        """
        path = getattr(self, '_scene_filepath', None)
        if not path:
            return None
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            return None
        cached = self._source_units_cache
        if cached is not None and cached[0] == (path, mtime):
            return cached[1]
        try:
            with open(path) as f:
                source = f.read()
            units = build_units(source, self.__class__.__name__)
        except (OSError, SyntaxError, SourceMapError) as e:
            log.warning(f"Could not map scene source: {e}")
            return None
        self._source_units_cache = ((path, mtime), units)
        return units

    @contextmanager
    def _no_checkpoints(self):
        """Play animations without saving checkpoints (e.g. the reverse
        transition, which is display-only and not part of history)."""
        prev = getattr(self, '_suppress_checkpoints', False)
        self._suppress_checkpoints = True
        try:
            yield
        finally:
            self._suppress_checkpoints = prev

    def run_next_animation(self):
        """Run the next animation unit, re-executed from the scene source."""
        if not getattr(self, '_scene_filepath', None):
            print("No scene file path stored")
            return

        units = self._get_source_units()
        if units is None:
            print("Cannot parse scene file; fix the error and save again")
            return

        current_checkpoint = self.animation_checkpoints[self.current_animation_index]
        next_index = self.current_animation_index + 1

        unit = next_play_unit(
            units,
            after_unit_index=current_checkpoint.get('unit_index'),
            after_line=current_checkpoint['line_number'],
        )
        if unit is None:
            # Past the last play call: run any trailing statements
            # (e.g. a final self.wait()) exactly once
            tail = units[-1] if units and not units[-1].has_play else None
            current_unit = current_checkpoint.get('unit_index')
            if tail is None or (current_unit is not None and current_unit >= tail.index):
                print("Already at last animation")
                return
            unit = tail

        # Work on a deep copy so the stored checkpoint stays pristine.
        # State and namespace are copied together, preserving references
        # between namespace variables and on-screen mobjects.
        checkpoint_temporary = deepcopy_namespace(current_checkpoint)

        self.clear()
        self.restore_state(checkpoint_temporary['state'])

        namespace = checkpoint_temporary['namespace']
        namespace['self'] = self
        # Anchor for the checkpoint(s) that play() will save during exec
        namespace['__animation_line_number__'] = unit.end_line
        namespace['__animation_unit_index__'] = unit.index

        if self.skip_animations:
            print(f"⏩ Fast-forwarding animation {next_index}")
        else:
            print(f"→ Running animation {next_index}")
        try:
            code = compile(unit.source, self._scene_filepath, 'exec')
            exec(code, namespace)
        except Exception as e:
            print(f"Error running animation: {e}")
            traceback.print_exc()
            # Restore the last successfully saved checkpoint so the scene
            # isn't left in a half-executed state
            checkpoint = self.animation_checkpoints[self.current_animation_index]
            self.clear()
            self.restore_state(checkpoint['state'])
            self.update_frame(dt=0, force_draw=True)
            return

        if not unit.has_play:
            # Tail unit: no play() fired to save a checkpoint, save one
            # here so the tail doesn't re-run on the next RIGHT arrow
            self._save_checkpoint(unit.end_line, unit.index, namespace)

        # The exec namespace holds the objects now on screen; keep it
        # for click-to-inspect name lookup
        self._live_namespace = namespace

        print(f"Animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1} complete")



def _classify_value(value):
    """
    Classify a value into one of three categories:
    - 'must_copy': Mutable objects that change between animations (Mobjects, lists of Mobjects)
    - 'can_skip': Immutable or non-copyable (modules, functions, classes, primitives)
    - 'shallow_copy': Collections that might contain Mobjects but are themselves cheap to copy

    Returns: ('must_copy' | 'can_skip' | 'shallow_copy', value)
    """
    import types
    import numpy as np

    # These types are never copyable - keep as references
    NON_COPYABLE_TYPES = (
        types.ModuleType,           # Imported modules (numpy, manim, etc.)
        types.FunctionType,         # User-defined functions
        types.BuiltinFunctionType,  # Built-in functions
        types.MethodType,           # Bound methods
        type,                       # Classes themselves
    )

    if isinstance(value, NON_COPYABLE_TYPES):
        return 'can_skip'

    # Check for common non-copyable objects by attribute
    if hasattr(value, '__module__'):
        if value.__module__ in ('builtins', 'types') and callable(value):
            return 'can_skip'

    # Mobjects MUST be deep copied - they change between animations
    if isinstance(value, Mobject):
        return 'must_copy'

    # Primitives and immutable types can be skipped (kept as reference)
    if isinstance(value, (int, float, str, bool, type(None), bytes, frozenset)):
        return 'can_skip'

    # Tuples are immutable but might contain mutable items
    if isinstance(value, tuple):
        # Check if tuple contains any Mobjects
        if any(isinstance(item, Mobject) for item in value):
            return 'must_copy'
        return 'can_skip'

    # Lists and dicts might contain Mobjects - need to check
    if isinstance(value, (list, dict)):
        items = value if isinstance(value, list) else value.values()
        if any(isinstance(item, Mobject) for item in items):
            return 'must_copy'
        # Even if no Mobjects, lists/dicts are mutable so we should copy them
        return 'must_copy'

    # NumPy arrays - these are often large and expensive to copy
    # Only copy if they might be animation-related
    if isinstance(value, np.ndarray):
        return 'must_copy'

    # SceneState must be copied (imported lazily: scene.py imports
    # this module, so a top-level import would be circular)
    from maniml.scene.scene import SceneState
    if isinstance(value, SceneState):
        return 'must_copy'

    # Default: copy to be safe
    return 'must_copy'


def _is_likely_copyable(value):
    """
    Quick type-based check if something is likely copyable.
    Avoids expensive test copies by checking type instead.
    """
    classification = _classify_value(value)
    return classification != 'can_skip'


def deepcopy_namespace(namespace_or_checkpoint):
    """
    Deep copy a namespace or checkpoint, using selective copying.

    Optimizations:
    1. Type-based classification instead of test copies (avoids N+1 copy problem)
    2. Skip immutable values (primitives, modules, functions, classes)
    3. Only deep copy Mobjects and mutable collections that contain them
    """
    import copy

    # Names to always skip (these are never useful to copy)
    SKIP_NAMES = {'__builtins__', '__loader__', '__spec__', '__cached__', 'self'}

    # Check if this is a checkpoint dict (has 'namespace' and 'state' keys)
    if isinstance(namespace_or_checkpoint, dict) and 'namespace' in namespace_or_checkpoint and 'state' in namespace_or_checkpoint:
        # This is a checkpoint - we need to deepcopy namespace and state together
        checkpoint = namespace_or_checkpoint

        # Classify items: must_copy vs can_skip
        must_copy = {}
        references = {}

        for name, value in checkpoint['namespace'].items():
            if name in SKIP_NAMES:
                continue
            classification = _classify_value(value)
            if classification == 'must_copy':
                must_copy[name] = value
            else:
                # Keep as reference (immutable or non-copyable)
                references[name] = value

        # Always deep copy the state
        must_copy['__checkpoint_state__'] = checkpoint['state']

        # Single deepcopy call for items that need it
        try:
            copied_items = copy.deepcopy(must_copy)

            # Extract the state
            state = copied_items.pop('__checkpoint_state__', checkpoint['state'])

            # Add references (no copying needed)
            for name, value in references.items():
                copied_items[name] = value

            # Return checkpoint structure
            return {
                'index': checkpoint.get('index', 0),
                'line_number': checkpoint.get('line_number', 0),
                'unit_index': checkpoint.get('unit_index'),
                'state': state,
                'namespace': copied_items
            }

        except Exception as e:
            print(f"Warning: Checkpoint deepcopy failed ({e}), falling back")
            # Fall through to regular handling

    # Regular namespace handling
    namespace = namespace_or_checkpoint

    # Classify items: must_copy vs can_skip
    must_copy = {}
    references = {}

    for name, value in namespace.items():
        if name in SKIP_NAMES:
            continue
        classification = _classify_value(value)
        if classification == 'must_copy':
            must_copy[name] = value
        else:
            # Keep as reference (immutable or non-copyable)
            references[name] = value

    # Single deepcopy call for items that need it
    try:
        copied_items = copy.deepcopy(must_copy)

        # Add references (no copying needed)
        for name, value in references.items():
            copied_items[name] = value

        return copied_items

    except Exception as e:
        # If deepcopy fails, try copying items individually. A single
        # memo shared across all the calls (and with the state, which
        # is inside must_copy) keeps namespace variables and on-screen
        # mobjects aliased to each other; separate memos would produce
        # diverging copies, and later plays would then animate detached
        # duplicates (ghost mobjects).
        print(f"Warning: Batch deepcopy failed ({e}), falling back to individual copy")

        new_namespace = {}
        memo = {}
        degraded = []

        for name, value in must_copy.items():
            try:
                new_namespace[name] = copy.deepcopy(value, memo)
            except Exception:
                # If individual copy fails, keep reference
                new_namespace[name] = value
                degraded.append(name)

        if degraded:
            log.warning(
                "Checkpoint isolation degraded — these variables could "
                f"not be copied and stay live: {', '.join(sorted(degraded))}. "
                "Navigating back may not fully restore them."
            )

        # Add references
        for name, value in references.items():
            new_namespace[name] = value

        return new_namespace
