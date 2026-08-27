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

from maniml.animation.animation import prepare_animation
from maniml.camera.camera import Camera
from maniml.camera.camera_frame import CameraFrame
from maniml.config import manim_config
from maniml.logger import log
from maniml.performance import performance
from maniml.mobject.mobject import _AnimationBuilder
from maniml.mobject.mobject import Group
from maniml.mobject.mobject import Mobject
from maniml.mobject.mobject import Point
from maniml.mobject.types.vectorized_mobject import VGroup
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.scene.scene_file_writer import SceneFileWriter
from maniml.utils.dict_ops import merge_dicts_recursively
from maniml.utils.family_ops import extract_mobject_family_members
from maniml.utils.family_ops import recursive_mobject_remove
from maniml.utils.iterables import batch_by_property
from maniml.utils.sounds import play_sound
from maniml.utils.color import color_to_rgba
from maniml.rendering.window import Window
from maniml.scene.checkpoints import CheckpointMixin
from maniml.scene.checkpoints import deepcopy_namespace  # re-export
from maniml.scene.interaction import InteractionMixin
from maniml.scene.presentation import PresentationMixin

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable, Iterable, TypeVar, Optional
    from maniml.typing import Vect3

    T = TypeVar('T')

    from PIL.Image import Image

    from maniml.animation.animation import Animation


class _RenderBatch:
    """Non-owning render aggregation for one adjacent shader batch.

    A normal Group registers itself in every member's semantic ``parents``
    list.  Render batching is ephemeral, so those links must not enter
    checkpoints or mutation traversal.  This wrapper keeps the batching
    behavior while polling the semantic family for dirty data at render
    time, without becoming part of that family.
    """

    def __init__(self, mobjects: Iterable[Mobject]):
        self.mobjects = tuple(mobjects)
        group_class = self.mobjects[0].get_group_class()
        self._group = group_class(*self.mobjects)
        # Group construction performs useful class-specific setup, but its
        # normal parent registration is semantic ownership.  Detach those
        # links immediately; this batch keeps only non-owning references.
        for mobject in self.mobjects:
            if self._group in mobject.parents:
                mobject.parents.remove(self._group)
        self._group.family = None
        self._family_ids: tuple[int, ...] = ()

    def is_fixed_in_frame(self) -> bool:
        return self.mobjects[0].is_fixed_in_frame()

    def family_members_with_points(self) -> list[Mobject]:
        """Expose the read-only drawable family geometry export expects."""
        self._group.family = None
        return self._group.family_members_with_points()

    def render(self, ctx, camera_uniforms: dict) -> None:
        # Semantic family structure can change during an animation.  Re-read
        # it cheaply and rebuild the merged wrapper only when membership or
        # member data changed.
        self._group.family = None
        family = self._group.get_family()
        family_ids = tuple(id(mob) for mob in family[1:])
        if family_ids != self._family_ids or any(
                mob._data_has_changed for mob in family[1:]):
            self._group._data_has_changed = True
            self._family_ids = family_ids
        self._group.render(ctx, camera_uniforms)
        # These semantic mobjects were consumed by this batch.  A later
        # mutation marks them dirty again through their real parent chain.
        for mob in family[1:]:
            mob._data_has_changed = False


class Scene(CheckpointMixin, InteractionMixin, PresentationMixin):
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
        # The browser viewer (--web) stands in for the pyglet window
        # everywhere except the camera, which runs on its standalone
        # (windowless) GL context — the same path --render uses
        self._web_viewer = window if getattr(window, 'is_web_viewer', False) else None
        if self.window:
            self.window.init_for_scene(self)
            # Make sure camera and Pyglet window sync
            self.camera_config["fps"] = 30

        # Core state of the scene
        self.camera: Camera = Camera(
            window=None if self._web_viewer else self.window,
            samples=self.samples,
            **self.camera_config
        )
        self.frame: CameraFrame = self.camera.frame
        self.frame.reorient(*self.default_frame_orientation)
        self.frame.make_orientation_default()

        self.file_writer = SceneFileWriter(self, **self.file_writer_config)
        self.mobjects: list[Mobject] = [self.camera.frame]
        self.render_groups: list[Mobject] = []
        self._mobject_list_mutation_depth = 0
        self._mobject_list_mutation_dirty = False
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
        # The newest checkpoint whose source lineage has actually run.
        # Display navigation may move current_animation_index behind it.
        self.frontier_index = -1
        self._processing_key = False  # Flag to prevent re-entry during key processing
        self._source_units_cache = None  # ((path, mtime), units) for the parsed scene file
        self._live_namespace = {}  # Variable name -> live (on-screen) object, for click-to-inspect

        # Run modes (set by __main__)
        self._present_mode = False  # Pre-built checkpoints, watcher off, timeline scrubber
        self._render_mode = False   # Headless: write video + checkpoint PNGs
        self._propagate_animation_errors = False  # Strict non-interactive runs

        # Presentation timeline overlay
        self._timeline_group = None
        self._timeline_xs = None

        # Click-to-inspect / drag state
        self._grabbed_mobject = None
        self._grab_offset = None
        self._grabbed_name = None

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
        self._reset_pacing_clocks()
        try:
            self.file_writer.begin()
            self.setup()
            # Create checkpoint 0 right before construct
            self._create_checkpoint_zero()
            performance.metadata(
                scene=type(self).__name__,
                source=getattr(self, '_scene_filepath', None),
                fps=self.camera.fps,
                resolution=list(self.camera.get_pixel_shape()),
                route="web" if self._web_viewer is not None else "native",
                render_mode=bool(self._render_mode),
                present_mode=bool(self._present_mode),
            )
            performance.sample_process(
                "scene_start", checkpoints=len(self.animation_checkpoints))
            if self._render_mode:
                self._render_all()
            elif self._present_mode:
                self._prepare_presentation()
                self.interact()
            else:
                # Nothing runs until the user asks for it. Running "just the
                # first animation" here meant running the first *unit*, and a
                # unit ends at the statement containing a play() — so a scene
                # whose first play sits inside a for-loop played the whole loop
                # before the window even opened. Paint checkpoint 0 and wait.
                self.update_frame(dt=0, force_draw=True)
                self.interact()
        except EndScene:
            pass
        except KeyboardInterrupt:
            # Get rid keyboard interupt symbols
            print("", end="\r")
            self.file_writer.ended_with_interrupt = True
        except BaseException:
            try:
                self._tear_down_resources(abort=True)
            except BaseException:
                log.exception("Scene cleanup failed while handling an earlier error")
            raise
        self.tear_down()

    def setup(self) -> None:
        """
        This is meant to be implement by any scenes which
        are comonly subclassed, and have some common setup
        involved before the construct method is called.
        """
        pass

    def construct(self) -> None:
        # Where all the animation happens
        # To be implemented in subclasses
        pass

    def tear_down(self) -> None:
        self._tear_down_resources(abort=False)

    def _tear_down_resources(self, *, abort: bool) -> None:
        """Release every owned resource while preserving the first failure."""
        errors: list[tuple[str, BaseException]] = []

        def attempt(label, operation):
            try:
                operation()
            except BaseException as exc:
                errors.append((label, exc))

        attempt("stopping skip mode", self.stop_skipping)
        if abort:
            attempt("aborting file output", self.file_writer.abort)
        else:
            attempt("finishing file output", self.file_writer.finish)

        watcher = self._file_watcher
        self._file_watcher = None
        if watcher is not None:
            attempt("stopping the file watcher", watcher.stop)

        window = self.window
        self.window = None
        if window is not None:
            attempt("destroying the viewer", window.destroy)

        performance.gauge(
            "checkpoint.count", len(getattr(self, 'animation_checkpoints', ())))
        performance.sample_process(
            "scene_teardown",
            checkpoints=len(getattr(self, 'animation_checkpoints', ())),
        )
        attempt("flushing performance data", performance.flush)

        if errors:
            first_label, first_error = errors[0]
            for label, error in errors[1:]:
                first_error.add_note(f"Also failed while {label}: {error}")
            first_error.add_note(f"Scene teardown failed while {first_label}")
            raise first_error

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

            frame_interval = 1 / self.camera.fps
            if self._web_viewer is not None:
                if not self._web_viewer.has_clients():
                    # A detached browser needs neither GL capture nor a busy
                    # event loop.  The viewer lease still gets checked by the
                    # while condition on every pass.
                    performance.increment("idle.detached_sleeps")
                    time.sleep(min(frame_interval, 0.1))
                    continue
                self._maybe_replay_loop_pause()

            self.update_frame(frame_interval)

    def _maybe_replay_loop_pause(self) -> None:
        """Looping hold, live viewer only: while the scene sits parked on a
        checkpoint saved by pause(loop=True), replay the unit that led into
        it, over and over, at real speed.

        There is no exit machinery: an arrow key parks the scene on some
        other checkpoint mid-lap or between laps, the flag check fails, and
        the looping simply stops. Render and export never enter interact(),
        so a loop pause is an ordinary pausepoint everywhere but here.
        """
        if self.skip_animations or getattr(self, '_is_playing', False):
            return
        checkpoints = self.animation_checkpoints
        index = self.current_animation_index
        if not (0 < index < len(checkpoints)) or not checkpoints[index].get('loop'):
            return
        # Rewind to the previous pausepoint (or the scene start) and run
        # the whole stretch again. run_next_animation restores each base
        # checkpoint before exec and the replays re-save the same slots —
        # the re-executed pause re-raises the flags — so the scene lands
        # parked here again for the next lap.
        base = next(
            (i for i in range(index - 1, -1, -1)
             if i == 0 or checkpoints[i].get('stop')),
            None,
        )
        if base is None:
            return
        self.current_animation_index = base
        self._advancing = True
        self._loop_hold_index = index
        exit_key = None
        try:
            while self.current_animation_index < index:
                last = self.current_animation_index
                self.run_next_animation()
                if self.current_animation_index == last:
                    return
                if getattr(self, '_loop_exit_key', None) is not None:
                    break
        finally:
            self._advancing = False
            self._loop_hold_index = None
            exit_key = getattr(self, '_loop_exit_key', None)
            self._loop_exit_key = None
        if exit_key is None:
            return
        # The exit: an arrow pressed during a lap was recorded by
        # on_key_press rather than run re-entrantly inside the playing
        # exec. The lap broke at a unit boundary; park on the loop
        # pausepoint and let the key mean what it always means from a
        # pausepoint — RIGHT the next stretch, LEFT the previous
        # pausepoint, UP/DOWN one play. Without this RIGHT could never
        # leave: from inside the stretch the next stop IS the loop
        # pausepoint, so advancing re-armed the hold forever.
        self._restore_checkpoint_for_display(index)
        self.on_key_press(exit_key, 0)

    def embed(self, *args, **kwargs) -> None:
        """ManimGL's IPython embed mode was removed from maniml.

        The checkpoint system supersedes it: arrow keys navigate
        animations and saving the file hot-reloads from the last safe
        checkpoint.
        """
        log.warning(
            "self.embed() is not supported in maniml; "
            "use arrow-key navigation and auto-reload instead"
        )
    
    def get_image(self) -> Image:
        # Guard on the camera's window: with the web viewer the camera
        # is windowless, so there is no window fbo to toggle
        if self.camera.window is not None:
            self.camera.use_window_fbo(False)
            self.camera.capture(*self.render_groups)
        image = self.camera.get_image()
        if self.camera.window is not None:
            self.camera.use_window_fbo(True)
        return image

    def show(self) -> None:
        self.update_frame(force_draw=True)
        self.get_image().show()

    def update_frame(self, dt: float = 0, force_draw: bool = False) -> None:
        performance.increment(
            "scene.frames.positive_dt" if dt > 0 else "scene.frames.zero_dt")
        if force_draw:
            performance.increment("scene.frames.forced")
        self.increment_time(dt)
        with performance.stage("scene.update_mobjects"):
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

        skip_native_capture = bool(
            self._web_viewer is not None
            and getattr(
                self._web_viewer, 'can_skip_native_capture', lambda: False
            )()
        )
        if not skip_native_capture:
            with performance.stage("renderer.native_capture"):
                self.camera.capture(*self.render_groups)
            performance.increment("renderer.native_capture.calls")
        else:
            performance.increment("renderer.native_capture.bypassed")

        if self._web_viewer is not None:
            self._web_viewer.on_frame_rendered()

        if self.window and not self.skip_animations:
            vt = self.time - self.virtual_animation_start_time
            rt = time.monotonic() - self.real_animation_start_time
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

    def _reset_pacing_clocks(self) -> None:
        """Start a fresh wall-clock pacing epoch at the current scene time.

        ``scene.time`` is authored media state and checkpoint restore may
        move it in either direction.  Pairing a restored media timestamp
        with an older wall-clock baseline causes backward free-running or a
        forward freeze, so every discontinuous restore starts a new epoch.
        """
        self.virtual_animation_start_time = getattr(self, 'time', 0.0)
        self.real_animation_start_time = time.monotonic()

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
        # CE-compatible z_index: a stable sort on draw order, so equal
        # z_index preserves add order and higher z_index draws on top.
        # In 3D the depth buffer still decides true occlusion; z_index
        # only orders the draw calls.
        with performance.stage("renderer.assemble_batches"):
            batches = batch_by_property(
                sorted(self.mobjects, key=lambda m: m.z_index),
                lambda m: str(type(m)) + str(m.get_shader_wrapper(self.camera.ctx).get_id()) + str(m.z_index)
            )

            self.render_groups = [
                _RenderBatch(batch)
                for batch, key in batches
            ]
        performance.increment("renderer.assemble_batches.calls")
        performance.gauge("scene.mobjects", len(self.mobjects))
        performance.gauge("renderer.batch_count", len(self.render_groups))

    @staticmethod
    def affects_mobject_list(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            with self.mobject_list_transaction():
                self._mobject_list_mutation_dirty = True
                func(self, *args, **kwargs)
            return self
        return wrapper

    @contextmanager
    def mobject_list_transaction(self):
        """Commit nested or related membership changes with one rebatch."""
        depth = getattr(self, '_mobject_list_mutation_depth', 0)
        if depth == 0:
            self._mobject_list_mutation_dirty = False
        self._mobject_list_mutation_depth = depth + 1
        try:
            yield
        finally:
            self._mobject_list_mutation_depth = depth
            if depth == 0:
                try:
                    if self._mobject_list_mutation_dirty:
                        self.assemble_render_groups()
                finally:
                    self._mobject_list_mutation_dirty = False

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
        self._reset_pacing_clocks()
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
            self._reset_pacing_clocks()
        if self._web_viewer is not None:
            self._web_viewer.begin_animation()

    def post_play(self):
        if self._web_viewer is not None:
            self._web_viewer.end_animation()
        self._is_playing = False
        if not self.skip_animations:
            self.file_writer.end_animation()

        if self.preview_while_skipping and self.skip_animations and self.window is not None:
            # Show some quick frames along the way
            self.update_frame(dt=0, force_draw=True)

        self.num_plays += 1

    def begin_animations(self, animations: Iterable[Animation]) -> None:
        with performance.stage("animation.begin"):
            with self.mobject_list_transaction():
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
                        all_mobjects = all_mobjects.union(
                            animation.mobject.get_family())

    def progress_through_animations(self, animations: Iterable[Animation]) -> None:
        if self.window:
            # pre_play() stamps the wall clock before begin_animations(), so
            # the animation's own setup -- one begin() per animation, which
            # for a few hundred of them is not cheap -- is charged against
            # the first frame's deadline. Since the pacing sleep in
            # update_frame can only ever add delay, never recover it, an
            # animation that starts behind schedule stays behind and its
            # frames come out compressed: a run_time=1/10 play emitting its
            # three frames over 55ms rather than 100ms. Start the clock where
            # the frames actually start.
            self._reset_pacing_clocks()
        last_t = 0
        for t in self.get_animation_time_progression(animations):
            dt = t - last_t
            last_t = t
            with performance.stage("animation.interpolate"):
                for animation in animations:
                    animation.update_mobjects(dt)
                    alpha = t / animation.run_time
                    animation.interpolate(alpha)
            self.update_frame(dt)
            self.emit_frame()

    def finish_animations(self, animations: Iterable[Animation]) -> None:
        with performance.stage("animation.finish"):
            with self.mobject_list_transaction():
                for animation in animations:
                    animation.finish()
                    animation.clean_up_from_scene(self)
            if self.skip_animations:
                self.update_mobjects(self.get_run_time(animations))
            else:
                self.update_mobjects(0)

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

        with performance.stage("animation.prepare"):
            animations = list(map(prepare_animation, proto_animations))
            for anim in animations:
                anim.update_rate_info(run_time, rate_func, lag_ratio)

        if getattr(self, '_suppress_checkpoints', False):
            line_no, unit_index = None, None
        else:
            line_no, unit_index = self._find_animation_anchor()
        # Which statement is playing, for anything watching the animation
        # rather than its result: the checkpoint this will save does not
        # exist yet, so it cannot be asked.
        self._playing_unit = unit_index
        self._is_playing = True

        # Play the animation
        self.pre_play()
        self.begin_animations(animations)
        self.progress_through_animations(animations)
        self.finish_animations(animations)
        self.post_play()

        # Save checkpoint AFTER animation completes. Every play saves —
        # the per-play copies are what power UP/DOWN navigation and the
        # play-by-play reverse morph. Pauses only mark which of these
        # checkpoints are stops.
        if line_no:
            self._remember_scene_filepath()
            namespace = self._capture_caller_namespace()
            self._save_checkpoint(line_no, unit_index, namespace,
                                  run_time=self.get_run_time(animations))

    def pause(self, name: str | None = None, loop: bool = False) -> None:
        """Mark a pausepoint: a checkpoint flagged as a stop.

        Every play saves its own checkpoint regardless; pause() saves one
        more, flagged, and the flags are what RIGHT/LEFT and a
        presentation move between — the plays inside a stretch run
        through, while UP/DOWN still step the per-play states. In a file
        with no pauses every checkpoint is a stop (the CE-compatible
        default) and this is a no-op.

        Runs anywhere play() does: helpers and loop bodies included, since
        the checkpoint is saved at call time rather than found in source.

        ``loop=True`` makes this a looping hold in the live viewer: while
        parked here, the stretch back to the previous pausepoint replays
        over and over until an arrow key moves elsewhere (see
        _maybe_replay_loop_pause). Everywhere else — render, export, a
        scene run to completion — it is an ordinary pausepoint.
        """
        if getattr(self, '_suppress_checkpoints', False):
            return
        if not self._pause_anchored():
            return
        line_no, unit_index = self._find_animation_anchor()
        if line_no:
            namespace = self._capture_caller_namespace()
            self._save_checkpoint(line_no, unit_index, namespace, name=name)
            self._remember_scene_filepath()
            checkpoint = self.animation_checkpoints[self.current_animation_index]
            checkpoint['stop'] = True
            if loop:
                checkpoint['loop'] = True

    def next_section(self, name: str = "", type: str | None = None,
                     skip_animations: bool = False) -> None:
        """CE-compatible section boundary, treated as a pausepoint."""
        self.pause(name=name or None)

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
        # Live playback through the system player. The viewer is
        # loopback-only, so the engine's speaker IS the viewer's speaker —
        # no browser audio machinery needed (see DECISIONS.md, "Live sound
        # is the system player"). Plays immediately: time_offset and gain
        # shape only the rendered mix. Silent without a live audience —
        # render and headless runs have no window, and export's recorder
        # stands in as _web_viewer without ever having clients.
        if self._web_viewer is not None:
            audible = getattr(self._web_viewer, 'has_clients', lambda: False)()
        else:
            audible = self.window is not None
        if audible:
            play_sound(sound_file)

    # Helpers for interactive development

    def get_state(self) -> SceneState:
        # The timeline scrubber is a display overlay, never part of
        # checkpoint history
        ignore = [self._timeline_group] if self._timeline_group is not None else None
        return SceneState(self, ignore=ignore)

    @affects_mobject_list
    def restore_state(self, scene_state: SceneState):
        scene_state.restore_scene(self)
        self._reset_pacing_clocks()
        # Restoring replaces self.mobjects wholesale; keep the
        # presentation timeline overlay alive across restores so it
        # stays on screen while a unit plays (it is excluded from
        # checkpoints via the ignore list in get_state)
        group = self._timeline_group
        if group is not None and group not in self.mobjects:
            self.add(group)
        # The affects_mobject_list wrapper rebuilds draw batches once after
        # the complete restore (including any timeline reattachment).

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
        if self.camera.window is not None:
            self.camera.use_window_fbo(False)
        try:
            try:
                self.file_writer.begin_insert()
                yield
            except BaseException as error:
                try:
                    self.file_writer.abort()
                except BaseException as cleanup_error:
                    error.add_note(
                        f"Also failed while aborting insert output: {cleanup_error}"
                    )
                self.file_writer.write_to_movie = False
                raise
            else:
                self.file_writer.end_insert()
        finally:
            if self.camera.window is not None:
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
        # Re-apply the z_index order Scene.add maintains: a direct assignment
        # would otherwise draw in snapshot order and ignore any z_index set
        # since the snapshot (stable sort, so equal z keeps snapshot order)
        scene.mobjects.sort(key=lambda m: m.z_index)
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
from maniml.mobject.mobject import Mobject
