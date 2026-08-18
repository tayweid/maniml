"""The maniml app: a persistent local server in the Plass/Knuth mold.

`maniml app` serves a landing page listing the scene files under the
launch directory (plus recently opened files); clicking a scene spawns
that scene as its own subprocess — exactly `maniml file.py Scene --web`
— and navigates to its viewer. Scene files are arbitrary user code, so
subprocess-per-scene keeps a crashing scene from taking the app down
(the same isolation argument as Knuth's kernel).

One port serves everything: plain GETs return the landing page and the
static assets, and the same port accepts the control WebSocket the page
connects back to (ops: `files`, `open`, `choose`). Page and socket therefore
share an origin exactly, so the page derives its socket URL from
`window.location` and has nothing to be told at launch.
"""

from __future__ import annotations

import ast
import atexit
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from maniml.utils.processes import (
    process_group_popen_kwargs,
    terminate_process_tree,
)
from maniml.desktop import choose_python_file
from maniml.web.assets import is_websocket_upgrade, static_response
from maniml.web.security import (
    MAX_CONTROL_MESSAGE,
    parse_json_object,
    resolve_authorized_file,
)
from maniml.web.server import ClientLease, bind_loopback

RECENTS_PATH = os.environ.get(
    "MANIML_RECENTS_PATH", os.path.expanduser("~/.maniml_recents.json")
)
RECENTS_MAX = 12
SKIP_DIRS = {".git", "__pycache__", "media", "node_modules", ".venv", "venv"}
VIEWER_LAUNCH_PATTERN = re.compile(
    r"^maniml web viewer: (?P<url>http://localhost:\d+/)\s*$"
)
# One port for the page and its control socket. It is a rendezvous, not a
# requirement: a background agent holds it for the login session, and a
# foreground `maniml app` started alongside falls back to an OS-assigned one.
DEFAULT_APP_PORT = 8685


def missing_module_hint(log: str) -> str | None:
    """When a scene dies on a missing import, say which Python maniml
    runs on and the exact install command — scene imports resolve in
    maniml's interpreter, which may not be the shell's default."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", log)  # strip ANSI colors
    match = re.search(r"ModuleNotFoundError: No module named '([^']+)'", plain)
    if not match:
        return None
    module = match.group(1).split(".")[0]
    pip = os.path.join(os.path.dirname(sys.executable), "pip")
    if not os.path.exists(pip):
        pip = f"{sys.executable} -m pip"
    return (
        f"Scenes run on {sys.executable} — "
        f"'{module}' is not installed there. "
        f"Install it with:  {pip} install {module}"
    )


def parse_viewer_launch_line(line: str) -> str | None:
    """Read only the viewer's dedicated, machine-readable launch line.

    Rich may line-wrap the human-readable log entry containing the same URL,
    so treating any URL-shaped substring as the handshake can capture a
    truncated address. The plain ``print`` emitted by WebViewer is
    deliberately stable and is the only accepted child-process handshake.
    """
    match = VIEWER_LAUNCH_PATTERN.fullmatch(line)
    return match.group("url") if match else None


def find_scene_classes(path: str) -> list[str]:
    """Scene classes in a file via AST — no import, no side effects.
    Heuristic: a class whose base names end with 'Scene'."""
    try:
        with open(path) as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return []
    scenes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = getattr(base, "id", getattr(base, "attr", ""))
            if isinstance(name, str) and name.endswith("Scene"):
                scenes.append(node.name)
                break
    return scenes


def find_scene_files(root: str, max_depth: int = 2) -> list[dict]:
    results = []
    root = os.path.abspath(root)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = os.path.relpath(dirpath, root).count(os.sep)
        dirnames[:] = [
            d
            for d in dirnames
            if d not in SKIP_DIRS and not d.startswith(".") and depth < max_depth
        ]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            scenes = find_scene_classes(path)
            if scenes:
                results.append(
                    {
                        "path": path,
                        "rel": os.path.relpath(path, root),
                        "scenes": scenes,
                    }
                )
    return results


def load_recents() -> list[str]:
    try:
        with open(RECENTS_PATH) as f:
            recents = json.load(f)
        return [p for p in recents if isinstance(p, str)]
    except (OSError, ValueError):
        return []


def remember_recent(path: str) -> None:
    recents = [p for p in load_recents() if p != path]
    recents.insert(0, path)
    try:
        with open(RECENTS_PATH, "w") as f:
            json.dump(recents[:RECENTS_MAX], f)
    except OSError:
        pass


class SceneProcess:
    """One running `maniml <file> <Scene> --web` subprocess."""

    def __init__(
        self,
        path: str,
        scene: str | None,
        transient: bool = False,
        identifier: str = "",
    ):
        self.path = path
        self.scene = scene
        # How the browser names this scene when it asks the app to relay to
        # it. The scene's own port never reaches the page.
        self.id = identifier
        command = [sys.executable, "-m", "maniml", path]
        if scene:
            command.append(scene)
        command += ["--web", "--no-browser"]
        # The scene serves its own page on its own port, so it needs to know
        # nothing about the app that spawned it.
        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if transient:
            child_env["MANIML_TRANSIENT_VIEWER"] = "1"
        self.proc = subprocess.Popen(
            command,
            cwd=os.path.dirname(path) or None,
            env=child_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **process_group_popen_kwargs(),
        )
        self.lines: deque[str] = deque(maxlen=200)
        self.url: str | None = None
        self._stop_lock = threading.Lock()
        self._stopped = False
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line)
            if self.url is None:
                self.url = parse_viewer_launch_line(line)

    @property
    def ws_url(self) -> str | None:
        """The scene's own socket, which only the app ever connects to."""
        if not self.url:
            return None
        port = urlsplit(self.url).port
        return f"ws://127.0.0.1:{port}/" if port else None

    def wait_for_url(self, timeout: float = 25.0) -> str | None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.url:
                return self.url
            if self.proc.poll() is not None:
                # Let the reader drain the pipe so error responses can
                # include the full traceback
                self._reader.join(timeout=2)
                return None
            time.sleep(0.05)
        return None

    def alive(self) -> bool:
        return self.proc.poll() is None

    def stop(self):
        with self._stop_lock:
            if self._stopped:
                return
            try:
                terminate_process_tree(self.proc)
            finally:
                self._reader.join(timeout=2)
                if self.proc.stdout is not None:
                    try:
                        self.proc.stdout.close()
                    except OSError:
                        pass
                self._stopped = True


class AppServer:
    def __init__(
        self,
        root: str,
        port: int | None = None,
        allow_outside_root: bool = False,
        transient: bool = False,
    ):
        self.root = str(Path(root).resolve())
        self._root_path = Path(self.root)
        if not self._root_path.is_dir():
            raise ValueError(f"app root is not a directory: {self.root}")
        self.allow_outside_root = allow_outside_root
        self.transient = transient
        self.processes: dict[tuple, SceneProcess] = {}
        self._scenes_by_id: dict[str, SceneProcess] = {}
        self._next_scene_id = 0
        self._granted_files: set[str] = set()
        self._lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._shutdown_event = threading.Event()
        self._serving = threading.Event()
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._loop = None
        self._closing = None
        self._session_lease = ClientLease()
        atexit.register(self.shutdown)

        # Bind before starting the server: the origin allowlist needs the
        # resolved port, and the caller needs a usable URL the moment the
        # constructor returns.
        self._socket = bind_loopback(DEFAULT_APP_PORT if port is None else port)
        self.port = self._socket.getsockname()[1]
        self.origin = f"http://localhost:{self.port}"
        self.url = f"{self.origin}/"
        # The whole boundary: the control socket is accepted only from the
        # origin this server serves its own page on.
        self.allowed_origins = {self.origin}
        self._start_server()

    def open_scene(self, path: str, scene: str | None) -> str | None:
        key = (path, scene or "")
        with self._lock:
            if self._shutdown_complete:
                return None
            process = self.processes.get(key)
            if process is not None and not process.alive():
                process.stop()
                # Its id names a process that no longer exists; drop it rather
                # than leave the relay a dead name to refuse.
                self._scenes_by_id.pop(process.id, None)
                process = None
            if process is None:
                self._next_scene_id += 1
                process = SceneProcess(
                    path, scene, transient=self.transient,
                    identifier=str(self._next_scene_id),
                )
                self.processes[key] = process
                self._scenes_by_id[process.id] = process
        url = process.wait_for_url()
        if url:
            remember_recent(path)
        return url

    def files_payload(self) -> dict:
        files = find_scene_files(self.root)
        listed = {f["path"] for f in files}
        recents = []
        for path in load_recents():
            try:
                recent = Path(path).resolve(strict=True)
            except OSError:
                continue
            if (
                path in listed
                or not recent.is_file()
                or recent.suffix.lower() != ".py"
                or (
                    not self.allow_outside_root
                    and str(recent) not in self._granted_files
                    and not recent.is_relative_to(self._root_path)
                )
            ):
                continue
            recent_str = str(recent)
            recents.append(
                {
                    "path": recent_str,
                    "rel": recent_str,
                    "scenes": find_scene_classes(recent_str),
                }
            )
        return {"root": self.root, "files": files, "recents": recents}

    def open_payload(self, request: dict) -> dict:
        raw_path = request.get("path")
        try:
            resolved_path = (
                str(Path(raw_path).expanduser().resolve(strict=True))
                if isinstance(raw_path, str)
                else ""
            )
        except OSError:
            resolved_path = ""
        try:
            candidate = resolve_authorized_file(
                self._root_path,
                raw_path,
                suffix=".py",
                allow_outside_root=(
                    self.allow_outside_root or resolved_path in self._granted_files
                ),
            )
        except ValueError as exc:
            return {"error": str(exc)}
        path = str(candidate)
        scenes = find_scene_classes(path)
        scene = request.get("scene") or None
        if scene is None:
            if len(scenes) != 1:
                return {"error": "specify exactly one discovered scene"}
            scene = scenes[0]
        if (
            not isinstance(scene, str)
            or not scene.isidentifier()
            or scene not in scenes
        ):
            return {"error": "scene was not discovered in this file"}
        url = self.open_scene(path, scene)
        if url is None:
            process = self.processes.get((path, scene or ""))
            tail = "".join(process.lines) if process else ""
            return {
                "error": "scene failed to start",
                "log": tail[-4000:],
                "hint": missing_module_hint(tail),
            }
        # The page stays on this origin: it opens the viewer here and the app
        # relays its socket to the scene process. One origin means one
        # installable app, and a scene opens *inside* it rather than popping
        # the browser out to another port.
        process = self.processes.get((path, scene or ""))
        if process is None or not process.id:
            return {"error": "scene process disappeared while starting"}
        return {
            "url": url,
            "scene_id": process.id,
            "viewer_url": f"viewer.html?{urlencode({'scene': process.id})}",
        }

    def grant_file(self, raw_path: str) -> str | None:
        """Authorize one file the user named outside the browser.

        A path handed over by Finder or a native dialog is an explicit user
        action, so it can be opened later without widening the root boundary
        for anything else. Listing it as a recent makes it reachable on the
        landing page when the direct open could not proceed.
        """
        try:
            candidate = resolve_authorized_file(
                self._root_path, raw_path, suffix=".py", allow_outside_root=True
            )
        except ValueError:
            return None
        path = str(candidate)
        self._granted_files.add(path)
        remember_recent(path)
        return path

    def choose_payload(self) -> dict:
        """Choose one file through an OS dialog and grant only that file.

        The dialog is initiated by an authenticated app request.  Selecting a
        file is an explicit native user action, so it can safely grant that
        canonical file without weakening the configured-root boundary for any
        other path.
        """
        try:
            selected = choose_python_file(self.root)
        except RuntimeError as exc:
            return {"error": str(exc)}
        if selected is None:
            return {"cancelled": True}
        try:
            candidate = resolve_authorized_file(
                self._root_path,
                selected,
                suffix=".py",
                allow_outside_root=True,
            )
        except ValueError as exc:
            return {"error": str(exc)}
        path = str(candidate)
        scenes = find_scene_classes(path)
        if not scenes:
            return {"error": "no Manim scene classes were discovered in this file"}
        self._granted_files.add(path)
        return {"file": {"path": path, "rel": candidate.name, "scenes": scenes}}

    def _start_server(self):
        """Serve the page and its control socket on the one bound port.

        Plain GETs are answered from `web/static/`; WebSocket handshakes fall
        through to the Origin check and then the control protocol. The page
        therefore reaches its engine at `window.location` and has no port or
        address to be told.
        """
        import asyncio

        import websockets.asyncio.server as ws_server

        def process_request(connection, request):
            if is_websocket_upgrade(request):
                return None
            return static_response(request, index="app.html")

        async def relay(ws, scene_id):
            """Pump one viewer's socket to the scene process that backs it.

            The scene process is a full server in its own right — `maniml
            file.py Scene --web` on its own is unchanged — but a scene opened
            through the app must not move the browser to another port, because
            the port is the installed app's identity. So the app connects to
            it as a client and copies frames both ways.
            """
            process = self._scenes_by_id.get(scene_id)
            target = process.ws_url if process is not None else None
            if target is None or not process.alive():
                await ws.close(code=1011, reason="no such scene")
                return
            import websockets.asyncio.client as ws_client

            try:
                async with ws_client.connect(
                    target,
                    # The scene checks Origin like every server here; the app
                    # is not a browser, so it states the scene's own origin.
                    origin=urlsplit(process.url).scheme
                    + f"://localhost:{urlsplit(process.url).port}",
                    max_size=None,
                    max_queue=32,
                    compression=None,
                    open_timeout=10,
                ) as upstream:

                    async def pump(source, sink):
                        async for message in source:
                            await sink.send(message)

                    done, pending = await asyncio.wait(
                        [
                            asyncio.create_task(pump(ws, upstream)),
                            asyncio.create_task(pump(upstream, ws)),
                        ],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for task in pending:
                        task.cancel()
            except Exception:
                pass  # the scene died or the tab went away; both just close
            finally:
                await ws.close()

        async def handler(ws):
            # The Origin check in the handshake already decided this; a
            # connection that gets here is the page we served.
            path = ws.request.path
            if path.startswith("/scene/"):
                await relay(ws, path[len("/scene/"):])
                return
            self._session_lease.connected()
            try:
                await ws.send(json.dumps({"type": "ready"}))
                async for message in ws:
                    request = parse_json_object(message)
                    if request is None:
                        continue
                    op = request.get("op")
                    if op == "files":
                        response = self.files_payload()
                    elif op == "choose":
                        response = await asyncio.to_thread(self.choose_payload)
                    elif op == "open":
                        response = await asyncio.to_thread(self.open_payload, request)
                    else:
                        response = {"error": f"unknown op {op}"}
                    response["id"] = request.get("id")
                    await ws.send(json.dumps(response))
            finally:
                self._session_lease.disconnected()

        async def main():
            self._loop = asyncio.get_running_loop()
            self._closing = asyncio.Event()
            async with ws_server.serve(
                handler,
                sock=self._socket,
                process_request=process_request,
                origins=sorted(self.allowed_origins),
                max_size=MAX_CONTROL_MESSAGE,
                max_queue=16,
                compression=None,
            ):
                self._ready.set()
                await self._closing.wait()  # released by stop_serving()

        def run():
            try:
                asyncio.run(main())
            except Exception as exc:  # noqa: BLE001 - report, don't take the app down
                print(f"warning: the app server stopped: {exc}")
            finally:
                self._ready.set()
                self._stopped.set()

        threading.Thread(target=run, name="maniml-app", daemon=True).start()
        if not self._ready.wait(timeout=5):
            raise RuntimeError("app server failed to start")

    def serve_forever(self):
        """Block until the server stops (Ctrl-C, SIGTERM, or the idle monitor)."""
        self._serving.set()
        self._stopped.wait()

    def stop_serving(self):
        """Stop accepting connections and release serve_forever()."""
        closing = getattr(self, "_closing", None)
        if self._loop is not None and closing is not None:
            try:
                self._loop.call_soon_threadsafe(closing.set)
            except RuntimeError:
                pass  # the loop is already gone
        self._stopped.set()

    def start_exit_when_idle(
        self,
        exit_when_children_finish: bool,
        poll_interval: float = 0.2,
    ) -> threading.Thread:
        """Stop a transient desktop-open server after its session ends."""

        def monitor():
            if not self._serving.wait(timeout=5):
                return
            while not self._shutdown_event.wait(poll_interval):
                with self._lock:
                    processes = list(self.processes.values())
                if (
                    exit_when_children_finish
                    and processes
                    and all(not process.alive() for process in processes)
                ) or (not processes and self._session_lease.expired()):
                    self.stop_serving()
                    return

        thread = threading.Thread(
            target=monitor, name="maniml-app-session", daemon=True
        )
        thread.start()
        return thread

    def shutdown(self):
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True
            self._shutdown_event.set()
            self.stop_serving()
            with self._lock:
                processes = list(self.processes.values())
            for process in processes:
                process.stop()


def run_app(
    root: str = ".",
    open_browser: bool = True,
    allow_outside_root: bool = False,
    initial_file: str | None = None,
    port: int | None = None,
    state_path: str | os.PathLike[str] | None = None,
) -> None:
    server = AppServer(
        root,
        port=port,
        allow_outside_root=allow_outside_root,
        transient=initial_file is not None,
    )
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def exit_on_sigterm(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, exit_on_sigterm)
    launch_url = server.url
    if initial_file is not None:
        opened = server.open_payload({"path": initial_file})
        if opened.get("viewer_url"):
            launch_url = opened["viewer_url"]
        elif opened.get("error"):
            # A desktop open has no UI of its own: without this the launcher
            # log is silent and the landing page gives no hint why the file
            # the user just picked did not open.
            print(f"maniml open: {initial_file}: {opened['error']}")
            # Fall back to the landing page, and make sure the file is
            # listed and openable there even though the direct open failed
            # (a multi-scene file is the common case — pick a scene).
            server.grant_file(initial_file)
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
    print(f"maniml app: {launch_url}  (scenes under {server.root})")
    if open_browser:
        webbrowser.open(launch_url)
    if initial_file is not None:
        server.start_exit_when_idle(
            exit_when_children_finish=bool(opened.get("viewer_url"))
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.shutdown()
        if previous_sigterm is not None:
            signal.signal(signal.SIGTERM, previous_sigterm)
