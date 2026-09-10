"""Optional real loopback WebSocket round trip for renderer measurements.

This deliberately reports an echo round trip, not a browser presentation
latency. Compression is disabled, matching the live scene server. The native
GL path has no wire and should report this stage as absent.
"""

from threading import Thread
from time import perf_counter

from websockets.sync.client import connect
from websockets.sync.server import serve


class LoopbackTransport:
    def __enter__(self):
        def echo(connection):
            for message in connection:
                connection.send(message)
        self.server = serve(echo, "127.0.0.1", 0, compression=None, max_size=None)
        port = self.server.socket.getsockname()[1]
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        try:
            self.client = connect(f"ws://127.0.0.1:{port}", compression=None,
                                  max_size=None, proxy=None)
        except BaseException:
            self.server.shutdown()
            self.thread.join(timeout=5)
            raise
        return self

    def transfer(self, message):
        started = perf_counter()
        self.client.send(message)
        received = self.client.recv(timeout=10)
        elapsed = 1000 * (perf_counter() - started)
        if received != message:
            raise RuntimeError("loopback changed the geometry message")
        return received, elapsed

    def __exit__(self, *_):
        self.client.close()
        self.server.shutdown()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError("loopback transport did not shut down")
