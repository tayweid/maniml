"""The ``MANIML_PROGRAMS`` switch (docs/phase_b3_plan.md).

``off`` (the default): animations rewrite rows on the CPU and the renderer
draws them. ``shadow``: the same rows are written, and a supported
animation also records its program on the mobject, which the Phase B
stages draw instead; the two must agree to the pixel. ``gpu``: the rows
are not written; the program is drawn, and a read of the rows evaluates
it on the CPU first (``Mobject.data``), so a reader sees what is drawn.
``strokes`` (B5.3, docs/phase_b4_plan.md): ``gpu`` for a path without
fill only, which is all Phase A can draw from a program (its stroke comes
from the program's finalized rows; its fill mesh has no program input), so
it needs no patch fill; a filled member's animation keeps the CPU path,
exactly as with programs off. In every mode a program is recorded only
over rows its own animation left there (``admits``, ``stamp``), so a
member that another writer changes in the same play keeps the CPU path,
which composes the two. The play's end is exact in every mode:
``Transform.finish`` writes the final rows.
"""

from __future__ import annotations

import os

import numpy as np

MODES = ("off", "shadow", "gpu", "strokes")

# Set by the viewer while its Phase B renderer is selected, so the plays
# that follow write programs; None defers to the environment. The
# animations read mode() at their begin, the serializer reads what the
# selected renderer asks for (env_mode() for Phase A, so an export or a
# checkpoint still made while Phase B is on screen keeps its own rules).
_override: str | None = None


def env_mode() -> str:
    value = os.environ.get("MANIML_PROGRAMS", "off")
    if value not in MODES:
        raise ValueError("MANIML_PROGRAMS must be 'off', 'shadow', 'gpu' or 'strokes'")
    return value


def mode() -> str:
    return _override if _override is not None else env_mode()


def set_override(value: str | None) -> None:
    global _override
    if value is not None and value not in MODES:
        raise ValueError(f"program mode must be one of {MODES}")
    _override = value


def deferred(mode: str) -> bool:
    """Whether a program recorded in ``mode`` leaves the rows to the GPU
    (and to the first read), as ``gpu`` and ``strokes`` do; ``shadow``
    writes them as well."""
    return mode in ("gpu", "strokes")


def admits(mode: str, animation, member, start) -> bool:
    """Whether ``animation`` may record a program on ``member``, whose
    starting copy is ``start``, this frame. Never under ``off``; under
    ``strokes`` only at a place its begin admitted
    (``animation.program_sources``: None before that begin decides, which
    admits nothing there). And in every mode only while the member is as
    the animation last left it (``animation.program_revisions``, noted by
    ``stamp``; None before the first note): a program is drawn from its
    sources' rows, so over a member that another writer has changed since,
    a second animation of the mobject in the same play or an updater, it
    would hide what that writer put there, which the CPU path keeps."""
    if mode == "off":
        return False
    if mode == "strokes":
        sources = animation.program_sources
        if sources is None or id(start) not in sources:
            return False
    revisions = animation.program_revisions
    return revisions is None or revisions.get(id(member)) == member.revision


def stamp(animation) -> None:
    """Note the revisions of ``animation``'s family as it leaves them: at
    the end of the begin of an animation that records programs, and after
    each of its frames (``Animation.interpolate``), for ``admits`` to
    compare on the next. Under ``off`` nothing is noted, so nothing is
    compared or kept."""
    if mode() == "off":
        animation.program_revisions = None
        return
    animation.program_revisions = {id(member): member.revision for member in animation.mobject.get_family()}


def begin(*mobjects):
    """At an animation's begin, the program sources among ``mobjects``
    (the families it zips, the starting copy's first) made ready and the
    places a program may be recorded at decided: the ids of the first
    family's members ``admits`` takes, or None. Under ``shadow`` and
    ``gpu`` every member is freshened and None returned (every place
    admits); under ``off`` nothing is touched. Under ``strokes`` only the
    places where every member is a path without fill are freshened and
    returned, so a filled member's animation, and its sources, are left
    exactly as with programs off."""
    current = mode()
    if current == "off":
        return None
    if current != "strokes":
        for mobject in mobjects:
            freshen(mobject)
        return None
    admitted = set()
    for members in zip(*(mobject.get_family() for mobject in mobjects)):
        if all(stroke_only(member) for member in members):
            admitted.add(id(members[0]))
            for member in members:
                _freshen_member(member)
    return admitted


def stroke_only(mobject) -> bool:
    """A path with no fill, or a member without points, of which nothing
    is drawn: what a program under ``strokes`` may stand for."""
    from maniml.mobject.types.vectorized_mobject import VMobject
    if not mobject.has_points():
        return True
    return isinstance(mobject, VMobject) and not np.any(mobject.data["fill_rgba"][:, 3])


def freshen(mobject) -> None:
    """Compute a program source's derived columns (joint angles, unit
    normal) once, at an animation's begin: the renderer refreshes them on
    the animated rows when it reads them, and a program's rows are never
    read, so the sources carry them instead."""
    for member in mobject.get_family():
        _freshen_member(member)


def _freshen_member(member) -> None:
    from maniml.mobject.types.vectorized_mobject import VMobject
    if isinstance(member, VMobject) and member.get_num_points() >= 3:
        member.get_joint_angles()
        member.get_unit_normal()
        # The base point rows, as get_shader_data sets them on a read.
        member.data["base_normal"][0::2] = member.data["point"][0]
