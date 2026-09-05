"""Checkpoint system for maniml scenes.

Saving/restoring deep-copied (state, namespace) snapshots at each
checkpoint anchor — every play() call in a plain file, only the authored
self.pause() calls in a pause-anchored one (see source_map.pause_anchored)
— re-executing animation units from source, and replaying after
file-watcher edits. The copy discipline lives here: state and namespace
are deep-copied *together* so variable-to-mobject references survive
(see deepcopy_namespace at the bottom).
"""
from __future__ import annotations

import copy
import inspect
import os
import random
import traceback
import weakref
from contextlib import contextmanager

import numpy as np

from maniml.logger import log
from maniml.mobject.mobject import Mobject
from maniml.mobject.mobject import copy_mode
from maniml.performance import performance
from maniml.scene.file_watcher import FileWatcher
from maniml.scene.source_map import SourceMapError
from maniml.scene.source_map import build_units
from maniml.scene.source_map import next_stop_unit
from maniml.scene.source_map import pause_anchored
from maniml.scene.source_map import unit_for_line


class CheckpointMixin:
    @property
    def checkpoint_ledger(self) -> "CheckpointLedger":
        """The scene's record of which live mobjects already have a frozen
        copy in some checkpoint (see CheckpointLedger). Created on first
        use so the mixin needs no __init__."""
        ledger = self.__dict__.get("_checkpoint_ledger")
        if ledger is None:
            ledger = self.__dict__["_checkpoint_ledger"] = CheckpointLedger()
        return ledger

    def _live_is_checkpoint(self, index: int) -> bool:
        """True while the live scene and `_live_namespace` are the very
        objects checkpoint `index` was frozen from: set when a unit
        finishes, cleared by anything that puts a thawed copy on screen
        (Scene.restore_state) or rebuilds checkpoint zero."""
        return (self.__dict__.get('_live_matches_checkpoint') == index
                and bool(self.__dict__.get('_live_namespace')))

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

        # Marks every scene-namespace dict, through every dict.copy() and
        # deepcopy that follows: _rebind_functions tells "a function written
        # in a unit" from "a function from some module" by this key, not by
        # dict identity (which the copies break).
        namespace[SCENE_NS_MARKER] = True
        
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
        with performance.stage("checkpoint.save_copy"):
            checkpoint_namespace = deepcopy_namespace(
                namespace, ledger=self.checkpoint_ledger, mode="freeze")
        checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')
        
        # Create checkpoint 0
        checkpoint_zero = {
            'index': 0,
            'line_number': 0,  # No specific line for initial state
            'unit_index': -1,  # Before the first animation unit
            'state': checkpoint_state,  # Empty scene state
            'namespace': checkpoint_namespace,
            'python_random_state': random.getstate(),
            'numpy_random_state': np.random.get_state(),
        }
        
        self.animation_checkpoints.append(checkpoint_zero)
        self.current_animation_index = 0
        self.frontier_index = 0
        self._live_matches_checkpoint = None
        performance.gauge("checkpoint.count", 1)
        performance.sample_process("checkpoint_saved", checkpoint=0)


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

        previous_mode = getattr(self, '_pause_anchored_mode', None)
        self._source_units_cache = None
        units = self._get_source_units()
        if units is None:
            print("Scene file has errors; fix them and save again")
            return

        if previous_mode is not None and self._pause_anchored_mode != previous_mode:
            # The first pause was added or the last one removed: every
            # stored unit index belongs to the other anchoring regime,
            # so surgical re-anchoring has nothing valid to keep.
            print("Pause anchoring changed: rebuilding scene")
            self._restart_from_source()
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
        self.frontier_index = safe_idx

        if self.current_animation_index != safe_idx:
            self.current_animation_index = safe_idx
            self.restore_state(thaw_state(
                self.animation_checkpoints[safe_idx]['state'], self.checkpoint_ledger))
            self.update_frame(dt=0, force_draw=True)
        log.info(f"Replaying from checkpoint {safe_idx} to unit {affected.index}")

        self._replay_to_unit(affected.index)

    def _replay_to_unit(self, target_unit_index: int) -> None:
        """Re-run units up to and including target_unit_index.

        Units before the target are fast-forwarded (animations skipped,
        so each costs only its state evaluation); the target unit itself
        plays at real speed.

        Replay executes source, so it must start from the execution
        frontier. Starting from an earlier display position would re-run
        retained history — and from an interior loop checkpoint it cannot
        resume the loop mid-statement, so it would overwrite the next
        slot with a wrong-lineage endpoint. The watcher paths are
        unaffected: they truncate first, so display and frontier agree.
        """
        frontier = min(
            getattr(self, 'frontier_index', self.current_animation_index),
            len(self.animation_checkpoints) - 1,
        )
        if self.current_animation_index < frontier:
            self._restore_checkpoint_for_display(frontier)
        self._advancing = True  # one rail move for the whole replay
        try:
            self._replay_to_unit_inner(target_unit_index)
        finally:
            self._advancing = False

    def _replay_to_unit_inner(self, target_unit_index: int) -> None:
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
            next_unit = next_stop_unit(units, after_unit_index=current_unit)
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
        self.frontier_index = -1
        self._presentation_ready = False
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
        with performance.stage("checkpoint.display_restore"):
            self.current_animation_index = index
            with performance.stage("checkpoint.restore_copy"):
                temp = deepcopy_namespace(
                    self.animation_checkpoints[index],
                    ledger=self.checkpoint_ledger, mode="thaw")
            self.restore_state(temp['state'])
            namespace = temp['namespace']
            namespace['self'] = self
            self._live_namespace = namespace
        performance.increment("checkpoint.display_restore.calls")

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

    def _save_checkpoint(self, line_no: int, unit_index: int | None, namespace: dict,
                         run_time: float | None = None, name: str | None = None) -> None:
        """Deep-copy the namespace and scene state into the checkpoint at
        current_animation_index + 1, replacing any existing one there.

        ``run_time`` is how long the play that produced this checkpoint
        took, kept so that stepping back can undo it over the same span.
        Nothing else can supply it later: the animation object is gone by
        then. A pause's checkpoint has none — nothing played between it
        and the play before it, which is also how the reverse path knows
        that hop is an instant one."""
        namespace = dict(namespace)
        namespace.pop('__animation_line_number__', None)
        namespace.pop('__animation_unit_index__', None)

        # Deep copy state and namespace together so references between
        # namespace variables and on-screen mobjects are preserved
        namespace['__checkpoint_state__'] = self.get_state()
        with performance.stage("checkpoint.save_copy"):
            checkpoint_namespace = deepcopy_namespace(
                namespace, ledger=self.checkpoint_ledger, mode="freeze")
        checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')
        if performance.enabled:
            performance.gauge("checkpoint.mobjects", _count_family(checkpoint_state.mobjects))

        self.current_animation_index += 1
        checkpoint = {
            'index': self.current_animation_index,
            'line_number': line_no,
            'unit_index': unit_index,
            'run_time': run_time,
            'name': name,
            'state': checkpoint_state,
            'namespace': checkpoint_namespace,
            'python_random_state': random.getstate(),
            'numpy_random_state': np.random.get_state(),
        }
        if self.current_animation_index < len(self.animation_checkpoints):
            # Re-running an existing animation: replace its checkpoint
            self.animation_checkpoints[self.current_animation_index] = checkpoint
        else:
            self.animation_checkpoints.append(checkpoint)
        self.frontier_index = max(
            getattr(self, 'frontier_index', -1),
            self.current_animation_index,
        )
        performance.gauge("checkpoint.count", len(self.animation_checkpoints))
        performance.gauge("checkpoint.frontier", self.frontier_index)
        if (self.current_animation_index <= 1
                or self.current_animation_index % 10 == 0):
            performance.sample_process(
                "checkpoint_saved",
                checkpoint=self.current_animation_index,
                checkpoint_count=len(self.animation_checkpoints),
                mobjects=len(getattr(self, 'mobjects', ())),
            )

    @staticmethod
    def _restore_checkpoint_random_state(checkpoint: dict) -> None:
        """Restore deterministic process-global RNGs before source runs.

        Display-only navigation intentionally leaves RNGs alone.  Actual
        execution, including watcher rebuilds and explicit loop replay,
        resumes from the selected checkpoint's stochastic state.
        """
        python_state = checkpoint.get('python_random_state')
        if python_state is not None:
            random.setstate(python_state)
        numpy_state = checkpoint.get('numpy_random_state')
        if numpy_state is not None:
            np.random.set_state(numpy_state)

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
            self._pause_anchored_mode = pause_anchored(source)
        except (OSError, SyntaxError, SourceMapError) as e:
            log.warning(f"Could not map scene source: {e}")
            return None
        self._source_units_cache = ((path, mtime), units)
        return units

    def _pause_anchored(self) -> bool:
        """Whether this scene's file authors its own pausepoints.

        True when the source calls self.pause()/self.next_section()
        anywhere: checkpoints then save only at pauses, and plays between
        them run through as one stretch. A file with no pauses keeps the
        legacy per-play anchoring, so unmodified CE files stay steppable.
        """
        self._get_source_units()
        return getattr(self, '_pause_anchored_mode', False)

    @contextmanager
    def _no_checkpoints(self):
        """Play animations without saving checkpoints, for display-only
        playback that is not part of history (kept for the recorded-stream
        layer; currently unused)."""
        prev = getattr(self, '_suppress_checkpoints', False)
        self._suppress_checkpoints = True
        try:
            yield
        finally:
            self._suppress_checkpoints = prev

    def run_next_animation(self):
        """Run the next animation unit, re-executed from the scene source."""
        if not getattr(self, '_scene_filepath', None):
            message = "No scene file path stored"
            if self._strict_animation_errors():
                raise RuntimeError(message)
            print(message)
            return

        units = self._get_source_units()
        if units is None:
            message = "Cannot parse scene file; fix the error and save again"
            if self._strict_animation_errors():
                raise RuntimeError(message)
            print(message)
            return

        current_checkpoint = self.animation_checkpoints[self.current_animation_index]
        next_index = self.current_animation_index + 1

        unit = next_stop_unit(
            units,
            after_unit_index=current_checkpoint.get('unit_index'),
            after_line=current_checkpoint['line_number'],
        )
        if unit is None:
            # Past the last stop call: run any trailing statements
            # (e.g. a final self.wait()) exactly once
            tail = units[-1] if units and not units[-1].has_stop else None
            current_unit = current_checkpoint.get('unit_index')
            if tail is None or (current_unit is not None and current_unit >= tail.index):
                print("Already at last animation")
                return
            unit = tail

        if self._live_is_checkpoint(self.current_animation_index):
            # At the frontier: the live scene and namespace are exactly
            # what the current checkpoint was frozen from, and the
            # checkpoint holds its own (immutable) copies. Running the
            # next unit against the live graph is what one straight run
            # of construct() would have done; the thaw only earns its
            # keep after a navigation replaced the live graph.
            performance.increment("checkpoint.execution_copy.skipped")
            state = current_checkpoint['state']
            self.time = state.time
            self.num_plays = state.num_plays
            if state.camera_frame_points is not None and hasattr(self.camera, 'frame'):
                self.camera.frame.set_points(state.camera_frame_points)
            self._reset_pacing_clocks()
            namespace = self._live_namespace
        else:
            # Work on a deep copy so the stored checkpoint stays pristine.
            # State and namespace are copied together, preserving references
            # between namespace variables and on-screen mobjects.
            with performance.stage("checkpoint.execution_copy"):
                checkpoint_temporary = deepcopy_namespace(
                    current_checkpoint, ledger=self.checkpoint_ledger, mode="thaw")

            with performance.stage("checkpoint.execution_restore"):
                with self.mobject_list_transaction():
                    self.clear()
                    self.restore_state(checkpoint_temporary['state'])

            namespace = checkpoint_temporary['namespace']
        namespace['self'] = self
        self._restore_checkpoint_random_state(current_checkpoint)
        # Anchor for the checkpoint(s) saved during exec
        namespace['__animation_line_number__'] = unit.end_line
        namespace['__animation_unit_index__'] = unit.index

        if self.skip_animations:
            print(f"⏩ Fast-forwarding animation {next_index}")
        else:
            print(f"→ Running animation {next_index}")
        try:
            code = compile(unit.source, self._scene_filepath, 'exec')
            with performance.stage("source.execute"):
                exec(code, namespace)
        except Exception as e:
            print(f"Error running animation: {e}")
            # Restore the last successfully saved checkpoint so the scene
            # isn't left in a half-executed state
            checkpoint = self.animation_checkpoints[self.current_animation_index]
            with self.mobject_list_transaction():
                self.clear()
                self.restore_state(thaw_state(checkpoint['state'], self.checkpoint_ledger))
            self.update_frame(dt=0, force_draw=True)
            if self._strict_animation_errors():
                raise
            traceback.print_exc()
            return

        if self.current_animation_index < next_index:
            # No checkpoint was saved during this unit (a trailing tail, or
            # a unit whose stop is written in a branch or helper that wasn't
            # reached): save one anyway so the unit counts as done and the
            # stepper moves on instead of re-running it forever.
            self._save_checkpoint(unit.end_line, unit.index, namespace)

        # The exec namespace holds the objects now on screen; keep it
        # for click-to-inspect name lookup
        self._live_namespace = namespace
        self._live_matches_checkpoint = self.current_animation_index

        print(f"Animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1} complete")

    def advance_to_next_pausepoint(self) -> None:
        """RIGHT: restore retained history, or execute at the frontier.

        Before the execution frontier, RIGHT selects an existing checkpoint
        exactly like fine navigation and never runs scene Python.  At the
        frontier it runs units until the next authored pause.  A file with
        no pauses treats every play checkpoint as a stop.
        """
        pause_anchored = self._pause_anchored()
        frontier = min(
            getattr(self, 'frontier_index', self.current_animation_index),
            len(self.animation_checkpoints) - 1,
        )
        if self.current_animation_index < frontier:
            if pause_anchored:
                target = next(
                    i for i in range(self.current_animation_index + 1, frontier + 1)
                    if i == frontier or self.animation_checkpoints[i].get('stop')
                )
            else:
                target = self.current_animation_index + 1
            print(f"→ Restore animation {target}/{len(self.animation_checkpoints) - 1}")
            self._restore_checkpoint_for_display(target)
            self.update_frame(dt=0, force_draw=True)
            return

        if not pause_anchored:
            self.run_next_animation()
            return
        # Flagged so a viewer's rail can hold at the pausepoint being left
        # for the whole stretch, rather than hopping through the interior
        # play checkpoints as they save.
        self._advancing = True
        try:
            while True:
                last = self.current_animation_index
                self.run_next_animation()
                now = self.current_animation_index
                if now == last:
                    return  # end of scene, or an error already reported
                if self.animation_checkpoints[now].get('stop'):
                    return
        finally:
            self._advancing = False

    def _strict_animation_errors(self) -> bool:
        return any((
            getattr(self, '_render_mode', False),
            getattr(self, '_present_mode', False),
            getattr(self, '_propagate_animation_errors', False),
        ))



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


SCENE_NS_MARKER = '__maniml_scene_ns__'


def _rebind_functions(old_namespace: dict, new_namespace: dict, memo: dict) -> None:
    """Point functions at the copies the snapshot just made.

    deepcopy copies objects, not the functions that read them: a function
    written in a unit keeps ``__globals__`` bound to that unit's namespace
    dict, and closures / default args / bound methods hold the *original*
    mobjects. After a snapshot, the next unit animates the copied tracker
    while ``always_redraw`` callbacks still read the original one, so the
    drawing never moves. (``always_redraw`` itself closes over the original
    ``mob`` and ``func``, so even the copy's own updater redraws the
    original.)

    This walks every function the copy can reach -- namespace values and the
    updaters of every copied mobject -- and re-creates it as code + the new
    environment: ``__globals__`` -> the new namespace (when the old one was
    a scene namespace, recognised by SCENE_NS_MARKER -- identity won't do,
    the save path hands over a dict.copy()), closure cells / defaults /
    ``__self__`` -> the copy recorded in ``memo`` where one exists. Functions
    from other modules keep their globals; only their cells are remapped.
    Rebinding chains across generations: save (live exec dict -> stored
    copy) and replay (stored copy -> fresh exec dict) both re-point it.

    It is a corrective pass over the copy rather than a property of the
    copy; see TODO.md "Open questions" for the design discussion.
    """
    import types

    fmap: dict[int, object] = {}

    def remap(value):
        copied = memo.get(id(value))
        if copied is not None and copied is not memo:
            return copied
        if isinstance(value, (types.FunctionType, types.MethodType)):
            return rebind(value)
        return value

    def rebind(f):
        if id(f) in fmap:
            return fmap[id(f)]
        if isinstance(f, types.MethodType):
            new_self = remap(f.__self__)
            new_func = rebind(f.__func__)
            if new_self is f.__self__ and new_func is f.__func__:
                fmap[id(f)] = f
                return f
            m = types.MethodType(new_func, new_self)
            fmap[id(f)] = m
            return m
        if not isinstance(f, types.FunctionType):
            return f
        fmap[id(f)] = f   # provisional: guards self-referential closures

        new_globals = new_namespace if SCENE_NS_MARKER in f.__globals__ else f.__globals__
        changed = new_globals is not f.__globals__

        new_closure = None
        if f.__closure__:
            cells = []
            for cell in f.__closure__:
                try:
                    val = cell.cell_contents
                except ValueError:          # empty cell
                    cells.append(cell)
                    continue
                new_val = remap(val)
                if new_val is not val:
                    changed = True
                    cells.append(types.CellType(new_val))
                else:
                    cells.append(cell)
            new_closure = tuple(cells)

        new_defaults = None
        if f.__defaults__:
            new_defaults = tuple(remap(d) for d in f.__defaults__)
            changed = changed or any(a is not b for a, b in zip(new_defaults, f.__defaults__))

        new_kwdefaults = None
        if f.__kwdefaults__:
            new_kwdefaults = {k: remap(v) for k, v in f.__kwdefaults__.items()}
            changed = changed or any(new_kwdefaults[k] is not v for k, v in f.__kwdefaults__.items())

        if not changed:
            return f
        g = types.FunctionType(f.__code__, new_globals, f.__name__, new_defaults, new_closure)
        g.__kwdefaults__ = new_kwdefaults
        g.__qualname__ = f.__qualname__
        g.__doc__ = f.__doc__
        g.__module__ = f.__module__
        g.__dict__.update(f.__dict__)
        fmap[id(f)] = g
        return g

    for name, value in list(new_namespace.items()):
        if isinstance(value, (types.FunctionType, types.MethodType)):
            new_namespace[name] = rebind(value)

    for value in list(memo.values()):
        if isinstance(value, Mobject) and getattr(value, 'updaters', None):
            rebound = [rebind(u) for u in value.updaters]
            if any(a is not b for a, b in zip(rebound, value.updaters)):
                value.updaters = rebound


VERIFY_LEDGER_ENV = "MANIML_VERIFY_LEDGER"

# Columns the render pass fills lazily (joint angles, unit normals, the
# nudged surface points). They change under a clean scene and are
# recomputed from the mobject's refresh flags, so they are neither a
# revision bump nor a difference the ledger cares about.
DERIVED_DATA_KEYS = frozenset({"joint_angle", "base_normal", "d_normal_point"})

# Attributes that are render-only, rebuilt on restore, or handled by the
# ledger's own rules (submobjects through the memo, parents relinked on
# thaw, updaters by the no-updaters rule).
_LEDGER_IGNORED_ATTRS = frozenset({
    "data", "uniforms", "submobjects", "parents", "family", "updaters",
    "revision", "shader_wrapper", "bounding_box",
    "_needs_new_bounding_box", "_data_has_changed", "_is_animating",
    "_has_updaters_in_family", "_triangulation_cache", "needs_new_joint_angles",
    "needs_new_unit_normal", "subpath_end_indices", "outer_vert_indices",
    "_shader_wrapper_id",
})


class LedgerStale(Exception):
    """A mobject's revision said "unchanged" but its state differs from
    the frozen copy the ledger would have reused. The message names the
    attribute; the fix is a missing revision bump at the mutation site."""


def verify_ledger_enabled() -> bool:
    return os.environ.get(VERIFY_LEDGER_ENV) == "1"


def _count_family(mobjects) -> int:
    return sum(len(mob.get_family()) for mob in mobjects)


def _values_differ(a, b, ledger=None) -> bool:
    if isinstance(a, np.ndarray) or isinstance(b, np.ndarray):
        try:
            return not np.array_equal(np.asarray(a), np.asarray(b))
        except Exception:
            return True
    if isinstance(a, Mobject) or isinstance(b, Mobject):
        if ledger is None or not (isinstance(a, Mobject) and isinstance(b, Mobject)):
            return ledger is not None
        entry = ledger.entries.get(a)
        return entry is None or entry.frozen is not b
    if isinstance(a, (list, tuple)):
        if not isinstance(b, (list, tuple)) or len(a) != len(b):
            return True
        return any(_values_differ(x, y, ledger) for x, y in zip(a, b))
    if isinstance(a, dict):
        if not isinstance(b, dict) or a.keys() != b.keys():
            return True
        return any(_values_differ(a[k], b[k], ledger) for k in a)
    if callable(a) or callable(b):
        return False   # functions are rebound by _rebind_functions
    if a is b:
        return False
    if type(a) is not type(b):
        return True
    if type(a).__eq__ is object.__eq__:
        # An opaque object that compares by identity (a scipy Rotation, an
        # EventListener): a copy can never be "equal", so nothing can be
        # said either way. Not a difference.
        return False
    try:
        return bool(a != b)
    except Exception:
        return False


def ledger_stale_attribute(live: Mobject, frozen: Mobject, memo: dict | None = None, ledger=None) -> str | None:
    """Name the first attribute in which `live` differs from `frozen`, or
    None when the two are the same checkpoint-relevant state.

    The comparison is what the ledger must be able to trust when a
    revision is unchanged: every data column except the derived ones,
    every uniform, the submobject list (through `memo` when the caller
    has one, by recursion otherwise), the updater count, and every plain
    attribute outside the render-only set."""
    if type(live) is not type(frozen):
        return "type"
    if live.data.dtype != frozen.data.dtype or live.data.shape != frozen.data.shape:
        return "data.shape"
    for key in live.data.dtype.names:
        if key in DERIVED_DATA_KEYS:
            continue
        if not np.array_equal(live.data[key], frozen.data[key]):
            return f"data.{key}"
    if live.uniforms.keys() != frozen.uniforms.keys():
        return "uniforms.keys"
    for key, value in live.uniforms.items():
        if _values_differ(value, frozen.uniforms[key], ledger):
            return f"uniforms.{key}"
    if len(live.submobjects) != len(frozen.submobjects):
        return "submobjects"
    for sub_live, sub_frozen in zip(live.submobjects, frozen.submobjects):
        if memo is not None:
            if memo.get(id(sub_live)) is not sub_frozen:
                return "submobjects"
        elif ledger is not None:
            entry = ledger.entries.get(sub_live)
            if entry is None or entry.frozen is not sub_frozen:
                return "submobjects"
        else:
            inner = ledger_stale_attribute(sub_live, sub_frozen)
            if inner is not None:
                return f"submobjects.{inner}"
    if len(live.updaters) != len(frozen.updaters):
        return "updaters"
    for name, value in live.__dict__.items():
        if name in _LEDGER_IGNORED_ATTRS:
            continue
        if name not in frozen.__dict__:
            return name
        if _values_differ(value, frozen.__dict__[name], ledger):
            return name
    for name in frozen.__dict__:
        if name not in live.__dict__ and name not in _LEDGER_IGNORED_ATTRS:
            return name
    return None


class LedgerEntry:
    """What the ledger knows about one live mobject: the frozen copy it
    got at its last checkpoint, the revision it had then, whether that
    copy may be shared at all (not while it has updaters: their closures
    hold other mobjects the copy could not be re-pointed to), and the
    names of its attributes that held other mobjects (target,
    saved_state, a SurroundingRectangle's mobject, ...). A frozen copy is
    reused only when everything it reaches through submobjects and those
    attributes is unchanged too, since the shared copy keeps pointing at
    their old frozen copies. `nattrs` is the attribute count at freeze
    time: a plain attribute write bumps nothing, so a mobject that gained
    or lost an attribute since is copied afresh (an attribute
    reassigned to a different mobject is the one write this cannot see;
    verify mode does)."""
    __slots__ = ("revision", "frozen", "reusable", "refs", "nattrs")

    def __init__(self, revision: int, frozen: Mobject, reusable: bool, refs: tuple, nattrs: int):
        self.revision = revision
        self.frozen = frozen
        self.reusable = reusable
        self.refs = refs
        self.nattrs = nattrs


class CheckpointLedger:
    """live mobject -> LedgerEntry, keyed by identity and dropped with the
    live object. A checkpoint save pre-seeds the deep copy's memo from it
    so an unchanged mobject hands back its previous frozen copy instead of
    being walked again; a thaw seeds it from the checkpoint being thawed
    so the next save after a step back also copies only what moved."""

    def __init__(self):
        self.entries: "weakref.WeakKeyDictionary[Mobject, LedgerEntry]" = weakref.WeakKeyDictionary()
        # frozen copy -> (reusable, refs, nattrs), learned when it was made,
        # so a thaw can enter its live copies without rescanning each one
        self.frozen_meta: "weakref.WeakKeyDictionary[Mobject, tuple]" = weakref.WeakKeyDictionary()


_STRUCTURE_ATTRS = frozenset({"submobjects", "parents", "family"})


_REF_DEPTH = 4   # Table.mob_table is a list of lists; allow a little more


def _mobjects_in(value, out: list, depth: int = _REF_DEPTH) -> None:
    """Append the mobjects held by `value`: itself, or the members of a
    list / tuple / set / dict nested up to `depth` levels."""
    if isinstance(value, Mobject):
        out.append(value)
    elif depth and isinstance(value, (list, tuple, set)):
        for item in value:
            _mobjects_in(item, out, depth - 1)
    elif depth and isinstance(value, dict):
        for item in value.values():
            _mobjects_in(item, out, depth - 1)


def _mobject_refs(mob: Mobject) -> tuple:
    """Names of the attributes through which `mob` reaches other mobjects,
    other than the family structure itself."""
    names = []
    found: list = []
    for name, value in mob.__dict__.items():
        if name in _STRUCTURE_ATTRS:
            continue
        if isinstance(value, Mobject):
            names.append(name)
        elif isinstance(value, (list, tuple, set, dict)):
            del found[:]
            _mobjects_in(value, found)
            if found:
                names.append(name)
    return tuple(names)


def _referenced(mob: Mobject, names) -> list:
    out: list = []
    for name in names:
        _mobjects_in(mob.__dict__.get(name), out)
    return out


def _new_entry(mob: Mobject, frozen: Mobject) -> LedgerEntry:
    return LedgerEntry(mob.revision, frozen, not mob.updaters, _mobject_refs(mob), len(mob.__dict__))


def _entry_from_meta(frozen: Mobject, meta: tuple | None) -> LedgerEntry:
    if meta is None:
        return _new_entry(frozen, frozen)
    reusable, refs, nattrs = meta
    return LedgerEntry(frozen.revision, frozen, reusable, refs, nattrs)


def _entry_is_current(entry: LedgerEntry | None, mob: Mobject) -> bool:
    return (entry is not None and entry.revision == mob.revision
            and entry.nattrs == len(mob.__dict__))


def _top_level_mobjects(must_copy: dict) -> list[Mobject]:
    """The mobjects a checkpoint copy starts from: namespace values, the
    members of one level of container, and the scene state's list."""
    from maniml.scene.scene import SceneState
    seen: set[int] = set()
    tops: list[Mobject] = []

    def take(value):
        if isinstance(value, Mobject) and id(value) not in seen:
            seen.add(id(value))
            tops.append(value)

    for value in must_copy.values():
        if isinstance(value, Mobject):
            take(value)
        elif isinstance(value, SceneState):
            for mob in value.mobjects:
                take(mob)
        elif isinstance(value, (list, tuple, set)):
            for item in value:
                take(item)
        elif isinstance(value, dict):
            for item in value.values():
                take(item)
    return tops


def _reusable_closure(ledger: CheckpointLedger, top: Mobject):
    """The (live, entry) pairs for everything `top` reaches — its family
    and the mobjects behind its reference attributes, transitively — when
    every one of them has a shareable frozen copy at its current
    revision; else None. All of them are required, not just `top`: the
    shared copy keeps pointing at their old frozen copies."""
    pairs = []
    seen: set[int] = set()
    stack = [top]
    while stack:
        mob = stack.pop()
        if id(mob) in seen:
            continue
        seen.add(id(mob))
        entry = ledger.entries.get(mob)
        if not _entry_is_current(entry, mob) or not entry.reusable:
            return None
        pairs.append((mob, entry))
        stack.extend(mob.submobjects)
        stack.extend(_referenced(mob, entry.refs))
    return pairs


def _closure(top: Mobject, ledger: CheckpointLedger | None):
    """Every mobject `top` reaches through submobjects and reference
    attributes. Uses the ledger's recorded attribute names for mobjects
    whose entry is current, and scans the rest."""
    seen: set[int] = set()
    stack = [top]
    while stack:
        mob = stack.pop()
        if id(mob) in seen:
            continue
        seen.add(id(mob))
        yield mob
        stack.extend(mob.submobjects)
        entry = ledger.entries.get(mob) if ledger is not None else None
        names = entry.refs if _entry_is_current(entry, mob) else _mobject_refs(mob)
        stack.extend(_referenced(mob, names))


def _freeze(must_copy: dict, ledger: CheckpointLedger | None) -> tuple[dict, dict]:
    """Deep-copy live -> checkpoint. Returns (copied, memo)."""
    memo: dict = {}
    reused_frozen: set[int] = set()
    tops = _top_level_mobjects(must_copy)
    if ledger is not None:
        verify = verify_ledger_enabled()
        for top in tops:
            pairs = _reusable_closure(ledger, top)
            if pairs is None:
                continue
            if verify:
                for mob, entry in pairs:
                    attr = ledger_stale_attribute(mob, entry.frozen, ledger=ledger)
                    if attr is not None:
                        raise LedgerStale(
                            f"{type(mob).__name__} changed in '{attr}' since its last "
                            f"checkpoint without a revision bump")
            for mob, entry in pairs:
                memo[id(mob)] = entry.frozen
                reused_frozen.add(id(entry.frozen))
    with copy_mode("freeze"):
        copied = copy.deepcopy(must_copy, memo)
    if ledger is not None:
        n_reused = n_copied = 0
        seen: set[int] = set()
        for top in tops:
            for mob in _closure(top, ledger):
                if id(mob) in seen:
                    continue
                seen.add(id(mob))
                frozen = memo.get(id(mob))
                if frozen is None:
                    continue
                if id(frozen) in reused_frozen:
                    n_reused += 1
                    continue
                entry = ledger.entries[mob] = _new_entry(mob, frozen)
                ledger.frozen_meta[frozen] = (entry.reusable, entry.refs, entry.nattrs)
                n_copied += 1
        performance.increment("checkpoint.ledger.reused", n_reused)
        performance.increment("checkpoint.ledger.copied", n_copied)
        performance.gauge("checkpoint.ledger.entries", len(ledger.entries))
    return copied, memo


def _thaw(must_copy: dict, ledger: CheckpointLedger | None) -> tuple[dict, dict]:
    """Deep-copy checkpoint -> live. Returns (copied, memo). The new live
    objects are entered in the ledger against the frozen ones they came
    from, so an untouched mobject is reused at the very next save."""
    memo: dict = {}
    with copy_mode("thaw"):
        copied = copy.deepcopy(must_copy, memo)
    if ledger is not None:
        meta_of = ledger.frozen_meta
        seen: set[int] = set()
        stack = list(_top_level_mobjects(must_copy))
        while stack:
            frozen = stack.pop()
            if id(frozen) in seen:
                continue
            seen.add(id(frozen))
            meta = meta_of.get(frozen)
            entry = _entry_from_meta(frozen, meta)
            if meta is None:
                meta_of[frozen] = (entry.reusable, entry.refs, entry.nattrs)
            live = memo.get(id(frozen))
            if live is not None and live is not frozen:
                ledger.entries[live] = entry
            stack.extend(frozen.submobjects)
            stack.extend(_referenced(frozen, entry.refs))
    return copied, memo


def _copy_items(must_copy: dict, ledger, mode) -> tuple[dict, dict]:
    if mode == "freeze":
        return _freeze(must_copy, ledger)
    if mode == "thaw":
        return _thaw(must_copy, ledger)
    memo: dict = {}
    return copy.deepcopy(must_copy, memo), memo


def thaw_state(state, ledger: CheckpointLedger | None = None):
    """A live copy of a frozen SceneState, parent links rebuilt. What a
    stored checkpoint's state has to go through before it can be shown."""
    copied, _ = _thaw({"__state__": state}, ledger)
    return copied["__state__"]


def deepcopy_namespace(namespace_or_checkpoint, *, ledger: CheckpointLedger | None = None, mode: str | None = None):
    """
    Deep copy a namespace or checkpoint, using selective copying.

    Optimizations:
    1. Type-based classification instead of test copies (avoids N+1 copy problem)
    2. Skip immutable values (primitives, modules, functions, classes)
    3. Only deep copy Mobjects and mutable collections that contain them

    `mode` is "freeze" when making a checkpoint from the live scene and
    "thaw" when making a live scene from a checkpoint (see
    Mobject.copy_mode); None is a plain deep copy. With a `ledger`, a
    freeze reuses the frozen copies of mobjects unchanged since their
    last checkpoint, and a thaw records what it produced so the next
    freeze can.
    """
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
            copied_items, memo = _copy_items(must_copy, ledger, mode)

            # Extract the state
            state = copied_items.pop('__checkpoint_state__', checkpoint['state'])

            # Add references (no copying needed)
            for name, value in references.items():
                copied_items[name] = value

            # Functions must read the copies, not the originals
            _rebind_functions(checkpoint['namespace'], copied_items, memo)

            # Return checkpoint structure
            return {
                'index': checkpoint.get('index', 0),
                'line_number': checkpoint.get('line_number', 0),
                'unit_index': checkpoint.get('unit_index'),
                'state': state,
                'namespace': copied_items
            }

        except LedgerStale:
            raise
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
        copied_items, memo = _copy_items(must_copy, ledger, mode)

        # Add references (no copying needed)
        for name, value in references.items():
            copied_items[name] = value

        _rebind_functions(namespace, copied_items, memo)
        return copied_items

    except LedgerStale:
        raise
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

        with copy_mode(mode):
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

        _rebind_functions(namespace, new_namespace, memo)
        return new_namespace
