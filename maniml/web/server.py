"""Localhost servers backing the browser viewer (--web).

Two servers on adjacent ports, both on daemon threads so the GL/scene
thread stays the process's main thread:

- an HTTP server (stdlib) serving the static client page
- a WebSocket server (`websockets`) that broadcasts frames/state to
  every authenticated client and queues inbound input events

Threading contract: the scene thread talks to this module only through
`broadcast()` (thread-safe, hands off to the asyncio loop) and
`pop_events()` (drains a thread-safe deque). WebSocket handlers never
touch the scene directly.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import os
import socket
import threading
import time
from collections import deque
from collections.abc import Callable

from maniml.logger import log
from maniml.web.security import (
    AUTH_TIMEOUT,
    MAX_CONTROL_MESSAGE,
    is_auth_message,
    new_capability_token,
    parse_json_object,
)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT_HTTP_PORT = 8687  # ws port is always http port + 1
MAX_EVENT_QUEUE = 1024
VIEWER_STARTUP_TIMEOUT = 120.0
VIEWER_DISCONNECT_GRACE = 30.0


class ClientLease:
    """Track authenticated clients and bound an unattended session.

    A startup timeout prevents a viewer that never connected (for example,
    because local-network access was denied) from living forever.  Once a
    client has connected, a shorter grace period tolerates page reloads and
    brief browser restarts before the session is considered abandoned.
    """

    def __init__(
        self,
        startup_timeout: float = VIEWER_STARTUP_TIMEOUT,
        disconnect_grace: float = VIEWER_DISCONNECT_GRACE,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.startup_timeout = startup_timeout
        self.disconnect_grace = disconnect_grace
        self._clock = clock
        self._created_at = clock()
        self._last_disconnect: float | None = None
        self._client_count = 0
        self._ever_connected = False
        self._lock = threading.Lock()

    def connected(self) -> None:
        with self._lock:
            self._client_count += 1
            self._ever_connected = True
            self._last_disconnect = None

    def disconnected(self) -> None:
        with self._lock:
            if self._client_count == 0:
                return
            self._client_count -= 1
            if self._client_count == 0:
                self._last_disconnect = self._clock()

    def has_clients(self) -> bool:
        with self._lock:
            return self._client_count > 0

    def expired(self) -> bool:
        with self._lock:
            if self._client_count > 0:
                return False
            now = self._clock()
            if not self._ever_connected:
                return now - self._created_at >= self.startup_timeout
            return (
                self._last_disconnect is not None
                and now - self._last_disconnect >= self.disconnect_grace
            )


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/viewer.html"  # a scene process serves the viewer
        super().do_GET()

    def log_message(self, format, *args):
        pass


def _find_port_pair(start: int) -> int:
    """First port p >= start with both p and p+1 free."""
    for p in range(start, start + 40, 2):
        try:
            for q in (p, p + 1):
                with socket.socket() as s:
                    s.bind(("127.0.0.1", q))
        except OSError:
            continue
        return p
    raise OSError(f"no free port pair near {start}")


class WebServer:
    """Owns both servers; exposes a thread-safe queue in each direction."""

    def __init__(
        self,
        http_port: int | None = None,
        capabilities: tuple[str, ...] = (),
    ):
        self.http_port = _find_port_pair(http_port or DEFAULT_HTTP_PORT)
        self.ws_port = self.http_port + 1
        self.token = new_capability_token()
        self.base_url = f"http://localhost:{self.http_port}/"
        self.url = f"{self.base_url}#token={self.token}"
        self.allowed_origins = {f"http://localhost:{self.http_port}"}
        parent_origin = os.environ.get("MANIML_APP_ORIGIN")
        if parent_origin:
            self.allowed_origins.add(parent_origin)
        self.capabilities = list(capabilities)

        self._events: deque[dict] = deque()
        self._clients: set = set()
        self._busy: set = set()  # clients with an unfinished frame send
        self._client_lease = ClientLease()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._started = threading.Event()

        self._httpd = http.server.ThreadingHTTPServer(
            ("127.0.0.1", self.http_port), _QuietHandler)
        threading.Thread(
            target=self._httpd.serve_forever, name="maniml-web-http",
            daemon=True).start()
        threading.Thread(
            target=self._run_ws_loop, name="maniml-web-ws",
            daemon=True).start()
        if not self._started.wait(timeout=5):
            raise RuntimeError("web viewer WebSocket server failed to start")

    # -- WebSocket side (runs on its own thread + event loop) --

    def _run_ws_loop(self):
        import websockets.asyncio.server as ws_server

        async def main():
            self._loop = asyncio.get_running_loop()
            async with ws_server.serve(
                    self._handle_client, "127.0.0.1", self.ws_port,
                    origins=sorted(self.allowed_origins),
                    max_size=MAX_CONTROL_MESSAGE, max_queue=32,
                    compression=None):
                self._started.set()
                await asyncio.Future()  # run until process exit

        try:
            asyncio.run(main())
        except Exception as e:  # daemon thread: report, don't kill the scene
            log.error(f"web viewer WebSocket server died: {e}")

    async def _handle_client(self, ws):
        registered = False
        try:
            first = await asyncio.wait_for(ws.recv(), timeout=AUTH_TIMEOUT)
            if not is_auth_message(first, self.token):
                await ws.close(code=1008, reason="authentication required")
                return
            self._clients.add(ws)
            self._client_lease.connected()
            registered = True
            self._events.append({"type": "_connect"})
            await ws.send(json.dumps({
                "type": "authenticated",
                "capabilities": self.capabilities,
            }))
            async for message in ws:
                event = parse_json_object(message)
                if event is None:
                    continue
                if len(self._events) >= MAX_EVENT_QUEUE:
                    await ws.close(code=1013, reason="event queue full")
                    return
                self._events.append(event)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            self._busy.discard(ws)
            if registered:
                self._client_lease.disconnected()

    def _send_to_all(self, data, droppable: bool):
        for ws in list(self._clients):
            if droppable and ws in self._busy:
                continue  # slow client: skip this frame rather than queue it
            self._busy.add(ws)

            async def send(ws=ws):
                try:
                    await ws.send(data)
                except Exception:
                    self._clients.discard(ws)
                finally:
                    self._busy.discard(ws)

            self._loop.create_task(send())

    # -- Scene-thread API --

    def has_clients(self) -> bool:
        return self._client_lease.has_clients()

    def client_lease_expired(self) -> bool:
        return self._client_lease.expired()

    def broadcast(self, data: bytes | str, droppable: bool = False) -> None:
        """Send to every client. `droppable` marks per-frame data that a
        client that hasn't finished its previous send may skip."""
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._send_to_all, data, droppable)

    def broadcast_json(self, obj: dict) -> None:
        self.broadcast(json.dumps(obj))

    def pop_events(self) -> list[dict]:
        events = []
        while True:
            try:
                events.append(self._events.popleft())
            except IndexError:
                return events

    def stop(self) -> None:
        self._httpd.shutdown()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
