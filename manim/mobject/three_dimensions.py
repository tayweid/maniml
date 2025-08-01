from __future__ import annotations

import math

import numpy as np

from manim.constants import BLUE, BLUE_D, BLUE_E, GREY_A, BLACK
from manim.constants import IN, ORIGIN, OUT, RIGHT
from manim.constants import PI, TAU
from manim.mobject.mobject import Mobject
from manim.mobject.types.surface import SGroup
from manim.mobject.types.surface import Surface
from manim.mobject.types.vectorized_mobject import VGroup
from manim.mobject.types.vectorized_mobject import VMobject
from manim.mobject.geometry import Polygon
from manim.mobject.geometry import Square
from manim.mobject.geometry import Squircle
from manim.utils.bezier import interpolate
from manim.utils.iterables import adjacent_pairs
from manim.utils.space_ops import compass_directions
from manim.utils.space_ops import get_norm
from manim.utils.space_ops import z_to_vector

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from typing import Tuple, TypeVar
    from manim.typing import ManimColor, Vect3, Sequence

    T = TypeVar("T", bound=Mobject)


class SurfaceMesh(VGroup):
    def __init__(
        self,
        uv_surface: Surface,
        resolution: Tuple[int, int] = (21, 11),
        stroke_width: float = 1,
        stroke_color: ManimColor = GREY_A,
        normal_nudge: float = 1e-2,
        depth_test: bool = True,
        joint_type: str = 'no_joint',
        **kwargs
    ):
        self.uv_surface = uv_surface
        self.resolution = resolution
        self.normal_nudge = normal_nudge

        super().__init__(
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            depth_test=depth_test,
            joint_type=joint_type,
            **kwargs
        )

    def init_points(self) -> None:
        uv_surface = self.uv_surface

        full_nu, full_nv = uv_surface.resolution
        part_nu, part_nv = self.resolution
        # 'indices' are treated as floats. Later, there will be
        # an interpolation between the floor and ceiling of these
        # indices
        u_indices = np.linspace(0, full_nu - 1, part_nu)
        v_indices = np.linspace(0, full_nv - 1, part_nv)

        points = uv_surface.get_points()
        normals = uv_surface.get_unit_normals()
        nudge = self.normal_nudge
        nudged_points = points + nudge * normals

        for ui in u_indices:
            path = VMobject()
            low_ui = full_nv * int(math.floor(ui))
            high_ui = full_nv * int(math.ceil(ui))
            path.set_points_smoothly(interpolate(
                nudged_points[low_ui:low_ui + full_nv],
                nudged_points[high_ui:high_ui + full_nv],
                ui % 1
            ))
            self.add(path)
        for vi in v_indices:
            path = VMobject()
            path.set_points_smoothly(interpolate(
                nudged_points[int(math.floor(vi))::full_nv],
                nudged_points[int(math.ceil(vi))::full_nv],
                vi % 1
            ))
            self.add(path)


# 3D shapes

class Sphere(Surface):
    def __init__(
        self,
        u_range: Tuple[float, float] = (0, TAU),
        v_range: Tuple[float, float] = (0, PI),
        resolution: Tuple[int, int] = (101, 51),
        radius: float = 1.0,
        true_normals: bool = True,
        clockwise=False,
        **kwargs,
    ):
        self.radius = radius
        self.clockwise = clockwise
        super().__init__(
            u_range=u_range,
            v_range=v_range,
            resolution=resolution,
            **kwargs
        )
        # Add bespoke normal specification to avoid issue at poles
        if true_normals:
            self.data['d_normal_point'] = self.data['point'] * ((radius + self.normal_nudge) / radius)

    def uv_func(self, u: float, v: float) -> np.ndarray:
        sign = -1 if self.clockwise else +1
        return self.radius * np.array([
            math.cos(sign * u) * math.sin(v),
            math.sin(sign * u) * math.sin(v),
            -math.cos(v)
        ])


class Torus(Surface):
    def __init__(
        self,
        u_range: Tuple[float, float] = (0, TAU),
        v_range: Tuple[float, float] = (0, TAU),
        r1: float = 3.0,
        r2: float = 1.0,
        **kwargs,
    ):
        self.r1 = r1
        self.r2 = r2
        super().__init__(
            u_range=u_range,
            v_range=v_range,
            **kwargs,
        )

    def uv_func(self, u: float, v: float) -> np.ndarray:
        P = np.array([math.cos(u), math.sin(u), 0])
        return (self.r1 - self.r2 * math.cos(v)) * P - self.r2 * math.sin(v) * OUT


class Cylinder(Surface):
    def __init__(
        self,
        u_range: Tuple[float, float] = (0, TAU),
        v_range: Tuple[float, float] = (-1, 1),
        resolution: Tuple[int, int] = (101, 11),
        height: float = 2,
        radius: float = 1,
        axis: Vect3 = OUT,
        **kwargs,
    ):
        self.height = height
        self.radius = radius
        self.axis = axis
        super().__init__(
            u_range=u_range,
            v_range=v_range,
            resolution=resolution,
            **kwargs
        )

    def init_points(self):
        super().init_points()
        self.scale(self.radius)
        self.set_depth(self.height, stretch=True)
        self.apply_matrix(z_to_vector(self.axis))

    def uv_func(self, u: float, v: float) -> np.ndarray:
        return np.array([np.cos(u), np.sin(u), v])


class Cone(Cylinder):
    def __init__(
        self,
        u_range: Tuple[float, float] = (0, TAU),
        v_range: Tuple[float, float] = (0, 1),
        *args,
        **kwargs,
    ):
        super().__init__(u_range=u_range, v_range=v_range, *args, **kwargs)

    def uv_func(self, u: float, v: float) -> np.ndarray:
        return np.array([(1 - v) * np.cos(u), (1 - v) * np.sin(u), v])


class Line3D(Cylinder):
    def __init__(
        self,
        start: Vect3,
        end: Vect3,
        width: float = 0.05,
        resolution: Tuple[int, int] = (21, 25),
        **kwargs
    ):
        axis = end - start
        super().__init__(
            height=get_norm(axis),
            radius=width / 2,
            axis=axis,
            resolution=resolution,
            **kwargs
        )
        self.shift((start + end) / 2)


class Disk3D(Surface):
    def __init__(
        self,
        radius: float = 1,
        u_range: Tuple[float, float] = (0, 1),
        v_range: Tuple[float, float] = (0, TAU),
        resolution: Tuple[int, int] = (2, 100),
        **kwargs
    ):
        super().__init__(
            u_range=u_range,
            v_range=v_range,
            resolution=resolution,
            **kwargs,
        )
        self.scale(radius)

    def uv_func(self, u: float, v: float) -> np.ndarray:
        return np.array([
            u * math.cos(v),
            u * math.sin(v),
            0
        ])


class Square3D(Surface):
    def __init__(
        self,
        side_length: float = 2.0,
        u_range: Tuple[float, float] = (-1, 1),
        v_range: Tuple[float, float] = (-1, 1),
        resolution: Tuple[int, int] = (2, 2),
        **kwargs,
    ):
        super().__init__(
            u_range=u_range, 
            v_range=v_range, 
            resolution=resolution, 
            **kwargs
        )
        self.scale(side_length / 2)

    def uv_func(self, u: float, v: float) -> np.ndarray:
        return np.array([u, v, 0])


class Rectangle3D(Surface):
    def __init__(
        self,
        width: float = 4.0,
        height: float = 2.0,
        u_range: Tuple[float, float] = None,
        v_range: Tuple[float, float] = None,
        resolution: Tuple[int, int] = (2, 2),
        **kwargs,
    ):
        # Set ranges based on width and height
        if u_range is None:
            u_range = (-width/2, width/2)
        if v_range is None:
            v_range = (-height/2, height/2)
            
        super().__init__(
            u_range=u_range, 
            v_range=v_range, 
            resolution=resolution, 
            **kwargs
        )

    def uv_func(self, u: float, v: float) -> np.ndarray:
        return np.array([u, v, 0])


def square_to_cube_faces(square: T) -> list[T]:
    radius = square.get_height() / 2
    square.move_to(radius * OUT)
    result = [square.copy()]
    result.extend([
        square.copy().rotate(PI / 2, axis=vect, about_point=ORIGIN)
        for vect in compass_directions(4)
    ])
    result.append(square.copy().rotate(PI, RIGHT, about_point=ORIGIN))
    return result


class Cube(SGroup):
    def __init__(
        self,
        color: ManimColor = BLUE,
        opacity: float = 1,
        shading: Tuple[float, float, float] = (0.1, 0.5, 0.1),
        square_resolution: Tuple[int, int] = (2, 2),
        side_length: float = 2,
        **kwargs,
    ):
        face = Square3D(
            resolution=square_resolution,
            side_length=side_length,
            color=color,
            opacity=opacity,
            shading=shading,
        )
        super().__init__(*square_to_cube_faces(face), **kwargs)


class Prism(Cube):
    def __init__(
        self,
        width: float = 3.0,
        height: float = 2.0,
        depth: float = 1.0,
        **kwargs
    ):
        super().__init__(**kwargs)
        for dim, value in enumerate([width, height, depth]):
            self.rescale_to_fit(value, dim, stretch=True)


class VGroup3D(VGroup):
    def __init__(
        self,
        *vmobjects: VMobject,
        depth_test: bool = True,
        shading: Tuple[float, float, float] = (0.2, 0.2, 0.2),
        joint_type: str = "no_joint",
        **kwargs
    ):
        super().__init__(*vmobjects, **kwargs)
        self.set_shading(*shading)
        self.set_joint_type(joint_type)
        if depth_test:
            self.apply_depth_test()


class VCube(VGroup3D):
    def __init__(
        self,
        side_length: float = 2.0,
        fill_color: ManimColor = BLUE_D,
        fill_opacity: float = 1,
        stroke_width: float = 0,
        **kwargs
    ):
        style = dict(
            fill_color=fill_color,
            fill_opacity=fill_opacity,
            stroke_width=stroke_width,
            **kwargs
        )
        face = Square(side_length=side_length, **style)
        super().__init__(*square_to_cube_faces(face), **style)


class VPrism(VCube):
    def __init__(
        self,
        width: float = 3.0,
        height: float = 2.0,
        depth: float = 1.0,
        **kwargs
    ):
        super().__init__(**kwargs)
        for dim, value in enumerate([width, height, depth]):
            self.rescale_to_fit(value, dim, stretch=True)


class Dodecahedron(VGroup3D):
    def __init__(
        self,
        fill_color: ManimColor = BLUE_E,
        fill_opacity: float = 1,
        stroke_color: ManimColor = BLUE_E,
        stroke_width: float = 1,
        shading: Tuple[float, float, float] = (0.2, 0.2, 0.2),
        **kwargs,
    ):
        style = dict(
            fill_color=fill_color,
            fill_opacity=fill_opacity,
            stroke_color=stroke_color,
            stroke_width=stroke_width,
            shading=shading,
            **kwargs
        )

        # Start by creating two of the pentagons, meeting
        # back to back on the positive x-axis
        phi = (1 + math.sqrt(5)) / 2
        x, y, z = np.identity(3)
        pentagon1 = Polygon(
            np.array([phi, 1 / phi, 0]),
            np.array([1, 1, 1]),
            np.array([1 / phi, 0, phi]),
            np.array([1, -1, 1]),
            np.array([phi, -1 / phi, 0]),
            **style
        )
        pentagon2 = pentagon1.copy().stretch(-1, 2, about_point=ORIGIN)
        pentagon2.reverse_points()
        x_pair = VGroup(pentagon1, pentagon2)
        z_pair = x_pair.copy().apply_matrix(np.array([z, -x, -y]).T)
        y_pair = x_pair.copy().apply_matrix(np.array([y, z, x]).T)

        pentagons = [*x_pair, *y_pair, *z_pair]
        for pentagon in list(pentagons):
            pc = pentagon.copy()
            pc.apply_function(lambda p: -p)
            pc.reverse_points()
            pentagons.append(pc)

        super().__init__(*pentagons, **style)


class Prismify(VGroup3D):
    def __init__(self, vmobject, depth=1.0, direction=IN, **kwargs):
        # At the moment, this assume stright edges
        vect = depth * direction
        pieces = [vmobject.copy()]
        points = vmobject.get_anchors()
        for p1, p2 in adjacent_pairs(points):
            wall = VMobject()
            wall.match_style(vmobject)
            wall.set_points_as_corners([p1, p2, p2 + vect, p1 + vect])
            pieces.append(wall)
        top = vmobject.copy()
        top.shift(vect)
        top.reverse_points()
        pieces.append(top)
        super().__init__(*pieces, **kwargs)


class Squircle3DSides(Surface):
    '''
    Creates the sides of a 3D squircle prism - an extruded squircle shape using Surface.
    
    Parameters
    ----------
    width : float
        Width of the bounding rectangle
    height : float
        Height of the bounding rectangle
    depth : float
        Depth of the 3D extrusion
    squareness : float
        Parameter controlling the shape (2 = ellipse, >2 = more rectangular, typically 4)
    u_range : Tuple[float, float]
        Parameter range for the perimeter (0 to 2π)
    v_range : Tuple[float, float]
        Parameter range for the height (-1 to 1)
    resolution : Tuple[int, int]
        Resolution of the surface mesh (perimeter_points, height_points)
    **kwargs
        Additional keyword arguments for Surface
        
    Examples
    --------
        squircle_3d = Squircle3D(side_length=2, height=1, squareness=4)
        squircle_3d = Squircle3D(side_length=3, height=2, squareness=3, color=BLUE)
        
    Returns
    -------
    out : Squircle3D object
        A 3D squircle prism object
    '''
    
    def __init__(
        self,
        width: float = 2.0,
        height: float = None,
        depth: float = 2.0,
        side_length: float = None,  # For backwards compatibility
        squareness: float = 4.0,
        u_range: Tuple[float, float] = (0, TAU),
        v_range: Tuple[float, float] = (-1, 1),
        resolution: Tuple[int, int] = (101, 11),
        **kwargs
    ):
        # Handle backwards compatibility
        if side_length is not None:
            width = side_length
            height = side_length
        elif height is None:
            height = width
            
        self.width = width
        self.height = height
        self.depth = depth
        self.squareness = squareness
        super().__init__(
            u_range=u_range,
            v_range=v_range,
            resolution=resolution,
            **kwargs
        )
    
    def init_points(self):
        super().init_points()
        # Scale x and y by width and height respectively
        self.apply_matrix(np.array([
            [self.width / 2, 0, 0],
            [0, self.height / 2, 0],
            [0, 0, 1]
        ]))
        # Set the depth
        self.set_depth(self.depth, stretch=True)
    
    def uv_func(self, u: float, v: float) -> np.ndarray:
        # Parametric equations for squircle in xy plane
        # For rectangular squircle, we keep the unit squircle
        # and scale in init_points
        n = self.squareness
        exponent = 2.0 / n
        
        cos_u = np.cos(u)
        sin_u = np.sin(u)
        
        x = np.sign(cos_u) * np.abs(cos_u) ** exponent
        y = np.sign(sin_u) * np.abs(sin_u) ** exponent
        z = v  # Height varies with v from -1 to 1
        
        return np.array([x, y, z])


class SquircleCap(Surface):
    '''A flat squircle surface for use as end caps'''
    def __init__(
        self,
        width: float = 2.0,
        height: float = None,
        side_length: float = None,  # For backwards compatibility
        squareness: float = 4.0,
        at_height: float = 0.0,
        u_range: Tuple[float, float] = (0, TAU),
        v_range: Tuple[float, float] = (0.01, 1),  # Start slightly away from center to avoid singularity
        resolution: Tuple[int, int] = (101, 51),
        **kwargs
    ):
        # Handle backwards compatibility
        if side_length is not None:
            width = side_length
            height = side_length
        elif height is None:
            height = width
            
        self.width = width
        self.height = height
        self.squareness = squareness
        self.at_height = at_height
        super().__init__(
            u_range=u_range,
            v_range=v_range,
            resolution=resolution,
            **kwargs
        )
    
    def init_points(self):
        super().init_points()
        # Scale x and y by width and height respectively
        self.apply_matrix(np.array([
            [self.width / 2, 0, 0],
            [0, self.height / 2, 0],
            [0, 0, 1]
        ]))
        self.shift(self.at_height * OUT)
    
    def uv_func(self, u: float, v: float) -> np.ndarray:
        # Create a filled disk using the squircle perimeter
        n = self.squareness
        exponent = 2.0 / n
        
        cos_u = np.cos(u)
        sin_u = np.sin(u)
        
        # Outer edge at v=1, center at v=0
        x = v * np.sign(cos_u) * np.abs(cos_u) ** exponent
        y = v * np.sign(sin_u) * np.abs(sin_u) ** exponent
        z = 0  # Flat surface
        
        return np.array([x, y, z])


class Squircle3D(SGroup):
    '''
    Creates a complete 3D squircle prism with sides and end caps.
    
    Parameters
    ----------
    width : float
        Width of the bounding rectangle
    height : float
        Height of the bounding rectangle (base shape height, not extrusion depth)
    depth : float
        Depth of the 3D extrusion (how tall the 3D shape is)
    side_length : float
        Edge length of the bounding square (for backwards compatibility)
    squareness : float
        Parameter controlling the shape (2 = ellipse, >2 = more rectangular, typically 4)
    **kwargs
        Additional keyword arguments for Surface
        
    Examples
    --------
        squircle_3d = Squircle3D(side_length=2, depth=1, squareness=4)
        squircle_3d = Squircle3D(width=3, height=2, depth=1, squareness=3, color=BLUE)
    '''
    
    def __init__(
        self,
        width: float = 2.0,
        height: float = None,
        depth: float = 2.0,
        side_length: float = None,  # For backwards compatibility
        squareness: float = 4.0,
        color: ManimColor = BLUE,
        opacity: float = 1,
        shading: Tuple[float, float, float] = (0.1, 0.5, 0.1),
        resolution: Tuple[int, int] = (101, 11),
        **kwargs
    ):
        # Handle backwards compatibility
        if side_length is not None:
            width = side_length
            height = side_length
            if 'height' in kwargs:
                # Legacy parameter name for depth
                depth = kwargs.pop('height')
        elif height is None:
            height = width
            
        # Remove our custom parameters from kwargs before passing to parent
        kwargs.pop('width', None)
        kwargs.pop('height', None)
        kwargs.pop('depth', None)
        kwargs.pop('side_length', None)
        kwargs.pop('squareness', None)
            
        # Create the sides
        sides = Squircle3DSides(
            width=width,
            height=height,
            depth=depth,
            squareness=squareness,
            color=color,
            opacity=opacity,
            shading=shading,
            resolution=resolution,
        )
        
        # Create top and bottom caps
        bottom_cap = SquircleCap(
            width=width,
            height=height,
            squareness=squareness,
            at_height=-depth/2,
            color=color,
            opacity=opacity,
            shading=shading,
        )
        
        top_cap = SquircleCap(
            width=width,
            height=height,
            squareness=squareness,
            at_height=depth/2,
            color=color,
            opacity=opacity,
            shading=shading,
        )
        
        # Combine all pieces
        super().__init__(
            sides,
            bottom_cap,
            top_cap,
            **kwargs
        )
