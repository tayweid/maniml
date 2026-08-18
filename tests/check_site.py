"""Guard the published preview against becoming the application again.

`site/` goes to a public origin. The application does not: it is served by the
engine that runs your scenes, from the same pip install, and that local copy is
the only installable one. Two rules follow, and this script enforces both so
that a future edit cannot quietly undo them.

**Nothing here may reach a local engine.** A public page talking to loopback is
the seam that caused essentially every delivery bug this project has had; it
was deleted deliberately (see CLAUDE.md, "Delivery: one artifact, local only").

**Nothing here may be installable.** Only one installed app can own the `.py`
double-click. If the hosted build were installable it would compete with the
local one for every file the user opens.

Run standalone (this is what CI does), or via tests/test_hosted_site.py:

    python3 tests/check_site.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"

# Substrings that would mean the preview had grown an engine or an identity.
# Naming `http://localhost:8685` in prose is the page's job; opening a
# connection to it is what must never appear, so these match the mechanisms
# rather than the address.
FORBIDDEN = {
    "ws://": "a socket to a local engine",
    "wss://": "a socket to a local engine",
    "WebSocket": "a socket to a local engine",
    "EventSource": "a stream from a local engine",
    "XMLHttpRequest": "a request to a local engine",
    "fetch(": "a request to a local engine",
    'rel="manifest"': "a web app manifest, which would make it installable",
    "file_handlers": "a file-type registration competing with the local app",
    "beforeinstallprompt": "an install prompt; installing belongs to the local app",
    "launchQueue": "OS file delivery, which only the local app should receive",
}

# Files that belong to the application and must never be published.
FORBIDDEN_FILES = (
    "manifest.webmanifest",
    "viewer.html",
    "gl.js",
    "webgpu.js",
    "player.html",
)


def problems() -> list[str]:
    found: list[str] = []
    if not SITE.is_dir():
        return [f"no preview site directory: {SITE}"]

    for name in FORBIDDEN_FILES:
        if (SITE / name).exists():
            found.append(f"site/{name} belongs to the local app, not the preview")

    for path in sorted(SITE.rglob("*")):
        if not path.is_file() or path.suffix not in {".html", ".js", ".json"}:
            continue
        text = path.read_text(encoding="utf-8")
        for needle, why in FORBIDDEN.items():
            if needle in text:
                found.append(f"site/{path.relative_to(SITE)} contains {needle!r}: {why}")

    worker = SITE / "sw.js"
    if not worker.is_file():
        # Browsers that installed the old worker keep running it until a
        # replacement at the same URL retires it.
        found.append("site/sw.js is missing: the old service worker stays live")
    else:
        source = worker.read_text(encoding="utf-8")
        if "registration.unregister()" not in source:
            found.append("site/sw.js must unregister itself, not cache a shell")
        if "addEventListener(\"fetch\"" in source or "addEventListener('fetch'" in source:
            found.append("site/sw.js must not serve requests")
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(f"preview site: {problem}", file=sys.stderr)
    if found:
        return 1
    print(f"preview site OK: {SITE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
