from __future__ import annotations

import numpy as np

from maniml.animation.animation import Animation
from maniml.animation.transform import Transform
from maniml.constants import ORIGIN
from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.mobject.mobject import Group
from maniml.utils.bezier import interpolate
from maniml.utils.rate_functions import linear
from maniml.utils.rate_functions import there_and_back

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Callable
    from maniml.mobject.mobject import Mobject
    from maniml.scene.scene import Scene
    from maniml.typing import Vect3


class Fade(Transform):
    def __init__(
        self,
        *mobjects: Mobject,
        shift: np.ndarray = ORIGIN,
        scale: float = 1,
        **kwargs
    ):
        # CE compatibility: several mobjects fade together as a group
        mobject = mobjects[0] if len(mobjects) == 1 else Group(*mobjects)
        self.shift_vect = shift
        self.scale_factor = scale
        super().__init__(mobject, **kwargs)


class FadeIn(Fade):
    def create_target(self) -> Mobject:
        return self.mobject.copy()

    def create_starting_mobject(self) -> Mobject:
        start = super().create_starting_mobject()
        start.set_opacity(0)
        start.scale(1.0 / self.scale_factor)
        start.shift(-self.shift_vect)
        return start


class FadeOut(Fade):
    def __init__(
        self,
        *mobjects: Mobject,
        shift: Vect3 = ORIGIN,
        remover: bool = True,
        final_alpha_value: float = 0.0,  # Put it back in original state when done,
        **kwargs
    ):
        super().__init__(
            *mobjects,
            shift=shift,
            remover=remover,
            final_alpha_value=final_alpha_value,
            **kwargs
        )

    def create_target(self) -> Mobject:
        result = self.mobject.copy()
        result.set_opacity(0)
        result.shift(self.shift_vect)
        result.scale(self.scale_factor)
        return result


class FadeInFromPoint(FadeIn):
    def __init__(self, mobject: Mobject, point: Vect3, **kwargs):
        super().__init__(
            mobject,
            shift=mobject.get_center() - point,
            scale=np.inf,
            **kwargs,
        )


class FadeOutToPoint(FadeOut):
    def __init__(self, mobject: Mobject, point: Vect3, **kwargs):
        super().__init__(
            mobject,
            shift=point - mobject.get_center(),
            scale=0,
            **kwargs,
        )


class FadeTransform(Transform):
    def __init__(
        self,
        mobject: Mobject,
        target_mobject: Mobject,
        stretch: bool = True,
        dim_to_match: int = 1,
        **kwargs
    ):
        self.to_add_on_completion = target_mobject
        self.stretch = stretch
        self.dim_to_match = dim_to_match

        mobject.save_state()
        super().__init__(Group(mobject, target_mobject.copy()), **kwargs)

    def begin(self) -> None:
        self.ending_mobject = self.mobject.copy()
        Animation.begin(self)
        # Both 'start' and 'end' consists of the source and target mobjects.
        # At the start, the traget should be faded replacing the source,
        # and at the end it should be the other way around.
        start, end = self.starting_mobject, self.ending_mobject
        for m0, m1 in ((start[1], start[0]), (end[0], end[1])):
            self.ghost_to(m0, m1)

    def ghost_to(self, source: Mobject, target: Mobject) -> None:
        source.replace(target, stretch=self.stretch, dim_to_match=self.dim_to_match)
        source.set_uniform(**target.get_uniforms())
        source.set_opacity(0)

    def get_all_mobjects(self) -> list[Mobject]:
        return [
            self.mobject,
            self.starting_mobject,
            self.ending_mobject,
        ]

    def get_all_families_zipped(self) -> zip[tuple[Mobject]]:
        return Animation.get_all_families_zipped(self)

    def clean_up_from_scene(self, scene: Scene) -> None:
        Animation.clean_up_from_scene(self, scene)
        scene.remove(self.mobject)
        self.mobject[0].restore()
        if not self.remover:
            scene.add(self.to_add_on_completion)


class FadeTransformPieces(FadeTransform):
    def begin(self) -> None:
        self.mobject[0].align_family(self.mobject[1])
        super().begin()

    def ghost_to(self, source: Mobject, target: Mobject) -> None:
        for sm0, sm1 in zip(source.get_family(), target.get_family()):
            super().ghost_to(sm0, sm1)


class VFadeIn(Animation):
    """
    VFadeIn and VFadeOut only work for VMobjects,
    """
    def __init__(self, vmobject: VMobject, suspend_mobject_updating: bool = False, **kwargs):
        super().__init__(
            vmobject,
            suspend_mobject_updating=suspend_mobject_updating,
            **kwargs
        )

    def interpolate_submobject(
        self,
        submob: VMobject,
        start: VMobject,
        alpha: float
    ) -> None:
        submob.set_stroke(
            opacity=interpolate(0, start.get_stroke_opacity(), alpha)
        )
        submob.set_fill(
            opacity=interpolate(0, start.get_fill_opacity(), alpha)
        )


class VFadeOut(VFadeIn):
    def __init__(
        self,
        vmobject: VMobject,
        remover: bool = True,
        final_alpha_value: float = 0.0,
        **kwargs
    ):
        super().__init__(
            vmobject,
            remover=remover,
            final_alpha_value=final_alpha_value,
            **kwargs
        )

    def interpolate_submobject(
        self,
        submob: VMobject,
        start: VMobject,
        alpha: float
    ) -> None:
        super().interpolate_submobject(submob, start, 1 - alpha)


class VFadeInThenOut(VFadeIn):
    def __init__(
        self,
        vmobject: VMobject,
        rate_func: Callable[[float], float] = there_and_back,
        remover: bool = True,
        final_alpha_value: float = 0.5,
        **kwargs
    ):
        super().__init__(
            vmobject,
            rate_func=rate_func,
            remover=remover,
            final_alpha_value=final_alpha_value,
            **kwargs
        )

def _flicker_schedule(flickers: int, seed: int) -> list[tuple[float, float]]:
    """Brightness steps for FlickerIn: (start_alpha, level) pairs, level
    holding until the next pair. Dark at 0, a sputter per slot across the
    first ~60% of the run, then steadily lit. Deterministic for a given
    seed, so a checkpoint replay sputters exactly like the first run."""
    import random

    rng = random.Random(seed)
    settle = 0.62
    segments = [(0.0, 0.0)]
    if flickers > 0:
        slot = settle / flickers
        for i in range(flickers):
            t0 = i * slot
            on_at = t0 + rng.uniform(0.15, 0.45) * slot
            off_at = t0 + rng.uniform(0.6, 0.9) * slot
            segments.append((on_at, rng.uniform(0.3, 1.0)))
            segments.append((off_at, 0.0))
    segments.append((settle, 1.0))
    return segments


class FlickerIn(FadeIn):
    """Switch a mobject on like an old tube light: dark, a few irregular
    sputters at varying brightness, then steadily lit — the "flicker on"
    preset familiar from video editors.

    The sputter pattern is a step function laid over FadeIn's dark-to-lit
    interpolation, so it works on anything FadeIn does. ``flickers`` sets
    how many sputters, ``seed`` picks a different pattern; the default is
    deterministic. A ``lag_ratio`` staggers the sputters across
    submobjects (letters of a Text light up out of step).
    """

    def __init__(
        self,
        *mobjects: Mobject,
        flickers: int = 4,
        seed: int = 0,
        rate_func: Callable[[float], float] = linear,
        **kwargs
    ):
        self.schedule = _flicker_schedule(flickers, seed)
        super().__init__(*mobjects, rate_func=rate_func, **kwargs)

    def get_sub_alpha(self, alpha: float, index: int, num_submobjects: int) -> float:
        return self._level_at(super().get_sub_alpha(alpha, index, num_submobjects))

    def _level_at(self, alpha: float) -> float:
        level = 0.0
        for start, brightness in self.schedule:
            if alpha < start:
                break
            level = brightness
        return level


# CE Compatibility Mappings (simplified)
FadeOutAndShift = FadeOut  # Simplified CE compatibility
FadeInFromLarge = FadeIn  # Simplified CE compatibility
