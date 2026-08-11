"""Interactive input for maniml scenes.

Arrow-key checkpoint navigation (RIGHT re-executes from source,
UP/DOWN jump, LEFT plays an animated reverse morph), click-to-inspect
and drag-to-move, and the window mouse/keyboard callbacks.
"""
from __future__ import annotations

from pyglet.window import key as PygletWindowKeys
from pyglet.window import mouse as PygletMouseButtons

from maniml.camera.camera_frame import CameraFrame
from maniml.config import manim_config
from maniml.event_handler import EVENT_DISPATCHER
from maniml.event_handler.event_type import EventType
from maniml.logger import log
from maniml.mobject.mobject import Mobject
from maniml.scene.checkpoints import deepcopy_namespace


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

    def _play_reverse_to(self, index: int) -> None:
        """Animate the display back to the checkpoint at `index`.

        This is a whole-scene morph between the current display and the
        target state, not a true reversal of the original animation
        (source re-execution can't run backwards), so complex changes
        blend rather than retrace. Lands exactly on a copy of the
        target state; falls back to an instant jump if the morph fails.
        """
        from maniml.animation.transform import Transform
        from maniml.animation.fading import FadeIn, FadeOut

        temp = deepcopy_namespace(self.animation_checkpoints[index])
        target_state = temp['state']
        try:
            # The camera frame lives in self.mobjects (and in stored
            # states) but can't be morphed like scene content
            current_mobs = [
                mob for mob in self.mobjects
                if not isinstance(mob, CameraFrame)
                and mob is not self._timeline_group
            ]
            target_mobs = [
                mob for mob in target_state.mobjects
                if not isinstance(mob, CameraFrame)
            ]
            # Pair each on-screen mobject with its counterpart in the
            # target checkpoint by variable name (identity can't match
            # across deep copies). Matched pairs morph one-to-one;
            # unmatched ones fade, so a mobject that doesn't exist in
            # the target never blends into an unrelated shape.
            live = self._live_namespace or {}
            names_by_id = {
                id(v): n for n, v in live.items() if isinstance(v, Mobject)
            }
            target_by_name = {
                n: v for n, v in temp['namespace'].items()
                if isinstance(v, Mobject)
            }
            target_ids = set(map(id, target_mobs))
            anims = []
            matched = set()
            for mob in current_mobs:
                tgt = target_by_name.get(names_by_id.get(id(mob)))
                if tgt is not None and id(tgt) in target_ids:
                    anims.append(Transform(mob, tgt))
                    matched.add(id(tgt))
                else:
                    anims.append(FadeOut(mob))
            anims.extend(
                FadeIn(tgt) for tgt in target_mobs if id(tgt) not in matched
            )
            if anims:
                with self._no_checkpoints():
                    self.play(*anims, run_time=0.7)
        except Exception as e:
            log.warning(f"Reverse transition failed ({e}); jumping instead")
        # Land exactly on the checkpoint state regardless of how the
        # morph went
        self.clear()
        self.restore_state(target_state)
        namespace = temp['namespace']
        namespace['self'] = self
        self._live_namespace = namespace

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
        # In present mode the timeline overlay rides along through
        # navigation: it survives checkpoint restores (see
        # restore_state) and is rebuilt around each move, with the
        # traversed segment emphasized while a unit plays
        timeline_visible = self._present_mode and self._timeline_group is not None

        # Handle UP arrow - jump to previous animation
        if symbol == PygletWindowKeys.UP:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index > 0:
                print(f"↑ Jump to animation {self.current_animation_index - 1}/{len(self.animation_checkpoints) - 1}")
                # Restores a copy: putting the stored mobjects on screen
                # would let later mutation corrupt the checkpoint
                self._restore_checkpoint_for_display(self.current_animation_index - 1)
                if timeline_visible:
                    self._show_timeline()
                self.update_frame(dt=0, force_draw=True)
            else:
                print("Already at first animation")

        # Handle DOWN arrow - jump to next animation
        elif symbol == PygletWindowKeys.DOWN:
            # Prevent if we're processing another key
            if hasattr(self, '_processing_key') and self._processing_key:
                return

            if self.current_animation_index < len(self.animation_checkpoints) - 1:
                print(f"↓ Jump to animation {self.current_animation_index + 1}/{len(self.animation_checkpoints) - 1}")
                self._restore_checkpoint_for_display(self.current_animation_index + 1)
                if timeline_visible:
                    self._show_timeline()
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
                    if timeline_visible:
                        self._show_timeline(active_segment=(
                            self.current_animation_index,
                            self.current_animation_index + 1,
                        ))
                    self._play_reverse_to(self.current_animation_index)
                    if timeline_visible:
                        self._show_timeline()
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
                if (timeline_visible and self.current_animation_index
                        < len(self.animation_checkpoints) - 1):
                    self._show_timeline(active_segment=(
                        self.current_animation_index,
                        self.current_animation_index + 1,
                    ))
                self.run_next_animation()
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

