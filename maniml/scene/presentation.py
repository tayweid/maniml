"""Delivery modes for maniml scenes.

Presentation mode (pre-run all units, clickable bottom-edge timeline
scrubber) and headless render mode (the movie, and — only when asked
for — one PNG per checkpoint).
"""
from __future__ import annotations

import os

import numpy as np

from maniml.mobject.mobject import Group


class PresentationMixin:
    def _prepare_presentation(self) -> None:
        """Pre-run every animation unit (skipped, so it takes seconds)
        to validate the whole scene and build every checkpoint, then
        rewind to the start. The file watcher stays off: nothing
        re-parses mid-presentation."""
        self._presentation_ready = False
        print("Preparing presentation...")
        self.auto_reload_enabled = False
        with self.temp_skip():
            self._run_all_units()
        total = len(self.animation_checkpoints) - 1
        self._restore_checkpoint_for_display(0)
        # Recorded motion may take over only after every advertised endpoint
        # has a live checkpoint to restore when playback exits.
        self._presentation_ready = True
        self.update_frame(dt=0, force_draw=True)
        print(f"Ready: {total} animations pre-built. RIGHT arrow to begin;")
        print("move the mouse to the bottom edge for the timeline.")

    def _render_all(self) -> None:
        """Run every unit at full speed so frames reach the file writer,
        saving a PNG snapshot of each checkpoint when asked to.

        The stills are opt-in (`_render_checkpoints`, set by
        `--export-checkpoints`): a full-resolution PNG per checkpoint is
        several times the movie it would sit beside, which is the wrong
        thing to drop into a repo on every render, so they are their own
        export — regenerated, and gitignored, on their own.
        """
        capture = self._render_checkpoints
        image_dir = None
        if capture:
            image_dir = os.path.join(
                self.file_writer.output_directory,
                f"{self.file_writer.get_output_file_name()}_checkpoints",
            )
            os.makedirs(image_dir, exist_ok=True)
            self._save_checkpoint_image(image_dir)  # initial (empty) state
        while True:
            last_index = self.current_animation_index
            self.run_next_animation()
            final = self.current_animation_index
            if final == last_index:
                break
            if not capture:
                continue
            if final == last_index + 1:
                self._save_checkpoint_image(image_dir)
            else:
                # One unit produced several checkpoints (e.g. play() in a
                # loop): restore each to capture its snapshot
                for i in range(last_index + 1, final + 1):
                    self._restore_checkpoint_for_display(i)
                    self._save_checkpoint_image(image_dir)
        if capture:
            print(f"Wrote {self.current_animation_index + 1} checkpoint images to {image_dir}")

    def _save_checkpoint_image(self, image_dir: str) -> None:
        self.update_frame(dt=0, force_draw=True)
        path = os.path.join(image_dir, f"{self.current_animation_index:03d}.png")
        self.get_image().save(path)

    # Presentation timeline (clickable checkpoint scrubber)

    def _timeline_zone_contains(self, point) -> bool:
        frame = self.camera.frame
        bottom = frame.get_bottom()[1]
        return point[1] < bottom + 0.08 * frame.get_height()

    def _show_timeline(self, active_segment: tuple[int, int] | None = None) -> None:
        """Checkpoint scrubber: a ring per pause point joined by a line.

        The current ring holds a filled pip; while a unit is playing,
        pass `active_segment=(i, j)` to emphasize the stretch being
        traversed instead of showing a pip.
        """
        from maniml.mobject.geometry import Circle, Dot, Line
        self._hide_timeline()
        n = len(self.animation_checkpoints)
        if n < 2:
            return
        if active_segment is not None:
            active_segment = tuple(sorted(active_segment))
        frame = self.camera.frame
        span = frame.get_width() * 0.6
        y = frame.get_bottom()[1] + 0.045 * frame.get_height()
        cx = frame.get_center()[0]
        xs = np.linspace(cx - span / 2, cx + span / 2, n)
        scale = frame.get_height() / 8.0  # keep marker size stable under zoom
        r = 0.055 * scale
        marks = []
        for i in range(n - 1):
            active = active_segment == (i, i + 1)
            line = Line(
                np.array([xs[i] + r, y, 0.0]),
                np.array([xs[i + 1] - r, y, 0.0]),
                color='#FFFFFF',
                stroke_width=5.0 if active else 1.5,
            )
            line.set_stroke(opacity=0.9 if active else 0.25)
            marks.append(line)
        for i, x in enumerate(xs):
            current = (i == self.current_animation_index)
            endpoint = active_segment is not None and i in active_segment
            ring = Circle(radius=r, color='#FFFFFF',
                          stroke_width=2.0, fill_opacity=0.0)
            ring.set_stroke(opacity=0.9 if current or endpoint else 0.45)
            ring.move_to(np.array([x, y, 0.0]))
            marks.append(ring)
            if current and active_segment is None:
                pip = Dot(radius=r * 0.55, color='#FFFFFF')
                pip.move_to(np.array([x, y, 0.0]))
                marks.append(pip)
        self._timeline_group = Group(*marks)
        self._timeline_xs = xs
        self.add(self._timeline_group)

    def _hide_timeline(self) -> None:
        group = self._timeline_group
        if group is not None and group in self.mobjects:
            self.remove(group)
        self._timeline_group = None
        self._timeline_xs = None

    def _handle_timeline_click(self, point) -> bool:
        """Jump to the clicked checkpoint. Returns True if handled."""
        if self._timeline_xs is None or not self._timeline_zone_contains(point):
            return False
        index = int(np.argmin(np.abs(self._timeline_xs - point[0])))
        self._hide_timeline()
        print(f"⤳ Jump to animation {index}/{len(self.animation_checkpoints) - 1}")
        self._restore_checkpoint_for_display(index)
        self._show_timeline()
        self.update_frame(dt=0, force_draw=True)
        return True

    # Click-to-inspect and drag-to-move (development mode)
