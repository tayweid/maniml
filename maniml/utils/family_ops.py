from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from typing import Callable, Iterable, List, Set, Tuple, TypeVar

    from maniml.mobject.mobject import Mobject

    K = TypeVar("K")


def extract_mobject_family_members(
    mobject_list: Iterable[Mobject],
    exclude_pointless: bool = False
) -> list[Mobject]:
    return [
        sm
        for mob in mobject_list
        for sm in mob.get_family()
        if (not exclude_pointless) or sm.has_points()
    ]


# Draw-order batching (shared by the native renderer and the web
# geometry serializer, which must partition families identically —
# tests/test_wgpu_port.py pixel-diffs the two).
#
# CE paints each family member completely (fill, then stroke) in family
# order, with the whole family stably sorted by z_index first.  maniml
# batches same-state members into one draw ("all fills, then all
# strokes" — the winding-number fill pass needs a whole batch in the
# float texture before its one composite), so a batch reorders passes
# relative to CE.  That is invisible except when an earlier member's
# late pass overlaps a later member's early pass: a stroke-only dashed
# line batched with a fill-only Dot paints its dashes over the dot no
# matter which came last.  These functions produce CE-faithful batches:
# sort by z_index, merge same-key neighbors, and split a batch rather
# than let an overlap invert CE's paint order.


def draw_pass_content(mob: Mobject) -> Tuple[bool, bool]:
    """(early, late): whether the member contributes to its batch's
    early and late render passes.  Normally fill renders early and
    stroke late; stroke_behind swaps them.  Non-vmobjects render in one
    pass and depth-tested members resolve occlusion per pixel, so
    neither can invert paint order within a batch."""
    if getattr(mob, 'depth_test', False):
        return False, False
    has_fill = getattr(mob, 'has_fill', None)
    has_stroke = getattr(mob, 'has_stroke', None)
    if has_fill is None or has_stroke is None:
        return False, False
    fill, stroke = has_fill(), has_stroke()
    if getattr(mob, 'stroke_behind', False):
        return stroke, fill
    return fill, stroke


def padded_draw_bbox(mob: Mobject) -> np.ndarray:
    """[[x_min, y_min], [x_max, y_max]] of the member's painted region:
    the point bounding box padded by stroke reach — the stroke shader
    widens by 0.005 * stroke_width scene units per side at default
    zoom, plus roughly a pixel of anti-aliasing fringe.  The pad stays
    tight on purpose: over-padding makes closely packed grids of
    filled+stroked shapes read as overlapping, splitting what should be
    one batch into hundreds (a composite per member).  A missed AA
    fringe costs sub-pixel blend differences, not a layering inversion.
    Only x/y: draw order is a 2D question — the depth-tested case never
    gets here."""
    bb = mob.get_bounding_box()
    pad = 0.008
    get_widths = getattr(mob, 'get_stroke_widths', None)
    if get_widths is not None:
        widths = get_widths()
        if len(widths):
            pad += 0.005 * float(np.max(widths))
    return np.array([bb[0][:2] - pad, bb[2][:2] + pad])


class DrawBatchHazard:
    """The late-pass footprint of one open draw batch, and the test for
    whether admitting another member would invert CE's paint order.

    Late-pass boxes are kept individually (vectorized intersection)
    rather than as one union: a union quickly covers the whole region a
    grid of shapes occupies, splitting members that overlap nothing
    actually painted.  Past _MAX_TRACKED boxes the oldest coalesce into
    an overflow union — layouts that large lay members out monotonically
    in practice, so the coalesced early boxes stay behind the frontier.
    """

    _MAX_TRACKED = 256

    def __init__(self):
        # Rows of (min_x, min_y, max_x, max_y); a flat buffer with a
        # fill count, so the per-member intersection test never
        # re-stacks a python list into an array
        self._boxes = np.empty((16, 4))
        self._count = 0

    def would_invert(self, early: bool, bbox: np.ndarray | None) -> bool:
        if not early or bbox is None or self._count == 0:
            return False
        boxes = self._boxes[:self._count]
        return bool(np.any(
            (bbox[0, 0] <= boxes[:, 2]) & (bbox[0, 1] <= boxes[:, 3])
            & (boxes[:, 0] <= bbox[1, 0]) & (boxes[:, 1] <= bbox[1, 1])
        ))

    def admit(self, late: bool, bbox: np.ndarray | None) -> None:
        if not late or bbox is None:
            return
        if self._count == len(self._boxes):
            if self._count < self._MAX_TRACKED:
                grown = np.empty((2 * self._count, 4))
                grown[:self._count] = self._boxes
                self._boxes = grown
            else:
                # Coalesce the two oldest boxes into one and shift
                self._boxes[1, :2] = np.minimum(
                    self._boxes[0, :2], self._boxes[1, :2])
                self._boxes[1, 2:] = np.maximum(
                    self._boxes[0, 2:], self._boxes[1, 2:])
                self._boxes[:-1] = self._boxes[1:]
                self._count -= 1
        self._boxes[self._count, :2] = bbox[0]
        self._boxes[self._count, 2:] = bbox[1]
        self._count += 1


def assemble_draw_batches(
    members: Iterable[Mobject],
    key_fn: Callable[[Mobject], K],
) -> list[Tuple[K, list[Mobject]]]:
    """Partition one render group's drawable family members into draw
    batches, in draw order.

    Members are stably sorted by z_index (CE sorts within families;
    equal z_index keeps family order), then consecutive members with
    equal keys merge — except that a member whose early-pass content
    overlaps the late-pass content already in the open batch starts a
    new batch instead, so batching never paints something under what
    CE would put it on top of.  The overlap test is the padded bounding
    box, so non-overlapping same-state members (text glyphs, the bars
    of a chart) still merge into one draw."""
    batches: list[Tuple[K, list[Mobject]]] = []
    open_key = None
    hazard_state = None
    for mob in sorted(members, key=lambda m: m.z_index):
        key = key_fn(mob)
        early, late = draw_pass_content(mob)
        bbox = padded_draw_bbox(mob) if (early or late) else None
        if (
            batches
            and open_key == key
            and not hazard_state.would_invert(early, bbox)
        ):
            batches[-1][1].append(mob)
        else:
            batches.append((key, [mob]))
            open_key = key
            hazard_state = DrawBatchHazard()
        hazard_state.admit(late, bbox)
    return batches


def recursive_mobject_remove(mobjects: List[Mobject], to_remove: Set[Mobject]) -> Tuple[List[Mobject], bool]:
    """
    Takes in a list of mobjects, together with a set of mobjects to remove.

    The first component of what's removed is a new list such that any mobject
    with one of the elements from `to_remove` in its family is no longer in
    the list, and in its place are its family members which aren't in `to_remove`

    The second component is a boolean value indicating whether any removals were made
    """
    result = []
    found_in_list = False
    for mob in mobjects:
        if mob in to_remove:
            found_in_list = True
            continue
        # Recursive call
        sub_list, found_in_submobjects = recursive_mobject_remove(
            mob.submobjects, to_remove
        )
        if found_in_submobjects:
            result.extend(sub_list)
            found_in_list = True
        else:
            result.append(mob)
    return result, found_in_list