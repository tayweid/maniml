"""The localhost server backing the browser viewer (--web).

One server on one port, on a daemon thread so the GL/scene thread stays the
process's main thread. The port answers both plain GETs for the client page
and its assets (`assets.static_response`) and the WebSocket that broadcasts
frames/state and queues inbound input events, so the page and its socket are
the same origin and the page needs to be told nothing about where to connect.

Threading contract: the scene thread talks to this module only through
`broadcast()` (thread-safe, hands off to the asyncio loop) and
`pop_events()` (drains a thread-safe deque). WebSocket handlers never
touch the scene directly.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from collections import deque

from maniml.logger import log
from maniml.web.assets import BOOT_ID
from maniml.web.assets import (
    file_response,
    folder_response,
    is_websocket_upgrade,
    static_response,
)
from maniml.web.security import MAX_CONTROL_MESSAGE, parse_json_object

DEFAULT_PORT = 8687
MAX_EVENT_QUEUE = 1024


class ClientLease:
    """Thread-safe count of connected clients.

    The scene thread reads `has_clients()` to skip frame readback and
    encoding entirely while no browser is attached.
    """

    def __init__(self):
        self._client_count = 0
        self._lock = threading.Lock()

    def connected(self) -> None:
        with self._lock:
            self._client_count += 1

    def disconnected(self) -> None:
        with self._lock:
            if self._client_count > 0:
                self._client_count -= 1

    def has_clients(self) -> bool:
        with self._lock:
            return self._client_count > 0


def bind_loopback(preferred: int, scan: int = 1) -> socket.socket:
    """Listening socket on loopback, falling back to an OS-assigned port.

    Binding here rather than inside the server means the port — and so the
    origin the page will run on — is known before the WebSocket server is
    configured, which is when the Origin allowlist has to be decided.

    `preferred` is a rendezvous, not a requirement: `scan` consecutive ports
    are tried so several scene viewers can coexist, and anything still taken
    (an agent holding the default, say) lands on an OS-assigned port.
    """
    for port in range(preferred, preferred + scan) if preferred else ():
        try:
            return socket.create_server(("127.0.0.1", port))
        except OSError:
            continue
    return socket.create_server(("127.0.0.1", 0))


class WebServer:
    """Owns the viewer's port; exposes a thread-safe queue in each direction."""

    def __init__(
        self,
        port: int | None = None,
        capabilities: tuple[str, ...] = (),
    ):
        self._socket = bind_loopback(DEFAULT_PORT if port is None else port, scan=40)
        self.port = self._socket.getsockname()[1]
        self.url = f"http://localhost:{self.port}/"
        # The whole boundary: a socket is accepted only from the origin this
        # server serves its own page on.
        self.allowed_origins = {f"http://localhost:{self.port}"}
        self.capabilities = list(capabilities)

        self._events: deque[dict] = deque()
        self._clients: set = set()
        self._busy: set = set()  # clients with an unfinished frame send
        self._client_lease = ClientLease()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closing: asyncio.Event | None = None
        self._started = threading.Event()

        threading.Thread(
            target=self._run_loop, name="maniml-web", daemon=True).start()
        if not self._started.wait(timeout=5):
            raise RuntimeError("web viewer server failed to start")

    # -- Server side (runs on its own thread + event loop) --

    def _serve_static(self, connection, request):
        """Answer page/asset GETs; let handshakes through to the Origin check."""
        if is_websocket_upgrade(request):
            return None
        from urllib.parse import urlsplit
        path = urlsplit(request.path).path
        # Per-scene outputs, mounted on this same one-port origin — no
        # second server, no second origin. Set by the viewer once the
        # scene is known; 404 until the files exist.
        if path == "/baked" or path.startswith("/baked/"):
            baked = getattr(self, "baked_dir", None)
            if baked is not None:
                return folder_response(request, baked, "/baked")
        if path.startswith("/present/"):
            # The presentation cache is exactly two files (the rendered
            # movie and its pausepoints table), served under fixed names —
            # a mapping, not a folder, so nothing else is reachable.
            mapping = getattr(self, "present_files", None) or {}
            target = mapping.get(path[len("/present/"):])
            if target is not None:
                return file_response(request, target)
        return static_response(request, index="viewer.html")

    def _run_loop(self):
        import websockets.asyncio.server as ws_server

        async def main():
            self._loop = asyncio.get_running_loop()
            self._closing = asyncio.Event()
            async with ws_server.serve(
                    self._handle_client, sock=self._socket,
                    process_request=self._serve_static,
                    origins=sorted(self.allowed_origins),
                    max_size=MAX_CONTROL_MESSAGE, max_queue=32,
                    compression=None):
                self._started.set()
                await self._closing.wait()  # released by stop()

        try:
            asyncio.run(main())
        except Exception as e:  # daemon thread: report, don't kill the scene
            log.error(f"web viewer server died: {e}")

    async def _handle_client(self, ws):
        registered = False
        try:
            # The Origin check in the handshake already decided this; a
            # connection that gets here is the page we served.
            self._clients.add(ws)
            self._client_lease.connected()
            registered = True
            self._events.append({"type": "_connect"})
            await ws.send(json.dumps({
                "type": "ready",
                "capabilities": self.capabilities,
                # The serving process's boot id: a page stamped by an
                # earlier process is running older JS (a pip upgrade, or
                # any restart under an editable install) and reloads
                # itself rather than driving a newer engine.
                "boot": BOOT_ID,
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
        if self._loop is not None and self._closing is not None:
            try:
                self._loop.call_soon_threadsafe(self._closing.set)
            except RuntimeError:
                pass  # the loop is already gone
