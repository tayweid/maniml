"""Background engine management: `maniml agent install` registers the app
server as a macOS launchd user agent — started at login, restarted if it
dies — so the hosted interface always finds a local engine.

This is what removes the desktop bridge from the common path. With an engine
always listening on the fixed control port, the hosted page is already paired
when you open it, so Open… uses the engine's own native file dialog and
navigates the current window. The `maniml://` launcher is then only needed to
start a scene straight from Finder.

The plist points at the current interpreter (sys.executable), so it survives
shell PATH changes but must be reinstalled if the environment moves.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from maniml.web.app import CONTROL_WS_PORT, open_hosted_url
from maniml.web.security import (
    HOSTED_APP_URL,
    capability_path,
    load_or_create_capability,
    rotate_capability,
)

LABEL = "io.tayweid.maniml.agent"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
LOG = Path.home() / "Library" / "Logs" / "maniml-agent.log"
UNSUPPORTED = (
    "maniml agent currently supports macOS (launchd) only.\n"
    "Use `maniml app . --hosted` for the cross-platform foreground engine."
)


def _domain() -> str:
    return f"gui/{os.getuid()}"


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def pairing_url() -> str:
    """Hosted URL carrying the stable capability, for a one-time pairing."""
    return f"{HOSTED_APP_URL}#token={load_or_create_capability()}"


def install(root: str | os.PathLike[str] | None = None, port: int = CONTROL_WS_PORT) -> int:
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
    print("Pair this browser once with: maniml agent pair")
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
    paired = "capability configured" if capability_path().exists() else "not paired"
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


def pair(open_browser: bool = True) -> int:
    """Hand the hosted app the capability once, through the URL fragment."""
    url = pairing_url()
    if open_browser and open_hosted_url(url):
        print("Opened ManimLive to pair this browser with the local engine.")
    else:
        print("Open this once to pair your browser with the local engine:")
        print(url)
    print("Treat that URL like a local password.")
    print("Revoke every paired browser with: maniml agent rotate-token")
    return 0


def rotate_token() -> int:
    rotate_capability()
    print("maniml pairing capability rotated; paired browsers are revoked.")
    if sys.platform == "darwin" and _launchctl(
        "kickstart", "-k", f"{_domain()}/{LABEL}"
    ).returncode == 0:
        print("The agent restarted with the new capability.")
    else:
        print("Restart any running engine to apply the rotation.")
    print("Pair again with: maniml agent pair")
    return 0


def serve(root: str, port: int = CONTROL_WS_PORT) -> int:
    """Run the engine in the foreground; this is what launchd supervises."""
    from maniml.web.app import run_app

    run_app(
        root=root,
        open_browser=False,
        hosted=True,
        control_port=port,
        token=load_or_create_capability(),
    )
    return 0
