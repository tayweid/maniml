from __future__ import annotations

from maniml.animation.animation import Animation
from maniml.constants import ORIGIN, OUT
from maniml.constants import PI, TAU
from maniml.utils import programs
from maniml.utils.rate_functions import linear
from maniml.utils.rate_functions import smooth
from maniml.utils.space_ops import rotation_matrix_transpose

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np
    from typing import Callable
    from maniml.mobject.mobject import Mobject


class Rotating(Animation):
    def __init__(
        self,
        mobject: Mobject,
        angle: float = TAU,
        axis: np.ndarray = OUT,
        about_point: np.ndarray | None = None,
        about_edge: np.ndarray | None = None,
        run_time: float = 5.0,
        rate_func: Callable[[float], float] = linear,
        suspend_mobject_updating: bool = True,  # CE's Rotating inherits the default
        **kwargs
    ):
        self.angle = angle
        self.axis = axis
        self.about_point = about_point
        self.about_edge = about_edge
        super().__init__(
            mobject,
            run_time=run_time,
            rate_func=rate_func,
            suspend_mobject_updating=suspend_mobject_updating,
            **kwargs
        )

    def begin(self) -> None:
        self._program_frames = 0
        super().begin()
        if programs.mode() != "off":
            programs.freshen(self.starting_mobject)
            # After the first frame the CPU path's rotate recomputes the
            # box it rotates about from the rows, which are the start's;
            # the start copy's box, recomputed, is that box.
            self.starting_mobject.refresh_bounding_box(recurse_down=True)

    def interpolate_mobject(self, alpha: float) -> None:
        angle = self.rate_func(self.time_spanned_alpha(alpha)) * self.angle
        mode = programs.mode()
        if mode != "off" and self._program_frame(angle, mode):
            return
        pairs = zip(
            self.mobject.family_members_with_points(),
            self.starting_mobject.family_members_with_points(),
        )
        for sm1, sm2 in pairs:
            for key in sm1.pointlike_data_keys:
                sm1.data[key][:] = sm2.data[key]
        self.mobject.rotate(
            angle,
            axis=self.axis,
            about_point=self.about_point,
            about_edge=self.about_edge,
        )

    def _program_frame(self, angle: float, mode: str) -> bool:
        """The frame as an affine program on every member (docs/phase_b3_plan.md):
        the start's points rotated about the point the CPU path rotates
        about, which is the start's, since the points are the start's when
        it is computed. All or nothing, so a family whose members do not
        all align keeps the CPU path."""
        pairs = list(zip(self.mobject.family_members_with_points(),
                         self.starting_mobject.family_members_with_points()))
        if not pairs or not all(hasattr(sm, "affine_program") and sm._aligned_source(start) for sm, start in pairs):
            return False
        about_point = self.about_point
        if about_point is None and self.about_edge is not None:
            # The first frame reads the mobject's own box as the CPU path
            # does (nothing is pending yet, so the read costs nothing);
            # every later frame's CPU box is recomputed from the start's
            # points, which the refreshed start copy holds.
            source = self.mobject if self._program_frames == 0 else self.starting_mobject
            about_point = source.get_bounding_box_point(self.about_edge)
        self._program_frames += 1
        rot_matrix_T = rotation_matrix_transpose(angle, self.axis)
        for sm, start in pairs:
            sm.affine_program(start, rot_matrix_T, about_point, defer=mode == "gpu")
        self.mobject.refresh_bounding_box(recurse_down=True)
        # As VMobject.rotate flags the whole family's normals.
        for member in self.mobject.get_family():
            refresh = getattr(member, "refresh_unit_normal", None)
            if refresh is not None:
                refresh()
        return True


class Rotate(Rotating):
    def __init__(
        self,
        mobject: Mobject,
        angle: float = PI,
        axis: np.ndarray = OUT,
        run_time: float = 1,
        rate_func: Callable[[float], float] = smooth,
        about_edge: np.ndarray = ORIGIN,
        **kwargs
    ):
        super().__init__(
            mobject, angle, axis,
            run_time=run_time,
            rate_func=rate_func,
            about_edge=about_edge,
            **kwargs
        )
