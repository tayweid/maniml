"""Static assets served from the same port as the control WebSocket.

Both servers in this package — the app shell and each scene viewer — hand
out `web/static/` over the port their WebSocket listens on, so the page and
the socket share an origin exactly. That is what lets the page derive its
socket URL from `window.location` and what makes `connect-src 'self'` a
meaningful restriction rather than a comment.

`websockets` calls `process_request` before it looks at the Upgrade header,
so a plain GET can be answered with an ordinary HTTP response and the
connection closed. Requests that are WebSocket handshakes return None here
and fall through to the handshake, where the Origin check applies.
"""

from __future__ import annotations

import email.utils
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

from websockets.datastructures import Headers
from websockets.http11 import Request, Response

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

# The renderers fetch their shader sources as text; nothing maps these.
SHADER_CONTENT_TYPES = {
    ".glsl": "text/plain",
    ".wgsl": "text/plain",
    ".webmanifest": "application/manifest+json",
}

VERSION_PLACEHOLDER = "__MANIML_VERSION__"


def _package_version() -> str:
    try:
        from importlib.metadata import PackageNotFoundError, version
    except ImportError:  # pragma: no cover - importlib.metadata is stdlib
        return "0"
    try:
        return version("maniml")
    except PackageNotFoundError:
        return "source"

# The page and its socket are one origin, so 'self' covers the WebSocket as
# well as the shader files the renderers fetch. Inline script/style is the
# viewer's own source, shipped in the same file.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "connect-src 'self'",
        "img-src 'self' data:",
        "script-src 'self' 'unsafe-inline'",
        "style-src 'self' 'unsafe-inline'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'none'",
        "frame-ancestors 'none'",
    )
)


def is_websocket_upgrade(request: Request) -> bool:
    return "websocket" in request.headers.get("Upgrade", "").lower()


def _response(status: int, phrase: str, body: bytes, content_type: str) -> Response:
    headers = Headers(
        [
            ("Date", email.utils.formatdate(usegmt=True)),
            ("Connection", "close"),
            ("Content-Length", str(len(body))),
            ("Content-Type", content_type),
            ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
            ("X-Content-Type-Options", "nosniff"),
            ("Referrer-Policy", "no-referrer"),
            ("Cache-Control", "no-store"),
        ]
    )
    return Response(status, phrase, headers, body)


def folder_response(request: Request, root: Path | str, prefix: str) -> Response:
    """Answer a GET from an on-disk folder mounted at ``prefix``.

    Read-only, `index.html` at the folder root, same resolve-then-contain
    discipline as static_response. No version stamping: the folder is user
    output (a baked scene export), not the packaged shell. `prefix` without
    a trailing slash redirects to `prefix + '/'` so the page's relative
    fetches resolve under the mount.
    """
    if request.method != "GET":
        return _response(405, "Method Not Allowed", b"method not allowed\n", "text/plain")
    request_path = urlsplit(request.path).path
    if request_path == prefix:
        headers = Headers([("Location", prefix + "/"), ("Connection", "close"),
                           ("Content-Length", "0")])
        return Response(301, "Moved Permanently", headers, b"")
    relative = request_path[len(prefix):].lstrip("/") or "index.html"
    try:
        root_path = Path(root).resolve(strict=True)
        target = (root_path / relative).resolve()
    except OSError:
        return _response(404, "Not Found", b"not found\n", "text/plain")
    if not target.is_relative_to(root_path) or not target.is_file():
        return _response(404, "Not Found", b"not found\n", "text/plain")
    body = target.read_bytes()
    content_type = (
        mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    )
    if content_type.startswith("text/") or content_type == "application/javascript":
        content_type += "; charset=utf-8"
    return _response(200, "OK", body, content_type)


def static_response(request: Request, index: str) -> Response:
    """Answer a GET from `web/static/`, serving `index` at the root."""
    if request.method != "GET":
        return _response(405, "Method Not Allowed", b"method not allowed\n", "text/plain")

    request_path = urlsplit(request.path).path
    relative = index if request_path in ("/", "/index.html") else request_path.lstrip("/")
    root = Path(STATIC_DIR).resolve()
    try:
        target = (root / relative).resolve()
    except OSError:
        return _response(404, "Not Found", b"not found\n", "text/plain")
    # Resolving before the containment test also stops a symlink under
    # static/ from reaching outside the package.
    if not target.is_relative_to(root) or not target.is_file():
        return _response(404, "Not Found", b"not found\n", "text/plain")

    body = target.read_bytes()
    if VERSION_PLACEHOLDER.encode() in body:
        # Stamp whatever asks for it with the installed version. Two things
        # depend on this: the service worker, because a browser decides
        # whether to install a new one by comparing bytes and because the
        # stamp keys its shell cache; and the app page, so `maniml app` can
        # ask a running engine what it is serving. pip replaces files, it
        # does not restart processes, and an engine that has been up since
        # before an upgrade keeps serving what it booted with.
        body = body.replace(
            VERSION_PLACEHOLDER.encode(), _package_version().encode()
        )
    content_type = (
        SHADER_CONTENT_TYPES.get(target.suffix.lower())
        or mimetypes.guess_type(target.name)[0]
        or "application/octet-stream"
    )
    if content_type.startswith("text/") or content_type == "application/javascript":
        content_type += "; charset=utf-8"
    return _response(200, "OK", body, content_type)
