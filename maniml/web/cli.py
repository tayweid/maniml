"""`maniml app` as a command: become the engine, then block.

The decisions here are a terminal's, not a server's: where the tools a
scene shells out to live when the engine was started with a bare PATH,
whether to open a browser tab, and how to come down cleanly on Ctrl-C or
SIGTERM. `AppServer` in app.py neither knows nor cares who started it.
"""

from __future__ import annotations

import os
import signal
import threading
import time
import webbrowser

from maniml.web.app import DEFAULT_APP_PORT, AppServer

# How long an engine a script started outlives its last window: long enough
# for a reload or a scene switch, the same three minutes as the course
# editor's (Edit <course>.app). ManimLive.app's engine is the shell's child
# (`--parent`) and needs no idle rule.
IDLE_EXIT_SECONDS = 180

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
    """A PATH that can find latex and ffmpeg, whatever Finder handed us.

    An engine started from ManimLive.app has launchd's PATH, which names
    none of the places a TeX distribution or Homebrew installs to — so a
    scene using Tex would fail with a message saying to install something
    that is already there, while the same scene run from a terminal works.
    The standard locations are appended, and only if they exist. Nothing
    is removed and nothing is reordered: an entry already present keeps its
    priority.
    """
    parts = [p for p in (base or os.environ.get("PATH", "")).split(os.pathsep) if p]
    for directory in TOOL_DIRS:
        if directory not in parts and os.path.isdir(directory):
            parts.append(directory)
    return os.pathsep.join(parts)


def parent_alive(pid: int) -> bool:
    """Whether process `pid` still exists.

    `os.kill(pid, 0)` is the POSIX liveness test; on Windows it is not one
    (it opens the process to terminate it, and a pid that has been reused
    answers for its predecessor), so there the process handle is asked.
    """
    if os.name == "nt":
        import ctypes

        SYNCHRONIZE = 0x00100000
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if not handle:
            return False
        try:
            # WAIT_TIMEOUT (258): still running. WAIT_OBJECT_0: it has ended.
            return kernel32.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def watch_parent(pid: int, server: AppServer, interval: float = 2.0) -> threading.Thread:
    """Stop `server` once process `pid` is gone.

    The shell that started the engine as its child normally stops it at
    quit; this covers the shell being killed, which runs no quit handler
    and would otherwise leave an engine on the port with no window.
    """

    def watch():
        while parent_alive(pid):
            time.sleep(interval)
        print(f"maniml app: parent process {pid} is gone, stopping", flush=True)
        server.stop_serving()

    thread = threading.Thread(target=watch, name="maniml-parent-watch", daemon=True)
    thread.start()
    return thread


def run_app(
    root: str = ".",
    open_browser: bool = True,
    allow_outside_root: bool = False,
    port: int | None = None,
    idle_exit: float | None = None,
    scene_grace: float | None = None,
    parent: int | None = None,
) -> None:
    # Started from Finder (ManimLive.app), the engine has a bare PATH, and a
    # scene that needs latex, dvisvgm or ffmpeg would fail where the same
    # scene in a terminal works. Add the usual places; this changes nothing
    # for a terminal that already has them.
    os.environ["PATH"] = search_path()
    server = AppServer(
        root,
        port=port,
        allow_outside_root=allow_outside_root,
        idle_exit=idle_exit,
        **({} if scene_grace is None else {"scene_grace": scene_grace}),
    )
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def exit_on_sigterm(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, exit_on_sigterm)
    asked = DEFAULT_APP_PORT if port is None else port
    if asked and server.port != asked:
        # The port is a rendezvous, not a requirement: a second engine from
        # a terminal lands on an OS-assigned one. Say which, so the address
        # printed below is not a surprise.
        print(f"note: port {asked} was taken, so this session is on {server.port}.")
    print(f"maniml app: {server.url}  (scenes under {server.root})", flush=True)
    if idle_exit is not None:
        print(f"maniml app: stops {idle_exit / 60:g} minutes after its last window closes", flush=True)
    if open_browser:
        webbrowser.open(server.url)
    if parent is not None:
        watch_parent(parent, server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.shutdown()
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
