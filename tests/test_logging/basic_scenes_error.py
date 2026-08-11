from __future__ import annotations

from maniml import *

# This module is intended to raise an error.


class Error(Scene):
    def construct(self):
        raise Exception("An error has occurred")
