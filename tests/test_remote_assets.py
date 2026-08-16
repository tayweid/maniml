"""Regression tests for bounded, atomic URL-backed asset downloads."""

import tempfile
import threading
import time
import traceback
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from maniml.utils import file_ops


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):
        pass


class AssetHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"
    requests = {}

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        self.requests[path] = self.requests.get(path, 0) + 1

        if path == "/asset.png":
            self._send(b"valid image bytes")
        elif path == "/deadline.png":
            self._send(b"late")
        elif path == "/advertised-large.png":
            self.send_response(200)
            self.send_header("Content-Length", "9")
            self.end_headers()
        elif path == "/streamed-large.png":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"123456789")
        elif path == "/truncated.png":
            self.send_response(200)
            self.send_header("Content-Length", "10")
            self.end_headers()
            self.wfile.write(b"short")
        elif path == "/slow.png":
            self.send_response(200)
            self.send_header("Content-Length", "4")
            self.end_headers()
            time.sleep(0.2)
            self.wfile.write(b"slow")
        else:
            self.send_error(404)

    def _send(self, content):
        self.send_response(200)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class RemoteAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        AssetHandler.requests = {}
        cls.server = QuietThreadingHTTPServer(("127.0.0.1", 0), AssetHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.downloads = Path(self.temporary_directory.name)
        patcher = patch.object(
            file_ops, "_get_downloads_dir", return_value=str(self.downloads)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def assert_no_partial_downloads(self):
        self.assertEqual(list(self.downloads.glob("*.part")), [])
        self.assertEqual(list(self.downloads.glob(".*.part")), [])

    def test_download_is_cached_and_query_is_not_used_as_a_suffix(self):
        url = f"{self.origin}/asset.png?token=do-not-log"

        first = file_ops.find_file(url)
        second = file_ops.find_file(url)

        self.assertEqual(first, second)
        self.assertEqual(first.suffix, ".png")
        self.assertEqual(first.read_bytes(), b"valid image bytes")
        self.assertEqual(AssetHandler.requests["/asset.png"], 1)
        self.assert_no_partial_downloads()

    def test_advertised_size_limit_leaves_no_cache_entry(self):
        url = f"{self.origin}/advertised-large.png"
        with patch.object(file_ops, "REMOTE_ASSET_MAX_BYTES", 8):
            with self.assertRaisesRegex(file_ops.RemoteAssetError, "download limit"):
                file_ops.find_file(url)

        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assert_no_partial_downloads()

    def test_streamed_size_limit_leaves_no_cache_entry(self):
        url = f"{self.origin}/streamed-large.png"
        with patch.object(file_ops, "REMOTE_ASSET_MAX_BYTES", 8):
            with self.assertRaisesRegex(file_ops.RemoteAssetError, "download limit"):
                file_ops.find_file(url)

        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assert_no_partial_downloads()

    def test_truncated_response_leaves_no_cache_entry(self):
        url = f"{self.origin}/truncated.png"

        with self.assertRaisesRegex(file_ops.RemoteAssetError, "incomplete"):
            file_ops.find_file(url)

        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assert_no_partial_downloads()

    def test_socket_timeout_leaves_no_cache_entry(self):
        url = f"{self.origin}/slow.png"
        with patch.object(file_ops, "REMOTE_ASSET_SOCKET_TIMEOUT", 0.05):
            with self.assertRaisesRegex(file_ops.RemoteAssetError, "timed out"):
                file_ops.find_file(url)

        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assert_no_partial_downloads()

    def test_total_deadline_leaves_no_cache_entry(self):
        url = f"{self.origin}/deadline.png"
        with patch.object(file_ops, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(file_ops.RemoteAssetError, "within 60"):
                file_ops.find_file(url)

        self.assertEqual(list(self.downloads.iterdir()), [])
        self.assert_no_partial_downloads()

    def test_http_error_does_not_disclose_query_secret(self):
        url = f"{self.origin}/missing.png?token=do-not-log"

        with self.assertRaises(file_ops.RemoteAssetError) as raised:
            file_ops.find_file(url)

        message = str(raised.exception)
        self.assertIn("HTTP status 404", message)
        self.assertNotIn("do-not-log", message)
        formatted = "".join(
            traceback.format_exception(
                type(raised.exception),
                raised.exception,
                raised.exception.__traceback__,
            )
        )
        self.assertNotIn("do-not-log", formatted)
        self.assertEqual(list(self.downloads.iterdir()), [])

    def test_non_http_url_is_rejected_explicitly(self):
        with self.assertRaisesRegex(file_ops.RemoteAssetError, "must use"):
            file_ops.find_file("ftp://example.com/asset.png")


if __name__ == "__main__":
    unittest.main()
