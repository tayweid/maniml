"""
3D mobjects with CE compatibility.
"""

import manim
import warnings
import numpy as np
from manim.constants import TAU, PI, OUT, UP, RIGHT, ORIGIN

# Import 3D objects from ManimGL's correct location
try:
    from manim.mobject.three_dimensions import (
        Sphere as GLSphere,
        Cube as GLCube, 
        Cylinder as GLCylinder,
        Cone as GLCone,
        Torus as GLTorus,
        Prism as GLPrism,
        Line3D,
        Disk3D,
        Square3D,
        VCube,
        VPrism,
        Dodecahedron,
        Surface
    )
    # ParametricSurface is just an alias for Surface in ManimGL
    ParametricSurface = Surface
    
    # Import coordinate systems
    from manim.mobject.coordinate_systems import ThreeDAxes
    
    # Create CE-compatible wrappers
    
    class Sphere(GLSphere):
        """CE-compatible Sphere."""
        def __init__(self, radius=1, **kwargs):
            # GL expects radius in kwargs
            kwargs['radius'] = radius
            super().__init__(**kwargs)
    
    class Cube(GLCube):
        """CE-compatible Cube."""
        def __init__(self, side_length=2, **kwargs):
            # GL expects side_length in kwargs
            kwargs['side_length'] = side_length
            super().__init__(**kwargs)
    
    class Cylinder(GLCylinder):
        """CE-compatible Cylinder."""
        def __init__(self, radius=1, height=2, **kwargs):
            # GL expects these in kwargs
            kwargs['radius'] = radius
            kwargs['height'] = height
            super().__init__(**kwargs)
    
    class Cone(GLCone):
        """CE-compatible Cone with base_radius and height parameters."""
        def __init__(self, base_radius=1, height=1, **kwargs):
            # Store CE-style parameters
            self.base_radius = base_radius
            self.height = height
            
            # GL Cone doesn't take these params, so we scale after creation
            super().__init__(**kwargs)
            
            # Scale to match requested dimensions
            # Default GL cone has base radius ~1 and height ~1
            self.scale(base_radius)
            self.stretch(height, dim=2)  # Stretch in z direction
    
    class Torus(GLTorus):
        """CE-compatible Torus."""
        def __init__(self, major_radius=3, minor_radius=1, r1=None, r2=None, **kwargs):
            # Handle both CE style (major/minor) and GL style (r1/r2)
            if r1 is not None:
                kwargs['r1'] = r1
            else:
                kwargs['r1'] = major_radius
                
            if r2 is not None:
                kwargs['r2'] = r2  
            else:
                kwargs['r2'] = minor_radius
                
            super().__init__(**kwargs)
    
    class Prism(GLPrism):
        """CE-compatible Prism."""
        def __init__(self, dimensions=None, width=3, height=2, depth=1, **kwargs):
            # Handle CE-style dimensions array or individual params
            if dimensions is not None:
                width, height, depth = dimensions
            
            kwargs['width'] = width
            kwargs['height'] = height  
            kwargs['depth'] = depth
            super().__init__(**kwargs)
    
    # Create placeholder classes for CE compatibility
    ThreeDVMobject = Surface  # Use Surface as base for 3D VMobjects
    
    class Dot3D(GLSphere):
        """CE-compatible 3D Dot."""
        def __init__(self, point=None, radius=0.08, color=None, **kwargs):
            if color is not None:
                kwargs['color'] = color
            kwargs['radius'] = radius
            super().__init__(**kwargs)
            if point is not None:
                self.move_to(point)
    
    class Arrow3D(Line3D):
        """CE-compatible 3D Arrow."""
        def __init__(self, start=None, end=None, **kwargs):
            if start is None:
                start = ORIGIN
            if end is None:
                end = RIGHT
            super().__init__(start_point=start, end_point=end, **kwargs)
            # TODO: Add cone tip for arrow head
    
    # Polyhedra - create basic implementations
    class Tetrahedron(VCube):
        """CE-compatible Tetrahedron (placeholder using cube)."""
        def __init__(self, edge_length=1, **kwargs):
            super().__init__(side_length=edge_length, **kwargs)
            # TODO: Implement actual tetrahedron geometry
    
    class Octahedron(VCube):
        """CE-compatible Octahedron (placeholder using cube)."""  
        def __init__(self, edge_length=1, **kwargs):
            super().__init__(side_length=edge_length, **kwargs)
            # TODO: Implement actual octahedron geometry
    
    class Icosahedron(Dodecahedron):
        """CE-compatible Icosahedron (using dodecahedron as placeholder)."""
        def __init__(self, edge_length=1, **kwargs):
            kwargs['edge_length'] = edge_length
            super().__init__(**kwargs)
except ImportError as e:
    # Fallback - define placeholders
    warnings.warn(f"maniml: 3D objects import error: {e}", UserWarning)
    
    class Sphere(manimlib.mobject.mobject.Mobject):
        pass
    
    class Cube(manimlib.mobject.mobject.Mobject):
        pass
    
    class Cylinder(manimlib.mobject.mobject.Mobject):
        pass
    
    class Cone(manimlib.mobject.mobject.Mobject):
        pass
    
    class Torus(manimlib.mobject.mobject.Mobject):
        pass
    
    class Tetrahedron(manimlib.mobject.mobject.Mobject):
        pass
    
    class Octahedron(manimlib.mobject.mobject.Mobject):
        pass
    
    class Icosahedron(manimlib.mobject.mobject.Mobject):
        pass
    
    class Dodecahedron(manimlib.mobject.mobject.Mobject):
        pass


class Box3D(Cube):
    """CE compatibility - Box3D is just a Cube."""
    pass


# The Surface and ParametricSurface are already imported above in the try block