"""Security primitives shared by the localhost app and scene viewers.

Loopback is a network boundary, not an authorization boundary: arbitrary
websites can attempt connections to localhost from a browser.  Every
privileged channel therefore requires both an allowed browser Origin and an
unguessable, process-local capability token.
"""

from __future__ import annotations

import hmac
import json
import secrets
from pathlib import Path
from typing import Any


AUTH_MESSAGE_TYPE = "authenticate"
MAX_CONTROL_MESSAGE = 64 * 1024
AUTH_TIMEOUT = 5.0

# GitHub Pages uses one origin for all project pages under this account.  The
# capability token remains the primary authorization check; this allowlist is
# an independent browser-side CSWSH defense.
HOSTED_APP_ORIGIN = "https://tayweid.github.io"
HOSTED_APP_URL = f"{HOSTED_APP_ORIGIN}/maniml/"


def new_capability_token() -> str:
    """Return a process-local capability with 256 bits of entropy."""
    return secrets.token_urlsafe(32)


def token_matches(candidate: Any, expected: str) -> bool:
    """Compare a caller-provided token without leaking prefix timing."""
    return isinstance(candidate, str) and hmac.compare_digest(candidate, expected)


def parse_json_object(message: Any) -> dict | None:
    """Parse a small, strict JSON object used by a control protocol.

    Python's JSON decoder accepts NaN and infinities by default.  Those values
    are never valid protocol input and can destabilize camera math, so reject
    them at the boundary.
    """
    if not isinstance(message, (str, bytes)) or len(message) > MAX_CONTROL_MESSAGE:
        return None

    def reject_constant(value: str):
        raise ValueError(f"invalid JSON constant: {value}")

    try:
        value = json.loads(message, parse_constant=reject_constant)
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError):
        return None
    return value if isinstance(value, dict) else None


def is_auth_message(message: Any, expected_token: str) -> bool:
    request = parse_json_object(message)
    return bool(
        request
        and request.get("type") == AUTH_MESSAGE_TYPE
        and token_matches(request.get("token"), expected_token)
    )


def resolve_authorized_file(
    root: str | Path,
    raw_path: Any,
    *,
    suffix: str | None = None,
    allow_outside_root: bool = False,
) -> Path:
    """Resolve a regular file and enforce containment in ``root``.

    Resolving both paths before the containment test also prevents a symlink
    inside the root from granting access to a file outside it.
    """
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("bad path")
    root_path = Path(root).resolve(strict=True)
    try:
        candidate = Path(raw_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"no such file: {raw_path}") from exc
    if not candidate.is_file():
        raise ValueError("path must name a regular file")
    if suffix is not None and candidate.suffix.lower() != suffix.lower():
        raise ValueError(f"path must have a {suffix} suffix")
    if not allow_outside_root and not candidate.is_relative_to(root_path):
        raise ValueError("path is outside the app root")
    return candidate
