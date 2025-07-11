"""Animations for changing numbers."""

from __future__ import annotations

__all__ = ["ChangingDecimal", "ChangeDecimalToValue"]

import typing
from typing import TYPE_CHECKING, Any, Callable

from manim.renderer.opengl.animation.animation import Animation
from manim.renderer.opengl.utils.bezier import interpolate

if TYPE_CHECKING:
    from manim.renderer.opengl.mobject.numbers import DecimalNumber


class ChangingDecimal(Animation):
    """Animation that changes a DecimalNumber dynamically using a function.
    
    Parameters
    ----------
    decimal_mob
        The DecimalNumber mobject to animate.
    number_update_func
        A function that takes the animation progress (0 to 1) and returns
        the number value to display.
    suspend_mobject_updating
        Whether to suspend other mobject updates during the animation.
    
    Examples
    --------
    .. manim:: ChangingDecimalExample
    
        class ChangingDecimalExample(Scene):
            def construct(self):
                number = DecimalNumber(0).scale(2)
                self.add(number)
                
                # Animate to show values following a sine wave
                self.play(ChangingDecimal(
                    number,
                    lambda t: np.sin(t * TAU),
                    run_time=3
                ))
    """
    
    def __init__(
        self,
        decimal_mob: DecimalNumber,
        number_update_func: Callable[[float], float],
        suspend_mobject_updating: bool = False,
        **kwargs: Any,
    ) -> None:
        self.check_validity_of_input(decimal_mob)
        self.number_update_func = number_update_func
        super().__init__(
            decimal_mob, suspend_mobject_updating=suspend_mobject_updating, **kwargs
        )

    def check_validity_of_input(self, decimal_mob: DecimalNumber) -> None:
        if not hasattr(decimal_mob, 'set_value'):
            raise TypeError("ChangingDecimal requires a DecimalNumber with set_value method")

    def interpolate_mobject(self, alpha: float) -> None:
        self.mobject.set_value(self.number_update_func(self.rate_func(alpha)))


class ChangeDecimalToValue(ChangingDecimal):
    """Animation that changes a DecimalNumber to a specific target value.
    
    Parameters
    ----------
    decimal_mob
        The DecimalNumber mobject to animate.
    target_number
        The target number to animate to.
    
    Examples
    --------
    .. manim:: ChangeDecimalToValueExample
    
        class ChangeDecimalToValueExample(Scene):
            def construct(self):
                number = DecimalNumber(0).scale(2)
                self.add(number)
                
                # Animate from 0 to 100
                self.play(ChangeDecimalToValue(number, 100), run_time=2)
                self.wait()
                
                # Animate from 100 to -50
                self.play(ChangeDecimalToValue(number, -50), run_time=2)
    """
    
    def __init__(
        self, decimal_mob: DecimalNumber, target_number: float, **kwargs: Any
    ) -> None:
        # Get the starting number
        if hasattr(decimal_mob, 'number'):
            start_number = decimal_mob.number
        elif hasattr(decimal_mob, 'get_value'):
            start_number = decimal_mob.get_value()
        else:
            start_number = 0
            
        super().__init__(
            decimal_mob, lambda a: interpolate(start_number, target_number, a), **kwargs
        )