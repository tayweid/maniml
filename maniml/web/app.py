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

import atexit
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from maniml.utils.processes import (
    process_group_popen_kwargs,
    terminate_process_tree,
)
from maniml import environment
from maniml.desktop import choose_python_file
from maniml.web.assets import (
    is_websocket_upgrade,
    static_response,
)
from maniml.web.library import find_scene_classes, load_recents, remember_recent
from maniml.web.security import (
    MAX_CONTROL_MESSAGE,
    parse_json_object,
    resolve_authorized_file,
)
from maniml.web.server import bind_loopback

VIEWER_LAUNCH_PATTERN = re.compile(
    r"^maniml web viewer: (?P<url>http://localhost:\d+/)\s*$"
)
# One port for the page and its control socket, for a terminal's `maniml
# app`. It is a rendezvous, not a requirement: a second engine started
# alongside falls back to an OS-assigned one. ManimLive.app's engine is
# given the shell's own port (8690, app/maniml.json) and never competes.
DEFAULT_APP_PORT = 8685


# How many packages one open adds from uv's cache before it stops and
# asks: a scene whose imports keep failing is not one more add away.
MAX_QUIET_ADDS = 5


def parse_viewer_launch_line(line: str) -> str | None:
    """Read only the viewer's dedicated, machine-readable launch line.

    Rich may line-wrap the human-readable log entry containing the same URL,
    so treating any URL-shaped substring as the handshake can capture a
    truncated address. The plain ``print`` emitted by WebViewer is
    deliberately stable and is the only accepted child-process handshake.
    """
    match = VIEWER_LAUNCH_PATTERN.fullmatch(line)
    return match.group("url") if match else None


class SceneProcess:
    """One running `maniml <file> <Scene> --web` subprocess."""

    def __init__(
        self,
        path: str,
        scene: str | None,
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
        idle_exit: float | None = None,
    ):
        self.root = str(Path(root).resolve())
        self._root_path = Path(self.root)
        if not self._root_path.is_dir():
            raise ValueError(f"app root is not a directory: {self.root}")
        self.allow_outside_root = allow_outside_root
        # A file you picked through the OS dialog stays openable in later
        # sessions: recents are the landing page's only discovery surface, and
        # an entry you cannot click is worse than no entry. See SECURITY.md —
        # this widens root confinement to files you named yourself, and
        # deleting the recents file revokes it.
        self._granted_files: set[str] = {
            path for path in load_recents() if path.endswith(".py")
        }
        self.processes: dict[tuple, SceneProcess] = {}
        self._scenes_by_id: dict[str, SceneProcess] = {}
        self._next_scene_id = 0
        self._lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._loop = None
        self._closing = None
        # ManimLive.app starts the engine when it opens and nothing stops it
        # but this: with idle_exit set, the server stops (and takes its scene
        # processes down) once no window has held a socket to it for that
        # many seconds, as Edit <course>.app's editor does. Every open page
        # holds one: the landing page its control socket, a viewer its relay.
        self.idle_exit = idle_exit
        self._connections = 0
        self._idle_since = time.monotonic()
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
        self.allowed_origins = {self.origin, f"http://127.0.0.1:{self.port}"}
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
                    path, scene, identifier=str(self._next_scene_id),
                )
                self.processes[key] = process
                self._scenes_by_id[process.id] = process
        url = process.wait_for_url()
        if url:
            remember_recent(path)
        return url

    def restart_scene(self, scene_id: str) -> SceneProcess | None:
        """Replace the process behind an id with a fresh one, under the same id.

        The viewer's Restart. A scene process is an interpreter holding the
        scene file and everything it imported, a Scene class built from
        them, and a camera and random state every checkpoint since descends
        from; nothing inside it can give all of that back (the in-process
        `_restart_from_source` re-execs the one file and keeps the rest), so
        a true restart is a new process. The id stays, so the page's
        reconnect loop finds the new process at the same /scene/<id>; its
        ready message carries a new boot id, and the page reloads itself on
        that (viewer.html), which resets the page as thoroughly as the
        engine.

        The replacement is built and waited for before it takes the id and
        the old process is stopped. A Restart while the file does not load
        (a syntax error mid-edit) is a replacement that dies at import;
        stopping the old process first left the id naming nothing — every
        reconnect refused, the error nowhere (a failed process's output is
        read only when an open fails), the scene gone until the landing
        page assigned a new id. So a replacement that does not serve is
        stopped and None returned with both maps untouched, and the relay
        forwards the restart to the process it has, which restarts from the
        code that last loaded as a terminal restart does.
        """
        with self._lock:
            if self._shutdown_complete:
                return None
            previous = self._scenes_by_id.get(scene_id)
            if previous is None:
                return None
        # Outside the lock: the wait is the new process's whole start-up.
        process = SceneProcess(previous.path, previous.scene, identifier=scene_id)
        if process.wait_for_url() is None:
            process.stop()
            return None
        with self._lock:
            if self._shutdown_complete:
                process.stop()
                return None
            # Whatever holds the id by now: the process this restart
            # replaces, or a concurrent restart's replacement, which this
            # one displaces rather than orphans.
            displaced = self._scenes_by_id.get(scene_id, previous)
            self.processes[(previous.path, previous.scene or "")] = process
            self._scenes_by_id[scene_id] = process
        # Outside the lock: stopping waits for the old process to go.
        displaced.stop()
        return process

    def recents_payload(self) -> dict:
        """Files the user has opened before, newest first.

        This is the whole of the landing page. It deliberately does not scan
        the launch directory: the app is not a file browser, and a listing of
        every scene class under a course tree was noise in front of the one
        file you actually wanted.
        """
        recents = []
        for path in load_recents():
            try:
                recent = Path(path).resolve(strict=True)
            except OSError:
                continue
            if (
                not recent.is_file()
                or recent.suffix.lower() != ".py"
                or (
                    not self.allow_outside_root
                    and str(recent) not in self._granted_files
                    and not recent.is_relative_to(self._root_path)
                )
            ):
                continue
            parent = recent.parent
            try:
                shown = "~/" + str(parent.relative_to(Path.home()))
            except ValueError:
                shown = str(parent)
            recents.append({"path": str(recent), "name": recent.name, "dir": shown})
        return {"root": self.root, "recents": recents}

    _SCENE_ASSET = re.compile(r"^/scene/([^/]+)(/(?:present|baked)(?:/.*)?)$")

    def _relay_scene_asset(self, request):
        """Serve a scene's output folders through the app's own origin.

        The page speaks only to where it came from — one port is the app's
        whole origin, the one the shell's window stays on — so
        /scene/<id>/present/* and /scene/<id>/baked/* are fetched here and
        answered from the scene
        process backing that id, the same way its socket is relayed. Only
        those two mounts, only GET, Range passed through for <video>
        seeking.
        """
        from urllib.error import HTTPError, URLError
        from urllib.request import Request as HttpRequest, urlopen

        from websockets.datastructures import Headers
        from websockets.http11 import Response

        if request.method != "GET":
            return None
        match = self._SCENE_ASSET.match(urlsplit(request.path).path)
        if match is None:
            return None
        scene_id, subpath = match.groups()
        process = self._scenes_by_id.get(scene_id)
        port = urlsplit(process.url).port if process and process.url else None
        if port is None or not process.alive():
            return Response(404, "Not Found", Headers(
                [("Content-Length", "0"), ("Connection", "close")]), b"")

        upstream = HttpRequest(f"http://127.0.0.1:{port}{subpath}")
        range_header = request.headers.get("Range")
        if range_header:
            upstream.add_header("Range", range_header)
        try:
            with urlopen(upstream, timeout=30) as answer:
                body = answer.read()
                status = answer.status
                phrase = answer.reason or "OK"
                passed = Headers([("Connection", "close"),
                                  ("Content-Length", str(len(body)))])
                for name in ("Content-Type", "Content-Range",
                             "Accept-Ranges", "Cache-Control"):
                    value = answer.headers.get(name)
                    if value:
                        passed[name] = value
                return Response(status, phrase, passed, body)
        except HTTPError as error:
            return Response(error.code, error.reason or "Error", Headers(
                [("Content-Length", "0"), ("Connection", "close")]), b"")
        except (URLError, OSError):
            return Response(502, "Bad Gateway", Headers(
                [("Content-Length", "0"), ("Connection", "close")]), b"")

    def _authorize(self, raw_path) -> Path:
        """The file a page may name: under the root, or granted (a native
        dialog's pick, a path the shell handed over). ValueError says why not."""
        try:
            resolved_path = (
                str(Path(raw_path).expanduser().resolve(strict=True))
                if isinstance(raw_path, str)
                else ""
            )
        except OSError:
            resolved_path = ""
        return resolve_authorized_file(
            self._root_path,
            raw_path,
            suffix=".py",
            allow_outside_root=(
                self.allow_outside_root or resolved_path in self._granted_files
            ),
        )

    def open_payload(self, request: dict, progress=None) -> dict:
        try:
            candidate = self._authorize(request.get("path"))
        except ValueError as exc:
            return {"error": str(exc)}
        path = str(candidate)
        scenes = find_scene_classes(path)
        scene = request.get("scene") or None
        if scene is None:
            if not scenes:
                return {"error": "no Manim scene classes were discovered in this file"}
            # A file with several scenes opens at its first one; the viewer's
            # own picker switches between them without another process, so
            # refusing to open at all only ever meant an extra click.
            # find_scene_classes walks breadth-first, so top-level classes come
            # out in file order and this really is the first scene in the file.
            scene = scenes[0]
        if (
            not isinstance(scene, str)
            or not scene.isidentifier()
            or scene not in scenes
        ):
            return {"error": "scene was not discovered in this file"}
        return self._start(path, scene, progress)

    def install_payload(self, request: dict, progress=None) -> dict:
        """The page's answer to a download offer (`_start`): add the package
        to the file's header and environment, downloading now, and start
        the scene again."""
        try:
            candidate = self._authorize(request.get("path"))
        except ValueError as exc:
            return {"error": str(exc)}
        path = str(candidate)
        scene = request.get("scene")
        if not isinstance(scene, str) or scene not in find_scene_classes(path):
            return {"error": "scene was not discovered in this file"}
        distribution = request.get("distribution")
        if not environment.is_package_name(distribution):
            return {"error": "bad package name"}
        if environment.find_uv() is None:
            return {"error": "uv is not installed"}
        if progress:
            progress(f"Downloading {distribution}")
        ok, reason, _download = environment.add_dependency(
            path, distribution, offline=False, on_progress=progress)
        if not ok:
            return {"error": f"could not add {distribution}", "hint": reason}
        print(f"maniml app: added {distribution} to {os.path.basename(path)}", flush=True)
        return self._start(path, scene, progress, added={distribution})

    def _start(self, path: str, scene: str, progress=None, added=None) -> dict:
        """Start the scene and answer the page. A scene that dies on a
        missing import gets the package added to its header and environment
        and is started again (environment.py): at once when uv already has
        the package on this Mac, after the page's click when it would have
        to download, which the answer offers as `install`."""
        added = set(added or ())
        while True:
            # The file's environment first, its steps shown: a header's
            # first build can take minutes, and a scene's start-up wait
            # (SceneProcess.wait_for_url) is 25 seconds. The scene process
            # does the same on load, which is then a moment's audit.
            if environment.has_header(path):
                environment.ensure_environment(path, on_progress=progress)
            url = self.open_scene(path, scene)
            if url is not None:
                break
            process = self.processes.get((path, scene or ""))
            tail = "".join(process.lines) if process else ""
            failure = {"error": "scene failed to start", "log": tail[-4000:]}
            module = environment.missing_module(tail)
            if module is None:
                return failure
            distribution = environment.distribution_for(module)
            if environment.find_uv() is None:
                failure["hint"] = (
                    f"Scenes run on {sys.executable} — '{module}' is not "
                    f"installed there. Install uv (https://docs.astral.sh/uv/) "
                    f"and open the scene again, or install it beside maniml "
                    f"with: {sys.executable} -m pip install {distribution}")
                return failure
            if distribution in added or len(added) >= MAX_QUIET_ADDS:
                # Added and still not importable: the package is named
                # differently, or the import is wrong. Say so, do not loop.
                hint = environment.import_name_hint(module)
                failure["hint"] = (
                    f"'{module}' still cannot be imported after adding {distribution}"
                    + (f": {hint}" if hint else ""))
                return failure
            if progress:
                progress(f"Adding {distribution}")
            ok, reason, download = environment.add_dependency(
                path, distribution, offline=True, on_progress=progress)
            if ok:
                added.add(distribution)
                print(f"maniml app: added {distribution} to {os.path.basename(path)}", flush=True)
                continue
            if download:
                failure["hint"] = (
                    f"'{module}' is not installed: {distribution} would have "
                    "to be downloaded.")
                failure["install"] = {
                    "path": path, "scene": scene,
                    "module": module, "distribution": distribution,
                }
                return failure
            failure["hint"] = reason
            return failure
        # The page stays on this origin: it opens the viewer here and the app
        # relays its socket to the scene process. One port is the app's whole
        # address (the page, and every window the shell opens, is on the port
        # the engine was started on); a scene process's port is one only the
        # engine knows, so a scene opens *here* rather than moving the browser.
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
        # Picking a file is exactly the event the Recent list should record.
        remember_recent(path)
        return {"file": {"path": path, "name": candidate.name}}

    def _start_server(self):
        """Serve the page and its control socket on the one bound port.

        Plain GETs are answered from `web/static/`; WebSocket handshakes fall
        through to the Origin check and then the control protocol. The page
        therefore reaches its engine at `window.location` and has no port or
        address to be told.
        """
        import asyncio

        import websockets.asyncio.server as ws_server
        from websockets.exceptions import ConnectionClosed

        def process_request(connection, request):
            if is_websocket_upgrade(request):
                return None
            relayed = self._relay_scene_asset(request)
            if relayed is not None:
                return relayed
            return static_response(request, index="app.html")

        async def relay(ws, scene_id):
            """Pump one viewer's socket to the scene process that backs it.

            The scene process is a full server in its own right — `maniml
            file.py Scene --web` on its own is unchanged — but a scene opened
            through the app must not move the browser to another port, because
            one port is the app's whole origin and the page speaks only to
            where it came from. So the app connects to it as a client and
            copies frames both ways.
            """
            process = self._scenes_by_id.get(scene_id)
            if process is not None and process.url is None and process.alive():
                # Still starting under this id: hold the page's socket
                # until the scene serves, so the page lands on the scene
                # rather than on the "can't reach the engine" overlay.
                await asyncio.to_thread(process.wait_for_url)
            target = process.ws_url if process is not None else None
            if target is None or not process.alive():
                await ws.close(code=1011, reason="no such scene")
                return
            import websockets.asyncio.client as ws_client

            async def pump_page(source, sink):
                """The page's messages to the scene — all but one. Restart
                is the app's to act on: the scene process cannot restart
                itself as thoroughly as the app can replace it (above),
                so the message is taken here, the process is replaced,
                and this socket closes for the page to reconnect. When
                the replacement does not serve (the file does not load:
                a syntax error mid-edit) the app keeps the process it
                has and the message goes through to it after all: the
                scene restarts from the code that last loaded, as a
                terminal restart does, the traceback on its console,
                and the state it announces clears the page's busy
                button."""
                async for message in source:
                    if isinstance(message, str) and "restart" in message:
                        event = parse_json_object(message)
                        if event is not None and event.get("type") == "restart":
                            replaced = await asyncio.to_thread(
                                self.restart_scene, scene_id)
                            if replaced is not None:
                                return
                    await sink.send(message)

            try:
                async with ws_client.connect(
                    target,
                    # The scene checks Origin like every server here; the app
                    # is not a browser, so it states the scene's own origin.
                    origin=urlsplit(process.url).scheme
                    + f"://localhost:{urlsplit(process.url).port}",
                    max_size=None,
                    # No buffer of its own. With a queue here the relay
                    # accepts frames from the scene far faster than it can
                    # hand them to the browser, so the scene sees a fast
                    # client, never applies its own send policy, and the
                    # backlog comes out the far side in clumps: frames
                    # arriving 5ms apart separated by 100ms stalls, which
                    # is judder even though not one frame was lost. At 1
                    # the relay is transparent and the scene's flow control
                    # measures the browser, which is what it is for.
                    max_queue=1,
                    compression=None,
                    open_timeout=10,
                ) as upstream:

                    async def pump(source, sink):
                        async for message in source:
                            await sink.send(message)

                    done, pending = await asyncio.wait(
                        [
                            asyncio.create_task(pump_page(ws, upstream)),
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
            self._connections += 1
            try:
                await serve_connection(ws)
            except ConnectionClosed:
                # The page went away without a close frame: a window the
                # shell closed, a tab the browser killed. Not a failure, and
                # not worth a traceback in the log for every closed window.
                pass
            finally:
                self._connections -= 1
                if self._connections == 0:
                    self._idle_since = time.monotonic()

        async def serve_connection(ws):
            # The Origin check in the handshake already decided this; a
            # connection that gets here is the page we served.
            path = ws.request.path
            if path.startswith("/scene/"):
                await relay(ws, path[len("/scene/"):])
                return
            await ws.send(json.dumps({"type": "ready"}))
            loop = asyncio.get_running_loop()
            async for message in ws:
                request = parse_json_object(message)
                if request is None:
                    continue
                op = request.get("op")

                def progress(step, request_id=request.get("id")):
                    # From the worker thread: a step of uv's work on this
                    # request, which the page shows under the request's
                    # id until the answer comes.
                    asyncio.run_coroutine_threadsafe(ws.send(json.dumps(
                        {"type": "progress", "id": request_id, "step": step})), loop)

                if op == "recents":
                    response = self.recents_payload()
                elif op == "choose":
                    response = await asyncio.to_thread(self.choose_payload)
                elif op == "open":
                    response = await asyncio.to_thread(self.open_payload, request, progress)
                elif op == "install":
                    response = await asyncio.to_thread(self.install_payload, request, progress)
                else:
                    response = {"error": f"unknown op {op}"}
                response["id"] = request.get("id")
                await ws.send(json.dumps(response))

        async def exit_when_idle():
            while not self._closing.is_set():
                await asyncio.sleep(min(5.0, self.idle_exit))
                idle = time.monotonic() - self._idle_since
                if self._connections == 0 and idle >= self.idle_exit:
                    print(f"maniml app: no window for {idle:.0f}s, stopping", flush=True)
                    self._closing.set()

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
                if self.idle_exit is not None:
                    watcher = asyncio.create_task(exit_when_idle())
                await self._closing.wait()  # released by stop_serving()
                if self.idle_exit is not None:
                    watcher.cancel()

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
        """Block until the server stops (Ctrl-C or SIGTERM)."""
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

    def shutdown(self):
        with self._shutdown_lock:
            if self._shutdown_complete:
                return
            self._shutdown_complete = True
            self.stop_serving()
            with self._lock:
                processes = list(self.processes.values())
            for process in processes:
                process.stop()
