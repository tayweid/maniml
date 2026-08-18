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
import subprocess
import sys
import json
import webbrowser
from pathlib import Path

from maniml.web.app import DEFAULT_APP_PORT
from maniml.web.security import (
    CONFIG_DIR,
    capability_path,
    load_or_create_capability,
    rotate_capability,
)

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
    """Local address of the running agent, carrying its capability.

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
    return f"{base}#token={load_or_create_capability()}"


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

    load_or_create_capability()
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
    paired = "capability configured" if capability_path().exists() else "no capability"
    print(f"{LABEL}: installed, {state}, {paired}. Log: {LOG}")
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
    print("Treat that URL like a local password.")
    print("Revoke it with: maniml agent rotate-token")
    return 0


def rotate_token() -> int:
    rotate_capability()
    print("maniml capability rotated; existing browser sessions are revoked.")
    if sys.platform == "darwin" and _launchctl(
        "kickstart", "-k", f"{_domain()}/{LABEL}"
    ).returncode == 0:
        print("The agent restarted with the new capability.")
    else:
        print("Restart any running engine to apply the rotation.")
    print("Reopen the app with: maniml agent open")
    return 0


def serve(root: str, port: int = DEFAULT_APP_PORT) -> int:
    """Run the engine in the foreground; this is what launchd supervises."""
    from maniml.web.app import run_app

    run_app(
        root=root,
        open_browser=False,
        port=port,
        token=load_or_create_capability(),
        state_path=STATE_PATH,
    )
    return 0
