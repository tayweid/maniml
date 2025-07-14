"""
Coordinate systems with CE compatibility.
"""

import manim
from manim.mobject.coordinate_systems import (
    Axes as GLAxes,
    ThreeDAxes as GLThreeDAxes,
    NumberPlane as GLNumberPlane,
)
from manim.constants import *
from manim.mobject.geometry import DashedLine
from manim.mobject.types.vectorized_mobject import VGroup
import warnings


class Axes(GLAxes):
    """CE-compatible Axes."""
    
    def __init__(
        self,
        x_range=None,
        y_range=None,
        x_length=None,
        y_length=None,
        axis_config=None,
        x_axis_config=None,
        y_axis_config=None,
        tips=True,
        **kwargs
    ):
        # CE uses different parameter structure
        if x_range is None:
            x_range = [-8, 8, 1]
        if y_range is None:
            y_range = [-4, 4, 1]
            
        # Convert CE ranges [min, max, step] to GL parameters
        if len(x_range) >= 2:
            x_min, x_max = x_range[0], x_range[1]
            x_step = x_range[2] if len(x_range) > 2 else 1
        else:
            x_min, x_max, x_step = -8, 8, 1
            
        if len(y_range) >= 2:
            y_min, y_max = y_range[0], y_range[1]
            y_step = y_range[2] if len(y_range) > 2 else 1
        else:
            y_min, y_max, y_step = -4, 4, 1
        
        # GL uses x_range and y_range directly!
        gl_kwargs = kwargs.copy()
        
        # Handle tips parameter (CE uses 'tips', GL might use something else)
        if 'tips' in gl_kwargs:
            gl_kwargs.pop('tips')
            if tips:
                # GL uses axis_config for tips
                if axis_config is None:
                    axis_config = {}
                axis_config['include_tip'] = tips
        
        # Handle axis configs - extract CE-specific parameters
        if axis_config:
            axis_config = axis_config.copy()
            # Remove CE-specific params that GL doesn't understand
            axis_config.pop('numbers_to_include', None)
            axis_config.pop('tip_width', None)
            axis_config.pop('tip_height', None)
            axis_config.pop('tip_shape', None)
            gl_kwargs['axis_config'] = axis_config
            
        if x_axis_config:
            x_axis_config = x_axis_config.copy()
            # Extract and store numbers_to_include
            self.x_numbers_to_include = x_axis_config.pop('numbers_to_include', None)
            # Remove CE-specific params
            x_axis_config.pop('numbers_with_elongated_ticks', None)
            x_axis_config.pop('longer_tick_multiple', None)
            gl_kwargs['x_axis_config'] = x_axis_config
        else:
            self.x_numbers_to_include = None
            
        if y_axis_config:
            y_axis_config = y_axis_config.copy()
            # Extract and store numbers_to_include
            self.y_numbers_to_include = y_axis_config.pop('numbers_to_include', None)
            # Remove CE-specific params
            y_axis_config.pop('numbers_with_elongated_ticks', None)
            y_axis_config.pop('longer_tick_multiple', None)
            gl_kwargs['y_axis_config'] = y_axis_config
        else:
            self.y_numbers_to_include = None
        
        # Handle lengths
        if x_length is not None:
            gl_kwargs['width'] = x_length
        if y_length is not None:
            gl_kwargs['height'] = y_length
        
        # Initialize GL version with proper ranges
        super().__init__(x_range=(x_min, x_max, x_step), 
                        y_range=(y_min, y_max, y_step), 
                        **gl_kwargs)
        
        # Store CE-compatible attributes
        self.x_range = x_range
        self.y_range = y_range
        
        # Add numbers if specified
        if hasattr(self, 'x_numbers_to_include') and self.x_numbers_to_include is not None:
            self.x_axis.add_numbers(self.x_numbers_to_include)
        if hasattr(self, 'y_numbers_to_include') and self.y_numbers_to_include is not None:
            self.y_axis.add_numbers(self.y_numbers_to_include)
    
    def coords_to_point(self, x, y, z=0):
        """CE compatibility method."""
        # Don't call c2p because it calls coords_to_point!
        # Call the parent's coords_to_point directly
        return super().coords_to_point(x, y, z)
    
    def point_to_coords(self, point):
        """CE compatibility method."""
        # Call parent's point_to_coords directly to avoid recursion
        return super().point_to_coords(point)
    
    def plot(self, function, x_range=None, **kwargs):
        """CE compatibility - plot a function."""
        # GL uses get_graph with x_range parameter
        if x_range is None:
            x_range = self.x_range
            
        # GL expects x_range to be a sequence, not individual min/max
        graph = self.get_graph(function, x_range=x_range, **kwargs)
        
        # Ensure graph has x_range attribute for area calculations
        # GL expects x_range to be (min, max) tuple for area calculations
        if not hasattr(graph, 'x_range'):
            if len(x_range) >= 2:
                graph.x_range = (x_range[0], x_range[1])
            else:
                graph.x_range = x_range
            
        return graph
    
    def plot_parametric_curve(self, function, t_range=None, **kwargs):
        """CE compatibility - plot a parametric curve."""
        # GL uses get_parametric_curve with t_range parameter
        if t_range is None:
            t_range = [0, 1, 0.01]
        elif len(t_range) == 2:
            # CE allows 2-element t_range, GL needs 3 (min, max, step)
            t_range = [t_range[0], t_range[1], 0.01]
            
        # GL expects t_range as a list/tuple with 3 elements
        return self.get_parametric_curve(function, t_range=t_range, **kwargs)
    
    def get_axis_labels(self, x_label=None, y_label=None, **kwargs):
        """CE compatibility - get axis labels at positive ends."""
        # Create labels using our properly positioned methods
        labels = VGroup()
        
        if x_label is not None:
            x_label_mob = self.get_x_axis_label(x_label, **kwargs.get('x_label_kwargs', {}))
            labels.add(x_label_mob)
            
        if y_label is not None:
            y_label_mob = self.get_y_axis_label(y_label, **kwargs.get('y_label_kwargs', {}))
            labels.add(y_label_mob)
            
        return labels
    
    def get_graph(self, function, x_range=None, **kwargs):
        """CE-compatible get_graph."""
        # GL expects x_range parameter, not x_min/x_max
        graph = super().get_graph(function, x_range=x_range, **kwargs)
        
        # Ensure graph has x_range attribute as 2-tuple for area calculations
        if hasattr(graph, 'x_range') and len(graph.x_range) > 2:
            graph.x_range = (graph.x_range[0], graph.x_range[1])
            
        return graph
    
    def get_area(self, graph, x_range=None, color=None, opacity=None, **kwargs):
        """CE compatibility - get area under graph."""
        # CE uses get_area, GL uses get_area_under_graph
        # CE uses color/opacity, GL uses fill_color/fill_opacity
        if color is not None:
            kwargs['fill_color'] = color
        if opacity is not None:
            kwargs['fill_opacity'] = opacity
        return self.get_area_under_graph(graph, x_range=x_range, **kwargs)
    
    def get_graph_label(self, graph, label, x_val=None, direction=UP, buff=SMALL_BUFF, **kwargs):
        """CE compatibility - get label for graph."""
        # GL uses get_graph_label with x parameter, not x_val
        if x_val is not None:
            kwargs['x'] = x_val
        return super().get_graph_label(graph, label, direction=direction, buff=buff, **kwargs)
    
    def get_riemann_rectangles(self, graph, x_range=None, n_iterations=1, dx=None, **kwargs):
        """CE compatibility - simplified version."""
        warnings.warn(
            "maniml: get_riemann_rectangles simplified. May not match CE exactly.",
            UserWarning
        )
        
        # CE uses n_iterations, GL uses dx
        if dx is None and n_iterations:
            if x_range is None:
                x_range = [self.x_range[0], self.x_range[1]]
            dx = (x_range[1] - x_range[0]) / n_iterations
        
        # Map CE kwargs to GL kwargs
        gl_kwargs = kwargs.copy()
        gl_kwargs.pop('n_iterations', None)
        
        # Map color to colors
        if 'color' in gl_kwargs:
            gl_kwargs['colors'] = [gl_kwargs.pop('color')]
        
        # Check if GL has this method
        if hasattr(super(), 'get_riemann_rectangles'):
            return super().get_riemann_rectangles(graph, x_range, dx, **gl_kwargs)
        else:
            from manim.mobject.types.vectorized_mobject import VGroup
            from manim.mobject.geometry import Rectangle
            
            rectangles = VGroup()
            if x_range is None:
                x_range = [self.x_min, self.x_max]
            
            x_min, x_max = x_range[0], x_range[1]
            x = x_min
            
            while x < x_max:
                try:
                    y = graph.function(x)
                    rect = Rectangle(
                        width=dx * self.get_x_unit_size(),
                        height=abs(y) * self.get_y_unit_size(),
                        **kwargs
                    )
                    rect.move_to(self.c2p(x + dx/2, y/2))
                    rectangles.add(rect)
                except:
                    pass
                x += dx
                
            return rectangles
    
    def get_x_axis_label(self, label, edge=RIGHT, direction=DOWN, buff=None, **kwargs):
        """CE compatibility - get x-axis label past positive end."""
        from manim.mobject.svg.tex_mobject import Tex
        
        # Adaptive buffer - larger if axis has tips, smaller if not
        if buff is None:
            # Check if x_axis has tips
            has_tip = getattr(self.x_axis, 'has_tip', lambda: True)()
            buff = MED_LARGE_BUFF if has_tip else MED_SMALL_BUFF
        
        # Create the label
        label_mob = Tex(label, **kwargs)
        
        # Position it past the right end of x-axis, on the axis line
        x_max_point = self.coords_to_point(self.x_range[1], 0)
        label_mob.next_to(x_max_point, RIGHT, buff=buff)
        
        return label_mob
    
    def get_y_axis_label(self, label, edge=UP, direction=RIGHT, buff=None, **kwargs):
        """CE compatibility - get y-axis label past positive end."""
        from manim.mobject.svg.tex_mobject import Tex
        
        # Adaptive buffer - larger if axis has tips, smaller if not
        if buff is None:
            # Check if y_axis has tips
            has_tip = getattr(self.y_axis, 'has_tip', lambda: True)()
            buff = MED_LARGE_BUFF if has_tip else MED_SMALL_BUFF
        
        # Create the label
        label_mob = Tex(label, **kwargs)
        
        # Position it past the top of y-axis, on the axis line
        y_max_point = self.coords_to_point(0, self.y_range[1])
        label_mob.next_to(y_max_point, UP, buff=buff)
        
        return label_mob
    
    def get_vertical_line(self, point, line_func=DashedLine, **kwargs):
        """Get a vertical line at a point."""
        x_val = self.point_to_coords(point)[0]
        return line_func(
            self.coords_to_point(x_val, self.y_range[0]),
            self.coords_to_point(x_val, self.y_range[1]),
            **kwargs
        )
    
    def input_to_graph_point(self, x, graph):
        """Get point on graph at given x value."""
        # GL already has this method, just call it
        return super().input_to_graph_point(x, graph)
    
    def add_coordinates(self, x_values=None, y_values=None):
        """Add coordinate labels to axes."""
        if x_values is None and hasattr(self, 'x_numbers_to_include'):
            x_values = self.x_numbers_to_include
        if y_values is None and hasattr(self, 'y_numbers_to_include'):
            y_values = self.y_numbers_to_include
            
        if x_values:
            self.x_axis.add_numbers(x_values)
        if y_values:
            self.y_axis.add_numbers(y_values)


class ThreeDAxes(GLThreeDAxes):
    """CE-compatible ThreeDAxes."""
    
    def __init__(
        self,
        x_range=None,
        y_range=None,
        z_range=None,
        x_length=None,
        y_length=None,
        z_length=None,
        **kwargs
    ):
        # Default ranges
        if x_range is None:
            x_range = [-6, 6, 1]
        if y_range is None:
            y_range = [-5, 5, 1]
        if z_range is None:
            z_range = [-4, 4, 1]
            
        # Pass ranges and other params to GL
        gl_kwargs = kwargs.copy()
        
        # Remove CE-specific params that GL doesn't understand
        ce_specific = ['x_min', 'x_max', 'y_min', 'y_max', 'z_min', 'z_max']
        for param in ce_specific:
            gl_kwargs.pop(param, None)
        
        # GL expects ranges as positional arguments
        super().__init__(x_range, y_range, z_range, **gl_kwargs)


class NumberPlane(GLNumberPlane):
    """CE-compatible NumberPlane."""
    
    def __init__(
        self,
        x_range=None,
        y_range=None,
        x_length=None,
        y_length=None,
        background_line_style=None,
        faded_line_style=None,
        faded_line_ratio=1,
        **kwargs
    ):
        # Default ranges
        if x_range is None:
            x_range = [-8, 8, 1]
        if y_range is None:
            y_range = [-4, 4, 1]
            
        # Convert to GL format - GL uses x_range/y_range directly
        gl_kwargs = {}
        
        if background_line_style:
            warnings.warn(
                "maniml: background_line_style not supported. Using defaults.",
                UserWarning
            )
            
        gl_kwargs.update(kwargs)
        
        # GL expects x_range and y_range as parameters
        super().__init__(x_range=x_range, y_range=y_range, **gl_kwargs)


class PolarPlane(Axes):
    """CE-compatible PolarPlane - simplified version."""
    
    def __init__(
        self,
        radius_max=4,
        size=6,
        radius_step=1,
        azimuth_step=PI/12,
        azimuth_units=None,
        azimuth_compact_fraction=None,
        azimuth_offset=None,
        **kwargs
    ):
        warnings.warn(
            "maniml: PolarPlane is simplified. Using regular Axes.",
            UserWarning
        )
        
        # Remove polar-specific parameters that Axes doesn't understand
        kwargs.pop('azimuth_units', None)
        kwargs.pop('azimuth_compact_fraction', None)
        kwargs.pop('azimuth_offset', None)
        kwargs.pop('size', None)
        
        # Approximate with regular axes
        super().__init__(
            x_range=[-radius_max, radius_max, radius_step],
            y_range=[-radius_max, radius_max, radius_step],
            **kwargs
        )
        
        # Add circular grid lines if possible
        from manim.mobject.geometry import Circle
        from manim.mobject.types.vectorized_mobject import VGroup
        
        circles = VGroup()
        for r in range(1, int(radius_max) + 1):
            circles.add(Circle(radius=r, color=GREY, stroke_width=1))
        
        self.add(circles)
        
    def plot_polar_graph(self, func, theta_range=None, **kwargs):
        """Plot a function in polar coordinates."""
        if theta_range is None:
            theta_range = [0, 2*PI, 0.01]
        elif len(theta_range) == 2:
            theta_range = [theta_range[0], theta_range[1], 0.01]
            
        # Convert polar to cartesian
        def polar_to_cart(t):
            r = func(t)
            return np.array([r * np.cos(t), r * np.sin(t), 0])
            
        return self.plot_parametric_curve(polar_to_cart, t_range=theta_range, **kwargs)