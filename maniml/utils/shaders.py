"""Pure source helpers for the shader customization compatibility API."""

from collections.abc import Sequence


def __getattr__(name):
    # Preserve historical public helpers without creating a GL context or
    # forcing native runtime imports during ordinary source construction.
    if name in {"image_path_to_texture", "get_shader_program", "set_program_uniform",
                "get_shader_code_from_file"}:
        from maniml.rendering import gl_shaders
        return getattr(gl_shaders, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["get_colormap_code", "image_path_to_texture", "get_shader_program",
           "set_program_uniform", "get_shader_code_from_file"]


def get_colormap_code(rgb_list: Sequence[float]) -> str:
    data = ",".join(
        "vec3({}, {}, {})".format(*rgb)
        for rgb in rgb_list
    )
    return f"vec3[{len(rgb_list)}]({data})"
