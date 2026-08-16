"""Regression tests for commands launched across OS process boundaries."""

import subprocess
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from maniml.scene.scene_file_writer import FFmpegError, SceneFileWriter
from maniml.utils.sounds import play_sound
from maniml.utils.tex_file_writing import (
    DVISVGM_TIMEOUT,
    TEX_COMPILATION_TIMEOUT,
    LatexError,
    full_tex_to_svg,
)


def completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class TeXProcessTests(unittest.TestCase):
    def render_uncached(self):
        return full_tex_to_svg.__wrapped__("content", message="")

    @patch("maniml.utils.tex_file_writing.subprocess.run")
    def test_bounded_tools_and_successful_svg(self, run):
        run.side_effect = [
            completed(),
            completed(stdout="<svg xmlns='http://www.w3.org/2000/svg'/>"),
        ]

        result = self.render_uncached()

        self.assertTrue(result.startswith("<svg"))
        self.assertEqual(
            run.call_args_list[0].kwargs["timeout"], TEX_COMPILATION_TIMEOUT
        )
        self.assertEqual(run.call_args_list[1].kwargs["timeout"], DVISVGM_TIMEOUT)
        for call in run.call_args_list:
            self.assertNotIn("shell", call.kwargs)
            self.assertEqual(call.kwargs["encoding"], "utf-8")

    @patch("maniml.utils.tex_file_writing.subprocess.run")
    def test_missing_compiler_has_actionable_error(self, run):
        run.side_effect = FileNotFoundError("latex")

        with self.assertRaisesRegex(LatexError, "latex executable was not found"):
            self.render_uncached()

    @patch("maniml.utils.tex_file_writing.subprocess.run")
    def test_compiler_timeout_is_reported(self, run):
        run.side_effect = subprocess.TimeoutExpired("latex", 120)

        with self.assertRaisesRegex(LatexError, "timed out after 120 seconds"):
            self.render_uncached()

    @patch("maniml.utils.tex_file_writing.subprocess.run")
    def test_dvisvgm_failure_is_not_cached_as_svg(self, run):
        run.side_effect = [
            completed(),
            completed(returncode=1, stderr="bad dvi"),
        ]

        with self.assertRaisesRegex(LatexError, "dvisvgm conversion failed"):
            self.render_uncached()

    @patch("maniml.utils.tex_file_writing.subprocess.run")
    def test_empty_dvisvgm_output_is_rejected(self, run):
        run.side_effect = [completed(), completed(stdout="")]

        with self.assertRaisesRegex(LatexError, "produced no SVG output"):
            self.render_uncached()


class FFmpegProcessTests(unittest.TestCase):
    def writer(self):
        writer = SceneFileWriter.__new__(SceneFileWriter)
        writer.progress_display = None
        writer.ended_with_interrupt = False
        writer.temp_file_path = "movie_temp.mp4"
        writer.final_file_path = "movie.mp4"
        return writer

    @patch("maniml.scene.scene_file_writer.shutil.move")
    def test_completed_movie_is_promoted_only_after_success(self, move):
        writer = self.writer()
        process = MagicMock()
        process.stdin = MagicMock()
        process.wait.return_value = 0
        writer.writing_process = process

        writer.close_movie_pipe()

        process.stdin.close.assert_called_once_with()
        move.assert_called_once_with("movie_temp.mp4", "movie.mp4")
        self.assertIsNone(writer.writing_process)

    @patch("maniml.scene.scene_file_writer.shutil.move")
    def test_failed_movie_is_not_promoted(self, move):
        writer = self.writer()
        process = MagicMock()
        process.stdin = MagicMock()
        process.wait.return_value = 7
        writer.writing_process = process

        with self.assertRaisesRegex(FFmpegError, "status 7"):
            writer.close_movie_pipe()

        move.assert_not_called()
        self.assertIsNone(writer.writing_process)

    @patch("maniml.scene.scene_file_writer.sp.Popen")
    def test_missing_ffmpeg_has_actionable_error(self, popen):
        writer = self.writer()
        writer.ffmpeg_bin = "missing-ffmpeg"
        writer.scene = MagicMock()
        writer.scene.camera.fps = 24
        writer.scene.camera.get_pixel_shape.return_value = (1920, 1080)
        writer.saturation = 1.0
        writer.gamma = 1.0
        writer.video_codec = "libx264"
        writer.pixel_format = "yuv420p"
        writer.quiet = True
        popen.side_effect = FileNotFoundError("missing-ffmpeg")

        with self.assertRaisesRegex(FFmpegError, "Could not start ffmpeg"):
            writer.open_movie_pipe("movie.mp4")


class SoundProcessTests(unittest.TestCase):
    @patch("maniml.utils.sounds.subprocess.Popen")
    @patch("maniml.utils.sounds.platform.system", return_value="Windows")
    @patch("maniml.utils.sounds.get_full_sound_file_path")
    def test_windows_filename_is_data_not_powershell_source(
        self, find_sound, _system, popen
    ):
        suspicious_path = Path("sound'; Write-Output injected; '.wav")
        find_sound.return_value = suspicious_path

        play_sound("ignored.wav")

        command = popen.call_args.args[0]
        kwargs = popen.call_args.kwargs
        self.assertNotIn(str(suspicious_path), " ".join(command))
        self.assertEqual(kwargs["env"]["MANIML_SOUND_FILE"], str(suspicious_path))
        self.assertNotIn("shell", kwargs)


if __name__ == "__main__":
    unittest.main()
