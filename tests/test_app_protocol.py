"""Display-independent tests for the app/scene subprocess handshake."""

import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import maniml.utils.processes as process_utils
from maniml.web.app import AppServer, SceneProcess, parse_viewer_launch_line, run_app
from maniml.web.server import ClientLease
from maniml.web.viewer import WebViewer

URL = "http://localhost:8689/"


class ClientLeaseTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.lease = ClientLease(
            startup_timeout=10,
            disconnect_grace=3,
            clock=lambda: self.now,
        )

    def test_unattended_startup_expires(self):
        self.now += 9.9
        self.assertFalse(self.lease.expired())
        self.now += 0.1
        self.assertTrue(self.lease.expired())

    def test_connected_client_prevents_expiry(self):
        self.lease.connected()
        self.now += 100
        self.assertTrue(self.lease.has_clients())
        self.assertFalse(self.lease.expired())

    def test_disconnect_uses_grace_and_reconnect_resets_it(self):
        self.lease.connected()
        self.lease.disconnected()
        self.now += 2.9
        self.assertFalse(self.lease.expired())

        self.lease.connected()
        self.lease.disconnected()
        self.now += 2.9
        self.assertFalse(self.lease.expired())
        self.now += 0.1
        self.assertTrue(self.lease.expired())

    def test_all_clients_must_disconnect(self):
        self.lease.connected()
        self.lease.connected()
        self.lease.disconnected()
        self.now += 100
        self.assertTrue(self.lease.has_clients())
        self.assertFalse(self.lease.expired())
        self.lease.disconnected()
        self.now += 3
        self.assertTrue(self.lease.expired())


class ViewerLaunchProtocolTests(unittest.TestCase):
    def test_accepts_dedicated_launch_line(self):
        self.assertEqual(
            parse_viewer_launch_line(f"maniml web viewer: {URL}\n"),
            URL,
        )

    def test_rejects_a_wrapped_rich_log_line(self):
        """Rich line-wraps the human-readable log entry carrying the same URL,
        so only the plain launch line counts as the handshake."""
        self.assertIsNone(
            parse_viewer_launch_line(
                "[12:56:17] INFO maniml web viewer: viewer.py:86\n"
            )
        )
        self.assertIsNone(
            parse_viewer_launch_line("                    http://localhost:8689/\n")
        )

    def test_rejects_prefixed_or_suffixed_output(self):
        self.assertIsNone(parse_viewer_launch_line(f"log: {URL}\n"))
        self.assertIsNone(parse_viewer_launch_line(f"maniml web viewer: {URL} extra\n"))


class SceneProcessLifecycleTests(unittest.TestCase):
    @patch("maniml.web.app.SceneProcess")
    def test_transient_app_marks_its_scene_process(self, scene_process):
        process = scene_process.return_value
        process.wait_for_url.return_value = URL
        server = AppServer.__new__(AppServer)
        server._lock = threading.Lock()
        server._shutdown_complete = False
        server.processes = {}
        server.transient = True

        self.assertEqual(server.open_scene("/tmp/scene.py", "Demo"), URL)

        scene_process.assert_called_once_with(
            "/tmp/scene.py", "Demo", transient=True
        )

    def test_process_group_options_are_cross_platform(self):
        self.assertEqual(
            process_utils.process_group_popen_kwargs("posix"),
            {"start_new_session": True},
        )
        self.assertEqual(
            process_utils.process_group_popen_kwargs("nt"),
            {
                "creationflags": getattr(
                    subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200
                )
            },
        )

    @patch("maniml.web.app.terminate_process_tree")
    def test_stop_terminates_tree_once_then_closes_pipe(self, terminate_tree):
        scene_process = SceneProcess.__new__(SceneProcess)
        scene_process.proc = MagicMock()
        scene_process._stop_lock = threading.Lock()
        scene_process._stopped = False
        scene_process._reader = MagicMock()

        scene_process.stop()
        scene_process.stop()

        terminate_tree.assert_called_once_with(scene_process.proc)
        scene_process._reader.join.assert_called_once_with(timeout=2)
        scene_process.proc.stdout.close.assert_called_once_with()

    @patch("maniml.utils.processes._process_group_exists", side_effect=[True, False])
    @patch("maniml.utils.processes.os.killpg")
    def test_posix_tree_escalates_from_term_to_kill(self, killpg, group_exists):
        process = MagicMock(pid=4321)

        process_utils.terminate_process_tree(
            process,
            platform="posix",
            terminate_timeout=0,
            kill_timeout=0,
        )

        self.assertEqual(
            killpg.call_args_list,
            [call(4321, signal.SIGTERM), call(4321, signal.SIGKILL)],
        )
        self.assertEqual(group_exists.call_count, 2)
        process.wait.assert_called_once_with(timeout=0)

    @patch("maniml.utils.processes._run_taskkill", side_effect=[True, True])
    def test_windows_tree_escalates_to_forced_taskkill(self, taskkill):
        process = MagicMock(pid=4321)
        process.poll.side_effect = [None, None]
        process.wait.side_effect = [
            subprocess.TimeoutExpired("maniml", 3),
            0,
        ]

        process_utils.terminate_process_tree(
            process,
            platform="nt",
            terminate_timeout=3,
            kill_timeout=2,
        )

        self.assertEqual(
            taskkill.call_args_list,
            [
                call(4321, force=False, timeout=3),
                call(4321, force=True, timeout=2),
            ],
        )
        process.terminate.assert_not_called()
        process.kill.assert_not_called()

    @patch("maniml.utils.processes.subprocess.run")
    def test_windows_taskkill_uses_an_argument_vector(self, run):
        run.return_value = subprocess.CompletedProcess([], 0)

        result = process_utils._run_taskkill(4321, force=True, timeout=2)

        self.assertTrue(result)
        run.assert_called_once_with(
            ["taskkill", "/PID", "4321", "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )

    @unittest.skipUnless(os.name == "posix", "POSIX process groups only")
    def test_posix_tree_termination_reaches_a_descendant(self):
        child_source = """
import signal
import sys
import time
from pathlib import Path

ready = Path(sys.argv[1])
stopped = Path(sys.argv[2])

def stop(signum, frame):
    stopped.write_text("stopped")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, stop)
ready.write_text("ready")
while True:
    time.sleep(0.1)
"""
        parent_source = """
import subprocess
import sys
import time

child = subprocess.Popen(
    [sys.executable, "-c", sys.argv[1], sys.argv[2], sys.argv[3]]
)
print(child.pid, flush=True)
while True:
    time.sleep(0.1)
"""
        with tempfile.TemporaryDirectory() as directory:
            ready = Path(directory, "ready")
            stopped = Path(directory, "stopped")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    parent_source,
                    child_source,
                    os.fspath(ready),
                    os.fspath(stopped),
                ],
                stdout=subprocess.PIPE,
                text=True,
                **process_utils.process_group_popen_kwargs(),
            )
            try:
                self.assertIsNotNone(process.stdout)
                child_pid = int(process.stdout.readline())
                self.assertGreater(child_pid, 0)
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(ready.exists(), "descendant did not start")

                process_utils.terminate_process_tree(
                    process,
                    terminate_timeout=1,
                    kill_timeout=1,
                )

                self.assertTrue(stopped.exists(), "descendant missed SIGTERM")
                self.assertIsNotNone(process.poll())
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                if process.stdout is not None:
                    process.stdout.close()

    @unittest.skipUnless(os.name == "nt", "Windows process trees only")
    def test_windows_tree_termination_stops_a_descendant(self):
        child_source = """
import sys
import time
from pathlib import Path

heartbeat = Path(sys.argv[1])
while True:
    heartbeat.write_text(str(time.monotonic_ns()))
    time.sleep(0.05)
"""
        parent_source = """
import subprocess
import sys
import time

child = subprocess.Popen([sys.executable, "-c", sys.argv[1], sys.argv[2]])
print(child.pid, flush=True)
while True:
    time.sleep(0.1)
"""
        with tempfile.TemporaryDirectory() as directory:
            heartbeat = Path(directory, "heartbeat")
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    parent_source,
                    child_source,
                    os.fspath(heartbeat),
                ],
                stdout=subprocess.PIPE,
                text=True,
                **process_utils.process_group_popen_kwargs(),
            )
            try:
                self.assertIsNotNone(process.stdout)
                child_pid = int(process.stdout.readline())
                self.assertGreater(child_pid, 0)
                deadline = time.monotonic() + 5
                while not heartbeat.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(heartbeat.exists(), "descendant did not start")

                process_utils.terminate_process_tree(
                    process,
                    terminate_timeout=3,
                    kill_timeout=2,
                )

                time.sleep(0.15)
                stopped_value = heartbeat.read_text()
                time.sleep(0.2)
                self.assertEqual(heartbeat.read_text(), stopped_value)
                self.assertIsNotNone(process.poll())
            finally:
                process_utils._run_taskkill(process.pid, force=True, timeout=2)
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                if process.stdout is not None:
                    process.stdout.close()


class AppShutdownTests(unittest.TestCase):
    @staticmethod
    def monitor_server(processes, session_lease=None):
        server = AppServer.__new__(AppServer)
        server._lock = threading.Lock()
        server.processes = processes
        server._session_lease = session_lease or ClientLease()
        server._serving = threading.Event()
        server._serving.set()
        server._shutdown_event = threading.Event()
        server.stop_serving = MagicMock()
        return server

    def test_transient_monitor_exits_after_scene_finishes(self):
        process = MagicMock()
        process.alive.return_value = False
        server = self.monitor_server({("scene.py", "Demo"): process})

        thread = server.start_exit_when_idle(True, poll_interval=0.001)
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        server.stop_serving.assert_called_once_with()

    def test_transient_monitor_exits_if_app_never_connects(self):
        server = self.monitor_server(
            {}, ClientLease(startup_timeout=0, disconnect_grace=0)
        )

        thread = server.start_exit_when_idle(False, poll_interval=0.001)
        thread.join(timeout=1)

        self.assertFalse(thread.is_alive())
        server.stop_serving.assert_called_once_with()

    def test_transient_monitor_keeps_live_scene(self):
        process = MagicMock()
        process.alive.return_value = True
        server = self.monitor_server({("scene.py", "Demo"): process})

        thread = server.start_exit_when_idle(True, poll_interval=0.001)
        time.sleep(0.01)
        server._shutdown_event.set()
        thread.join(timeout=1)

        server.stop_serving.assert_not_called()

    def test_shutdown_is_idempotent(self):
        server = AppServer.__new__(AppServer)
        server._shutdown_lock = threading.Lock()
        server._shutdown_complete = False
        server._shutdown_event = threading.Event()
        server._stopped = threading.Event()
        server._loop = None
        server._lock = threading.Lock()
        process = MagicMock()
        server.processes = {("scene.py", "Demo"): process}

        server.shutdown()
        server.shutdown()

        process.stop.assert_called_once_with()

    @patch("maniml.web.app.AppServer")
    def test_sigterm_runs_app_cleanup_and_restores_handler(self, app_server):
        server = app_server.return_value
        server.url = "http://localhost/"
        server.root = "/scenes"
        previous_handler = signal.getsignal(signal.SIGTERM)

        def send_sigterm():
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        server.serve_forever.side_effect = send_sigterm

        with self.assertRaises(SystemExit) as raised:
            run_app("/scenes", open_browser=False)

        self.assertEqual(raised.exception.code, 128 + signal.SIGTERM)
        server.shutdown.assert_called_once_with()
        self.assertEqual(signal.getsignal(signal.SIGTERM), previous_handler)


class WebViewerLeaseTests(unittest.TestCase):
    def _viewer(self):
        viewer = WebViewer.__new__(WebViewer)
        viewer.server = MagicMock()
        viewer.server.client_lease_expired.return_value = True
        viewer._pending_scene = None
        return viewer

    def test_only_transient_viewers_close_when_the_lease_expires(self):
        viewer = self._viewer()
        viewer._transient_session = False
        self.assertFalse(viewer.is_closing)
        viewer._transient_session = True
        self.assertTrue(viewer.is_closing)

    def test_a_pending_scene_ends_the_scene_but_not_the_session(self):
        """The run loop needs interact() to return, but the servers must
        survive so the next scene reuses this viewer and its token."""
        viewer = self._viewer()
        viewer._transient_session = False
        viewer.server.client_lease_expired.return_value = False
        viewer._pending_scene = "BetaScene"

        self.assertTrue(viewer.is_closing)
        viewer.destroy()
        viewer.server.stop.assert_not_called()

        self.assertEqual(viewer.take_pending_scene(), "BetaScene")
        self.assertIsNone(viewer.take_pending_scene())
        self.assertFalse(viewer.is_closing)

        viewer.destroy()
        viewer.server.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
