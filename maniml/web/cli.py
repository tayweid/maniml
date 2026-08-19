"""`maniml app` as a command: find or become the engine, then block.

The decisions here are a terminal's, not a server's: is an engine
already holding the default port (use it, don't compete with it — the
port is the installed app's identity), should this first run offer the
background agent, where to publish the address a supervised agent
landed on, and how to come down cleanly on Ctrl-C or SIGTERM.
`AppServer` in app.py neither knows nor cares who started it.
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import threading
import webbrowser
from pathlib import Path

from maniml.web.app import DEFAULT_APP_PORT, AppServer
from maniml.web.assets import _package_version


def running_engine(port: int = DEFAULT_APP_PORT, timeout: float = 1.5) -> str | None:
    """The version a ManimLive engine on `port` is serving, or None.

    Distinguishes our own engine from anything else that happens to hold the
    port, and reports what it is *running* rather than what is installed —
    pip replaces files, it does not restart processes.
    """
    import re
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/", timeout=timeout
        ) as response:
            head = response.read(4096).decode("utf-8", "replace")
    except (OSError, urllib.error.URLError, ValueError):
        return None
    found = re.search(r'<meta name="maniml" content="([^"]*)"', head)
    return found.group(1) if found else None


def hand_off_to_a_running_engine(root: str, open_browser: bool) -> bool:
    """Use an engine that is already up, or offer to install one that stays.

    Returns True when this command has nothing left to serve.

    Two things follow from the port being the installed app's identity. An
    engine already on it should be *used*, not competed with — starting a
    second one on another port gives you a page the installed app will never
    open. And an engine still serving pre-upgrade code should be restarted:
    pip replaces files, it does not restart processes, and the symptoms of
    that are baffling.
    """
    from maniml import agent

    serving = running_engine()
    if serving is not None:
        installed = _package_version()
        if serving != installed and agent.is_installed():
            print(
                f"The running engine is serving {serving}, but {installed} is "
                "installed. Restarting it."
            )
            agent.restart()
        elif serving != installed:
            print(
                f"Note: the engine on port {DEFAULT_APP_PORT} is serving "
                f"{serving}, but {installed} is installed. Restart it to pick "
                "up the new version."
            )
        url = f"http://localhost:{DEFAULT_APP_PORT}/"
        print(f"maniml app: {url}  (already running)")
        if open_browser:
            webbrowser.open(url)
        return True

    if agent.offer_at_first_run(root):
        url = f"http://localhost:{DEFAULT_APP_PORT}/"
        print(f"maniml app: {url}  (running in the background)")
        if open_browser:
            webbrowser.open(url)
        return True
    return False


def run_app(
    root: str = ".",
    open_browser: bool = True,
    allow_outside_root: bool = False,
    port: int | None = None,
    state_path: str | os.PathLike[str] | None = None,
    offer_agent: bool = False,
) -> None:
    if offer_agent and hand_off_to_a_running_engine(root, open_browser):
        return
    server = AppServer(
        root,
        port=port,
        allow_outside_root=allow_outside_root,
    )
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def exit_on_sigterm(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, exit_on_sigterm)
    # A supervised agent is not the one printing to a terminal, and it may not
    # have got the default port. Publish where it actually landed.
    if state_path is not None:
        try:
            state_file = Path(state_path)
            state_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor = os.open(
                state_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump({"url": server.url, "port": server.port}, file)
            atexit.register(lambda: state_file.unlink(missing_ok=True))
        except OSError:
            pass
    if server.port != DEFAULT_APP_PORT:
        # The port is the installed app's identity: a PWA installed from
        # :8685 is scoped to it, so a session that landed elsewhere is a
        # different app to the browser. Usually this means the login agent
        # already holds the default, which is fine — but say so rather than
        # let someone wonder why their installed window is not this one.
        print(
            f"note: port {DEFAULT_APP_PORT} was taken, so this session is on "
            f"{server.port}. An installed ManimLive opens the one on "
            f"{DEFAULT_APP_PORT}; this one runs in a tab."
        )
    print(f"maniml app: {server.url}  (scenes under {server.root})")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.shutdown()
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
