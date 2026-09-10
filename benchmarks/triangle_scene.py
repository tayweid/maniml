"""Compatibility import for the A0 harness; implementation lives in the package."""

import sys
from maniml.web import triangle_scene

# Keep archived probes and mock.patch targets bound to the same implementation.
sys.modules[__name__] = triangle_scene
