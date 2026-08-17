"""The maniml app: a persistent local server in the Plass/Knuth mold.

`maniml app` serves a landing page listing the scene files under the
launch directory (plus recently opened files); clicking a scene spawns
that scene as its own subprocess — exactly `maniml file.py Scene --web`
— and navigates to its viewer. Scene files are arbitrary user code, so
subprocess-per-scene keeps a crashing scene from taking the app down
(the same isolation argument as Knuth's kernel).

Endpoints:
    GET  /            the landing page (static/app.html)
    GET  /api/files   authenticated scene files under the launch dir + recents,
                      each with its Scene classes (AST scan, no import)
    POST /api/open    authenticated {"path":..., "scene":...} -> viewer URL
                      (reuses a live process for the same file+scene)
"""

from __future__ import annotations

import ast
import atexit
import hashlib
import json
import os
import plistlib
import re
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from maniml.utils.processes import (
    process_group_popen_kwargs,
    terminate_process_tree,
)
from maniml.desktop import choose_python_file
from maniml.web.security import (
    AUTH_TIMEOUT,
    HOSTED_APP_ORIGINS,
    HOSTED_APP_URL,
    MAX_CONTROL_MESSAGE,
    WEB_PROTOCOL_VERSION,
    is_auth_message,
    new_capability_token,
    parse_json_object,
    resolve_authorized_file,
    token_matches,
)
from maniml.web.server import ClientLease

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RECENTS_PATH = os.environ.get(
    "MANIML_RECENTS_PATH", os.path.expanduser("~/.maniml_recents.json")
)
RECENTS_MAX = 12
SKIP_DIRS = {".git", "__pycache__", "media", "node_modules", ".venv", "venv"}
# Bounds for resolving an OS-launched file back to a path on disk.
RESOLVE_MAX_DEPTH = 6
RESOLVE_MAX_FILES = 50000
VIEWER_LAUNCH_PATTERN = re.compile(
    r"^maniml web viewer: " r"(?P<url>http://localhost:\d+/#token=[A-Za-z0-9_-]+)\s*$"
)
DEFAULT_APP_PORT = 8685
# Fixed control-channel port, Knuth-style.  The hosted frontend connects to
# loopback after the CLI pairs it with a process-local capability.  Both that
# token and an exact Origin allowlist are required before any operation.
CONTROL_WS_PORT = 8686


def _macos_maniml_pwa_candidates() -> tuple[Path, ...]:
    """Return the conventional Chrome PWA locations on macOS."""
    home = Path.home()
    return (
        home / "Applications/Chrome Apps.localized/ManimLive.app",
        home / "Applications/Chrome Apps/ManimLive.app",
        Path("/Applications/Chrome Apps.localized/ManimLive.app"),
        Path("/Applications/Chrome Apps/ManimLive.app"),
    )


def _is_maniml_chrome_pwa(application: Path) -> bool:
    """Return whether this is Chrome's shim for the hosted ManimLive PWA."""
    return _maniml_chrome_pwa_metadata(application) is not None


def _maniml_chrome_pwa_metadata(
    application: Path,
) -> tuple[str, str | None] | None:
    """Read the validated Chrome app ID and optional profile directory.

    Hosted viewer URLs contain a short-lived capability token.  Do not hand
    one to an arbitrary same-named bundle in a user-writable directory.
    """
    try:
        with (application / "Contents/Info.plist").open("rb") as file:
            info = plistlib.load(file)
    except (OSError, plistlib.InvalidFileException):
        return None

    shortcut_url = info.get("CrAppModeShortcutURL")
    if not isinstance(shortcut_url, str):
        return None
    shortcut = urlsplit(shortcut_url)
    hosted = urlsplit(HOSTED_APP_URL)
    app_id = info.get("CrAppModeShortcutID")
    if not (
        isinstance(app_id, str)
        and re.fullmatch(r"[a-p]{32}", app_id)
        and info.get("CFBundleIdentifier") == f"com.google.Chrome.app.{app_id}"
        and application.is_dir()
        and info.get("CFBundleExecutable") == "app_mode_loader"
        and info.get("CrBundleIdentifier") == "com.google.Chrome"
        and info.get("CrAppModeShortcutName") == "ManimLive"
        and (shortcut.scheme, shortcut.netloc) == (hosted.scheme, hosted.netloc)
    ):
        return None

    profile = info.get("CrAppModeProfileDir")
    if profile is not None and not (
        isinstance(profile, str)
        and profile not in {"", ".", ".."}
        and Path(profile).name == profile
    ):
        return None
    return app_id, profile


def _macos_chrome_executable(application: Path) -> Path | None:
    executable = application / "Contents/MacOS/Google Chrome"
    return executable if executable.is_file() else None


def _macos_pwa_launch_command(
    application: Path, chrome: Path, url: str
) -> list[str] | None:
    """Build Chrome's supported deep-link command for an installed PWA.

    Launch Services opens a Chrome PWA shim at its manifest ``start_url`` and
    discards a URL passed to ``open -a``.  Chrome's app launch switches retain
    the requested in-scope viewer URL, including its capability fragment.
    """
    metadata = _maniml_chrome_pwa_metadata(application)
    executable = _macos_chrome_executable(chrome)
    if metadata is None or executable is None:
        return None
    app_id, profile = metadata
    command = [str(executable)]
    if profile is not None:
        command.append(f"--profile-directory={profile}")
    command.extend(
        [
            f"--app-id={app_id}",
            f"--app-launch-url-for-shortcuts-menu-item={url}",
        ]
    )
    return command


def _macos_chrome_app() -> Path | None:
    """Return the supported system Chrome installation, if present."""
    application = Path("/Applications/Google Chrome.app")
    return application if application.is_dir() else None


def open_hosted_url(url: str) -> bool:
    """Open a hosted session in its installed PWA or supported browser."""
    if sys.platform == "darwin":
        chrome = _macos_chrome_app()
        if chrome is not None:
            commands = []
            for application in _macos_maniml_pwa_candidates():
                command = _macos_pwa_launch_command(application, chrome, url)
                if command is not None:
                    commands.append(command)
            commands.append(["/usr/bin/open", "-a", str(chrome), url])
        else:
            commands = []
        for command in commands:
            try:
                subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                    start_new_session=True,
                )
                return True
            except OSError:
                continue
    return bool(webbrowser.open(url))


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

    Rich may line-wrap the human-readable log entry containing the same URL.
    Treating any URL-shaped substring as the handshake can therefore capture
    a truncated capability token. The plain ``print`` emitted by WebViewer is
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
        app_origin: str,
        transient: bool = False,
    ):
        self.path = path
        self.scene = scene
        command = [sys.executable, "-m", "maniml", path]
        if scene:
            command.append(scene)
        command += ["--web", "--no-browser"]
        child_env = {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "MANIML_APP_ORIGIN": app_origin,
        }
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
        control_port: int = CONTROL_WS_PORT,
        transient: bool = False,
        token: str | None = None,
    ):
        self.root = str(Path(root).resolve())
        self._root_path = Path(self.root)
        if not self._root_path.is_dir():
            raise ValueError(f"app root is not a directory: {self.root}")
        self.allow_outside_root = allow_outside_root
        self.transient = transient
        # A background agent supplies a persisted capability so paired
        # browsers survive restarts; a foreground session stays per-process.
        self.token = token or new_capability_token()
        self.processes: dict[tuple, SceneProcess] = {}
        self._granted_files: set[str] = set()
        self._lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._shutdown_complete = False
        self._shutdown_event = threading.Event()
        self._serving = threading.Event()
        self._session_lease = ClientLease()
        atexit.register(self.shutdown)

        app = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _json(self, obj, status=200):
                body = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorized(self) -> bool:
                prefix = "Bearer "
                header = self.headers.get("Authorization", "")
                if not header.startswith(prefix) or not token_matches(
                    header[len(prefix) :], app.token
                ):
                    self._json({"error": "authorization required"}, 401)
                    return False
                origin = self.headers.get("Origin")
                if origin is not None and origin not in app.allowed_origins:
                    self._json({"error": "origin not allowed"}, 403)
                    return False
                if self.headers.get("Sec-Fetch-Site") == "cross-site":
                    self._json({"error": "cross-site request rejected"}, 403)
                    return False
                return True

            def do_GET(self):
                if self.path == "/api/files":
                    if not self._authorized():
                        return
                    self._json(app.files_payload())
                    return
                # Serve the whole static dir (landing, viewer, renderer
                # assets) so the local flow matches the hosted one
                request_path = urlsplit(self.path).path
                path = (
                    "app.html"
                    if request_path in ("/", "/index.html")
                    else request_path.lstrip("/")
                )
                static_root = Path(STATIC_DIR).resolve()
                full = (static_root / path).resolve()
                if not full.is_relative_to(static_root) or not full.is_file():
                    self._json({"error": "not found"}, 404)
                    return
                import mimetypes

                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                with open(full, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                if self.path != "/api/open":
                    self._json({"error": "not found"}, 404)
                    return
                if not self._authorized():
                    return
                if (
                    self.headers.get("Content-Type", "").split(";", 1)[0].lower()
                    != "application/json"
                ):
                    self._json({"error": "application/json required"}, 415)
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                except ValueError:
                    self._json({"error": "bad request"}, 400)
                    return
                if length <= 0 or length > MAX_CONTROL_MESSAGE:
                    self._json({"error": "request too large"}, 413)
                    return
                request = parse_json_object(self.rfile.read(length))
                if request is None:
                    self._json({"error": "bad request"}, 400)
                    return
                response = app.open_payload(request)
                self._json(response, 200 if "url" in response else 400)

        try:
            self.httpd = ThreadingHTTPServer(
                ("127.0.0.1", port or DEFAULT_APP_PORT), Handler
            )
        except OSError:  # port taken: let the OS pick
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.origin = f"http://localhost:{self.port}"
        self.url = f"{self.origin}/"
        self.launch_url = f"{self.url}#token={self.token}"
        self.allowed_origins = {self.origin, *HOSTED_APP_ORIGINS}
        self.control_port = control_port
        self._start_control_ws(control_port)

    def open_scene(self, path: str, scene: str | None) -> str | None:
        key = (path, scene or "")
        with self._lock:
            if self._shutdown_complete:
                return None
            process = self.processes.get(key)
            if process is not None and not process.alive():
                process.stop()
                process = None
            if process is None:
                process = SceneProcess(
                    path, scene, self.origin, transient=self.transient
                )
                self.processes[key] = process
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
        # ws_port lets a hosted frontend connect its own viewer page
        parsed = urlsplit(url)
        if parsed.port is None:
            return {"error": "scene returned an invalid viewer URL"}
        ws_port = parsed.port + 1
        viewer_token = parsed.fragment.removeprefix("token=")
        viewer_url = f"viewer.html?ws={ws_port}#token={viewer_token}"
        return {"url": url, "ws_port": ws_port, "viewer_url": viewer_url}

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

    def _resolve_candidates(self, name: str):
        """Paths that could be the launched file, nearest first.

        Recents and already-granted files come first: they are the files this
        user actually works on, so the common case never walks the tree.
        """
        seen: set[str] = set()

        def offer(raw: str):
            if raw in seen:
                return None
            seen.add(raw)
            return raw

        for known in (*self._granted_files, *load_recents()):
            if os.path.basename(known) == name and offer(known):
                yield known

        root = self.root
        examined = 0
        for dirpath, dirnames, filenames in os.walk(root):
            depth = os.path.relpath(dirpath, root).count(os.sep)
            dirnames[:] = [
                d for d in dirnames
                if d not in SKIP_DIRS
                and not d.startswith(".")
                and depth < RESOLVE_MAX_DEPTH
            ]
            if name in filenames:
                candidate = os.path.join(dirpath, name)
                if offer(candidate):
                    yield candidate
            examined += len(filenames)
            if examined > RESOLVE_MAX_FILES:
                return

    def resolve_payload(self, request: dict) -> dict:
        """Map a browser-launched file back to its real path on disk.

        The File Handling API hands the page a file handle with no path, but
        the engine needs the real one: the watcher follows it, and scene files
        routinely resolve imports and assets relative to ``__file__``. Copying
        the bytes somewhere would break both. So match on name and verify by
        content digest — a same-named file elsewhere cannot pass.

        Being handed a file by the OS is an explicit user action, so a
        verified match grants that one file, exactly as the native dialog does.
        """
        name = request.get("name")
        digest = request.get("sha256")
        size = request.get("size")
        if (
            not isinstance(name, str)
            or not name
            or os.path.basename(name) != name
            or not name.lower().endswith(".py")
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return {"error": "bad launch request"}

        for candidate in self._resolve_candidates(name):
            try:
                if isinstance(size, int) and os.path.getsize(candidate) != size:
                    continue
                with open(candidate, "rb") as file:
                    if hashlib.sha256(file.read()).hexdigest() != digest:
                        continue
                resolved = resolve_authorized_file(
                    self._root_path, candidate, suffix=".py",
                    allow_outside_root=True,
                )
            except (OSError, ValueError):
                continue
            path = str(resolved)
            self._granted_files.add(path)
            return {
                "file": {
                    "path": path,
                    "rel": os.path.relpath(path, self.root)
                    if resolved.is_relative_to(self._root_path) else path,
                    "scenes": find_scene_classes(path),
                }
            }
        return {
            "error": f"could not find {name} under {self.root}",
            "hint": "Open it with the Open… button, or point the engine at "
                    "its folder (maniml agent install <dir>).",
        }

    def _start_control_ws(self, control_port: int):
        """Loopback control channel for the hosted and local frontends.

        Normal app sessions use the stable default port; desktop-open sessions
        request an OS-assigned port so independently opened files cannot
        collide.
        """
        import asyncio

        import websockets.asyncio.server as ws_server

        async def handler(ws):
            registered = False
            try:
                first = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
            except Exception:
                return
            if not is_auth_message(first, self.token):
                await ws.close(code=1008, reason="authentication required")
                return
            self._session_lease.connected()
            registered = True
            try:
                await ws.send(
                    json.dumps(
                        {
                            "type": "authenticated",
                            "protocol": WEB_PROTOCOL_VERSION,
                        }
                    )
                )
                async for message in ws:
                    request = parse_json_object(message)
                    if request is None:
                        continue
                    op = request.get("op")
                    if op == "files":
                        response = self.files_payload()
                    elif op == "resolve":
                        response = await asyncio.to_thread(
                            self.resolve_payload, request)
                    elif op == "choose":
                        response = await asyncio.to_thread(self.choose_payload)
                    elif op == "open":
                        response = await asyncio.to_thread(self.open_payload, request)
                    else:
                        response = {"error": f"unknown op {op}"}
                    response["id"] = request.get("id")
                    await ws.send(json.dumps(response))
            finally:
                if registered:
                    self._session_lease.disconnected()

        async def main(port):
            async with ws_server.serve(
                handler,
                "127.0.0.1",
                port,
                origins=sorted(self.allowed_origins),
                max_size=MAX_CONTROL_MESSAGE,
                max_queue=16,
                compression=None,
            ) as server:
                self.control_port = server.sockets[0].getsockname()[1]
                self._control_ready.set()
                await asyncio.Future()

        def run():
            try:
                asyncio.run(main(control_port))
                return
            except OSError:
                pass
            # The default port is a rendezvous, not a requirement: a
            # background agent holds it for the whole login session, and a
            # foreground `maniml app` must still be reachable. Fall back to an
            # OS-assigned port — run_app puts it in the launch URL, so the
            # page it opens connects to this server rather than the agent.
            if control_port == 0:
                print("warning: could not start the control channel")
                self._control_ready.set()
                return
            try:
                asyncio.run(main(0))
            except OSError:
                print("warning: could not start the control channel")
                self._control_ready.set()

        self._control_ready = threading.Event()
        threading.Thread(target=run, name="maniml-app-control", daemon=True).start()
        self._control_ready.wait(timeout=5)

    def serve_forever(self):
        self._serving.set()
        self.httpd.serve_forever()

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
                    self.httpd.shutdown()
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
            with self._lock:
                processes = list(self.processes.values())
            for process in processes:
                process.stop()


def run_app(
    root: str = ".",
    open_browser: bool = True,
    allow_outside_root: bool = False,
    hosted: bool = False,
    initial_file: str | None = None,
    control_port: int = CONTROL_WS_PORT,
    token: str | None = None,
) -> None:
    server = AppServer(
        root,
        allow_outside_root=allow_outside_root,
        control_port=control_port,
        transient=initial_file is not None,
        token=token,
    )
    previous_sigterm = None
    if threading.current_thread() is threading.main_thread():
        previous_sigterm = signal.getsignal(signal.SIGTERM)

        def exit_on_sigterm(signum, frame):
            raise SystemExit(128 + signum)

        signal.signal(signal.SIGTERM, exit_on_sigterm)
    control_fragment = f"token={server.token}"
    if server.control_port != CONTROL_WS_PORT:
        control_fragment += f"&control={server.control_port}"
    # The local page needs the resolved port for the same reason the hosted
    # one does: it may not be the default when an agent already holds it.
    launch_url = (
        f"{HOSTED_APP_URL}#{control_fragment}" if hosted
        else f"{server.url}#{control_fragment}"
    )
    if initial_file is not None:
        opened = server.open_payload({"path": initial_file})
        if hosted and opened.get("viewer_url"):
            launch_url = HOSTED_APP_URL + opened["viewer_url"]
        elif opened.get("error"):
            # A desktop open has no UI of its own: without this the launcher
            # log is silent and the landing page gives no hint why the file
            # the user just picked did not open.
            print(f"maniml open: {initial_file}: {opened['error']}")
            # Fall back to the landing page, and make sure the file is
            # listed and openable there even though the direct open failed
            # (a multi-scene file is the common case — pick a scene).
            server.grant_file(initial_file)
    print(f"maniml app: {launch_url}  (scenes under {server.root})")
    if open_browser:
        if hosted:
            open_hosted_url(launch_url)
        else:
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
