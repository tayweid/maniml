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
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from maniml.web.security import (
    AUTH_TIMEOUT,
    HOSTED_APP_ORIGIN,
    HOSTED_APP_URL,
    MAX_CONTROL_MESSAGE,
    is_auth_message,
    new_capability_token,
    parse_json_object,
    resolve_authorized_file,
    token_matches,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RECENTS_PATH = os.environ.get(
    "MANIML_RECENTS_PATH", os.path.expanduser("~/.maniml_recents.json"))
RECENTS_MAX = 12
SKIP_DIRS = {".git", "__pycache__", "media", "node_modules", ".venv", "venv"}
URL_PATTERN = re.compile(
    r"http://localhost:\d+/#token=[A-Za-z0-9_-]+")
DEFAULT_APP_PORT = 8685
# Fixed control-channel port, Knuth-style.  The hosted frontend connects to
# loopback after the CLI pairs it with a process-local capability.  Both that
# token and an exact Origin allowlist are required before any operation.
CONTROL_WS_PORT = 8686


def missing_module_hint(log: str) -> str | None:
    """When a scene dies on a missing import, say which Python maniml
    runs on and the exact install command — scene imports resolve in
    maniml's interpreter, which may not be the shell's default."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", log)  # strip ANSI colors
    match = re.search(
        r"ModuleNotFoundError: No module named '([^']+)'", plain)
    if not match:
        return None
    module = match.group(1).split(".")[0]
    pip = os.path.join(os.path.dirname(sys.executable), "pip")
    if not os.path.exists(pip):
        pip = f"{sys.executable} -m pip"
    return (f"Scenes run on {sys.executable} — "
            f"'{module}' is not installed there. "
            f"Install it with:  {pip} install {module}")


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
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(".")
                       and depth < max_depth]
        for filename in sorted(filenames):
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            scenes = find_scene_classes(path)
            if scenes:
                results.append({
                    "path": path,
                    "rel": os.path.relpath(path, root),
                    "scenes": scenes,
                })
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

    def __init__(self, path: str, scene: str | None, app_origin: str):
        self.path = path
        self.scene = scene
        command = [sys.executable, "-m", "maniml", path]
        if scene:
            command.append(scene)
        command += ["--web", "--no-browser"]
        self.proc = subprocess.Popen(
            command, cwd=os.path.dirname(path) or None,
            env={**os.environ, "PYTHONUNBUFFERED": "1",
                 "MANIML_APP_ORIGIN": app_origin},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.lines: deque[str] = deque(maxlen=200)
        self.url: str | None = None
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line)
            if self.url is None:
                match = URL_PATTERN.search(line)
                if match:
                    self.url = match.group(0)

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
        if self.alive():
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)


class AppServer:
    def __init__(self, root: str, port: int | None = None,
                 allow_outside_root: bool = False):
        self.root = str(Path(root).resolve())
        self._root_path = Path(self.root)
        if not self._root_path.is_dir():
            raise ValueError(f"app root is not a directory: {self.root}")
        self.allow_outside_root = allow_outside_root
        self.token = new_capability_token()
        self.processes: dict[tuple, SceneProcess] = {}
        self._lock = threading.Lock()
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
                        header[len(prefix):], app.token):
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
                path = "app.html" if request_path in ("/", "/index.html") \
                    else request_path.lstrip("/")
                static_root = Path(STATIC_DIR).resolve()
                full = (static_root / path).resolve()
                if not full.is_relative_to(static_root) or not full.is_file():
                    self._json({"error": "not found"}, 404)
                    return
                import mimetypes
                ctype = mimetypes.guess_type(full)[0] \
                    or "application/octet-stream"
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
                if self.headers.get("Content-Type", "").split(";", 1)[0].lower() \
                        != "application/json":
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
                ("127.0.0.1", port or DEFAULT_APP_PORT), Handler)
        except OSError:  # port taken: let the OS pick
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.origin = f"http://localhost:{self.port}"
        self.url = f"{self.origin}/"
        self.launch_url = f"{self.url}#token={self.token}"
        self.allowed_origins = {self.origin, HOSTED_APP_ORIGIN}
        self._start_control_ws()

    def open_scene(self, path: str, scene: str | None) -> str | None:
        key = (path, scene or "")
        with self._lock:
            process = self.processes.get(key)
            if process is None or not process.alive():
                process = SceneProcess(path, scene, self.origin)
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
            if (path in listed or not recent.is_file()
                    or recent.suffix.lower() != ".py"
                    or (not self.allow_outside_root
                        and not recent.is_relative_to(self._root_path))):
                continue
            recent_str = str(recent)
            recents.append({"path": recent_str, "rel": recent_str,
                            "scenes": find_scene_classes(recent_str)})
        return {"root": self.root, "files": files, "recents": recents}

    def open_payload(self, request: dict) -> dict:
        try:
            candidate = resolve_authorized_file(
                self._root_path,
                request.get("path"),
                suffix=".py",
                allow_outside_root=self.allow_outside_root,
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
        if (not isinstance(scene, str) or not scene.isidentifier()
                or scene not in scenes):
            return {"error": "scene was not discovered in this file"}
        url = self.open_scene(path, scene)
        if url is None:
            process = self.processes.get((path, scene or ""))
            tail = "".join(process.lines) if process else ""
            return {"error": "scene failed to start", "log": tail[-4000:],
                    "hint": missing_module_hint(tail)}
        # ws_port lets a hosted frontend connect its own viewer page
        parsed = urlsplit(url)
        ws_port = parsed.port + 1
        viewer_token = parsed.fragment.removeprefix("token=")
        viewer_url = f"viewer.html?ws={ws_port}#token={viewer_token}"
        return {"url": url, "ws_port": ws_port,
                "viewer_url": viewer_url}

    def _start_control_ws(self):
        """Fixed-port WebSocket control channel for the hosted frontend
        (the local landing page uses it too — one code path)."""
        import asyncio
        import websockets.asyncio.server as ws_server

        async def handler(ws):
            try:
                first = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
            except Exception:
                return
            if not is_auth_message(first, self.token):
                await ws.close(code=1008, reason="authentication required")
                return
            await ws.send(json.dumps({"type": "authenticated"}))
            async for message in ws:
                request = parse_json_object(message)
                if request is None:
                    continue
                op = request.get("op")
                if op == "files":
                    response = self.files_payload()
                elif op == "open":
                    response = await asyncio.to_thread(
                        self.open_payload, request)
                else:
                    response = {"error": f"unknown op {op}"}
                response["id"] = request.get("id")
                await ws.send(json.dumps(response))

        async def main():
            async with ws_server.serve(handler, "127.0.0.1",
                                       CONTROL_WS_PORT,
                                       origins=sorted(self.allowed_origins),
                                       max_size=MAX_CONTROL_MESSAGE,
                                       max_queue=16,
                                       compression=None):
                self._control_ready.set()
                await asyncio.Future()

        def run():
            try:
                asyncio.run(main())
            except OSError:
                print(f"warning: control port {CONTROL_WS_PORT} is taken — "
                      "the hosted app page will not find this server")
                self._control_ready.set()

        self._control_ready = threading.Event()
        threading.Thread(target=run, name="maniml-app-control",
                         daemon=True).start()
        self._control_ready.wait(timeout=5)

    def serve_forever(self):
        self.httpd.serve_forever()

    def shutdown(self):
        for process in self.processes.values():
            process.stop()


def run_app(root: str = ".", open_browser: bool = True,
            allow_outside_root: bool = False,
            hosted: bool = False) -> None:
    server = AppServer(root, allow_outside_root=allow_outside_root)
    launch_url = (f"{HOSTED_APP_URL}#token={server.token}"
                  if hosted else server.launch_url)
    print(f"maniml app: {launch_url}  (scenes under {server.root})")
    if open_browser:
        webbrowser.open(launch_url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.shutdown()
