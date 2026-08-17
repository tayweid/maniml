"""Desktop integration for opening scene files without a terminal.

The hosted interface deliberately cannot launch local programs.  On macOS we
bridge that boundary with a very small, locally generated application bundle:
Finder hands it an absolute path, and it starts this exact Python interpreter
with ``python -m maniml open <path>``.  Binding the launcher to the interpreter
used at install time also preserves the environment in which maniml and the
scene's dependencies were installed.

The generated launcher is intentionally an additive developer preview.  A
signed/notarized release bundle and Windows/Linux launchers remain release
packaging work; none of this changes the existing CLI path.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

APP_NAME = "ManimLive"
BUNDLE_IDENTIFIER = "io.tayweid.maniml"


def _applescript_string(value: str) -> str:
    """Quote a trusted value as an AppleScript string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _launcher_source(python: Path, log_path: Path, executable_path: str) -> str:
    return f"""property pythonExecutable : {_applescript_string(str(python))}
property launcherLog : {_applescript_string(str(log_path))}
property executablePath : {_applescript_string(executable_path)}

on launchScene(scenePath)
    set quotedPath to quoted form of executablePath
    set quotedPython to quoted form of pythonExecutable
    set quotedScene to quoted form of scenePath
    set quotedLog to quoted form of launcherLog
    set launchCommand to "/usr/bin/env PATH=" & quotedPath & " PYTHONUNBUFFERED=1 " & quotedPython & " -m maniml open " & quotedScene & " >> " & quotedLog & " 2>&1 </dev/null &"
    do shell script launchCommand
end launchScene

on chooseAndLaunch()
    try
        set sceneFile to choose file with prompt "Open a Manim scene"
        my launchScene(POSIX path of sceneFile)
    on error number -128
        return
    end try
end chooseAndLaunch

on run
    my chooseAndLaunch()
end run

on open sceneFiles
    repeat with sceneFile in sceneFiles
        my launchScene(POSIX path of sceneFile)
    end repeat
end open

on open location launchURL
    if launchURL starts with "maniml://open" then
        my chooseAndLaunch()
    end if
end open location
"""


def install_desktop_launcher(
    destination: str | os.PathLike[str] | None = None,
    *,
    replace: bool = False,
    log_directory: str | os.PathLike[str] | None = None,
    register: bool = True,
) -> Path:
    """Install the macOS Finder launcher and return its application path."""
    if sys.platform != "darwin":
        raise RuntimeError(
            "desktop launcher installation currently supports macOS only"
        )
    compiler = shutil.which("osacompile")
    if compiler is None:
        raise RuntimeError("macOS osacompile was not found")

    # Do not resolve a virtualenv's Python symlink: invoking that symlink is
    # what makes Python retain the environment where maniml was installed.
    python = Path(os.path.abspath(sys.executable))
    if not python.is_file():
        raise RuntimeError(f"Python interpreter was not found: {python}")
    destination_path = Path(
        destination or Path.home() / "Applications" / f"{APP_NAME}.app"
    ).expanduser()
    if destination_path.exists() and not replace:
        raise FileExistsError(
            f"{destination_path} already exists; rerun with --replace to update it"
        )
    if destination_path.suffix.lower() != ".app":
        raise ValueError("desktop launcher destination must end in .app")

    destination_path.parent.mkdir(parents=True, exist_ok=True)
    log_dir = Path(
        log_directory or Path.home() / "Library" / "Logs" / APP_NAME
    ).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    source = _launcher_source(
        python, log_dir / "launcher.log", os.environ.get("PATH", "")
    )

    # Compile beside the destination and move into place only after a complete
    # bundle exists, so an interrupted update cannot destroy a working app.
    with tempfile.TemporaryDirectory(
        prefix=".maniml-launcher-", dir=destination_path.parent
    ) as temporary:
        temporary_path = Path(temporary)
        source_path = temporary_path / "launcher.applescript"
        bundle_path = temporary_path / f"{APP_NAME}.app"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [compiler, "-o", str(bundle_path), str(source_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"could not compile desktop launcher: {detail}")

        info_path = bundle_path / "Contents" / "Info.plist"
        with info_path.open("rb") as file:
            info = plistlib.load(file)
        # osacompile adds generic purpose strings for every privacy service an
        # arbitrary AppleScript might use. This launcher requests none of
        # them; retaining those declarations would misrepresent its access.
        for key in list(info):
            if key.startswith("NS") and key.endswith("UsageDescription"):
                info.pop(key)
        info.update(
            {
                "CFBundleDisplayName": APP_NAME,
                "CFBundleIdentifier": BUNDLE_IDENTIFIER,
                "CFBundleName": APP_NAME,
                "CFBundleDocumentTypes": [
                    {
                        "CFBundleTypeExtensions": ["py"],
                        "CFBundleTypeName": "Python source file",
                        "CFBundleTypeRole": "Viewer",
                        # Appear in Open With without taking over every Python
                        # file as the user's default editor.
                        "LSHandlerRank": "Alternate",
                    }
                ],
                "CFBundleURLTypes": [
                    {
                        "CFBundleURLName": BUNDLE_IDENTIFIER,
                        # Required by Launch Services for a URL-type
                        # declaration. Without it, Finder document handling
                        # still works but maniml:// links may have no handler.
                        "CFBundleTypeRole": "Viewer",
                        "CFBundleURLSchemes": ["maniml"],
                    }
                ],
                "LSApplicationCategoryType": "public.app-category.developer-tools",
                "NSHighResolutionCapable": True,
            }
        )
        with info_path.open("wb") as file:
            plistlib.dump(info, file)

        signed = subprocess.run(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                "-",
                "--timestamp=none",
                str(bundle_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if signed.returncode:
            detail = (signed.stderr or signed.stdout).strip()
            raise RuntimeError(f"could not sign desktop launcher: {detail}")

        if destination_path.exists():
            backup = temporary_path / "previous.app"
            destination_path.replace(backup)
            try:
                bundle_path.replace(destination_path)
            except Exception:
                backup.replace(destination_path)
                raise
        else:
            bundle_path.replace(destination_path)

    # Refresh Launch Services so Finder offers ManimLive immediately.  Failure
    # is non-fatal; macOS will discover the bundle on its next normal scan.
    registrar = Path(
        "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
        "LaunchServices.framework/Support/lsregister"
    )
    if register and registrar.is_file():
        subprocess.run(
            [str(registrar), "-f", str(destination_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    return destination_path


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
