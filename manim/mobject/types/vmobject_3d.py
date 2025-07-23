"""
VMobject3D - A Surface-based implementation of VMobjects for proper 3D depth rendering
"""

from __future__ import annotations

import numpy as np
import re
from typing import TYPE_CHECKING

from manim.mobject.types.surface import Surface
from manim.mobject.types.vectorized_mobject import VMobject
from manim.utils.space_ops import earclip_triangulation
from manim.utils.bezier import bezier
from manim.constants import TAU, PI, ORIGIN, OUT

if TYPE_CHECKING:
    from manim.typing import ManimColor, Vect3Array


class VMobject3D(Surface):
    """
    A 3D-rendered version of VMobject that uses triangulated fill
    for proper depth testing in 3D scenes.
    """
    
    def __init__(
        self,
        vmobject: VMobject | None = None,
        resolution: int = 50,
        color: ManimColor | None = None,
        opacity: float = 1.0,
        **kwargs
    ):
        # If no vmobject provided, we'll initialize empty
        self.source_vmobject = vmobject
        self.polygon_resolution = resolution
        
        # Extract color from source if not specified
        if vmobject is not None:
            if color is None:
                color = vmobject.get_fill_color()
            # Note: we now use the default opacity=1.0 unless explicitly overridden
        
        # Initialize as Surface with extracted properties
        super().__init__(
            color=color,
            opacity=opacity,
            resolution=(1, 1),  # We'll set our own points
            **kwargs
        )
        
        # Generate triangulated mesh from vmobject
        if vmobject is not None:
            self.init_from_vmobject(vmobject)
    
    def init_from_vmobject(self, vmobject: VMobject):
        """Extract path data from VMobject and triangulate"""
        # print(f"\n[VMobject3D] Initializing from {type(vmobject).__name__}")
        # print(f"[VMobject3D] VMobject has {len(vmobject.get_points())} points")
        # print(f"[VMobject3D] VMobject has {len(vmobject.get_subpaths())} subpaths")
        
        # Get all the points from the vmobject's bezier curves
        polygon_points_list = self.get_polygon_from_vmobject(vmobject)
        
        # print(f"[VMobject3D] Got {len(polygon_points_list)} polygon rings")
        if len(polygon_points_list) == 0:
            # print("[VMobject3D] No polygon points found!")
            pass
            return
        
        # Flatten the list and get ring ends
        all_points = []
        ring_ends = []
        
        for ring_points in polygon_points_list:
            all_points.extend(ring_points)
            ring_ends.append(len(all_points))
        
        if len(all_points) == 0:
            return
            
        polygon_points = np.array(all_points)
        
        # Triangulate the polygon
        try:
            triangle_indices = earclip_triangulation(polygon_points[:, :2], ring_ends)
        except Exception as e:
            # print(f"Triangulation failed: {e}")
            # Fallback: create a simple triangulated shape
            self.init_simple_triangulation(polygon_points)
            return
        
        # Create the triangulated surface data
        self.set_points_from_triangulation(polygon_points, triangle_indices)
    
    def get_polygon_from_vmobject(self, vmobject: VMobject) -> list[list[np.ndarray]]:
        """Convert VMobject bezier curves to polygon points, returning a list of rings"""
        all_rings = []
        
        # Check if this VMobject has submobjects (like Text which has letters)
        if len(vmobject.submobjects) > 0:
            # print(f"[VMobject3D] Processing {len(vmobject.submobjects)} submobjects")
            for submob in vmobject.get_family():
                if submob is vmobject:
                    continue  # Skip the parent
                if len(submob.get_points()) > 0:
                    sub_rings = self.get_polygon_from_single_vmobject(submob)
                    all_rings.extend(sub_rings)
        else:
            # Process this VMobject directly
            all_rings = self.get_polygon_from_single_vmobject(vmobject)
            
        return all_rings
    
    def get_polygon_from_single_vmobject(self, vmobject: VMobject) -> list[list[np.ndarray]]:
        """Convert a single VMobject's bezier curves to polygon points"""
        all_rings = []
        
        subpaths = vmobject.get_subpaths()
        # print(f"[VMobject3D] Single VMobject has {len(subpaths)} subpaths")
        for subpath in subpaths:
            if len(subpath) < 3:
                continue
                
            # Each subpath is made of quadratic bezier segments
            # subpath has format: [anchor1, handle1, anchor2, handle2, anchor3, ...]
            polygon_points = []
            
            for i in range(0, len(subpath) - 1, 2):
                if i + 2 >= len(subpath):
                    break
                    
                # Get the three control points for this bezier segment
                p0 = subpath[i]
                p1 = subpath[i + 1]
                p2 = subpath[i + 2]
                
                # Sample the bezier curve
                n_samples = max(3, self.polygon_resolution // max(1, (len(subpath) // 2)))
                bezier_func = bezier([p0, p1, p2])
                for t in np.linspace(0, 1, n_samples, endpoint=(i == len(subpath) - 3)):
                    point = bezier_func(t)
                    polygon_points.append(point)
            
            if len(polygon_points) > 0:
                all_rings.append(polygon_points)
        
        return all_rings
    
    def set_points_from_triangulation(self, vertices: np.ndarray, triangle_indices: list[int]):
        """Set up Surface data from triangulated vertices"""
        if len(triangle_indices) == 0:
            # print("[VMobject3D] No triangle indices!")
            return
            
        # print(f"[VMobject3D] Setting up {len(vertices)} vertices and {len(triangle_indices)//3} triangles")
        
        # Store the vertices
        self.set_points(vertices)
        
        # Convert triangle indices to numpy array
        self.triangle_indices = np.array(triangle_indices, dtype=int)
        
        # For Surface rendering, we need to organize points by triangles
        # But actually Surface expects a grid structure, so we need a different approach
        # Let's override the rendering methods instead
    
    def get_triangle_indices(self) -> np.ndarray:
        """Override to return our triangulated indices"""
        return self.triangle_indices if hasattr(self, 'triangle_indices') else np.array([], dtype=int)
    
    def init_points(self):
        """Override Surface init_points since we set our own"""
        if not hasattr(self, 'data') or self.data is None:
            super().init_points()
    
    def init_simple_triangulation(self, points: np.ndarray):
        """Fallback: Create a simple fan triangulation from the center"""
        if len(points) < 3:
            return
            
        # Calculate center point
        center = points.mean(axis=0)
        
        # Create triangle fan
        triangles = []
        for i in range(len(points)):
            next_i = (i + 1) % len(points)
            triangles.extend([len(points), i, next_i])  # center, current, next
        
        # Add center to points
        all_points = np.vstack([points, center])
        self.set_points_from_triangulation(all_points, triangles)


class Circle3D(VMobject3D):
    """A 3D-rendered circle using triangulated fill"""
    
    def __init__(
        self,
        radius: float = 1.0,
        arc_center: Vect3Array = ORIGIN,
        resolution: int = 50,
        **kwargs
    ):
        # Import here to avoid circular import
        from manim.mobject.geometry import Circle
        
        # Create a regular Circle VMobject
        circle = Circle(radius=radius, arc_center=arc_center, **kwargs)
        
        # Initialize as VMobject3D with the circle
        super().__init__(
            vmobject=circle,
            resolution=resolution,
            **kwargs
        )


class Text(VMobject3D):
    """A 3D-rendered text using triangulated fill"""
    
    def __init__(
        self,
        text: str,
        resolution: int = 100,
        **kwargs
    ):
        # Import here to avoid circular import
        from manim.mobject.svg.text_mobject import MarkupText
        
        # Separate Text-specific kwargs from Surface kwargs
        text_kwargs = {}
        surface_kwargs = {}
        
        # List of kwargs that Text accepts
        text_specific = ['font_size', 'font', 'weight', 'slant', 'line_spacing']
        
        for key, value in kwargs.items():
            if key in text_specific:
                text_kwargs[key] = value
            else:
                surface_kwargs[key] = value
        
        # Create a regular MarkupText VMobject with text-specific kwargs
        # Use the same defaults as the old Text class for compatibility
        text_mob = MarkupText(
            text, 
            isolate=(re.compile(r"\w+", re.U), re.compile(r"\S+", re.U)),
            use_labelled_svg=True,
            path_string_config=dict(use_simple_quadratic_approx=True),
            **text_kwargs
        )
        
        # Initialize as VMobject3D with the text and surface kwargs
        super().__init__(
            vmobject=text_mob,
            resolution=resolution,
            **surface_kwargs
        )