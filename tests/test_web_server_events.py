"""The scene server's inbound event queue under pressure.

The scene thread drains the queue only between animations. A file edit
that fast-forwards many units keeps it from draining for tens of seconds
while the page keeps sending pointer samples, so the queue can fill. The
old policy closed the socket on overflow; the page then reconnected into
the same still-full queue and gave up after three tries with the scene
alive and busy (dogfood, 2026-09-09). These tests pin the replacement:
evict rather than close, and start a rejoining page from an empty queue.
"""

import asyncio
import json
import threading
import unittest
from collections import deque

from maniml.web import server as server_module
from maniml.web.server import ClientLease, WebServer


class FakeSocket:
    def __init__(self, messages):
        self._messages = list(messages)
        self.sent = []
        self.closed = []

    async def send(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed.append((code, reason))

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._messages:
            raise StopAsyncIteration
        return self._messages.pop(0)


def bare_server():
    """A WebServer without its socket or thread: only the queue state."""
    server = WebServer.__new__(WebServer)
    server._events = deque()
    server._events_lock = threading.Lock()
    server._clients = set()
    server._client_lease = ClientLease()
    server.capabilities = []
    return server


def pointer(i):
    return json.dumps({"type": "pointer", "action": "move", "x": i, "y": 0})


class EventQueueOverflowTests(unittest.TestCase):
    def setUp(self):
        self.server = bare_server()
        self.limit = server_module.MAX_EVENT_QUEUE

    def types(self):
        return [e.get("type") for e in self.server._events]

    def keep_another_client_attached(self):
        # The queue empties when the last client leaves; these tests look
        # at it after the fake client's stream ends, so hold a second lease.
        self.server._client_lease.connected()

    def test_a_full_queue_drops_old_pointer_samples_and_keeps_the_socket(self):
        self.keep_another_client_attached()
        key = json.dumps({"type": "key", "action": "down", "key": "ArrowRight"})
        messages = [key] + [pointer(i) for i in range(self.limit + 50)]
        ws = FakeSocket(messages)
        asyncio.run(self.server._handle_client(ws))
        self.assertEqual(ws.closed, [], "overflow must not close the socket")
        self.assertEqual(len(self.server._events), self.limit)
        types = self.types()
        # _connect and the key press survive; only pointer samples went
        self.assertEqual(types[:2], ["_connect", "key"])
        self.assertTrue(all(t == "pointer" for t in types[2:]))
        # the newest samples are the ones kept
        xs = [e["x"] for e in self.server._events if e.get("type") == "pointer"]
        self.assertEqual(xs[-1], self.limit + 49)
        self.assertEqual(xs[0], 52)

    def test_without_droppable_events_the_oldest_goes(self):
        self.keep_another_client_attached()
        keys = [json.dumps({"type": "key", "action": "down", "key": "a"})
                for _ in range(self.limit + 5)]
        ws = FakeSocket(keys)
        asyncio.run(self.server._handle_client(ws))
        self.assertEqual(ws.closed, [])
        self.assertEqual(len(self.server._events), self.limit)
        self.assertNotIn("_connect", self.types(), "oldest event evicted first")

    def test_the_last_client_leaving_empties_the_queue(self):
        ws = FakeSocket([pointer(0), pointer(1)])
        asyncio.run(self.server._handle_client(ws))
        self.assertEqual(self.server._events, deque())
        self.assertFalse(self.server.has_clients())

    def test_a_second_client_keeps_its_events_when_the_first_leaves(self):
        # The other page is still attached: its queue survives.
        self.server._client_lease.connected()
        ws = FakeSocket([pointer(0)])
        asyncio.run(self.server._handle_client(ws))
        self.assertEqual(self.types(), ["_connect", "pointer"])

    def test_pop_events_drains_in_order_and_empties(self):
        for i in range(3):
            self.server._events.append({"type": "pointer", "x": i})
        popped = self.server.pop_events()
        self.assertEqual([e["x"] for e in popped], [0, 1, 2])
        self.assertEqual(self.server.pop_events(), [])


if __name__ == "__main__":
    unittest.main()
