"""The per-program uniform mirror must die with its program.

set_program_uniform skips a GL write when the mirror says the value is
already set. The mirror used to live in a module dict keyed by
id(program); once the lru-cached programs start being evicted and
freed, a new program can reuse a freed id, inherit the stale mirror, and
silently skip its first uniform writes — a wrong native frame that only
appears after enough scenes have been created (the full-suite fidelity
flake of 2026-09-02).
"""
import unittest

import moderngl

from maniml.utils.shaders import set_program_uniform

VERT = "#version 330\nuniform float scale;\nin vec2 v;\nvoid main() { gl_Position = vec4(v * scale, 0.0, 1.0); }"
FRAG = "#version 330\nout vec4 c;\nvoid main() { c = vec4(1.0); }"


class UniformMirrorLifetime(unittest.TestCase):
    def test_fresh_program_always_gets_its_first_write(self):
        ctx = moderngl.create_standalone_context()
        try:
            for i in range(40):
                program = ctx.program(vertex_shader=VERT, fragment_shader=FRAG)
                # A brand-new program has no uniform state: the first
                # write must happen no matter what id() it landed on.
                self.assertTrue(
                    set_program_uniform(program, "scale", 1.0),
                    f"iteration {i}: first write skipped — stale mirror "
                    f"inherited from a freed program at the same id")
                self.assertFalse(set_program_uniform(program, "scale", 1.0))
                program.release()
                del program
        finally:
            ctx.release()
