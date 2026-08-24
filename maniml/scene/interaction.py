"""Interactive input for maniml scenes.

Arrow-key checkpoint navigation (RIGHT re-executes from source,
UP/DOWN jump, LEFT plays an animated reverse morph), click-to-inspect
and drag-to-move, and the window mouse/keyboard callbacks.
"""
from __future__ import annotations

from maniml.camera.camera_frame import CameraFrame
from maniml.config import manim_config
from maniml.event_constants import MouseButtons as PygletMouseButtons
from maniml.event_constants import WindowKeys as PygletWindowKeys
from maniml.event_handler import EVENT_DISPATCHER
from maniml.event_handler.event_type import EventType
from maniml.logger import log
from maniml.mobject.mobject import Mobject

class InteractionMixin:
    def _inspectable_mobjects(self) -> list[Mobject]:
        return [
            mob for mob in self.mobjects
            if mob is not self._timeline_group
            and not isinstance(mob, CameraFrame)
            and not mob.is_fixed_in_frame()
        ]

    def _find_mobject_at(self, point) -> Mobject | None:
        """Topmost mobject whose bounding box contains the point."""
        from maniml.constants import SMALL_BUFF
        return self.point_to_mobject(
            point, self._inspectable_mobjects(), buff=SMALL_BUFF)

    def _name_of(self, mobject) -> str | None:
        """Variable name of a live mobject in the current animation's
        namespace — or of the container (e.g. VGroup) holding it."""
        items = [
            (name, value) for name, value in self._live_namespace.items()
            if not name.startswith('_') and name != 'self'
        ]
        for name, value in items:
            if value is mobject:
                return name
        for name, value in items:
            if isinstance(value, Mobject) and mobject in value.get_family():
                return name
        return None

    def _begin_grab(self, mobject: Mobject, point) -> None:
        name = self._name_of(mobject)
        self._grabbed_mobject = mobject
        self._grabbed_name = name
        self._grab_offset = point - mobject.get_center()
        mobject.set_animating_status(True)
        x, y, z = mobject.get_center()
        label = name or mobject.__class__.__name__
        print(f"⊙ {label}  center=({x:.2f}, {y:.2f}, {z:.2f})")

    def _end_grab(self) -> None:
        mobject = self._grabbed_mobject
        if mobject is None:
            return
        mobject.set_animating_status(False)
        mobject.refresh_bounding_box()
        x, y, z = mobject.get_center()
        name = self._grabbed_name or mobject.__class__.__name__
        print(f"  {name}.move_to([{x:.2f}, {y:.2f}, {z:.2f}])")
        self._grabbed_mobject = None
        self._grabbed_name = None
        self._grab_offset = None

    # Only these methods should touch the camera

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

        # Presentation timeline appears when the mouse nears the bottom edge
        if self._present_mode:
            if self._timeline_zone_contains(point):
                if self._timeline_group is None:
                    self._show_timeline()
            elif self._timeline_group is not None:
                self._hide_timeline()

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
        if self._grabbed_mobject is not None:
            # Dragging a mobject: move it, don't pan
            self._grabbed_mobject.move_to(point - self._grab_offset)
        elif self.drag_to_pan:
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

        if self._present_mode:
            if self._handle_timeline_click(point):
                return
        elif button == PygletMouseButtons.LEFT:
            # Click a mobject to identify it; keep holding to drag it
            mobject = self._find_mobject_at(point)
            if mobject is not None:
                self._begin_grab(mobject, point)

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

        self._end_grab()

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

    def _reverse_to_previous_pausepoint(self, timeline_visible: bool = False) -> None:
        """LEFT: jump instantly to the previous pausepoint's exact state
        (or the scene start; the previous checkpoint in a pause-less file).

        Deliberately not animated. A state morph cannot truly reverse an
        animation — states are photographs, and no photograph contains how
        it was drawn, so a morph fades what it cannot retrace and misleads
        exactly when the reverse matters most (see DECISIONS.md,
        "Backward navigation is a jump"). Honest and instant instead; real
        backward playback arrives with the recorded-stream layer
        (TODO.md), which replays what the GPU was actually sent, in
        reverse, for any content.
        """
        checkpoints = self.animation_checkpoints
        index = self.current_animation_index
        if index <= 0:
            print("Already at first animation")
            return
        if self._pause_anchored():
            target = next(
                (i for i in range(index - 1, -1, -1)
                 if i == 0 or checkpoints[i].get('stop')),
                0,
            )
        else:
            target = index - 1
        print(f"← Back to animation {target}/{len(checkpoints) - 1}")
        self._restore_checkpoint_for_display(target)
        if timeline_visible:
            self._show_timeline()
        self.update_frame(dt=0, force_draw=True)

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
        # A loop hold (pause(loop=True)) replays its stretch until an
        # arrow. The lap is mid-play when the key arrives, so handling it
        # here would re-enter run_next_animation inside a running exec —
        # instead the key is recorded, the lap breaks at its next unit
        # boundary, and _maybe_replay_loop_pause applies it from the
        # pausepoint.
        if getattr(self, '_loop_hold_index', None) is not None and symbol in (
                PygletWindowKeys.LEFT, PygletWindowKeys.RIGHT,
                PygletWindowKeys.UP, PygletWindowKeys.DOWN):
            self._loop_exit_key = symbol
            return

        # In present mode the timeline overlay rides along through
        # navigation: it survives checkpoint restores (see
        # restore_state) and is rebuilt around each move, with the
        # traversed segment emphasized while a unit plays
        timeline_visible = self._present_mode and self._timeline_group is not None

        # Handle UP arrow - jump to next animation
        if symbol == PygletWindowKeys.UP:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index < len(self.animation_checkpoints) - 1:
                print(f"↑ Jump to animation {self.current_animation_index + 1}/{len(self.animation_checkpoints) - 1}")
                self._restore_checkpoint_for_display(self.current_animation_index + 1)
                if timeline_visible:
                    self._show_timeline()
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at last animation")

        # Handle DOWN arrow - jump to previous animation
        elif symbol == PygletWindowKeys.DOWN:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index > 0:
                print(f"↓ Jump to animation {self.current_animation_index - 1}/{len(self.animation_checkpoints) - 1}")
                # Restores a copy: putting the stored mobjects on screen
                # would let later mutation corrupt the checkpoint
                self._restore_checkpoint_for_display(self.current_animation_index - 1)
                if timeline_visible:
                    self._show_timeline()
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at first animation")

        # Handle LEFT arrow - play animation in reverse
        elif symbol == PygletWindowKeys.LEFT:
            # Prevent handling if we're already processing a key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index > 0:
                # Set flag to prevent re-entry
                self._processing_key = True
                try:
                    self._reverse_to_previous_pausepoint(timeline_visible)
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
                if (timeline_visible and self.current_animation_index
                        < len(self.animation_checkpoints) - 1):
                    self._show_timeline(active_segment=(
                        self.current_animation_index,
                        self.current_animation_index + 1,
                    ))
                self.advance_to_next_pausepoint()
                if timeline_visible:
                    self._show_timeline()
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
