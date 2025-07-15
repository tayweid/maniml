from __future__ import annotations

from collections import OrderedDict
import platform
import random
import time
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
        self.animation_checkpoints = []  # List of dicts with {index, line_number, state, namespace}
        self.current_animation_index = -1
        self._navigating_animations = False  # Flag to prevent checkpoint creation during navigation
        self._processing_key = False  # Flag to prevent re-entry during key processing
        
        # File watcher for auto-reload
        self._file_watcher = None
        self._file_changed_flag = False  # Thread-safe flag for file changes
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

    def _create_checkpoint_zero(self) -> None:
        """
        Create checkpoint 0 with the full namespace from the scene file.
        Called right before construct() to capture all imports.
        """
        import sys
        
        # Get the main module namespace (the scene file that was run)
        namespace = {}
        
        # If we have the scene filepath, use it to find the module
        if hasattr(self, '_scene_filepath') and self._scene_filepath:
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
        log.info(
            "\nTips: Using the keys `d`, `f`, or `z` " +
            "you can interact with the scene. " +
            "Press `command + q` or `esc` to quit"
        )
        
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
            log.info(f"Setting up file watcher for: {self._scene_filepath}")
            self._file_watcher = FileWatcher(self._scene_filepath)
            self._file_watcher.start(self._on_file_changed)
        else:
            log.warning("No scene filepath available, file watching disabled")
    
    def _on_file_changed(self, change_info: dict) -> None:
        """Callback when file changes are detected."""
        log.info(f"File change detected: Line {change_info['earliest_changed_line']}, Safe animation index: {change_info['safe_animation_index']}")
        # Set flag for main thread to handle
        self._file_changed_flag = True
        self._pending_change_info = change_info
    
    def _handle_file_change(self) -> None:
        """Handle file changes in the main thread."""
        if not hasattr(self, '_pending_change_info'):
            return
            
        change_info = self._pending_change_info
        log.info(f"Handling file change at line {change_info['earliest_changed_line']}")
        
        earliest_change = change_info['earliest_changed_line']
        safe_animation_index = change_info['safe_animation_index']
        current_checkpoint = self.animation_checkpoints[self.current_animation_index]
        current_line = current_checkpoint['line_number']
        
        log.info(f"Current checkpoint {self.current_animation_index} at line {current_line}")
        log.info(f"Safe animation index from tracker: {safe_animation_index}")
        
        # The safe_animation_index is the last animation before the edit
        # But if the edit IS on an animation line, we need to run that animation
        # Check if the edited line is an animation line
        animation_lines = change_info.get('animation_lines', [])
        if animation_lines and earliest_change in animation_lines:
            # The edit is ON an animation line, so we need to run that animation
            target_animation_index = animation_lines.index(earliest_change)
            log.info(f"Edit is ON animation line, target animation index: {target_animation_index}")
        else:
            # The edit is between animations, so run the next one after safe
            target_animation_index = safe_animation_index + 1 if safe_animation_index is not None else 0
            log.info(f"Edit is between animations, target animation index: {target_animation_index}")
        
        # Debug: Let's see what the AnimationTracker is telling us
        log.info(f"AnimationTracker says: safe_animation_index={safe_animation_index}, target={target_animation_index}")
        
        # Debug: Show all checkpoint line numbers
        checkpoint_lines = [cp['line_number'] for cp in self.animation_checkpoints]
        log.info(f"Current checkpoints at lines: {checkpoint_lines}")
        
        # Case 1: Edit is after current position - need to forward to it
        if target_animation_index > self.current_animation_index:
            log.info(f"Edit is after current position, need to forward to animation {target_animation_index}")
            
            # Jump to the animation just before the target if we can
            if target_animation_index - 1 < len(self.animation_checkpoints) and target_animation_index - 1 > self.current_animation_index:
                jump_to_idx = target_animation_index - 1
                log.info(f"Jumping forward to checkpoint {jump_to_idx}")
                self.current_animation_index = jump_to_idx
                checkpoint = self.animation_checkpoints[jump_to_idx]
                self.restore_state(checkpoint['state'])
                self.update_frame(dt=0, force_draw=True)
            
            # Now run animations until we've played the edited line
            while True:
                # Check if we've reached or passed the edited line
                current_checkpoint = self.animation_checkpoints[self.current_animation_index]
                if current_checkpoint['line_number'] >= earliest_change:
                    log.info(f"Current checkpoint at line {current_checkpoint['line_number']} covers edit at line {earliest_change}")
                    break
                
                # Run the next animation
                log.info(f"Current at line {current_checkpoint['line_number']}, running next animation to reach line {earliest_change}")
                last_index = self.current_animation_index
                self.run_next_animation()
                
                # Check if we advanced
                if self.current_animation_index == last_index:
                    log.info("No more animations available")
                    break
                        
        # Case 2: Edit is before current position - need to rewind
        else:
            log.info(f"Edit is before current position, need to rewind")
            
            # Find the safe checkpoint to restore to
            safe_checkpoint_idx = -1
            for i, checkpoint in enumerate(self.animation_checkpoints):
                if checkpoint['line_number'] < earliest_change:
                    safe_checkpoint_idx = i
                else:
                    break
            
            log.info(f"Safe checkpoint index: {safe_checkpoint_idx}")
            
            # Truncate checkpoints after the safe point
            if safe_checkpoint_idx >= 0:
                self.animation_checkpoints = self.animation_checkpoints[:safe_checkpoint_idx + 1]
                self.current_animation_index = safe_checkpoint_idx
                
                # Restore the checkpoint state
                checkpoint = self.animation_checkpoints[safe_checkpoint_idx]
                self.restore_state(checkpoint['state'])
                log.info(f"Restored to checkpoint {safe_checkpoint_idx}")
                
                # Force a frame update to show the restored state
                self.update_frame(dt=0, force_draw=True)
                
                # Run animations through the edited line
                # We need to run at least the animation that contains the edit
                while True:
                    # Run the next animation
                    log.info(f"Running animation to show edited content")
                    last_index = self.current_animation_index
                    self.run_next_animation()
                    
                    # Check if we've covered the edit
                    current_checkpoint = self.animation_checkpoints[self.current_animation_index]
                    if current_checkpoint['line_number'] >= earliest_change:
                        log.info(f"Animation at line {current_checkpoint['line_number']} covers the edit")
                        break
                    
                    # Check if we didn't advance (no more animations)
                    if self.current_animation_index == last_index:
                        log.info("No more animations available")
                        break
            else:
                log.info("No safe checkpoint found, would need to restart from beginning")
                # TODO: Implement full restart logic

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
        """Play animations with checkpoint support."""
        if len(proto_animations) == 0:
            log.warning("Called Scene.play with no animations")
            return
            
        animations = list(map(prepare_animation, proto_animations))
        for anim in animations:
            anim.update_rate_info(run_time, rate_func, lag_ratio)
            
        # Don't save checkpoints if we're navigating with arrow keys
        save_checkpoint = not (hasattr(self, '_navigating_animations') and self._navigating_animations)
        
        # Get the line number where this play was called
        line_no = None
        if save_checkpoint:
            # Check if we have a line number passed from run_next_animation
            # Walk up the stack to find our special variable
            frame = inspect.currentframe()
            while frame:
                if '__animation_line_number__' in frame.f_locals:
                    line_no = frame.f_locals['__animation_line_number__']
                    break
                if '__animation_line_number__' in frame.f_globals:
                    line_no = frame.f_globals['__animation_line_number__']
                    break
                frame = frame.f_back
            
            if line_no is None:
                # We need to find the line number in the actual scene file
                import traceback
                stack = traceback.extract_stack()
                
                # Find the call from the user's scene file
                for frame_info in reversed(stack):
                    # Skip internal manim files
                    if '/manim/' not in frame_info.filename and frame_info.filename.endswith('.py'):
                        line_no = frame_info.lineno
                        break
                        
                if line_no is None:
                    # Fallback to direct caller
                    line_no = frame.f_lineno
            
        # Play the animation
        self.pre_play()
        self.begin_animations(animations)
        self.progress_through_animations(animations)
        self.finish_animations(animations)
        self.post_play()
        
        # Save checkpoint AFTER animation completes
        if save_checkpoint and line_no:
            # We need to find the construct method's frame
            frame = inspect.currentframe()
            namespace = {}
            
            # Walk up the call stack to find the construct method
            while frame:
                # Check if this is the construct method
                if 'self' in frame.f_locals and frame.f_code.co_name == 'construct':
                    # Found it! Get local variables
                    namespace = frame.f_locals.copy()
                    # Also get globals from the module
                    namespace.update(frame.f_globals)
                    break
                # Also check if we're running from exec (called by run_next_animation)
                elif frame.f_code.co_filename == '<string>':
                    # We're in exec'd code - get the globals which is our checkpoint namespace
                    namespace = frame.f_globals.copy()
                    # Also include locals
                    namespace.update(frame.f_locals)
                    break
                frame = frame.f_back
            
            # If we didn't find construct, fall back to direct caller
            if not namespace:
                frame = inspect.currentframe().f_back
                namespace = frame.f_locals.copy()
                namespace.update(frame.f_globals)
            
            # Add current state to namespace BEFORE deepcopy
            namespace['__checkpoint_state__'] = self.get_state()
            
            # Deep copy everything together - references are preserved!
            checkpoint_namespace = deepcopy_namespace(namespace)
            
            # Extract state from deepcopied namespace
            checkpoint_state = checkpoint_namespace.pop('__checkpoint_state__')
            
            # Save checkpoint
            self.current_animation_index += 1
            checkpoint = {
                'index': self.current_animation_index,
                'line_number': line_no,
                'state': checkpoint_state,
                'namespace': checkpoint_namespace
            }
            
            # Check if we're replacing an existing checkpoint or creating a new one
            if self.current_animation_index < len(self.animation_checkpoints):
                # We're re-running an animation, replace the checkpoint
                self.animation_checkpoints[self.current_animation_index] = checkpoint
            else:
                # New checkpoint
                self.animation_checkpoints.append(checkpoint)
            
            # Store scene file path if available
            # We need to find the actual scene file, not scene.py
            if not hasattr(self, '_scene_filepath') or not self._scene_filepath:
                # Walk up the call stack to find the user's scene file
                import traceback
                for frame_info in traceback.extract_stack():
                    filename = frame_info.filename
                    # Skip internal manim files
                    if '/manim/' not in filename and filename.endswith('.py'):
                        self._scene_filepath = filename
                        break

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
        state = self.get_state()
        if self.undo_stack and state.mobjects_match(self.undo_stack[-1]):
            return
        self.redo_stack = []
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_num_saved_states:
            self.undo_stack.pop(0)

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self.get_state())
            self.restore_state(self.undo_stack.pop())

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self.get_state())
            self.restore_state(self.redo_stack.pop())

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
        """Run the next animation using checkpoint_temporary workflow."""
        
        # Get current checkpoint
        current_checkpoint = self.animation_checkpoints[self.current_animation_index]
        next_index = self.current_animation_index + 1
        
        # Deep copy the entire checkpoint to preserve references between state and namespace
        checkpoint_temporary = deepcopy_namespace(current_checkpoint)
        
        # Clear the scene completely - start fresh
        self.clear()
        
        # Restore state from the deep copied checkpoint
        # This adds all the mobjects to the scene
        self.restore_state(checkpoint_temporary['state'])
        
        # Add self reference to namespace
        checkpoint_temporary['namespace']['self'] = self

        # Get the code to run
        if hasattr(self, '_scene_filepath') and self._scene_filepath:
            try:
                with open(self._scene_filepath, 'r') as f:
                    lines = f.readlines()
                
                # Extract code from current checkpoint to next play() call
                current_line = current_checkpoint['line_number']
                code_lines = []
                in_construct = False
                base_indent = None
                found_next_play = False
                next_line_number = 0
                
                for i, line in enumerate(lines):
                    line_no = i + 1
                    
                    if 'def construct(self):' in line:
                        in_construct = True
                        base_indent = len(line) - len(line.lstrip())
                        continue
                    
                    if in_construct:
                        # Check if we've exited construct
                        if line.strip() and not line.startswith(' ' * (base_indent + 1)):
                            break
                        
                        # Start collecting after current line
                        # Special case: for checkpoint 0, start from beginning of construct
                        if line_no > current_line or (current_line == 0 and in_construct):
                            # Stop at next play() call
                            if 'self.play(' in line or '.play(' in line:
                                found_next_play = True
                                next_line_number = line_no
                                # Include the play line
                                code_lines.append(line.rstrip())
                                
                                # Check if play continues on next lines (multi-line play call)
                                # Count open and close parentheses to handle nested calls
                                paren_count = line.count('(') - line.count(')')
                                j = i + 1
                                while j < len(lines) and paren_count > 0:
                                    next_line = lines[j]
                                    code_lines.append(next_line.rstrip())
                                    paren_count += next_line.count('(') - next_line.count(')')
                                    j += 1
                                break
                            else:
                                code_lines.append(line.rstrip())
                
                if found_next_play and code_lines:
                    # Remove common indentation from all lines
                    if code_lines:
                        # Find minimum indentation (excluding empty lines)
                        min_indent = float('inf')
                        for line in code_lines:
                            if line.strip():  # Skip empty lines
                                indent = len(line) - len(line.lstrip())
                                min_indent = min(min_indent, indent)
                        
                        # Remove the common indentation
                        if min_indent < float('inf'):
                            code_lines = [line[min_indent:] if line.strip() else line for line in code_lines]
                    
                    code_to_run = '\n'.join(code_lines)
                    
                    # Set flag to allow next checkpoint
                    self._navigating_animations = False
                    
                    print(f"→ Running animation {next_index} at line {next_line_number}")
                    print(f"DEBUG: Scene has {len(self.mobjects)} mobjects before exec")
                    
                    # Pass the line number through the namespace so play() can use it
                    checkpoint_temporary['namespace']['__animation_line_number__'] = next_line_number
                    
                    # Execute in the checkpoint namespace
                    exec(code_to_run, checkpoint_temporary['namespace'])
                    
                    print(f"Animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1} complete")
                else:
                    print(f"No more animations found after line {current_line}")
                    
            except FileNotFoundError:
                print(f"Scene file not found: {self._scene_filepath}")
            except Exception as e:
                print(f"Error running animation: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("No scene file path stored")

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
            
            # If animation is playing, skip to end first
            if hasattr(self, 'playing') and self.playing:
                self.skip_animations = True
                return  # Let animation finish, then user can press UP again
                
            if self.current_animation_index > 0:
                self.current_animation_index -= 1
                checkpoint = self.animation_checkpoints[self.current_animation_index]
                print(f"↑ Jump to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                self.restore_state(checkpoint['state'])
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at first animation")
        
        # Handle DOWN arrow - jump to next animation
        elif symbol == PygletWindowKeys.DOWN:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return
            
            # If animation is playing, skip to end first
            if hasattr(self, 'playing') and self.playing:
                self.skip_animations = True
                return  # Let animation finish, then user can press DOWN again
                
            if self.current_animation_index < len(self.animation_checkpoints) - 1:
                self.current_animation_index += 1
                checkpoint = self.animation_checkpoints[self.current_animation_index]
                print(f"↓ Jump to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                self.restore_state(checkpoint['state'])
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
                    # Get the current checkpoint and the previous one
                    current_checkpoint = self.animation_checkpoints[self.current_animation_index]
                    prev_checkpoint = self.animation_checkpoints[self.current_animation_index - 1]
                    
                    # We need to reverse the animation from current to previous state
                    # This is tricky - for now just jump back
                    self.current_animation_index -= 1
                    print(f"← Reverse to animation {self.current_animation_index}/{len(self.animation_checkpoints) - 1}")
                    self.restore_state(prev_checkpoint['state'])
                    self.update_frame(dt=0, force_draw=True)
                    # TODO: Implement actual reverse animation playback
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

    def restore_scene(self, scene: Scene):
        scene.time = self.time
        scene.num_plays = self.num_plays
        # Use the stored mobjects directly (they're references now, not copies)
        scene.mobjects = list(self.mobjects)


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
            if isinstance(mob, VMobject) and mob.has_stroke() and perp_stroke:
                mob.set_flat_stroke(False)
        super().add(*mobjects)


"""Utility functions for scene checkpoint management."""

import copy
from manim.mobject.mobject import Mobject


def deepcopy_namespace(namespace_or_checkpoint):
    """Deep copy a namespace or checkpoint, filtering out uncopyable items first."""
    import copy
    
    # Check if this is a checkpoint dict (has 'namespace' and 'state' keys)
    if isinstance(namespace_or_checkpoint, dict) and 'namespace' in namespace_or_checkpoint and 'state' in namespace_or_checkpoint:
        # This is a checkpoint - we need to deepcopy namespace and state together
        checkpoint = namespace_or_checkpoint
        
        # Combine namespace and state into one dict for deepcopying together
        combined = {}
        combined['__checkpoint_state__'] = checkpoint['state']
        
        # Add namespace items
        for name, value in checkpoint['namespace'].items():
            if name in ['__builtins__', '__loader__', '__spec__', '__cached__', 'self']:
                continue
            combined[name] = value
            
        # Test what can be deepcopied
        deepcopyable = {}
        non_deepcopyable = {}
        
        for name, value in combined.items():
            try:
                test_copy = copy.deepcopy(value)
                deepcopyable[name] = value
            except Exception:
                non_deepcopyable[name] = value
                
        # Deepcopy all deepcopyable items together
        try:
            copied_items = copy.deepcopy(deepcopyable)
            
            # Extract the state
            state = copied_items.pop('__checkpoint_state__', checkpoint['state'])
            
            # Add non-deepcopyable items
            for name, value in non_deepcopyable.items():
                if name != '__checkpoint_state__':
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
    
    # First pass: test what can be deepcopied
    deepcopyable = {}
    non_deepcopyable = {}
    
    for name, value in namespace.items():
        # Always skip these
        if name in ['__builtins__', '__loader__', '__spec__', '__cached__', 'self']:
            continue
            
        # Test if this item can be deepcopied
        try:
            test_copy = copy.deepcopy(value)
            deepcopyable[name] = value
        except Exception:
            # Can't deepcopy this item, keep as reference
            non_deepcopyable[name] = value
    
    # Second pass: deepcopy all deepcopyable items together
    # This preserves reference relationships between them
    try:
        copied_items = copy.deepcopy(deepcopyable)
        
        # Add back the non-deepcopyable items as references
        for name, value in non_deepcopyable.items():
            copied_items[name] = value
            
        return copied_items
        
    except Exception as e:
        # If even this fails, fall back to manual implementation
        print(f"Warning: Filtered deepcopy failed ({e}), falling back to individual copy")
        
        # Fallback implementation
        new_namespace = {}
        
        for name, value in filtered.items():
            try:
                if isinstance(value, Mobject):
                    # Deep copy mobjects
                    new_namespace[name] = value.copy()
                elif isinstance(value, (list, tuple)):
                    # Handle collections that might contain mobjects
                    new_items = []
                    for item in value:
                        if isinstance(item, Mobject):
                            new_items.append(item.copy())
                        else:
                            new_items.append(item)
                    new_namespace[name] = type(value)(new_items)
                elif isinstance(value, dict):
                    # Handle dicts that might contain mobjects
                    new_dict = {}
                    for k, v in value.items():
                        if isinstance(v, Mobject):
                            new_dict[k] = v.copy()
                        else:
                            new_dict[k] = v
                    new_namespace[name] = new_dict
                else:
                    # Try to deepcopy, but fall back to reference if it fails
                    try:
                        new_namespace[name] = copy.deepcopy(value)
                    except (TypeError, AttributeError):
                        # Keep reference for unpicklable objects
                        new_namespace[name] = value
            except Exception:
                # If anything goes wrong, keep the reference
                new_namespace[name] = value
                
        return new_namespace
