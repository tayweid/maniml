"""
SVG and Image mobjects with CE compatibility.
"""

import manim
from manim.mobject.svg.svg_mobject import SVGMobject as GLSVGMobject
from manim.mobject.types.image_mobject import ImageMobject as GLImageMobject
import warnings


class SVGMobject(GLSVGMobject):
    """CE-compatible SVGMobject."""
    
    def __init__(self, file_name, fill_color=None, stroke_color=None,
                 stroke_width=None, height=2, width=None, **kwargs):
        # CE uses different parameter names
        gl_kwargs = kwargs.copy()
        
        # Parameter mapping
        if fill_color is not None:
            gl_kwargs['fill_color'] = fill_color
        if stroke_color is not None:
            gl_kwargs['stroke_color'] = stroke_color
        if stroke_width is not None:
            gl_kwargs['stroke_width'] = stroke_width
            
        # Handle size
        if 'height' not in gl_kwargs:
            gl_kwargs['height'] = height
        if width is not None:
            gl_kwargs['width'] = width
            
        super().__init__(file_name, **gl_kwargs)


class ImageMobject(GLImageMobject):
    """CE-compatible ImageMobject."""
    
    def __init__(self, filename_or_array, height=None, width=None,
                 scale_to_resolution=None, invert=False, **kwargs):
        # GL parameter adaptation
        gl_kwargs = kwargs.copy()
        
        # Handle dimensions
        if height is not None:
            gl_kwargs['height'] = height
        if width is not None:
            warnings.warn(
                "maniml: ImageMobject width parameter not directly supported. "
                "Use height or scale after creation.",
                UserWarning
            )
        
        if scale_to_resolution is not None:
            warnings.warn(
                "maniml: scale_to_resolution not supported. Use height instead.",
                UserWarning
            )
            
        if invert:
            warnings.warn(
                "maniml: invert parameter not supported.",
                UserWarning
            )
            
        super().__init__(filename_or_array, **gl_kwargs)