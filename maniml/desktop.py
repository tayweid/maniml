"""Native file chooser for the local app.

The app serves its own interface on loopback, so opening a scene needs no
browser bridge: the page asks the engine, and the engine shows the platform's
own dialog. Using a separate dialog process keeps GUI-main-thread requirements
and GUI dependencies out of the renderer.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def choose_python_file(initial_directory: str | os.PathLike[str]) -> str | None:
    """Show a native Python-file chooser; return ``None`` on cancellation.

    This is called on a worker thread by the authenticated loopback service.
    Using the platform dialog process avoids GUI-main-thread requirements in
    the renderer process and keeps GUI libraries out of maniml's dependencies.
    """
    initial = str(Path(initial_directory).resolve())
    if sys.platform == "darwin":
        script = """on run argv
set startFolder to POSIX file (item 1 of argv)
try
    set sceneFile to choose file with prompt "Open a Manim scene" default location startFolder
    return POSIX path of sceneFile
on error number -128
    return ""
end try
end run"""
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script, initial],
            capture_output=True,
            text=True,
            check=False,
        )
    elif os.name == "nt":
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if powershell is None:
            raise RuntimeError("Windows file picker is unavailable")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms;"
            "$d=New-Object System.Windows.Forms.OpenFileDialog;"
            "$d.Filter='Python files (*.py)|*.py';"
            "$d.InitialDirectory=$env:MANIML_PICKER_ROOT;"
            "if($d.ShowDialog() -eq 'OK'){[Console]::Write($d.FileName)}"
        )
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            env={**os.environ, "MANIML_PICKER_ROOT": initial},
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        zenity = shutil.which("zenity")
        kdialog = shutil.which("kdialog")
        if zenity:
            result = subprocess.run(
                [
                    zenity,
                    "--file-selection",
                    "--title=Open a Manim scene",
                    f"--filename={initial}{os.sep}",
                    "--file-filter=Python files | *.py",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
        elif kdialog:
            result = subprocess.run(
                [kdialog, "--getopenfilename", initial, "*.py|Python files"],
                capture_output=True,
                text=True,
                check=False,
            )
        else:
            raise RuntimeError(
                "native file picker unavailable (install zenity or kdialog)"
            )

    if result.returncode:
        if sys.platform == "darwin":
            detail = result.stderr.strip() or "native file picker failed"
            raise RuntimeError(detail)
        # Windows returns success with no output on cancellation; Zenity and
        # KDialog use a nonzero status.
        return None
    selected = result.stdout.rstrip("\r\n")
    return selected or None
