from __future__ import annotations

from collections import OrderedDict
import os
import platform
import random
import time
import traceback
import inspect
from functools import wraps
from contextlib import contextmanager
from contextlib import ExitStack

import numpy as np
from tqdm.auto import tqdm as ProgressDisplay
from pyglet.window import key as PygletWindowKeys

from manim.animation.animation import prepare_animation
from manim.camera.camera import Camera
from manim.camera.camera_frame import CameraFrame
from manim.config import manim_config
from manim.event_handler import EVENT_DISPATCHER
from manim.event_handler.event_type import EventType
from manim.logger import log
from manim.mobject.mobject import _AnimationBuilder
from manim.mobject.mobject import Group
from manim.mobject.mobject import Mobject
from manim.mobject.mobject import Point
from manim.mobject.types.vectorized_mobject import VGroup
from manim.mobject.types.vectorized_mobject import VMobject
from manim.scene.scene_embed import InteractiveSceneEmbed
from manim.scene.scene_embed import CheckpointManager
from manim.scene.scene_file_writer import SceneFileWriter
from manim.scene.file_watcher import FileWatcher
from manim.scene.source_map import SourceMapError
from manim.scene.source_map import build_units
from manim.scene.source_map import next_play_unit
from manim.scene.source_map import unit_for_line
from manim.utils.dict_ops import merge_dicts_recursively
from manim.utils.family_ops import extract_mobject_family_members
from manim.utils.family_ops import recursive_mobject_remove
from manim.utils.iterables import batch_by_property
from manim.utils.sounds import play_sound
from manim.utils.color import color_to_rgba
from manim.rendering.window import Window

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterable, TypeVar, Optional
    from manim.typing import Vect3

    T = TypeVar('T')

    from PIL.Image import Image

    from manim.animation.animation import Animation


class Scene(object):
    random_seed: int = 0
    pan_sensitivity: float = 0.5
    scroll_sensitivity: float = 20
    drag_to_pan: bool = True
    max_num_saved_states: int = 50
    default_camera_config: dict = dict()
    default_file_writer_config: dict = dict()
    samples = 0
    # Euler angles, in degrees
    default_frame_orientation = (0, 0)

    def __init__(
        self,
        window: Optional[Window] = None,
        camera_config: dict = dict(),
        file_writer_config: dict = dict(),
        skip_animations: bool = False,
        always_update_mobjects: bool = False,
        start_at_animation_number: int | None = None,
        end_at_animation_number: int | None = None,
        show_animation_progress: bool = False,
        leave_progress_bars: bool = False,
        preview_while_skipping: bool = True,
        presenter_mode: bool = False,
        default_wait_time: float = 1.0,
    ):
        self.skip_animations = skip_animations
        self.always_update_mobjects = always_update_mobjects
        self.start_at_animation_number = start_at_animation_number
        self.end_at_animation_number = end_at_animation_number
        self.show_animation_progress = show_animation_progress
        self.leave_progress_bars = leave_progress_bars
        self.preview_while_skipping = preview_while_skipping
        self.presenter_mode = presenter_mode
        self.default_wait_time = default_wait_time

        self.camera_config = merge_dicts_recursively(
            manim_config.camera,         # Global default
            self.default_camera_config,  # Updated configuration that subclasses may specify
            camera_config,               # Updated configuration from instantiation
        )
        self.file_writer_config = merge_dicts_recursively(
            manim_config.file_writer,
            self.default_file_writer_config,
            file_writer_config,
        )

        self.window = window
        if self.window:
            self.window.init_for_scene(self)
            # Make sure camera and Pyglet window sync
            self.camera_config["fps"] = 30

        # Core state of the scene
        self.camera: Camera = Camera(
            window=self.window,
            samples=self.samples,
            **self.camera_config
        )
        self.frame: CameraFrame = self.camera.frame
        self.frame.reorient(*self.default_frame_orientation)
        self.frame.make_orientation_default()

        self.file_writer = SceneFileWriter(self, **self.file_writer_config)
        self.mobjects: list[Mobject] = [self.camera.frame]
        self.render_groups: list[Mobject] = []
        self.id_to_mobject_map: dict[int, Mobject] = dict()
        self.num_plays: int = 0
        self.time: float = 0
        self.skip_time: float = 0
        self.original_skipping_status: bool = self.skip_animations
        self.undo_stack = []
        self.redo_stack = []

        if self.start_at_animation_number is not None:
            self.skip_animations = True
        if self.file_writer.has_progress_display():
            self.show_animation_progress = False

        # Items associated with interaction
        self.mouse_point = Point()
        self.mouse_drag_point = Point()
        self.hold_on_wait = self.presenter_mode
        self.quit_interaction = False

        # Much nicer to work with deterministic scenes
        if self.random_seed is not None:
            random.seed(self.random_seed)
            np.random.seed(self.random_seed)
        
        # Checkpoint system for arrow key navigation
        self.animation_checkpoints = []  # List of dicts with {index, line_number, unit_index, state, namespace}
        self.current_animation_index = -1
        self._processing_key = False  # Flag to prevent re-entry during key processing
        self._source_units_cache = None  # ((path, mtime), units) for the parsed scene file

        # File watcher for auto-reload
        self._file_watcher = None
        self._file_changed_flag = False  # Thread-safe flag for file changes
        self._pending_change_info = None
        self.auto_reload_enabled = True  # Can be disabled if needed

    def __str__(self) -> str:
        return self.__class__.__name__

    def get_window(self) -> Window | None:
        return self.window

    def run(self) -> None:
        self.virtual_animation_start_time: float = 0
        self.real_animation_start_time: float = time.time()
        self.file_writer.begin()

        self.setup()
        try:
            # Create checkpoint 0 right before construct
            self._create_checkpoint_zero()
            # Run only the first animation instead of all of construct
            self.run_next_animation()
            self.interact()
        except EndScene:
            pass
        except KeyboardInterrupt:
            # Get rid keyboard interupt symbols
            print("", end="\r")
            self.file_writer.ended_with_interrupt = True
        self.tear_down()

    def setup(self) -> None:
        """
        This is meant to be implement by any scenes which
        are comonly subclassed, and have some common setup
        involved before the construct method is called.
        """
        pass

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
            exec("from manim import *", namespace)
        
        # Explicitly import constants if BLUE is missing
        if 'BLUE' not in namespace:
            import manim
            # Get all color constants from manim.constants
            for name in dir(manim.constants):
                if not name.startswith('_'):
                    namespace[name] = getattr(manim.constants, name)
        
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


    def construct(self) -> None:
        # Where all the animation happens
        # To be implemented in subclasses
        pass

    def tear_down(self) -> None:
        self.stop_skipping()
        self.file_writer.finish()
        if self._file_watcher:
            self._file_watcher.stop()
            self._file_watcher = None
        if self.window:
            self.window.destroy()
            self.window = None

    def interact(self) -> None:
        """
        If there is a window, enter a loop
        which updates the frame while under
        the hood calling the pyglet event loop
        """
        if self.window is None:
            return
        # log.info(
        #     "\nTips: Using the keys `d`, `f`, or `z` " +
        #     "you can interact with the scene. " +
        #     "Press `command + q` or `esc` to quit"
        # )
        
        # Setup file watcher if enabled
        if self.auto_reload_enabled:
            self._setup_file_watcher()
        
        self.skip_animations = False
        while not self.is_window_closing():
            # Check for file changes
            if self._file_changed_flag:
                self._file_changed_flag = False
                self._handle_file_change()
            
            self.update_frame(1 / self.camera.fps)

    def embed(
        self,
        close_scene_on_exit: bool = True,
        show_animation_progress: bool = False,
    ) -> None:
        if not self.window:
            # Embed is only relevant for interactive development with a Window
            return
        self.show_animation_progress = show_animation_progress
        self.stop_skipping()
        self.update_frame(force_draw=True)

        InteractiveSceneEmbed(self).launch()

        # End scene when exiting an embed
        if close_scene_on_exit:
            raise EndScene()
    
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

        from manim.__main__ import load_scene_module
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

    # Only these methods should touch the camera

    def get_image(self) -> Image:
        if self.window is not None:
            self.camera.use_window_fbo(False)
            self.camera.capture(*self.render_groups)
        image = self.camera.get_image()
        if self.window is not None:
            self.camera.use_window_fbo(True)
        return image

    def show(self) -> None:
        self.update_frame(force_draw=True)
        self.get_image().show()

    def update_frame(self, dt: float = 0, force_draw: bool = False) -> None:
        self.increment_time(dt)
        self.update_mobjects(dt)
        if self.skip_animations and not force_draw:
            return

        if self.is_window_closing():
            raise EndScene()

        if self.window and dt == 0 and not self.window.has_undrawn_event() and not force_draw:
            # In this case, there's no need for new rendering, but we
            # shoudl still listen for new events
            self.window._window.dispatch_events()
            return

        self.camera.capture(*self.render_groups)

        if self.window and not self.skip_animations:
            vt = self.time - self.virtual_animation_start_time
            rt = time.time() - self.real_animation_start_time
            time.sleep(max(vt - rt, 0))

    def emit_frame(self) -> None:
        if not self.skip_animations:
            self.file_writer.write_frame(self.camera)

    # Related to updating

    def update_mobjects(self, dt: float) -> None:
        for mobject in self.mobjects:
            mobject.update(dt)

    def should_update_mobjects(self) -> bool:
        return self.always_update_mobjects or any(
            mob.has_updaters() for mob in self.mobjects
        )

    # Related to time

    def get_time(self) -> float:
        return self.time

    def increment_time(self, dt: float) -> None:
        self.time += dt

    # Related to internal mobject organization

    def get_top_level_mobjects(self) -> list[Mobject]:
        # Return only those which are not in the family
        # of another mobject from the scene
        mobjects = self.get_mobjects()
        families = [m.get_family() for m in mobjects]

        def is_top_level(mobject):
            num_families = sum([
                (mobject in family)
                for family in families
            ])
            return num_families == 1
        return list(filter(is_top_level, mobjects))

    def get_mobject_family_members(self) -> list[Mobject]:
        return extract_mobject_family_members(self.mobjects)

    def assemble_render_groups(self):
        """
        Rendering can be more efficient when mobjects of the
        same type are grouped together, so this function creates
        Groups of all clusters of adjacent Mobjects in the scene
        """
        batches = batch_by_property(
            self.mobjects,
            lambda m: str(type(m)) + str(m.get_shader_wrapper(self.camera.ctx).get_id()) + str(m.z_index)
        )

        for group in self.render_groups:
            group.clear()
        self.render_groups = [
            batch[0].get_group_class()(*batch)
            for batch, key in batches
        ]

    @staticmethod
    def affects_mobject_list(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            func(self, *args, **kwargs)
            self.assemble_render_groups()
            return self
        return wrapper

    @affects_mobject_list
    def add(self, *new_mobjects: Mobject):
        """
        Mobjects will be displayed, from background to
        foreground in the order with which they are added.
        """
        self.remove(*new_mobjects)
        self.mobjects += new_mobjects

        # Reorder based on z_index
        id_to_scene_order = {id(m): idx for idx, m in enumerate(self.mobjects)}
        self.mobjects.sort(key=lambda m: (m.z_index, id_to_scene_order[id(m)]))

        self.id_to_mobject_map.update({
            id(sm): sm
            for m in new_mobjects
            for sm in m.get_family()
        })
        return self

    def add_mobjects_among(self, values: Iterable):
        """
        This is meant mostly for quick prototyping,
        e.g. to add all mobjects defined up to a point,
        call self.add_mobjects_among(locals().values())
        """
        self.add(*filter(
            lambda m: isinstance(m, Mobject),
            values
        ))
        return self

    @affects_mobject_list
    def replace(self, mobject: Mobject, *replacements: Mobject):
        if mobject in self.mobjects:
            index = self.mobjects.index(mobject)
            self.mobjects = [
                *self.mobjects[:index],
                *replacements,
                *self.mobjects[index + 1:]
            ]
        return self

    @affects_mobject_list
    def remove(self, *mobjects_to_remove: Mobject):
        """
        Removes anything in mobjects from scenes mobject list, but in the event that one
        of the items to be removed is a member of the family of an item in mobject_list,
        the other family members are added back into the list.

        For example, if the scene includes Group(m1, m2, m3), and we call scene.remove(m1),
        the desired behavior is for the scene to then include m2 and m3 (ungrouped).
        """
        to_remove = set(extract_mobject_family_members(mobjects_to_remove))
        new_mobjects, _ = recursive_mobject_remove(self.mobjects, to_remove)
        self.mobjects = new_mobjects

    @affects_mobject_list
    def remove_all_except(self, *mobjects_to_keep : Mobject):
        self.clear()
        self.add(*mobjects_to_keep)

    def bring_to_front(self, *mobjects: Mobject):
        self.add(*mobjects)
        return self

    @affects_mobject_list
    def bring_to_back(self, *mobjects: Mobject):
        self.remove(*mobjects)
        self.mobjects = list(mobjects) + self.mobjects
        return self

    @affects_mobject_list
    def clear(self):
        self.mobjects = []
        return self

    def get_mobjects(self) -> list[Mobject]:
        return list(self.mobjects)

    def get_mobject_copies(self) -> list[Mobject]:
        return [m.copy() for m in self.mobjects]

    def point_to_mobject(
        self,
        point: np.ndarray,
        search_set: Iterable[Mobject] | None = None,
        buff: float = 0
    ) -> Mobject | None:
        """
        E.g. if clicking on the scene, this returns the top layer mobject
        under a given point
        """
        if search_set is None:
            search_set = self.mobjects
        for mobject in reversed(search_set):
            if mobject.is_point_touching(point, buff=buff):
                return mobject
        return None

    def get_group(self, *mobjects):
        if all(isinstance(m, VMobject) for m in mobjects):
            return VGroup(*mobjects)
        else:
            return Group(*mobjects)

    def id_to_mobject(self, id_value):
        return self.id_to_mobject_map[id_value]

    def ids_to_group(self, *id_values):
        return self.get_group(*filter(
            lambda x: x is not None,
            map(self.id_to_mobject, id_values)
        ))

    def i2g(self, *id_values):
        return self.ids_to_group(*id_values)

    def i2m(self, id_value):
        return self.id_to_mobject(id_value)

    # Related to skipping

    def update_skipping_status(self) -> None:
        if self.start_at_animation_number is not None:
            if self.num_plays == self.start_at_animation_number:
                self.skip_time = self.time
                if not self.original_skipping_status:
                    self.stop_skipping()
        if self.end_at_animation_number is not None:
            if self.num_plays >= self.end_at_animation_number:
                raise EndScene()

    def stop_skipping(self) -> None:
        self.virtual_animation_start_time = self.time
        self.real_animation_start_time = time.time()
        self.skip_animations = False

    # Methods associated with running animations

    def get_time_progression(
        self,
        run_time: float,
        n_iterations: int | None = None,
        desc: str = "",
        override_skip_animations: bool = False
    ) -> list[float] | np.ndarray | ProgressDisplay:
        if self.skip_animations and not override_skip_animations:
            return [run_time]

        times = np.arange(0, run_time, 1 / self.camera.fps) + 1 / self.camera.fps

        self.file_writer.set_progress_display_description(sub_desc=desc)

        if self.show_animation_progress:
            return ProgressDisplay(
                times,
                total=n_iterations,
                leave=self.leave_progress_bars,
                ascii=True if platform.system() == 'Windows' else None,
                desc=desc,
                bar_format="{l_bar} {n_fmt:3}/{total_fmt:3} {rate_fmt}{postfix}",
            )
        else:
            return times

    def get_run_time(self, animations: Iterable[Animation]) -> float:
        return np.max([animation.get_run_time() for animation in animations])

    def get_animation_time_progression(
        self,
        animations: Iterable[Animation]
    ) -> list[float] | np.ndarray | ProgressDisplay:
        animations = list(animations)
        run_time = self.get_run_time(animations)
        description = f"{self.num_plays} {animations[0]}"
        if len(animations) > 1:
            description += ", etc."
        time_progression = self.get_time_progression(run_time, desc=description)
        return time_progression

    def get_wait_time_progression(
        self,
        duration: float,
        stop_condition: Callable[[], bool] | None = None
    ) -> list[float] | np.ndarray | ProgressDisplay:
        kw = {"desc": f"{self.num_plays} Waiting"}
        if stop_condition is not None:
            kw["n_iterations"] = -1  # So it doesn't show % progress
            kw["override_skip_animations"] = True
        return self.get_time_progression(duration, **kw)

    def pre_play(self):
        if self.presenter_mode and self.num_plays == 0:
            self.hold_loop()

        self.update_skipping_status()

        if not self.skip_animations:
            self.file_writer.begin_animation()

        if self.window:
            self.virtual_animation_start_time = self.time
            self.real_animation_start_time = time.time()

    def post_play(self):
        if not self.skip_animations:
            self.file_writer.end_animation()

        if self.preview_while_skipping and self.skip_animations and self.window is not None:
            # Show some quick frames along the way
            self.update_frame(dt=0, force_draw=True)

        self.num_plays += 1

    def begin_animations(self, animations: Iterable[Animation]) -> None:
        all_mobjects = set(self.get_mobject_family_members())
        for animation in animations:
            animation.begin()
            # Anything animated that's not already in the
            # scene gets added to the scene.  Note, for
            # animated mobjects that are in the family of
            # those on screen, this can result in a restructuring
            # of the scene.mobjects list, which is usually desired.
            if animation.mobject not in all_mobjects:
                self.add(animation.mobject)
                all_mobjects = all_mobjects.union(animation.mobject.get_family())

    def progress_through_animations(self, animations: Iterable[Animation]) -> None:
        last_t = 0
        for t in self.get_animation_time_progression(animations):
            dt = t - last_t
            last_t = t
            for animation in animations:
                animation.update_mobjects(dt)
                alpha = t / animation.run_time
                animation.interpolate(alpha)
            self.update_frame(dt)
            self.emit_frame()

    def finish_animations(self, animations: Iterable[Animation]) -> None:
        for animation in animations:
            animation.finish()
            animation.clean_up_from_scene(self)
        if self.skip_animations:
            self.update_mobjects(self.get_run_time(animations))
        else:
            self.update_mobjects(0)

    @affects_mobject_list
    def play(
        self,
        *proto_animations: Animation | _AnimationBuilder,
        run_time: float | None = None,
        rate_func: Callable[[float], float] | None = None,
        lag_ratio: float | None = None,
    ) -> None:
        """Play animations, saving a checkpoint once they complete."""
        if len(proto_animations) == 0:
            log.warning("Called Scene.play with no animations")
            return

        animations = list(map(prepare_animation, proto_animations))
        for anim in animations:
            anim.update_rate_info(run_time, rate_func, lag_ratio)

        if getattr(self, '_suppress_checkpoints', False):
            line_no, unit_index = None, None
        else:
            line_no, unit_index = self._find_animation_anchor()

        # Play the animation
        self.pre_play()
        self.begin_animations(animations)
        self.progress_through_animations(animations)
        self.finish_animations(animations)
        self.post_play()

        # Save checkpoint AFTER animation completes
        if line_no:
            namespace = self._capture_caller_namespace()
            self._save_checkpoint(line_no, unit_index, namespace)
            self._remember_scene_filepath()

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
            if '/manim/' not in frame_info.filename and frame_info.filename.endswith('.py'):
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
            if '/manim/' not in filename and filename.endswith('.py'):
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

    def wait(
        self,
        duration: Optional[float] = None,
        stop_condition: Callable[[], bool] = None,
        note: str = None,
        ignore_presenter_mode: bool = False
    ):
        if duration is None:
            duration = self.default_wait_time
        self.pre_play()
        self.update_mobjects(dt=0)  # Any problems with this?
        if self.presenter_mode and not self.skip_animations and not ignore_presenter_mode:
            if note:
                log.info(note)
            self.hold_loop()
        else:
            time_progression = self.get_wait_time_progression(duration, stop_condition)
            last_t = 0
            for t in time_progression:
                dt = t - last_t
                last_t = t
                self.update_frame(dt)
                self.emit_frame()
                if stop_condition is not None and stop_condition():
                    break
        self.post_play()

    def hold_loop(self):
        while self.hold_on_wait:
            self.update_frame(dt=1 / self.camera.fps)
        self.hold_on_wait = True

    def wait_until(
        self,
        stop_condition: Callable[[], bool],
        max_time: float = 60
    ):
        self.wait(max_time, stop_condition=stop_condition)

    def force_skipping(self):
        self.original_skipping_status = self.skip_animations
        self.skip_animations = True
        return self

    def revert_to_original_skipping_status(self):
        if hasattr(self, "original_skipping_status"):
            self.skip_animations = self.original_skipping_status
        return self

    def add_sound(
        self,
        sound_file: str,
        time_offset: float = 0,
        gain: float | None = None,
        gain_to_background: float | None = None
    ):
        if self.skip_animations:
            return
        time = self.get_time() + time_offset
        self.file_writer.add_sound(sound_file, time, gain, gain_to_background)

    # Helpers for interactive development

    def get_state(self) -> SceneState:
        return SceneState(self)

    @affects_mobject_list
    def restore_state(self, scene_state: SceneState):
        scene_state.restore_scene(self)

    def save_state(self) -> None:
        # Store a copy: a reference snapshot aliases the live mobjects
        # and mutates along with them, making undo a no-op
        state = self.get_state().copy()
        self.redo_stack = []
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_num_saved_states:
            self.undo_stack.pop(0)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.get_state().copy())
            self.restore_state(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.get_state().copy())
            self.restore_state(self.redo_stack.pop())

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

    @contextmanager
    def temp_skip(self):
        prev_status = self.skip_animations
        self.skip_animations = True
        try:
            yield
        finally:
            if not prev_status:
                self.stop_skipping()

    @contextmanager
    def temp_progress_bar(self):
        prev_progress = self.show_animation_progress
        self.show_animation_progress = True
        try:
            yield
        finally:
            self.show_animation_progress = prev_progress

    @contextmanager
    def temp_record(self):
        self.camera.use_window_fbo(False)
        self.file_writer.begin_insert()
        try:
            yield
        finally:
            self.file_writer.end_insert()
            self.camera.use_window_fbo(True)

    def temp_config_change(self, skip=False, record=False, progress_bar=False):
        stack = ExitStack()
        if skip:
            stack.enter_context(self.temp_skip())
        if record:
            stack.enter_context(self.temp_record())
        if progress_bar:
            stack.enter_context(self.temp_progress_bar())
        return stack

    def is_window_closing(self):
        return self.window and (self.window.is_closing or self.quit_interaction)

    # Event handling
    def set_floor_plane(self, plane: str = "xy"):
        if plane == "xy":
            self.frame.set_euler_axes("zxz")
        elif plane == "xz":
            self.frame.set_euler_axes("zxy")
        else:
            raise Exception("Only `xz` and `xy` are valid floor planes")

    def on_mouse_motion(
        self,
        point: Vect3,
        d_point: Vect3
    ) -> None:
        assert self.window is not None
        self.mouse_point.move_to(point)

        event_data = {"point": point, "d_point": d_point}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseMotionEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return

        frame = self.camera.frame
        # Handle perspective changes
        if self.window.is_key_pressed(ord(manim_config.key_bindings.pan_3d)):
            ff_d_point = frame.to_fixed_frame_point(d_point, relative=True)
            ff_d_point *= self.pan_sensitivity
            frame.increment_theta(-ff_d_point[0])
            frame.increment_phi(ff_d_point[1])
        # Handle frame movements
        elif self.window.is_key_pressed(ord(manim_config.key_bindings.pan)):
            frame.shift(-d_point)

    def on_mouse_drag(
        self,
        point: Vect3,
        d_point: Vect3,
        buttons: int,
        modifiers: int
    ) -> None:
        self.mouse_drag_point.move_to(point)
        if self.drag_to_pan:
            self.frame.shift(-d_point)

        event_data = {"point": point, "d_point": d_point, "buttons": buttons, "modifiers": modifiers}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseDragEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return

    def on_mouse_press(
        self,
        point: Vect3,
        button: int,
        mods: int
    ) -> None:
        self.mouse_drag_point.move_to(point)
        event_data = {"point": point, "button": button, "mods": mods}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MousePressEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return

    def on_mouse_release(
        self,
        point: Vect3,
        button: int,
        mods: int
    ) -> None:
        event_data = {"point": point, "button": button, "mods": mods}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseReleaseEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return

    def on_mouse_scroll(
        self,
        point: Vect3,
        offset: Vect3,
        x_pixel_offset: float,
        y_pixel_offset: float
    ) -> None:
        event_data = {"point": point, "offset": offset}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.MouseScrollEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return

        rel_offset = y_pixel_offset / self.camera.get_pixel_height()
        self.frame.scale(
            1 - self.scroll_sensitivity * rel_offset,
            about_point=point
        )

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

        print(f"Animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1} complete")

    def _play_reverse_to(self, index: int) -> None:
        """Animate the display back to the checkpoint at `index`.

        This is a whole-scene morph between the current display and the
        target state, not a true reversal of the original animation
        (source re-execution can't run backwards), so complex changes
        blend rather than retrace. Lands exactly on a copy of the
        target state; falls back to an instant jump if the morph fails.
        """
        from manim.animation.transform import Transform

        target_state = self.animation_checkpoints[index]['state'].copy()
        try:
            current = Group(*self.mobjects)
            target = Group(*target_state.mobjects)
            if len(current.get_family()) > 1 and len(target.get_family()) > 1:
                with self._no_checkpoints():
                    self.play(Transform(current, target), run_time=0.7)
        except Exception as e:
            log.warning(f"Reverse transition failed ({e}); jumping instead")
        # Land exactly on the checkpoint state regardless of how the
        # morph went
        self.clear()
        self.restore_state(target_state)

    def on_key_release(
        self,
        symbol: int,
        modifiers: int
    ) -> None:
        event_data = {"symbol": symbol, "modifiers": modifiers}
        propagate_event = EVENT_DISPATCHER.dispatch(EventType.KeyReleaseEvent, **event_data)
        if propagate_event is not None and propagate_event is False:
            return

    def on_key_press(
        self,
        symbol: int,
        modifiers: int
    ) -> None:
        # Handle UP arrow - jump to previous animation
        if symbol == PygletWindowKeys.UP:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index > 0:
                self.current_animation_index -= 1
                checkpoint = self.animation_checkpoints[self.current_animation_index]
                print(f"↑ Jump to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                # Restore a copy: putting the stored mobjects on screen
                # would let later mutation corrupt the checkpoint
                self.restore_state(checkpoint['state'].copy())
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at first animation")
        
        # Handle DOWN arrow - jump to next animation
        elif symbol == PygletWindowKeys.DOWN:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index < len(self.animation_checkpoints) - 1:
                self.current_animation_index += 1
                checkpoint = self.animation_checkpoints[self.current_animation_index]
                print(f"↓ Jump to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                self.restore_state(checkpoint['state'].copy())
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at last animation")
        
        # Handle LEFT arrow - play animation in reverse
        elif symbol == PygletWindowKeys.LEFT:
            # Prevent handling if we're already processing a key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
                
            if self.current_animation_index > 0:
                # Set flag to prevent re-entry
                self._processing_key = True
                try:
                    self.current_animation_index -= 1
                    print(f"← Reverse to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                    self._play_reverse_to(self.current_animation_index)
                    self.update_frame(dt=0, force_draw=True)
                finally:
                    # Clear the flag
                    self._processing_key = False
            else:
                print("Already at first animation")
        
        # Handle RIGHT arrow - play next animation forward
        elif symbol == PygletWindowKeys.RIGHT:
            # Prevent handling if we're already processing a key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
            
            # Set flag to prevent re-entry
            self._processing_key = True
            try:
                self.run_next_animation()
            finally:
                self._processing_key = False
        
        else:
            # Handle other keys
            try:
                char = chr(symbol)
            except OverflowError:
                log.warning("The value of the pressed key is too large.")
                return

            event_data = {"symbol": symbol, "modifiers": modifiers}
            propagate_event = EVENT_DISPATCHER.dispatch(EventType.KeyPressEvent, **event_data)
            if propagate_event is not None and propagate_event is False:
                return

            if char == manim_config.key_bindings.reset:
                self.play(self.camera.frame.animate.to_default_state())
            elif char == "z" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
                self.undo()
            elif char == "z" and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL | PygletWindowKeys.MOD_SHIFT)):
                self.redo()
            # command + q
            elif char == manim_config.key_bindings.quit and (modifiers & (PygletWindowKeys.MOD_COMMAND | PygletWindowKeys.MOD_CTRL)):
                self.quit_interaction = True
            # Space
            elif char == " ":
                self.hold_on_wait = False

    def on_resize(self, width: int, height: int) -> None:
        pass

    def on_show(self) -> None:
        pass

    def on_hide(self) -> None:
        pass

    def on_close(self) -> None:
        pass

    def focus(self) -> None:
        """
        Puts focus on the ManimGL window.
        """
        if not self.window:
            return
        self.window.focus()

    def set_background_color(self, background_color, background_opacity=1) -> None:
        self.camera.background_rgba = list(color_to_rgba(
            background_color, background_opacity
        ))


class SceneState():
    def __init__(self, scene: Scene, ignore: list[Mobject] | None = None):
        self.time = scene.time
        self.num_plays = scene.num_plays
        # Store direct references instead of copies
        self.mobjects = list(scene.mobjects)
        if ignore:
            self.mobjects = [mob for mob in self.mobjects if mob not in ignore]

        # For compatibility, keep the old attribute name but with direct references
        self.mobjects_to_copies = OrderedDict()
        for mob in self.mobjects:
            self.mobjects_to_copies[mob] = mob  # Direct reference, not a copy

        # Save camera frame state (since it's mutated by animations but stored as reference)
        if hasattr(scene, 'camera') and hasattr(scene.camera, 'frame'):
            self.camera_frame_points = scene.camera.frame.get_points().copy()
        else:
            self.camera_frame_points = None

    def __eq__(self, state: SceneState):
        return all((
            self.time == state.time,
            self.num_plays == state.num_plays,
            self.mobjects_to_copies == state.mobjects_to_copies
        ))

    def mobjects_match(self, state: SceneState):
        return self.mobjects_to_copies == state.mobjects_to_copies

    def n_changes(self, state: SceneState):
        m2c = state.mobjects_to_copies
        return sum(
            1 - int(mob in m2c and mob.looks_identical(m2c[mob]))
            for mob in self.mobjects_to_copies
        )

    def copy(self) -> SceneState:
        """Return an isolated deep copy of this state.

        SceneState itself stores direct references (checkpoint saving
        deep-copies state and namespace together to preserve identity).
        Anything restored for *display* must be a copy, or on-screen
        mutation (updaters, dragging, later animations) would corrupt
        the stored history.
        """
        return deepcopy_namespace({'__state__': self})['__state__']

    def restore_scene(self, scene: Scene):
        scene.time = self.time
        scene.num_plays = self.num_plays
        # Use the stored mobjects directly (they're references now, not copies)
        scene.mobjects = list(self.mobjects)
        # Restore camera frame state
        if self.camera_frame_points is not None and hasattr(scene, 'camera') and hasattr(scene.camera, 'frame'):
            scene.camera.frame.set_points(self.camera_frame_points)


class EndScene(Exception):
    pass


class ThreeDScene(Scene):
    samples = 4
    default_frame_orientation = (-30, 70)
    always_depth_test = True

    def add(self, *mobjects: Mobject, set_depth_test: bool = True, perp_stroke: bool = True):
        for mob in mobjects:
            if set_depth_test and not mob.is_fixed_in_frame() and self.always_depth_test:
                mob.apply_depth_test()
                
                # Special handling for text objects - ensure all submobjects get depth test
                if hasattr(mob, '__class__') and any(base.__name__ in ['Text', 'MarkupText', 'StringMobject']
                                                     for base in mob.__class__.__mro__):
                    # Force refresh on all family members
                    for submob in mob.get_family():
                        submob.depth_test = True
                        if hasattr(submob, 'refresh_shader_wrapper_id'):
                            submob.refresh_shader_wrapper_id()

            if isinstance(mob, VMobject):
                # Check if this is a text object - don't use triangulated fill for text
                # as it breaks the SVG path rendering
                is_text = any(base.__name__ in ['Text', 'MarkupText', 'StringMobject', 'SVGMobject']
                              for base in mob.__class__.__mro__)

                if not is_text:
                    # Enable triangulated fill for proper 3D depth (but not for text)
                    mob.use_triangulated_fill = True
                    # Apply to all submobjects as well
                    for submob in mob.get_family():
                        if isinstance(submob, VMobject):
                            submob.use_triangulated_fill = True

                if mob.has_stroke() and perp_stroke:
                    mob.set_flat_stroke(False)
        super().add(*mobjects)
    
    def set_camera_orientation(
        self,
        phi: float | None = None,
        theta: float | None = None,
        gamma: float | None = None,
        zoom: float | None = None,
        focal_distance: float | None = None,
        frame_center: np.ndarray | None = None,
    ):
        """Set the camera's spherical orientation."""
        if phi is not None:
            self.frame.set_phi(phi)
        if theta is not None:
            self.frame.set_theta(theta)
        if gamma is not None:
            self.frame.set_gamma(gamma)
        if zoom is not None:
            self.frame.scale(zoom)
        if focal_distance is not None:
            self.frame.set_focal_distance(focal_distance)
        if frame_center is not None:
            self.frame.move_to(frame_center)
    
    def begin_ambient_camera_rotation(self, rate: float = 0.02, about: str = "theta"):
        """Begin ambient rotation of the camera."""
        # Store the rotation state
        self.ambient_rotation_rate = rate
        self.ambient_rotation_about = about
        self.ambient_rotation_active = True
        
    def stop_ambient_camera_rotation(self):
        """Stop ambient rotation of the camera."""
        self.ambient_rotation_active = False
    
    def update_mobjects(self, dt: float) -> None:
        """Update mobjects and handle ambient camera rotation."""
        super().update_mobjects(dt)
        
        # Handle ambient camera rotation if active
        if hasattr(self, 'ambient_rotation_active') and self.ambient_rotation_active:
            if self.ambient_rotation_about == "theta":
                new_theta = self.frame.get_theta() + self.ambient_rotation_rate
                self.frame.set_theta(new_theta)
            elif self.ambient_rotation_about == "phi":
                new_phi = self.frame.get_phi() + self.ambient_rotation_rate
                self.frame.set_phi(new_phi)
            elif self.ambient_rotation_about == "gamma":
                new_gamma = self.frame.get_gamma() + self.ambient_rotation_rate
                self.frame.set_gamma(new_gamma)


"""Utility functions for scene checkpoint management."""

import copy
from manim.mobject.mobject import Mobject


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

    # SceneState must be copied
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
        # If deepcopy fails, try copying items individually
        print(f"Warning: Batch deepcopy failed ({e}), falling back to individual copy")

        new_namespace = {}

        for name, value in must_copy.items():
            try:
                new_namespace[name] = copy.deepcopy(value)
            except Exception:
                # If individual copy fails, keep reference
                new_namespace[name] = value

        # Add references
        for name, value in references.items():
            new_namespace[name] = value

        return new_namespace
