from __future__ import annotations

import os
import platform
import subprocess

from maniml.utils.directories import get_sound_dir
from maniml.utils.file_ops import find_file


def get_full_sound_file_path(sound_file_name: str) -> str:
    return find_file(
        sound_file_name,
        directories=[get_sound_dir()],
        extensions=[".wav", ".mp3", ""]
    )


def play_sound(sound_file):
    """Play a sound file using the system's audio player"""
    full_path = get_full_sound_file_path(sound_file)
    system = platform.system()

    if system == "Windows":
        # Pass the path as data in the child environment.  Interpolating it
        # into PowerShell source would let quotes in a filename become code.
        env = {**os.environ, "MANIML_SOUND_FILE": os.fspath(full_path)}
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "(New-Object Media.SoundPlayer "
                "$env:MANIML_SOUND_FILE).PlaySync()",
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    elif system == "Darwin":
        # macOS
        subprocess.Popen(
            ["afplay", full_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    else:
        subprocess.Popen(
            ["aplay", full_path],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
