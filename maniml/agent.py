"""Background engine management: `maniml agent install` registers the app
server as a macOS launchd user agent — started at login, restarted if it
dies — so ManimLive is always there at a stable local address.

With the agent running, http://localhost:8685 is simply always up: no
terminal to keep open, no pairing dance, and the page it serves comes from
the installed package, so it can never be out of step with the engine.

The plist points at the current interpreter (sys.executable), so it survives
shell PATH changes but must be reinstalled if the environment moves.
"""

from __future__ import annotations

import os
import plistlib
import socket
import time
import subprocess
import sys
import json
import webbrowser
from pathlib import Path

from maniml.web.app import DEFAULT_APP_PORT
from maniml.web.security import CONFIG_DIR, prepare_config_dir

LABEL = "io.tayweid.maniml.agent"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "maniml-agent.log"
UNSUPPORTED = (
    "maniml agent currently supports macOS (launchd) only.\n"
    "Use `maniml app` for the cross-platform foreground engine."
)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


STATE_PATH = CONFIG_DIR / "agent.json"


def app_url() -> str:
    """Local address of the running agent.

    Read from the file the agent writes at startup rather than assumed: if
    something already held the default port, it is serving somewhere else.
    """
    base = f"http://localhost:{DEFAULT_APP_PORT}/"
    try:
        with STATE_PATH.open(encoding="utf-8") as file:
            published = json.load(file).get("url")
        if isinstance(published, str) and published.startswith("http://localhost:"):
            base = published
    except (OSError, ValueError):
        pass
    return base


OFFERED_PATH = CONFIG_DIR / "agent-offered"


def is_installed() -> bool:
    return PLIST.exists()


def offer_at_first_run(root: str, port: int = DEFAULT_APP_PORT) -> bool:
    """Ask once whether to keep the engine running after the terminal closes.

    Returns True when the agent now owns the engine, so the caller has nothing
    left to serve.

    The agent is what makes ManimLive an application rather than a command you
    have to leave running: close the terminal, log out, reboot, and
    http://localhost:8685 is still there. The only moment worth asking is the
    first time someone starts the app — asking again would be nagging, and
    never asking leaves the good behaviour behind a command nobody knows
    exists.
    """
    if sys.platform != "darwin" or OFFERED_PATH.exists():
        return False
    if is_installed():
        _mark_offered()
        return False
    if not (sys.stdin and sys.stdin.isatty()):
        return False  # a supervised or piped run must never block on input

    print()
    print("Keep ManimLive running in the background, so it stays at")
    print(f"http://localhost:{port} without a terminal?")
    try:
        answer = input("[Y/n] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    _mark_offered()
    if answer not in ("", "y", "yes"):
        print("Skipped. Run `maniml agent install` later if you change your mind.")
        return False
    if install(root, port) != 0:
        return False
    # The agent is the engine now. Wait for it to take the port so the caller
    # opens a page that answers.
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            if probe.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.1)
    return True


def _mark_offered() -> None:
    try:
        prepare_config_dir()
        OFFERED_PATH.touch()
    except OSError:
        pass  # asking twice is a nuisance, not a failure


# Where the tools a scene shells out to actually live on macOS. Appended to
# an inherited PATH rather than replacing it, so this can only ever add
# somewhere to look.
TOOL_DIRS = (
    "/Library/TeX/texbin",      # MacTeX
    "/usr/local/texlive",
    "/opt/homebrew/bin",        # Homebrew, Apple silicon
    "/usr/local/bin",           # Homebrew, Intel; MacPorts
)


def search_path(base: str | None = None) -> str:
    """A PATH that can find latex and ffmpeg, whatever launchd handed us.

    The install-time PATH is captured into the plist, but it goes stale the
    moment a TeX distribution is installed afterwards — so the standard
    locations are appended too, and only if they exist. Nothing is removed
    and nothing is reordered: an entry already present keeps its priority.
    """
    parts = [p for p in (base or os.environ.get("PATH", "")).split(os.pathsep) if p]
    for directory in TOOL_DIRS:
        if directory not in parts and os.path.isdir(directory):
            parts.append(directory)
    return os.pathsep.join(parts)


def install(
    root: str | os.PathLike[str] | None = None, port: int = DEFAULT_APP_PORT
) -> int:
    if sys.platform != "darwin":
        print(UNSUPPORTED)
        return 1
    try:
        scene_root = Path(root).expanduser().resolve(strict=True) if root else Path.home()
    except OSError:
        print(f"Error: agent root not found: {root}")
        return 1
    if not scene_root.is_dir():
        print(f"Error: agent root is not a directory: {scene_root}")
        return 1

    uninstall(quiet=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": LABEL,
        "ProgramArguments": [
            # One argv entry: the CLI treats any leading-dash token as a flag,
            # so a separated value would be parsed as a positional argument.
            sys.executable, "-m", "maniml", "agent", "serve", str(scene_root),
            f"--port={port}",
        ],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(LOG),
        "StandardErrorPath": str(LOG),
        # launchd gives a login agent PATH=/usr/bin:/bin:/usr/sbin:/sbin and
        # nothing else, so a scene run through the app cannot find latex,
        # dvisvgm or ffmpeg even when they are installed — while the same
        # scene run from a terminal works, which makes it look like a maniml
        # bug rather than a missing search path. Carry the installing shell's
        # PATH: it is the closest thing to "what your terminal sees".
        "EnvironmentVariables": {"PATH": search_path()},
    }
    with open(PLIST, "wb") as file:
        plistlib.dump(plist, file)
    result = _launchctl("bootstrap", _domain(), str(PLIST))
    if result.returncode != 0:
        print(f"launchctl bootstrap failed: {result.stderr.strip()}")
        return 1
    # bootstrap registers the job; RunAtLoad only fires at login. Start it now.
    _launchctl("kickstart", f"{_domain()}/{LABEL}")
    print(f"Installed {LABEL}: engine on 127.0.0.1:{port} (scenes under {scene_root})")
    print(f"Runs at login, restarts on exit. Log: {LOG}")
    print("Open it with: maniml agent open")
    return 0


def uninstall(quiet: bool = False) -> int:
    if sys.platform != "darwin":
        if not quiet:
            print(UNSUPPORTED)
        return 1
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    existed = PLIST.exists()
    PLIST.unlink(missing_ok=True)
    if not quiet:
        print(f"Removed {LABEL}" if existed else f"{LABEL} was not installed")
    return 0


def status() -> int:
    if sys.platform != "darwin":
        print(UNSUPPORTED)
        return 1
    result = _launchctl("print", f"{_domain()}/{LABEL}")
    if result.returncode != 0:
        print(f"{LABEL}: not installed (maniml agent install)")
        return 1
    state = next(
        (line.strip() for line in result.stdout.splitlines() if "state =" in line),
        "state unknown",
    )
    print(f"{LABEL}: installed, {state}. Log: {LOG}")
    return 0


def restart() -> int:
    if sys.platform != "darwin":
        print(UNSUPPORTED)
        return 1
    result = _launchctl("kickstart", "-k", f"{_domain()}/{LABEL}")
    if result.returncode != 0:
        print(f"Could not restart {LABEL}: {result.stderr.strip()}")
        return 1
    print(f"Restarted {LABEL}; running scenes were stopped.")
    return 0


def open_app(open_browser: bool = True) -> int:
    """Open the running agent's app."""
    if not STATE_PATH.exists():
        print(f"{LABEL} does not appear to be running (maniml agent status)")
    url = app_url()
    if open_browser and webbrowser.open(url):
        print(f"Opened {url}")
    else:
        print(url)
    return 0


def serve(root: str, port: int = DEFAULT_APP_PORT) -> int:
    """Run the engine in the foreground; this is what launchd supervises."""
    from maniml.web.cli import run_app

    # Also at run time, not just at install: an agent installed before MacTeX
    # was would otherwise carry a PATH that cannot find it until it is
    # reinstalled, and every scene using Tex would fail with a message saying
    # to install something that is already there.
    os.environ["PATH"] = search_path()

    run_app(
        root=root,
        open_browser=False,
        port=port,
        state_path=STATE_PATH,
    )
    return 0
