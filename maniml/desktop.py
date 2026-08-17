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

import ctypes
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

APP_NAME = "ManimLive Desktop"
BUNDLE_IDENTIFIER = "io.tayweid.maniml.desktop"
LEGACY_APP_NAME = "ManimLive"
LEGACY_BUNDLE_IDENTIFIER = "io.tayweid.maniml"
PYTHON_CONTENT_TYPE = "public.python-script"
LS_ROLES_VIEWER = 0x00000002
LAUNCH_SERVICES_REGISTRAR = Path(
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)
LAUNCH_SERVICES_ATTEMPTS = 3
CORE_FOUNDATION = Path(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)
CORE_SERVICES = Path(
    "/System/Library/Frameworks/CoreServices.framework/CoreServices"
)
CF_STRING_ENCODING_UTF8 = 0x08000100


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


def _register_desktop_launcher(
    application: Path,
    *,
    registrar: Path = LAUNCH_SERVICES_REGISTRAR,
    attempts: int = LAUNCH_SERVICES_ATTEMPTS,
) -> None:
    """Replace any stale registration with this permanent app path."""
    if not registrar.is_file():
        raise RuntimeError("macOS Launch Services registrar was not found")

    subprocess.run(
        [str(registrar), "-u", str(application)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    last_detail = "Launch Services rejected the application"
    for attempt in range(attempts):
        result = subprocess.run(
            [str(registrar), "-lint", "-f", str(application)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return
        last_detail = (
            result.stderr.strip() or result.stdout.strip() or last_detail
        )
        if attempt + 1 < attempts:
            time.sleep(0.2)
    raise RuntimeError(f"could not register desktop launcher: {last_detail}")


def _set_default_url_handler(
    scheme: str = "maniml",
    bundle_identifier: str = BUNDLE_IDENTIFIER,
) -> None:
    """Assign and verify the native handler for the launch URL scheme.

    ``lsregister`` makes Launch Services aware of an application, but it does
    not guarantee that a default handler was assigned.  Chrome can only hand
    ``maniml://`` links to the launcher when this mapping exists, so use the
    public Launch Services API and fail installation if macOS does not retain
    it.  ctypes keeps this developer installer dependency-free.
    """
    try:
        core_foundation = ctypes.CDLL(str(CORE_FOUNDATION))
        core_services = ctypes.CDLL(str(CORE_SERVICES))
    except OSError as error:
        raise RuntimeError("macOS Launch Services APIs were not found") from error

    create_string = core_foundation.CFStringCreateWithCString
    create_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    create_string.restype = ctypes.c_void_p
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None
    compare = core_foundation.CFStringCompare
    compare.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    compare.restype = ctypes.c_long

    set_handler = core_services.LSSetDefaultHandlerForURLScheme
    set_handler.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    set_handler.restype = ctypes.c_int32
    copy_handler = core_services.LSCopyDefaultHandlerForURLScheme
    copy_handler.argtypes = [ctypes.c_void_p]
    copy_handler.restype = ctypes.c_void_p

    scheme_ref = create_string(
        None, scheme.encode("utf-8"), CF_STRING_ENCODING_UTF8
    )
    bundle_ref = create_string(
        None, bundle_identifier.encode("utf-8"), CF_STRING_ENCODING_UTF8
    )
    if not scheme_ref or not bundle_ref:
        for reference in (scheme_ref, bundle_ref):
            if reference:
                release(reference)
        raise RuntimeError("could not create the macOS URL handler values")

    actual_ref = None
    try:
        status = set_handler(scheme_ref, bundle_ref)
        if status != 0:
            raise RuntimeError(
                f"could not assign the {scheme}: URL handler (OSStatus {status})"
            )
        actual_ref = copy_handler(scheme_ref)
        if not actual_ref or compare(actual_ref, bundle_ref, 0) != 0:
            raise RuntimeError(
                f"macOS did not retain {bundle_identifier} as the {scheme}: "
                "URL handler"
            )
    finally:
        if actual_ref:
            release(actual_ref)
        release(bundle_ref)
        release(scheme_ref)


def _verify_document_handler(
    content_type: str = PYTHON_CONTENT_TYPE,
    bundle_identifier: str = BUNDLE_IDENTIFIER,
) -> None:
    """Require Finder to recognize the desktop app as a Python viewer."""
    try:
        core_foundation = ctypes.CDLL(str(CORE_FOUNDATION))
        core_services = ctypes.CDLL(str(CORE_SERVICES))
    except OSError as error:
        raise RuntimeError("macOS Launch Services APIs were not found") from error

    create_string = core_foundation.CFStringCreateWithCString
    create_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    create_string.restype = ctypes.c_void_p
    release = core_foundation.CFRelease
    release.argtypes = [ctypes.c_void_p]
    release.restype = None
    compare = core_foundation.CFStringCompare
    compare.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]
    compare.restype = ctypes.c_long
    array_count = core_foundation.CFArrayGetCount
    array_count.argtypes = [ctypes.c_void_p]
    array_count.restype = ctypes.c_long
    array_value = core_foundation.CFArrayGetValueAtIndex
    array_value.argtypes = [ctypes.c_void_p, ctypes.c_long]
    array_value.restype = ctypes.c_void_p

    copy_handlers = core_services.LSCopyAllRoleHandlersForContentType
    copy_handlers.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    copy_handlers.restype = ctypes.c_void_p

    type_ref = create_string(
        None, content_type.encode("utf-8"), CF_STRING_ENCODING_UTF8
    )
    bundle_ref = create_string(
        None, bundle_identifier.encode("utf-8"), CF_STRING_ENCODING_UTF8
    )
    if not type_ref or not bundle_ref:
        for reference in (type_ref, bundle_ref):
            if reference:
                release(reference)
        raise RuntimeError("could not create the macOS document handler values")

    handlers_ref = None
    try:
        handlers_ref = copy_handlers(type_ref, LS_ROLES_VIEWER)
        recognized = handlers_ref and any(
            compare(array_value(handlers_ref, index), bundle_ref, 0) == 0
            for index in range(array_count(handlers_ref))
        )
        if not recognized:
            raise RuntimeError(
                f"Finder did not register {bundle_identifier} for "
                f"{content_type} files"
            )
    finally:
        if handlers_ref:
            release(handlers_ref)
        release(bundle_ref)
        release(type_ref)


def _retire_legacy_launcher(
    *,
    registrar: Path = LAUNCH_SERVICES_REGISTRAR,
    legacy_application: Path | None = None,
) -> None:
    """Remove the obsolete same-named bridge after its replacement works."""
    legacy = legacy_application or (
        Path.home() / "Applications" / f"{LEGACY_APP_NAME}.app"
    )
    info_path = legacy / "Contents" / "Info.plist"
    try:
        with info_path.open("rb") as file:
            info = plistlib.load(file)
    except (OSError, plistlib.InvalidFileException):
        return
    if not (
        info.get("CFBundleIdentifier") == LEGACY_BUNDLE_IDENTIFIER
        and info.get("CFBundleExecutable") == "droplet"
    ):
        return
    if registrar.is_file():
        subprocess.run(
            [str(registrar), "-u", str(legacy)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    shutil.rmtree(legacy)


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
    default_destination = destination is None
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
    registrar = LAUNCH_SERVICES_REGISTRAR

    # Compile beside the destination and move into place only after a complete
    # bundle exists, so an interrupted update cannot destroy a working app.
    with tempfile.TemporaryDirectory(
        prefix=".maniml-launcher-", dir=destination_path.parent
    ) as temporary:
        temporary_path = Path(temporary)
        source_path = temporary_path / "launcher.applescript"
        compiled_path = temporary_path / "CompiledLauncher.app"
        # Once osacompile finishes, remove the .app suffix before assigning
        # ManimLive's real bundle identifier. Launch Services otherwise keeps
        # dead records for staging paths and can route files/URLs to them.
        payload_path = temporary_path / "launcher.payload"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [compiler, "-o", str(compiled_path), str(source_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeError(f"could not compile desktop launcher: {detail}")

        if registrar.is_file():
            subprocess.run(
                [str(registrar), "-u", str(compiled_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        compiled_path.replace(payload_path)

        info_path = payload_path / "Contents" / "Info.plist"
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
                        "LSItemContentTypes": [PYTHON_CONTENT_TYPE],
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
                str(payload_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if signed.returncode:
            detail = (signed.stderr or signed.stdout).strip()
            raise RuntimeError(f"could not sign desktop launcher: {detail}")

        if destination_path.exists():
            backup = temporary_path / "previous.payload"
            destination_path.replace(backup)
            try:
                payload_path.replace(destination_path)
            except Exception:
                backup.replace(destination_path)
                raise
        else:
            payload_path.replace(destination_path)

    # Finder and the PWA both depend on this registration. Do not claim the
    # installation succeeded when the OS rejected it.
    if register:
        _register_desktop_launcher(destination_path, registrar=registrar)
        _set_default_url_handler()
        _verify_document_handler()
        if default_destination:
            _retire_legacy_launcher(registrar=registrar)
    elif registrar.is_file():
        # osacompile/Finder may notice even a test or custom unregistered
        # bundle. Honor register=False by removing that incidental record so
        # a temporary copy can never compete with the installed application.
        subprocess.run(
            [str(registrar), "-u", str(destination_path)],
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
