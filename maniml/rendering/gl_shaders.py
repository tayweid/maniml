"""Shader loading and resource helpers for the packaged native GL renderer."""
from __future__ import annotations

import os
import re
from functools import lru_cache
from PIL import Image
import numpy as np

from maniml.utils.directories import get_shader_dir
from maniml.utils.file_ops import find_file

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import moderngl
    from typing import Sequence, Optional




def context_resources(ctx):
    """Keep native resources with their context, never in a process-wide cache."""
    resources = getattr(ctx, "_maniml_gl_resources", None)
    if not isinstance(resources, dict):
        resources = {"programs": {}, "textures": {}}
        ctx._maniml_gl_resources = resources
    return resources


def release_context_resources(ctx):
    """Retire this context's resources without touching other active contexts."""
    resources = getattr(ctx, "_maniml_gl_resources", None)
    ctx._maniml_gl_resources = None
    if not isinstance(resources, dict):
        return
    seen, errors = set(), []

    def release(value):
        if isinstance(value, dict):
            for item in value.values():
                release(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                release(item)
        elif value is not None and id(value) not in seen:
            seen.add(id(value))
            try:
                value.release()
            except Exception as error:
                errors.append(error)

    release(resources)
    resources.clear()
    if errors:
        for error in errors[1:]:
            errors[0].add_note(f"Additional GL cleanup failure: {error}")
        raise errors[0]


def image_path_to_texture(path: str, ctx: moderngl.Context) -> moderngl.Texture:
    textures = context_resources(ctx)["textures"]
    if path in textures:
        return textures[path]
    with Image.open(path) as source:
        im = source.convert("RGBA")
    texture = ctx.texture(
        size=im.size,
        components=len(im.getbands()),
        data=im.tobytes(),
    )
    textures[path] = texture
    return texture


def get_shader_program(
        ctx: moderngl.context.Context,
        vertex_shader: str,
        fragment_shader: Optional[str] = None,
        geometry_shader: Optional[str] = None,
) -> moderngl.Program:
    programs = context_resources(ctx)["programs"]
    key = (vertex_shader, fragment_shader, geometry_shader)
    if key in programs:
        return programs[key]
    program = ctx.program(
        vertex_shader=vertex_shader,
        fragment_shader=fragment_shader,
        geometry_shader=geometry_shader,
    )
    programs[key] = program
    return program


def set_program_uniform(
    program: moderngl.Program,
    name: str,
    value: float | tuple | np.ndarray
) -> bool:
    """
    Sets a program uniform, and also keeps track of a dictionary
    of previously set uniforms for that program so that it
    doesn't needlessly reset it, requiring an exchange with gpu
    memory, if it sees the same value again.

    Returns True if changed the program, False if it left it as is.
    """

    # The mirror lives on the program itself (moderngl's user slot), so
    # it dies with the program. A module dict keyed by id(program) let a
    # new program inherit the mirror of a freed one at the same address
    # and skip its first uniform writes (tests/test_shader_uniforms.py).
    if not isinstance(program.extra, dict):
        program.extra = {}
    uniform_mirror = program.extra.setdefault("uniform_mirror", {})

    if type(value) is np.ndarray and value.ndim > 0:
        value = tuple(value.flatten())
    if uniform_mirror.get(name, None) == value:
        return False

    try:
        program[name].value = value
    except KeyError:
        return False
    uniform_mirror[name] = value
    return True


@lru_cache()
def get_shader_code_from_file(filename: str) -> str | None:
    if not filename:
        return None

    try:
        filepath = find_file(
            filename,
            directories=[get_shader_dir(), "/"],
            extensions=[],
        )
    except IOError:
        return None

    with open(filepath, "r") as f:
        result = f.read()

    # To share functionality between shaders, some functions are read in
    # from other files an inserted into the relevant strings before
    # passing to ctx.program for compiling
    # Replace "#INSERT " lines with relevant code
    insertions = re.findall(r"^#INSERT .*\.glsl$", result, flags=re.MULTILINE)
    for line in insertions:
        inserted_code = get_shader_code_from_file(
            os.path.join("inserts", line.replace("#INSERT ", ""))
        )
        result = result.replace(line, inserted_code)
    return result


def get_colormap_code(rgb_list: Sequence[float]) -> str:
    data = ",".join(
        "vec3({}, {}, {})".format(*rgb)
        for rgb in rgb_list
    )
    return f"vec3[{len(rgb_list)}]({data})"
