"""uv on this machine, for tests that need a package in its cache.

The engine adds a missing import's package without asking only when uv
already has it on this Mac (environment.add_dependency, offline). A test
of that path needs a package in the cache that the engine does not have:
colorama, pure Python and small, put there by an install into a throwaway
environment.
"""

import os
import subprocess
import sys
import tempfile

from maniml.environment import find_uv


def cached(distribution: str, python: str = sys.executable) -> bool:
    """True once `distribution` is in uv's cache. An install into a
    throwaway environment puts it there, one download if it is not there
    already, so no network means False; so does no uv."""
    uv = find_uv()
    if uv is None:
        return False
    with tempfile.TemporaryDirectory() as scratch:
        venv = os.path.join(scratch, "venv")
        made = subprocess.run(
            [uv, "venv", "--python", python, venv], capture_output=True, text=True)
        if made.returncode != 0:
            return False
        installed = subprocess.run(
            [uv, "pip", "install", "--python", venv, distribution],
            capture_output=True, text=True)
        return installed.returncode == 0


def importable(module: str) -> bool:
    try:
        __import__(module)
    except ImportError:
        return False
    return True
