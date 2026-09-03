from __future__ import annotations

import os
import platform
import shutil
import subprocess as sp
import sys
import tempfile

import numpy as np
try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None
from tqdm.auto import tqdm as ProgressDisplay
from pathlib import Path

from maniml.logger import log
from maniml.mobject.mobject import Mobject
from maniml.utils.file_ops import guarantee_existence
from maniml.utils.sounds import get_full_sound_file_path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL.Image import Image

    from maniml.camera.camera import Camera
    from maniml.scene.scene import Scene


class FFmpegError(RuntimeError):
    """Raised when ffmpeg cannot produce a valid output file."""


class SceneFileWriter(object):
    def __init__(
        self,
        scene: Scene,
        write_to_movie: bool = False,
        subdivide_output: bool = False,
        png_mode: str = "RGBA",
        save_last_frame: bool = False,
        movie_file_extension: str = ".mp4",
        # Where should this be written
        output_directory: str = ".",
        file_name: str | None = None,
        open_file_upon_completion: bool = False,
        show_file_location_upon_completion: bool = False,
        quiet: bool = False,
        total_frames: int = 0,
        progress_description_len: int = 40,
        # Name of the binary used for ffmpeg
        ffmpeg_bin: str = "ffmpeg",
        video_codec: str = "libx264",
        pixel_format: str = "yuv420p",
        saturation: float = 1.0,
        gamma: float = 1.0,
    ):
        self.scene: Scene = scene
        self.write_to_movie = write_to_movie
        self.subdivide_output = subdivide_output
        self.png_mode = png_mode
        self.save_last_frame = save_last_frame
        self.movie_file_extension = movie_file_extension
        self.output_directory = output_directory
        self.file_name = file_name
        self.open_file_upon_completion = open_file_upon_completion
        self.show_file_location_upon_completion = show_file_location_upon_completion
        self.quiet = quiet
        self.total_frames = total_frames
        self.progress_description_len = progress_description_len
        self.ffmpeg_bin = ffmpeg_bin
        self.video_codec = video_codec
        self.pixel_format = pixel_format
        self.saturation = saturation
        self.gamma = gamma

        # State during file writing
        self.writing_process: sp.Popen | None = None
        self.progress_display: ProgressDisplay | None = None
        self.ended_with_interrupt: bool = False
        self._movie_staging_dir: Path | None = None

        self.init_output_directories()
        self.init_audio()

    # Output directories and files
    def init_output_directories(self) -> None:
        if self.save_last_frame:
            self.image_file_path = self.init_image_file_path()
        if self.write_to_movie:
            self.movie_file_path = self.init_movie_file_path()
        if self.subdivide_output:
            self.partial_movie_directory = self.init_partial_movie_directory()

    def init_image_file_path(self) -> Path:
        return self.get_output_file_rootname().with_suffix(".png")

    def init_movie_file_path(self) -> Path:
        return self.get_output_file_rootname().with_suffix(self.movie_file_extension)

    def init_partial_movie_directory(self):
        return guarantee_existence(self.get_output_file_rootname())

    def get_output_file_rootname(self) -> Path:
        return Path(
            guarantee_existence(self.output_directory),
            self.get_output_file_name()
        )

    def get_output_file_name(self) -> str:
        if self.file_name:
            return self.file_name
        # Otherwise, use the name of the scene, potentially
        # appending animation numbers
        name = str(self.scene)
        saan = self.scene.start_at_animation_number
        eaan = self.scene.end_at_animation_number
        if saan is not None:
            name += f"_{saan}"
        if eaan is not None:
            name += f"_{eaan}"
        return name

    # Directory getters
    def get_image_file_path(self) -> str:
        return self.image_file_path

    def get_next_partial_movie_path(self) -> str:
        result = Path(self.partial_movie_directory, f"{self.scene.num_plays:05}")
        return result.with_suffix(self.movie_file_extension)

    def get_movie_file_path(self) -> str:
        return self.movie_file_path

    # Sound
    def init_audio(self) -> None:
        self.includes_sound: bool = False

    def create_audio_segment(self) -> None:
        if AudioSegment is None:
            raise ImportError(
                "Audio features require the packaged pydub/audioop-lts "
                "dependencies; reinstall maniml to repair this environment."
            )
        self.audio_segment = AudioSegment.silent()

    def add_audio_segment(
        self,
        new_segment: AudioSegment,
        time: float | None = None,
        gain_to_background: float | None = None
    ) -> None:
        if not self.includes_sound:
            self.includes_sound = True
            self.create_audio_segment()
        segment = self.audio_segment
        curr_end = segment.duration_seconds
        if time is None:
            time = curr_end
        if time < 0:
            raise Exception("Adding sound at timestamp < 0")

        new_end = time + new_segment.duration_seconds
        diff = new_end - curr_end
        if diff > 0:
            segment = segment.append(
                AudioSegment.silent(int(np.ceil(diff * 1000))),
                crossfade=0,
            )
        self.audio_segment = segment.overlay(
            new_segment,
            position=int(1000 * time),
            gain_during_overlay=gain_to_background,
        )

    def add_sound(
        self,
        sound_file: str,
        time: float | None = None,
        gain: float | None = None,
        gain_to_background: float | None = None
    ) -> None:
        file_path = get_full_sound_file_path(sound_file)
        new_segment = AudioSegment.from_file(file_path)
        if gain:
            new_segment = new_segment.apply_gain(gain)
        self.add_audio_segment(new_segment, time, gain_to_background)

    # Writers
    def begin(self) -> None:
        if not self.subdivide_output and self.write_to_movie:
            self.open_movie_pipe(self.get_movie_file_path())

    def begin_animation(self) -> None:
        if self.subdivide_output and self.write_to_movie:
            self.open_movie_pipe(self.get_next_partial_movie_path())

    def end_animation(self) -> None:
        if self.subdivide_output and self.write_to_movie:
            self.close_movie_pipe()

    def finish(self) -> None:
        if not self.subdivide_output and self.write_to_movie:
            self.close_movie_pipe()
            if self.includes_sound:
                self.add_sound_to_video()
            self.print_file_ready_message(self.get_movie_file_path())
        if self.save_last_frame:
            self.scene.update_frame(force_draw=True)
            self.save_final_image(self.scene.get_image())
        if self.should_open_file():
            self.open_file()

    def open_movie_pipe(self, file_path: str) -> None:
        if self.writing_process is not None:
            raise FFmpegError("ffmpeg movie pipe is already open")

        final_path = Path(file_path)
        self.final_file_path = final_path
        try:
            self._movie_staging_dir = Path(tempfile.mkdtemp(
                prefix=f".{final_path.stem}-",
                dir=final_path.parent,
            ))
        except OSError as exc:
            raise FFmpegError(
                f"Could not create movie staging data beside {final_path}: {exc}"
            ) from exc
        self.temp_file_path = self._movie_staging_dir / final_path.name

        fps = self.scene.camera.fps
        width, height = self.scene.camera.get_pixel_shape()

        vf_arg = 'vflip'
        if self.saturation != 1.0 or self.gamma != 1.0:
            # eq works in YUV, so with RGBA input ffmpeg inserts an extra
            # RGB->YUV conversion in front of it; as a no-op it still costs
            # a rounding pass that tints neutral greys (measured (24,26,26)
            # for a #1a1a1a background). Only pay for it when asked.
            vf_arg += f',eq=saturation={self.saturation}:gamma={self.gamma}'
        # Tag the stream as BT.709 limited range and convert with that
        # matrix. Untagged H.264 gets converted with swscale's BT.601
        # default and then decoded by browsers as BT.709, so the recorded
        # colours drift from the live WebGPU canvas (a maniml BLUE square
        # measured (80,188,225) in the video against (89,197,223) live;
        # tagged it plays back as (90,197,222)). Greys are unaffected by
        # the matrix, so the mismatch shows on saturated colour, not the
        # background.
        color_tags = []
        if self.pixel_format and self.pixel_format.startswith('yuv'):
            vf_arg += ',scale=out_color_matrix=bt709:out_range=tv'
            color_tags = [
                '-colorspace', 'bt709',
                '-color_primaries', 'bt709',
                '-color_trc', 'bt709',
                '-color_range', 'tv',
            ]

        command = [
            self.ffmpeg_bin,
            '-y',  # overwrite output file if it exists
            '-f', 'rawvideo',
            '-s', f'{width}x{height}',  # size of one frame
            '-pix_fmt', 'rgba',
            '-r', str(fps),  # frames per second
            '-i', '-',  # The input comes from a pipe
            '-vf', vf_arg,
            '-an',  # Tells ffmpeg not to expect any audio
            '-loglevel', 'error',
        ]
        if self.video_codec:
            command += ['-vcodec', self.video_codec]
            # Keyframe at least once a second: presentation playback scrubs
            # by seeking, and seeks land on keyframes. Costs a few percent
            # of size, makes every seek land instantly.
            command += ['-g', str(fps)]
        if self.pixel_format:
            command += ['-pix_fmt', self.pixel_format]
        command += color_tags
        command += [self.temp_file_path]
        try:
            self.writing_process = sp.Popen(command, stdin=sp.PIPE)
        except OSError as exc:
            self._cleanup_movie_staging()
            raise FFmpegError(
                f"Could not start ffmpeg executable {self.ffmpeg_bin!r}: {exc}"
            ) from exc

        try:
            if not self.quiet:
                self.progress_display = ProgressDisplay(
                    range(self.total_frames),
                    leave=False,
                    ascii=True if platform.system() == 'Windows' else None,
                    dynamic_ncols=True,
                )
                self.set_progress_display_description()
        except BaseException:
            self.abort()
            raise

    def use_fast_encoding(self):
        self.video_codec = "libx264rgb"
        self.pixel_format = "rgb32"

    def get_insert_file_path(self, index: int) -> Path:
        movie_path = Path(self.get_movie_file_path())
        scene_name = movie_path.stem
        insert_dir = Path(movie_path.parent, "inserts")
        guarantee_existence(insert_dir)
        return Path(insert_dir, f"{scene_name}_{index}").with_suffix(self.movie_file_extension)

    def begin_insert(self):
        # Begin writing process
        self.write_to_movie = True
        self.init_output_directories()
        index = 0
        while (insert_path := self.get_insert_file_path(index)).exists():
            index += 1
        self.inserted_file_path = insert_path
        self.open_movie_pipe(self.inserted_file_path)

    def end_insert(self):
        try:
            self.close_movie_pipe()
        finally:
            self.write_to_movie = False
        self.print_file_ready_message(self.inserted_file_path)

    def has_progress_display(self):
        return self.progress_display is not None

    def set_progress_display_description(self, file: str = "", sub_desc: str = "") -> None:
        if self.progress_display is None:
            return

        desc_len = self.progress_description_len
        if not file:
            file = os.path.split(self.get_movie_file_path())[1]
        full_desc = f"{file} {sub_desc}"
        if len(full_desc) > desc_len:
            full_desc = full_desc[:desc_len - 3] + "..."
        else:
            full_desc += " " * (desc_len - len(full_desc))
        self.progress_display.set_description(full_desc)

    def write_frame(self, camera: Camera) -> None:
        if self.write_to_movie:
            raw_bytes = camera.get_raw_fbo_data()
            process = self.writing_process
            if process is None or process.stdin is None:
                raise FFmpegError("ffmpeg movie pipe is not open")
            if process.poll() is not None:
                raise FFmpegError(
                    f"ffmpeg exited early with status {process.returncode}"
                )
            try:
                process.stdin.write(raw_bytes)
            except BrokenPipeError as exc:
                process.wait()
                raise FFmpegError(
                    f"ffmpeg exited early with status {process.returncode}"
                ) from exc
            if self.progress_display is not None:
                self.progress_display.update()

    def close_movie_pipe(self) -> None:
        process = self.writing_process
        if process is None or process.stdin is None:
            raise FFmpegError("ffmpeg movie pipe is not open")
        try:
            try:
                process.stdin.close()
            except BrokenPipeError:
                # wait() below supplies the stable, actionable failure.
                pass
            returncode = process.wait()
        finally:
            self.writing_process = None
            if self.progress_display is not None:
                self.progress_display.close()
                self.progress_display = None

        if returncode != 0:
            self._cleanup_movie_staging()
            raise FFmpegError(f"ffmpeg exited with status {returncode}")

        if self.ended_with_interrupt:
            destination = self._reserve_interrupted_path()
        else:
            destination = self.final_file_path

        try:
            os.replace(self.temp_file_path, destination)
        except OSError:
            if self.ended_with_interrupt:
                Path(destination).unlink(missing_ok=True)
            raise
        else:
            self._cleanup_movie_staging()

        if self.ended_with_interrupt:
            self.movie_file_path = Path(destination)

    def abort(self) -> None:
        """Stop an in-progress encode and discard only generated staging data."""
        process = self.writing_process
        self.writing_process = None
        try:
            if process is not None:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except OSError:
                        pass
                if process.stdin is not None:
                    try:
                        process.stdin.close()
                    except (BrokenPipeError, OSError):
                        pass
                try:
                    process.wait(timeout=3)
                except sp.TimeoutExpired:
                    try:
                        process.kill()
                    except OSError:
                        pass
                    try:
                        process.wait(timeout=2)
                    except sp.TimeoutExpired:
                        pass
        finally:
            if self.progress_display is not None:
                self.progress_display.close()
                self.progress_display = None
            self._cleanup_movie_staging()

    def _cleanup_movie_staging(self) -> None:
        staging_dir = self._movie_staging_dir
        self._movie_staging_dir = None
        if staging_dir is not None:
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _reserve_interrupted_path(self) -> Path:
        final_path = Path(self.final_file_path)
        descriptor, path = tempfile.mkstemp(
            prefix=f"{final_path.stem}_interrupted_",
            suffix=final_path.suffix,
            dir=final_path.parent,
        )
        os.close(descriptor)
        return Path(path)

    def add_sound_to_video(self) -> None:
        movie_file_path = Path(self.get_movie_file_path())
        with tempfile.TemporaryDirectory(
            prefix=f".{movie_file_path.stem}-audio-",
            dir=movie_file_path.parent,
        ) as staging_dir:
            sound_file_path = Path(staging_dir, "audio.wav")
            muxed_file_path = Path(staging_dir, movie_file_path.name)

            # Makes sure sound file length will match video file
            self.add_audio_segment(AudioSegment.silent(0))
            self.audio_segment.export(
                sound_file_path,
                bitrate='312k',
            )
            commands = [
                self.ffmpeg_bin,
                "-i", movie_file_path,
                "-i", sound_file_path,
                '-y',  # overwrite the generated staging file if needed
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "320k",
                # select video stream from first file
                "-map", "0:v:0",
                # select audio stream from second file
                "-map", "1:a:0",
                '-loglevel', 'error',
                # "-shortest",
                muxed_file_path,
            ]
            try:
                process = sp.run(commands)
            except OSError as exc:
                raise FFmpegError(
                    f"Could not start ffmpeg executable {self.ffmpeg_bin!r}: {exc}"
                ) from exc
            if process.returncode != 0:
                raise FFmpegError(
                    f"ffmpeg audio mux failed with status {process.returncode}"
                )
            os.replace(muxed_file_path, movie_file_path)

    def save_final_image(self, image: Image) -> None:
        file_path = Path(self.get_image_file_path())
        with tempfile.TemporaryDirectory(
            prefix=f".{file_path.stem}-image-",
            dir=file_path.parent,
        ) as staging_dir:
            staging_path = Path(staging_dir, file_path.name)
            image.save(staging_path)
            os.replace(staging_path, file_path)
        self.print_file_ready_message(file_path)

    def print_file_ready_message(self, file_path: str) -> None:
        if not self.quiet:
            log.info(f"File ready at {file_path}")

    def should_open_file(self) -> bool:
        return any([
            self.show_file_location_upon_completion,
            self.open_file_upon_completion,
        ])

    def open_file(self) -> None:
        if self.quiet:
            curr_stdout = sys.stdout
            sys.stdout = open(os.devnull, "w")

        current_os = platform.system()
        file_paths = []

        if self.save_last_frame:
            file_paths.append(self.get_image_file_path())
        if self.write_to_movie:
            file_paths.append(self.get_movie_file_path())

        for file_path in file_paths:
            if current_os == "Windows":
                os.startfile(file_path)
            else:
                commands = []
                if current_os == "Linux":
                    commands.append("xdg-open")
                elif current_os.startswith("CYGWIN"):
                    commands.append("cygstart")
                else:  # Assume macOS
                    commands.append("open")

                if self.show_file_location_upon_completion:
                    commands.append("-R")

                commands.append(file_path)

                FNULL = open(os.devnull, 'w')
                sp.call(commands, stdout=FNULL, stderr=sp.STDOUT)
                FNULL.close()

        if self.quiet:
            sys.stdout.close()
            sys.stdout = curr_stdout
