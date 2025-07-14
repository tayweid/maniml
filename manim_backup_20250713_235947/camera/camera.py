"""
Camera with CE compatibility.
"""

import manim
from manim.camera.camera import Camera as GLCamera
import warnings


class Camera(GLCamera):
    """CE-compatible Camera - mostly a pass-through."""
    
    def __init__(self, **kwargs):
        # CE uses different parameter names
        ce_to_gl = {
            'background_color': 'background_color',
            'pixel_width': 'pixel_width',
            'pixel_height': 'pixel_height',
            'frame_rate': 'frame_rate',
        }
        
        gl_kwargs = {}
        for ce_key, gl_key in ce_to_gl.items():
            if ce_key in kwargs:
                gl_kwargs[gl_key] = kwargs.pop(ce_key)
        
        # Merge remaining kwargs
        gl_kwargs.update(kwargs)
        
        super().__init__(**gl_kwargs)
        
        # CE compatibility attributes
        self.background_opacity = 1.0
    
    def set_background(self, color, opacity=1.0):
        """CE compatibility method."""
        self.background_color = color
        self.background_opacity = opacity
        # GL doesn't support background opacity
        if opacity < 1.0:
            warnings.warn(
                "maniml: Background opacity not supported. Using opaque background.",
                UserWarning
            )


# For 3D scenes
ThreeDCamera = Camera  # In GL, camera handles 3D automatically