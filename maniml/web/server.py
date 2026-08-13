"""Localhost servers backing the browser viewer (--web).

Two servers on adjacent ports, both on daemon threads so the GL/scene
thread stays the process's main thread:

- an HTTP server (stdlib) serving the static client page
- a WebSocket server (`websockets`) that broadcasts frames/state to
  every connected client and queues inbound input events

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
from collections import deque

from maniml.logger import log

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT_HTTP_PORT = 8687  # ws port is always http port + 1


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC_DIR, **kwargs)

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

    def __init__(self, http_port: int | None = None):
        self.http_port = _find_port_pair(http_port or DEFAULT_HTTP_PORT)
        self.ws_port = self.http_port + 1
        self.url = f"http://localhost:{self.http_port}/"

        self._events: deque[dict] = deque()
        self._clients: set = set()
        self._busy: set = set()  # clients with an unfinished frame send
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
                    max_size=2**20, compression=None):
                self._started.set()
                await asyncio.Future()  # run until process exit

        try:
            asyncio.run(main())
        except Exception as e:  # daemon thread: report, don't kill the scene
            log.error(f"web viewer WebSocket server died: {e}")

    async def _handle_client(self, ws):
        self._clients.add(ws)
        self._events.append({"type": "_connect"})
        try:
            async for message in ws:
                try:
                    event = json.loads(message)
                except (ValueError, TypeError):
                    continue
                if isinstance(event, dict):
                    self._events.append(event)
        except Exception:
            pass
        finally:
            self._clients.discard(ws)
            self._busy.discard(ws)

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
        return bool(self._clients)

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
