"""Regression tests for commands launched across OS process boundaries."""

import subprocess
import tempfile
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
        writer.writing_process = None
        writer.ended_with_interrupt = False
        writer.temp_file_path = "movie_temp.mp4"
        writer.final_file_path = "movie.mp4"
        writer._movie_staging_dir = None
        return writer

    @patch("maniml.scene.scene_file_writer.os.replace")
    def test_completed_movie_is_promoted_only_after_success(self, replace):
        writer = self.writer()
        process = MagicMock()
        process.stdin = MagicMock()
        process.wait.return_value = 0
        writer.writing_process = process

        writer.close_movie_pipe()

        process.stdin.close.assert_called_once_with()
        replace.assert_called_once_with("movie_temp.mp4", "movie.mp4")
        self.assertIsNone(writer.writing_process)

    @patch("maniml.scene.scene_file_writer.os.replace")
    def test_failed_movie_is_not_promoted(self, replace):
        writer = self.writer()
        process = MagicMock()
        process.stdin = MagicMock()
        process.wait.return_value = 7
        writer.writing_process = process

        with self.assertRaisesRegex(FFmpegError, "status 7"):
            writer.close_movie_pipe()

        replace.assert_not_called()
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

    @patch("maniml.scene.scene_file_writer.sp.Popen")
    def test_movie_staging_does_not_touch_legacy_temp_name(self, popen):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            legacy_temp = directory / "movie_temp.mp4"
            legacy_temp.write_bytes(b"user data")
            writer = self.writer()
            writer.ffmpeg_bin = "ffmpeg"
            writer.scene = MagicMock()
            writer.scene.camera.fps = 24
            writer.scene.camera.get_pixel_shape.return_value = (4, 4)
            writer.saturation = 1.0
            writer.gamma = 1.0
            writer.video_codec = "libx264"
            writer.pixel_format = "yuv420p"
            writer.quiet = True
            process = MagicMock()
            process.poll.return_value = 0
            popen.return_value = process

            writer.open_movie_pipe(directory / "movie.mp4")

            self.assertNotEqual(Path(writer.temp_file_path), legacy_temp)
            self.assertEqual(legacy_temp.read_bytes(), b"user data")
            staging_dir = writer._movie_staging_dir
            self.assertTrue(staging_dir.is_dir())
            writer.abort()
            self.assertFalse(staging_dir.exists())

    @patch("maniml.scene.scene_file_writer.sp.Popen")
    def test_movie_pipe_tags_bt709(self, popen):
        # Untagged H.264 is converted with swscale's BT.601 default and
        # decoded by browsers as BT.709, so recorded colours drift from the
        # live canvas. The pipe must convert with, and tag, BT.709 limited.
        with tempfile.TemporaryDirectory() as directory:
            writer = self.writer()
            writer.ffmpeg_bin = "ffmpeg"
            writer.scene = MagicMock()
            writer.scene.camera.fps = 24
            writer.scene.camera.get_pixel_shape.return_value = (4, 4)
            writer.saturation = 1.0
            writer.gamma = 1.0
            writer.video_codec = "libx264"
            writer.pixel_format = "yuv420p"
            writer.quiet = True
            process = MagicMock()
            process.poll.return_value = 0
            popen.return_value = process

            writer.open_movie_pipe(Path(directory) / "movie.mp4")
            command = [str(part) for part in popen.call_args.args[0]]
            writer.abort()

        vf = command[command.index("-vf") + 1]
        self.assertIn("scale=out_color_matrix=bt709:out_range=tv", vf)
        for flag, value in (("-colorspace", "bt709"),
                            ("-color_primaries", "bt709"),
                            ("-color_trc", "bt709"),
                            ("-color_range", "tv")):
            self.assertIn(flag, command)
            self.assertEqual(command[command.index(flag) + 1], value)
        # Output options must precede the output path
        self.assertLess(command.index("-colorspace"), len(command) - 1)

    def test_interrupted_movie_is_preserved_without_overwriting_final(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            final_path = directory / "movie.mp4"
            final_path.write_bytes(b"previous movie")
            staging_dir = directory / ".movie-staging"
            staging_dir.mkdir()
            temp_path = staging_dir / "movie.mp4"
            temp_path.write_bytes(b"partial movie")
            writer = self.writer()
            writer.final_file_path = final_path
            writer.temp_file_path = temp_path
            writer._movie_staging_dir = staging_dir
            writer.ended_with_interrupt = True
            process = MagicMock()
            process.stdin = MagicMock()
            process.wait.return_value = 0
            writer.writing_process = process

            writer.close_movie_pipe()

            interrupted_path = Path(writer.movie_file_path)
            self.assertEqual(final_path.read_bytes(), b"previous movie")
            self.assertEqual(interrupted_path.read_bytes(), b"partial movie")
            self.assertIn("movie_interrupted_", interrupted_path.name)
            self.assertFalse(staging_dir.exists())

    def test_abort_escalates_and_removes_owned_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            staging_dir = Path(directory, ".movie-staging")
            staging_dir.mkdir()
            Path(staging_dir, "movie.mp4").write_bytes(b"partial")
            writer = self.writer()
            writer._movie_staging_dir = staging_dir
            process = MagicMock()
            process.poll.return_value = None
            process.wait.side_effect = [
                subprocess.TimeoutExpired("ffmpeg", 3),
                0,
            ]
            writer.writing_process = process

            writer.abort()

            process.terminate.assert_called_once_with()
            process.kill.assert_called_once_with()
            self.assertEqual(process.wait.call_count, 2)
            self.assertFalse(staging_dir.exists())

    @patch("maniml.scene.scene_file_writer.AudioSegment.silent")
    @patch("maniml.scene.scene_file_writer.sp.run")
    def test_audio_mux_staging_does_not_touch_user_files(self, run, silent):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            movie_path = directory / "movie.mp4"
            movie_path.write_bytes(b"video")
            user_wav = directory / "movie.wav"
            user_wav.write_bytes(b"user audio")
            legacy_temp = directory / "movie_temp.mp4"
            legacy_temp.write_bytes(b"user temp")
            writer = self.writer()
            writer.movie_file_path = movie_path
            writer.ffmpeg_bin = "ffmpeg"
            writer.add_audio_segment = MagicMock()
            writer.audio_segment = MagicMock()
            writer.audio_segment.export.side_effect = lambda path, **_kwargs: Path(
                path
            ).write_bytes(b"audio")

            def mux(command):
                Path(command[-1]).write_bytes(b"muxed movie")
                return completed()

            run.side_effect = mux

            writer.add_sound_to_video()

            self.assertEqual(movie_path.read_bytes(), b"muxed movie")
            self.assertEqual(user_wav.read_bytes(), b"user audio")
            self.assertEqual(legacy_temp.read_bytes(), b"user temp")

    def test_failed_final_image_save_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory, "frame.png")
            image_path.write_bytes(b"previous image")
            writer = self.writer()
            writer.image_file_path = image_path
            writer.quiet = True
            image = MagicMock()
            image.save.side_effect = RuntimeError("save failed")

            with self.assertRaisesRegex(RuntimeError, "save failed"):
                writer.save_final_image(image)

            self.assertEqual(image_path.read_bytes(), b"previous image")


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
