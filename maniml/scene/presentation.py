"""Delivery modes for maniml scenes.

Presentation mode (pre-run all units; the viewer's rail is the
scrubber) and headless render mode (the movie, and — only when asked
for — one PNG per checkpoint).
"""
from __future__ import annotations

import os


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
        print(f"Ready: {total} animations pre-built. RIGHT arrow to begin.")

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
