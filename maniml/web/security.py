"""Security primitives shared by the local app and its scene viewers.

**The Origin check is the boundary.** Every server here binds loopback and
serves its page from the same port its WebSocket listens on, so it accepts a
socket only from its own origin. Browsers set `Origin` themselves and a page
cannot forge it, so no website — however malicious, and whether or not it
guesses the port — can drive the engine.

There used to be a capability token as well. It defended against the other
attacker in the table: a program already running on this machine, which can
reach 127.0.0.1 and can forge any header it likes. Keeping that defence real
meant the token could never reach the page through the served HTML, so it
travelled in the URL fragment — which made launching a delivery problem (a
printed address to open, a fragment that Chromium app shims silently drop)
and recovery a terminal command. The defence it bought was small: a program
running as you does not need to drive maniml to run Python: it can run
Python. So the token is gone, and `http://localhost:8685` is simply an
address that works.

Scene files are still arbitrary code, which is why `resolve_authorized_file`
keeps the app confined to its launch directory.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any


MAX_CONTROL_MESSAGE = 64 * 1024

CONFIG_DIR = Path.home() / ".maniml"


def prepare_config_dir() -> Path:
    """Return ~/.maniml, created 0700, refusing a symlinked or non-directory."""
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
