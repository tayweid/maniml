"""The maniml app: a persistent local server in the Plass/Knuth mold.

`maniml app` serves a landing page listing the scene files under the
launch directory (plus recently opened files); clicking a scene spawns
that scene as its own subprocess — exactly `maniml file.py Scene --web`
— and navigates to its viewer. Scene files are arbitrary user code, so
subprocess-per-scene keeps a crashing scene from taking the app down
(the same isolation argument as Knuth's kernel).

Endpoints:
    GET  /            the landing page (static/app.html)
    GET  /api/files   scene files under the launch dir + recents,
                      each with its Scene classes (AST scan, no import)
    POST /api/open    {"path":..., "scene":...} -> {"url": viewer url}
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

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
RECENTS_PATH = os.path.expanduser("~/.maniml_recents.json")
RECENTS_MAX = 12
SKIP_DIRS = {".git", "__pycache__", "media", "node_modules", ".venv", "venv"}
URL_PATTERN = re.compile(r"http://localhost:\d+/")
DEFAULT_APP_PORT = 8685


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

    def __init__(self, path: str, scene: str | None):
        self.path = path
        self.scene = scene
        command = [sys.executable, "-m", "maniml", path]
        if scene:
            command.append(scene)
        command += ["--web", "--no-browser"]
        self.proc = subprocess.Popen(
            command, cwd=os.path.dirname(path) or None,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
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


class AppServer:
    def __init__(self, root: str, port: int | None = None):
        self.root = os.path.abspath(root)
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
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path in ("/", "/index.html"):
                    with open(os.path.join(STATIC_DIR, "app.html"),
                              "rb") as f:
                        body = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type",
                                     "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path == "/api/files":
                    files = find_scene_files(app.root)
                    listed = {f["path"] for f in files}
                    recents = []
                    for path in load_recents():
                        if path in listed or not os.path.exists(path):
                            continue
                        recents.append({
                            "path": path, "rel": path,
                            "scenes": find_scene_classes(path),
                        })
                    self._json({"root": app.root, "files": files,
                                "recents": recents})
                else:
                    self._json({"error": "not found"}, 404)

            def do_POST(self):
                if self.path != "/api/open":
                    self._json({"error": "not found"}, 404)
                    return
                length = int(self.headers.get("Content-Length", 0))
                try:
                    request = json.loads(self.rfile.read(length))
                    path = os.path.abspath(request["path"])
                except (ValueError, KeyError):
                    self._json({"error": "bad request"}, 400)
                    return
                if not os.path.exists(path):
                    self._json({"error": f"no such file: {path}"}, 404)
                    return
                scene = request.get("scene") or None
                url = app.open_scene(path, scene)
                if url is None:
                    key = (path, scene or "")
                    process = app.processes.get(key)
                    tail = "".join(process.lines) if process else ""
                    self._json({"error": "scene failed to start",
                                "log": tail[-4000:],
                                "hint": missing_module_hint(tail)}, 500)
                else:
                    self._json({"url": url})

        try:
            self.httpd = ThreadingHTTPServer(
                ("127.0.0.1", port or DEFAULT_APP_PORT), Handler)
        except OSError:  # port taken: let the OS pick
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.url = f"http://localhost:{self.port}/"

    def open_scene(self, path: str, scene: str | None) -> str | None:
        key = (path, scene or "")
        with self._lock:
            process = self.processes.get(key)
            if process is None or not process.alive():
                process = SceneProcess(path, scene)
                self.processes[key] = process
        url = process.wait_for_url()
        if url:
            remember_recent(path)
        return url

    def serve_forever(self):
        self.httpd.serve_forever()

    def shutdown(self):
        for process in self.processes.values():
            process.stop()


def run_app(root: str = ".", open_browser: bool = True) -> None:
    server = AppServer(root)
    print(f"maniml app: {server.url}  (scenes under {server.root})")
    if open_browser:
        webbrowser.open(server.url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("")
    finally:
        server.shutdown()
