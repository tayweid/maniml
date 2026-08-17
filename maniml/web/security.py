"""Security primitives shared by the local app and its scene viewers.

Everything ManimLive serves is same-origin on loopback, so there is no public
origin to allowlist.  Loopback is still a network boundary rather than an
authorization boundary — any page in any browser, and any other program on
this machine, can reach 127.0.0.1 — so each server keeps an unguessable
capability token and requires it before it will act.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any


AUTH_MESSAGE_TYPE = "authenticate"
MAX_CONTROL_MESSAGE = 64 * 1024
AUTH_TIMEOUT = 5.0


def new_capability_token() -> str:
    """Return a process-local capability with 256 bits of entropy."""
    return secrets.token_urlsafe(32)


CONFIG_DIR = Path.home() / ".maniml"
CAPABILITY_FILE = "capability"


def capability_path() -> Path:
    return CONFIG_DIR / CAPABILITY_FILE


def _prepare_config_dir() -> Path:
    directory = CONFIG_DIR
    try:
        info = directory.lstat()
    except FileNotFoundError:
        directory.mkdir(mode=0o700, parents=True)
    else:
        if not stat.S_ISDIR(info.st_mode) or directory.is_symlink():
            raise RuntimeError(f"maniml config path is not a directory: {directory}")
    if os.name != "nt":
        directory.chmod(0o700)
    return directory


def _read_capability(path: Path) -> str:
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"capability file is empty: {path}")
    return value


def load_or_create_capability() -> str:
    """Return the stable per-install capability, creating it without races.

    A per-process token dies with the process, which is fine for a
    terminal-launched session but not for a background agent: the browser has
    to stay paired across restarts and logins. This one is written 0600 and
    replaced only by rotate_capability().
    """
    directory = _prepare_config_dir()
    path = directory / CAPABILITY_FILE
    try:
        return _read_capability(path)
    except FileNotFoundError:
        pass

    capability = new_capability_token()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        # Another concurrently starting engine won the creation race.
        return _read_capability(path)
    with os.fdopen(descriptor, "w", encoding="utf-8") as file:
        file.write(capability + "\n")
    return capability


def rotate_capability() -> str:
    """Atomically replace the capability, revoking every paired browser."""
    directory = _prepare_config_dir()
    destination = directory / CAPABILITY_FILE
    capability = new_capability_token()
    temporary = directory / f".{CAPABILITY_FILE}.{secrets.token_hex(8)}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(capability + "\n")
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return capability


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
