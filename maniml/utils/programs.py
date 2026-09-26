"""The ``MANIML_PROGRAMS`` switch (docs/phase_b3_plan.md).

``off`` (the default): animations rewrite rows on the CPU and the renderer
draws them. ``shadow``: the same rows are written, and a supported
animation also records its program on the mobject, which the Phase B
stages draw instead; the two must agree to the pixel. ``gpu``: the rows
are not written; the program is drawn, and a read of the rows evaluates
it on the CPU first (``Mobject.data``), so a reader sees what is drawn.
The play's end is exact in every mode: ``Transform.finish`` writes the
final rows.
"""

from __future__ import annotations

import os

MODES = ("off", "shadow", "gpu")

# Set by the viewer while its Phase B renderer is selected, so the plays
# that follow write programs; None defers to the environment. The
# animations read mode() at their begin, the serializer reads what the
# selected renderer asks for (env_mode() for Phase A, so an export or a
# checkpoint still made while Phase B is on screen keeps its own rules).
_override: str | None = None


def env_mode() -> str:
    value = os.environ.get("MANIML_PROGRAMS", "off")
    if value not in MODES:
        raise ValueError("MANIML_PROGRAMS must be 'off', 'shadow' or 'gpu'")
    return value


def mode() -> str:
    return _override if _override is not None else env_mode()


def set_override(value: str | None) -> None:
    global _override
    if value is not None and value not in MODES:
        raise ValueError(f"program mode must be one of {MODES}")
    _override = value


def freshen(mobject) -> None:
    """Compute a program source's derived columns (joint angles, unit
    normal) once, at an animation's begin: the renderer refreshes them on
    the animated rows when it reads them, and a program's rows are never
    read, so the sources carry them instead."""
    from maniml.mobject.types.vectorized_mobject import VMobject
    for member in mobject.get_family():
        if isinstance(member, VMobject) and member.get_num_points() >= 3:
            member.get_joint_angles()
            member.get_unit_normal()
            # The base point rows, as get_shader_data sets them on a read.
            member.data["base_normal"][0::2] = member.data["point"][0]
