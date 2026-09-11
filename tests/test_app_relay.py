"""The app's `/scene/<id>` relay when the scene behind it is gone.

A page opened through the app never learns the scene process's port; the
app connects to the scene as a client and copies frames both ways. When
there is nothing to connect to, the page's socket must close promptly with
a reason rather than hang, and the app must stay up.
"""

import tempfile
import unittest
from types import SimpleNamespace

from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect as ws_connect

from maniml.web.app import AppServer
from maniml.web.server import bind_loopback


class RelayFailureTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.server = AppServer(self.tmpdir.name, port=0)
        self.addCleanup(self.server.shutdown)

    def relay_close(self, scene_id):
        with ws_connect(f"ws://localhost:{self.server.port}/scene/{scene_id}",
                        origin=self.server.origin, open_timeout=5) as ws:
            with self.assertRaises(ConnectionClosed) as closed:
                ws.recv(timeout=10)
        return closed.exception.rcvd

    def test_a_dead_scene_process_closes_with_no_such_scene(self):
        self.server._scenes_by_id["ghost"] = SimpleNamespace(
            url="http://localhost:1/", ws_url="ws://localhost:1/", alive=lambda: False)
        close = self.relay_close("ghost")
        self.assertEqual((close.code, close.reason), (1011, "no such scene"))

    def test_an_unreachable_scene_closes_the_page_socket_cleanly(self):
        # A port that was bound and released: nothing answers there.
        sock = bind_loopback(0)
        port = sock.getsockname()[1]
        sock.close()
        self.server._scenes_by_id["vanished"] = SimpleNamespace(
            url=f"http://localhost:{port}/", ws_url=f"ws://localhost:{port}/", alive=lambda: True)
        close = self.relay_close("vanished")
        self.assertEqual(close.code, 1000, "the relay closes normally when its upstream never opens")
        # The app is still serving.
        self.assertEqual(self.relay_close("ghost-again").code, 1011)


if __name__ == "__main__":
    unittest.main()
