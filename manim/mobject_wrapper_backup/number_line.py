"""
NumberLine and related objects with CE compatibility.
"""

import manim
from manim.mobject.number_line import NumberLine as GLNumberLine
from manim.constants import *
import warnings


class NumberLine(GLNumberLine):
    """CE-compatible NumberLine."""
    
    def __init__(
        self,
        x_range=None,
        length=None,
        unit_size=1,
        include_ticks=True,
        tick_size=0.1,
        tick_frequency=1,
        numbers_with_elongated_ticks=None,
        longer_tick_multiple=2,
        include_numbers=False,
        numbers_to_show=None,
        numbers_to_exclude=None,
        label_direction=DOWN,
        font_size=36,
        include_tip=False,
        tip_width=0.25,
        tip_height=0.25,
        decimal_number_config=None,
        **kwargs
    ):
        # CE uses different parameter structure
        # Convert x_range from CE format [min, max, step] to GL format
        if x_range is None:
            x_range = [-8, 8, 1]
        
        if len(x_range) == 3:
            x_min, x_max, x_step = x_range
        else:
            x_min, x_max = x_range[0], x_range[1]
            x_step = 1
            
        # GL parameter adaptation
        gl_kwargs = {
            'x_min': x_min,
            'x_max': x_max,
            'unit_size': unit_size,
            'include_ticks': include_ticks,
            'tick_size': tick_size,
            'include_numbers': include_numbers,
            'label_direction': label_direction,
            'include_tip': include_tip,
        }
        
        # Merge with other kwargs
        gl_kwargs.update(kwargs)
        
        # Handle length
        if length is not None:
            # Calculate unit_size from length
            gl_kwargs['unit_size'] = length / (x_max - x_min)
            
        # Initialize GL version
        super().__init__(**gl_kwargs)
        
        # Apply CE-specific features
        if numbers_to_show is not None:
            self.add_numbers(numbers_to_show)
        
        if decimal_number_config is not None:
            warnings.warn(
                "maniml: decimal_number_config not fully supported.",
                UserWarning
            )
    
    def get_number_mobject(self, x, **kwargs):
        """CE compatibility method."""
        # GL uses different method name
        if hasattr(super(), 'get_number_mobject'):
            return super().get_number_mobject(x, **kwargs)
        else:
            # Create number manually
            from manim.mobject.number_line import DecimalNumber
            return DecimalNumber(x, **kwargs)
    
    def n2p(self, x):
        """CE compatibility: number_to_point."""
        return self.number_to_point(x)
    
    def p2n(self, point):
        """CE compatibility: point_to_number."""
        return self.point_to_number(point)


class UnitInterval(NumberLine):
    """CE-compatible UnitInterval - a NumberLine from 0 to 1."""
    
    def __init__(self, unit_size=10, include_ticks=True, tick_frequency=0.1,
                 include_numbers=True, **kwargs):
        super().__init__(
            x_range=[0, 1, tick_frequency],
            unit_size=unit_size,
            include_ticks=include_ticks,
            tick_frequency=tick_frequency,
            include_numbers=include_numbers,
            **kwargs
        )