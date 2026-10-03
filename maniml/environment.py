"""A scene file's environment: a PEP 723 header, built by uv, layered on the engine.

The header is the one Knuth writes (knuth/env.py, its ENVIRONMENT.md): a
``# /// script`` comment block at the top of the file naming the packages
the scene imports, each pinned exactly, and a date stamp (``[tool.uv]
exclude-newer``) holding everything underneath. It is comments, so ManimCE
and bare Python read past it, and a scene file opened in Knuth shows the
header Knuth would have written. uv builds the environment the header
describes in its own store (``uv sync --script``), on the engine's own
interpreter, and the scene process puts that environment's site-packages
ahead of its own (`activate`): maniml and its dependencies come from the
engine, the scene's imports from the header. Running the scene *in* the
header's environment, as Knuth runs a kernel, would need maniml and its
compiled dependencies installed there too; layering keeps one maniml per
machine, and a file without a header costs nothing.

A scene that dies on a missing import gets the package added (``uv add
--script --bounds exact``) and is started again (web/app.py): at once when
uv already has the package on this Mac, after a click when it would have
to download. Knuth's rule (Taylor, 2026-09-27): using what is downloaded
needs no permission; downloading does.

Standard library only: the scene process imports this before anything else.
"""

from __future__ import annotations

import datetime
import hashlib
import importlib
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path

HEADER_OPEN = "# /// script"
HEADER_CLOSE = "# ///"

# The uv the shell installed, handed down to the engine and its scene
# processes (claerbout main.js sets `<envPrefix>_UV`).
UV_VAR = "MANIML_UV"

# The floor a new header gets. maniml's own (pyproject.toml, held together
# by tests/test_environment.py), not the engine's minor version as Knuth
# writes: the scene runs on the engine's interpreter whatever the header
# says, and a header written beside a 3.14 checkout must still build for
# the app's 3.13.
REQUIRES_PYTHON = ">=3.11"

# uv's progress bars are for a terminal; its one-line steps are what the
# page shows. The interpreter is named on every call (`--python`), so no
# preference setting is needed to keep uv off the machine's own Pythons.
UV_ENVIRON = {"UV_NO_PROGRESS": "1"}

# Import names that differ from the distribution that provides them (the
# same table as Knuth's). Anything not listed is assumed to share its
# name, which is the common case.
DISTRIBUTIONS = {
    "PIL": "pillow",
    "bs4": "beautifulsoup4",
    "cv2": "opencv-python",
    "Crypto": "pycryptodome",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "dotenv": "python-dotenv",
    "fitz": "pymupdf",
    "gi": "PyGObject",
    "google.protobuf": "protobuf",
    "jwt": "pyjwt",
    "Levenshtein": "python-Levenshtein",
    "magic": "python-magic",
    "nacl": "pynacl",
    "OpenSSL": "pyopenssl",
    "pptx": "python-pptx",
    "serial": "pyserial",
    "skimage": "scikit-image",
    "sklearn": "scikit-learn",
    "usb": "pyusb",
    "wx": "wxPython",
    "yaml": "pyyaml",
    "zmq": "pyzmq",
}

MAX_REASON_CHARS = 600

# The line a missing import leaves in a scene's output. The top-level name
# only: `No module named 'seaborn.palettes'` is still seaborn's package.
MISSING_IMPORT = re.compile(r"ModuleNotFoundError: No module named '([A-Za-z_][A-Za-z0-9_]*)")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# A distribution name as PEP 508 spells it: what the page may ask to add,
# and nothing that uv would read as an option.
_PACKAGE_NAME = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$")
# A requirement's leading project name (PEP 508), for reading pins back.
_REQUIREMENT = re.compile(r"^\s*([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)\s*(\[[^\]]*\])?\s*(.*)$")
# The header's date line, `# exclude-newer = "..."`, value replaced whole.
_EXCLUDE_NEWER = re.compile(r'^(#\s*exclude-newer\s*=\s*)"[^"\n]*"', re.MULTILINE)


# --- the header -------------------------------------------------------------


def find_header(text: str) -> tuple[int, int] | None:
    """(first, last) line indexes of the file's script header, or None.

    PEP 723: the first ``# /// script`` line, then comment lines (``#`` or
    ``# ...``) up to a ``# ///`` line. Anything else before the close means
    there is no header, however the block started.
    """
    lines = text.splitlines()
    for first, line in enumerate(lines):
        if line.rstrip() != HEADER_OPEN:
            continue
        for last in range(first + 1, len(lines)):
            body = lines[last].rstrip()
            if body == HEADER_CLOSE:
                return first, last
            if body != "#" and not body.startswith("# "):
                break
        return None
    return None


def header_lines(text: str) -> list[str] | None:
    span = find_header(text)
    if span is None:
        return None
    first, last = span
    return text.splitlines()[first:last + 1]


def parse_header(text: str) -> dict | None:
    """The header's fields, or None when the file has no header. A header
    that is not valid TOML comes back with an `error` and empty fields."""
    lines = header_lines(text)
    if lines is None:
        return None
    body = "\n".join(
        line[2:] if line.startswith("# ") else "" for line in lines[1:-1]
    )
    result: dict = {"requires_python": None, "dependencies": [], "exclude_newer": None}
    try:
        data = tomllib.loads(body)
    except tomllib.TOMLDecodeError as exc:
        result["error"] = f"environment header is not valid TOML: {exc}"
        return result
    requires = data.get("requires-python")
    if isinstance(requires, str):
        result["requires_python"] = requires
    dependencies = data.get("dependencies")
    if isinstance(dependencies, list):
        result["dependencies"] = [d for d in dependencies if isinstance(d, str)]
    tool = data.get("tool")
    uv = tool.get("uv", {}) if isinstance(tool, dict) else {}
    stamp = uv.get("exclude-newer") if isinstance(uv, dict) else None
    if isinstance(stamp, str):
        result["exclude_newer"] = stamp
    return result


def stamp_today() -> str:
    """Midnight UTC today: the date after which the resolver sees nothing."""
    today = datetime.datetime.now(datetime.timezone.utc).date()
    return f"{today.isoformat()}T00:00:00Z"


def stamp_now() -> str:
    """This second, UTC: a package added now comes at its newest version."""
    now = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    return now.strftime("%Y-%m-%dT%H:%M:%SZ")


def new_header(requires_python: str | None = None, stamp: str | None = None) -> list[str]:
    """The header a scene file gets: no packages, maniml's floor, the stamp.

    Formatted exactly as `uv init --script` writes it, so a later `uv add`
    changes only the lines it must.
    """
    return [
        HEADER_OPEN,
        f'# requires-python = "{requires_python or REQUIRES_PYTHON}"',
        "# dependencies = []",
        "#",
        "# [tool.uv]",
        f'# exclude-newer = "{stamp or stamp_today()}"',
        HEADER_CLOSE,
    ]


def with_header(text: str, requires_python: str | None = None, stamp: str | None = None) -> tuple[str, bool]:
    """(text, created): the text with a fresh header prepended, or as it
    was when it already has one. The existing text is untouched below the
    blank line that separates the header from it."""
    if find_header(text) is not None:
        return text, False
    lines = new_header(requires_python, stamp)
    eol = "\r\n" if "\r\n" in text else "\n"
    header = eol.join(lines) + eol
    if text == "":
        return header, True
    return header + eol + text, True


def pinned_version(text: str, distribution: str) -> str | None:
    """The `==` version the header pins `distribution` to, or None."""
    header = parse_header(text) or {}
    wanted = _normalize(distribution)
    for spec in header.get("dependencies", []):
        match = _REQUIREMENT.match(spec)
        if not match:
            continue
        version, _semicolon, _marker = match.group(3).partition(";")
        if _normalize(match.group(1)) == wanted and version.strip().startswith("=="):
            return version.strip()[2:].strip()
    return None


def _normalize(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


# --- uv ---------------------------------------------------------------------


def find_uv() -> str | None:
    """The uv binary: $MANIML_UV, then beside our interpreter, then on PATH."""
    named = os.environ.get(UV_VAR)
    if named and os.path.isfile(named):
        return named
    suffix = ".exe" if sys.platform == "win32" else ""
    sibling = Path(sys.executable).resolve().parent / f"uv{suffix}"
    if sibling.is_file():
        return str(sibling)
    return shutil.which("uv")


def _uv_environ() -> dict:
    environ = dict(os.environ)
    for key, value in UV_ENVIRON.items():
        environ.setdefault(key, value)
    return environ


def run_uv(args: list[str], cwd: str | None = None, on_progress=None) -> subprocess.CompletedProcess:
    """Run uv; never raises for uv's own failures (a nonzero return code
    carries them), only when uv is absent.

    `on_progress` hears each step uv reports as it happens ("Downloading
    scipy (33.1MiB)"), so a long build is never an opaque wait. uv writes
    those to stderr, one line per step."""
    uv = find_uv()
    if not uv:
        raise FileNotFoundError("uv is not installed")
    if on_progress is None:
        return subprocess.run(
            [uv, *args], capture_output=True, text=True, cwd=cwd, env=_uv_environ()
        )
    process = subprocess.Popen(
        [uv, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        cwd=cwd, env=_uv_environ(),
    )
    stdout: list[str] = []
    reader = threading.Thread(target=lambda: stdout.append(process.stdout.read()), daemon=True)
    reader.start()
    stderr: list[str] = []
    for line in process.stderr:
        stderr.append(line)
        step = progress_step(line)
        if step:
            on_progress(step)
    process.wait()
    reader.join()
    return subprocess.CompletedProcess(process.args, process.returncode, "".join(stdout), "".join(stderr))


def progress_step(line: str) -> str | None:
    """A line of uv's worth showing, or None: its steps, not the per-package
    list (`+ numpy==2.5.3`) it prints at the end."""
    line = line.strip()
    if line.startswith(("Creating script environment", "Using script environment")):
        return "Preparing the scene's environment"  # not the cache path it names
    if not line or line[0] in "+-~" or len(line) > MAX_REASON_CHARS:
        return None
    return line


def _reason(result: subprocess.CompletedProcess, fallback: str) -> str:
    """The useful part of uv's stderr, bounded, for a user-facing message."""
    lines = [line.rstrip() for line in result.stderr.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith((
        "Creating", "Using", "Resolved", "Prepared", "Installed", "Uninstalled", "Audited", "Checked"))]
    text = "\n".join(lines).strip() or fallback
    if len(text) > MAX_REASON_CHARS:
        text = text[: MAX_REASON_CHARS - 1] + "…"
    return text


# --- the environment --------------------------------------------------------


@dataclass
class Environment:
    """What a scene file runs with. `managed` means the file's own uv
    environment is layered on the engine's interpreter, `site_packages`
    naming it; otherwise the scene runs on the engine alone and `reason`
    says why (for a file without a header, that is the normal case)."""

    document: str | None
    python: str
    site_packages: str | None
    managed: bool
    reason: str | None = None


def _fallback(document: str | None, reason: str) -> Environment:
    return Environment(document, sys.executable, None, False, reason)


def _read(document: str) -> str | None:
    try:
        return Path(document).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def has_header(document: str) -> bool:
    text = _read(document)
    return text is not None and find_header(text) is not None


def _site_packages(python: str) -> str | None:
    """The site-packages of the environment whose interpreter `python` is.
    Not resolved: uv's `bin/python` is a link to the base interpreter, and
    the environment is the directory the link sits in."""
    prefix = str(Path(python).parent.parent)
    try:
        path = sysconfig.get_path("purelib", "venv", vars={"base": prefix, "platbase": prefix})
    except (KeyError, LookupError):
        return None
    return path if path and os.path.isdir(path) else None


def ensure_environment(document: str, on_progress=None) -> Environment:
    """Build or refresh the file's environment and name its site-packages.

    Blocking, possibly for minutes the first time (uv may download). Never
    raises: every failure is a fallback to the engine alone with a reason.
    The environment is built on the engine's own interpreter, so what it
    holds loads in the scene process that layers it.
    """
    text = _read(document)
    if text is None:
        return _fallback(document, "the scene file could not be read")
    if find_header(text) is None:
        return _fallback(document, "no environment header")
    if find_uv() is None:
        return _fallback(document, "uv is not installed")
    folder = str(Path(document).parent)
    try:
        synced = run_uv(["sync", "--script", document, "--python", sys.executable],
                        cwd=folder, on_progress=on_progress)
        if synced.returncode != 0:
            return _fallback(document, _reason(synced, "uv could not build the environment"))
        found = run_uv(["python", "find", "--script", document], cwd=folder)
    except (OSError, subprocess.SubprocessError) as exc:
        return _fallback(document, f"uv could not run: {exc}")
    if found.returncode != 0:
        return _fallback(document, _reason(found, "uv could not find the environment"))
    python = found.stdout.strip().splitlines()[-1] if found.stdout.strip() else ""
    if not python or not os.path.exists(python):
        return _fallback(document, "uv did not report an interpreter")
    site = _site_packages(python)
    if site is None:
        return _fallback(document, "the environment has no site-packages")
    return Environment(document, python, site, True)


# What `activate` last did for each file: the header it saw and the path it
# put on sys.path, so a reload with the same header costs one file read.
_activated: dict[str, tuple[str, str | None]] = {}


def _print_step(step: str) -> None:
    print(f"maniml environment: {step}", flush=True)


def activate(document: str, on_progress=_print_step) -> Environment:
    """Give this process the file's environment: build it if the header
    changed since last time, and put its site-packages first on sys.path.

    Called by the scene loader before every load of the file, so a header
    edit takes effect on the next reload. A file without a header is left
    alone, and a previously layered path is dropped when its header goes."""
    document = os.path.abspath(document)
    text = _read(document)
    lines = header_lines(text) if text is not None else None
    key = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest() if lines else ""
    seen = _activated.get(document)
    if seen is not None and seen[0] == key:
        site = seen[1]
        if site is None:
            return _fallback(document, "no environment header")
        if site not in sys.path:
            sys.path.insert(0, site)
            importlib.invalidate_caches()
        return Environment(document, sys.executable, site, True)
    if seen is not None and seen[1] is not None and seen[1] in sys.path:
        sys.path.remove(seen[1])
    if not lines:
        _activated[document] = (key, None)
        return _fallback(document, "no environment header")
    environment = ensure_environment(document, on_progress=on_progress)
    if not environment.managed:
        # Not remembered: the next load tries again (uv may have arrived,
        # the network may be back), and the reason is printed each time.
        print(f"maniml environment: running on the engine alone ({environment.reason})", flush=True)
        return environment
    _activated[document] = (key, environment.site_packages)
    if environment.site_packages not in sys.path:
        sys.path.insert(0, environment.site_packages)
    importlib.invalidate_caches()
    return environment


# --- adding a package -------------------------------------------------------


def missing_module(log: str) -> str | None:
    """The top-level module a scene's output says it could not import."""
    match = MISSING_IMPORT.search(_ANSI.sub("", log))
    return match.group(1) if match else None


def distribution_for(module: str) -> str:
    return DISTRIBUTIONS.get(module, module)


def is_package_name(name: object) -> bool:
    return isinstance(name, str) and _PACKAGE_NAME.match(name) is not None


def import_name_hint(module: str) -> str | None:
    """When `module` is a package's name spelled as an import (`import
    scikitlearn`, `import pillow`) and that package imports as something
    else, the words to say so; otherwise None. Nothing to download: the
    import itself is what is wrong."""
    squashed = re.sub(r"[-_.]", "", module).lower()
    for name, distribution in DISTRIBUTIONS.items():
        if re.sub(r"[-_.]", "", distribution).lower() == squashed and name != module:
            return f"it's {distribution}, which is imported as {name}"
    return None


def add_dependency(document: str, distribution: str, offline: bool = False,
                   on_progress=None) -> tuple[bool, str | None, bool]:
    """`uv add --script --bounds exact`, then sync: the header gains an
    exact pin and the environment gains the package. (ok, reason, download).

    A file without a header gets one first. The header's date moves to now,
    so the package comes at its newest version; everything already listed
    is pinned exactly, so nothing else moves. `offline`: only what uv
    already has on this Mac, never a download; when that is the only thing
    in the way, `download` is True and the file is as it was. Any failure
    leaves the file as it was, header and date included."""
    if not is_package_name(distribution):
        return False, f"{distribution!r} is not a package name", False
    folder = str(Path(document).parent)
    before = _read(document)
    if before is None:
        return False, "the scene file could not be read", False
    text, _created = with_header(before)
    text = _EXCLUDE_NEWER.sub(lambda m: f'{m.group(1)}"{stamp_now()}"', text, count=1)
    if text != before:
        Path(document).write_text(text, encoding="utf-8")
    network = ["--offline"] if offline else []

    def undo():
        Path(document).write_text(before, encoding="utf-8")

    try:
        added = run_uv(
            ["add", *network, "--script", document, "--bounds", "exact", distribution],
            cwd=folder, on_progress=on_progress,
        )
        if added.returncode != 0:
            undo()
            if offline and "not found in the cache" in added.stderr:
                return False, None, True
            if "not found in the package registry" in added.stderr:
                # uv's resolver prose is a paragraph; the fact is one line.
                return False, f"there's no package named {distribution} on PyPI. Check the import's spelling", False
            return False, _reason(added, f"uv could not add {distribution}"), False
        synced = run_uv(["sync", *network, "--script", document, "--python", sys.executable],
                        cwd=folder, on_progress=on_progress)
    except (OSError, subprocess.SubprocessError) as exc:
        undo()
        return False, f"uv could not run: {exc}", False
    if synced.returncode != 0:
        undo()
        return False, _reason(synced, f"uv could not install {distribution}"), False
    return True, None, False


def terminal_hint(document: str, module: str) -> str:
    """What to print under a missing-import traceback in a terminal: the
    one command that adds the package to the file's environment."""
    distribution = distribution_for(module)
    uv = find_uv()
    if uv is None:
        return (f"'{module}' is not installed for {os.path.basename(document)}. "
                f"Install uv (https://docs.astral.sh/uv/) and run the scene again, "
                f"or install it beside maniml with: {sys.executable} -m pip install {distribution}")
    hint = import_name_hint(module)
    if hint:
        return f"'{module}' is not a module: {hint}."
    return (f"'{module}' is not installed for {os.path.basename(document)}. "
            f"Add it to the scene's environment with:  uv add --script "
            f"{document} --bounds exact {distribution}")
