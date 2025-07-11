"""
TeX/LaTeX mobjects with CE compatibility.
"""

import manim.renderer.opengl
from manim.renderer.opengl.mobject.svg.tex_mobject import Tex as GLTex
from manim.renderer.opengl.mobject.types.vectorized_mobject import VGroup
import warnings


class TexTemplate:
    """Simplified TeX template for CE compatibility."""
    
    def __init__(self, tex_compiler="latex", output_format="svg", 
                 preamble="", placeholder_text="YourTextHere",
                 post_doc_commands=""):
        self.tex_compiler = tex_compiler
        self.output_format = output_format
        self.preamble = preamble
        self.placeholder_text = placeholder_text
        self.post_doc_commands = post_doc_commands
        
        # Warn if using non-default settings
        if tex_compiler != "latex" or output_format != "svg":
            warnings.warn(
                "maniml: Custom TeX settings ignored. Using GL defaults.",
                UserWarning
            )


class Tex(GLTex):
    """
    CE-compatible Tex using GL backend.
    
    Simplified: Multiple strings are joined with space.
    """
    
    def __init__(self, *tex_strings, arg_separator=" ", tex_template=None, 
                 font_size=48, color=None, **kwargs):
        # Join multiple strings CE-style
        if len(tex_strings) == 0:
            tex_string = ""
        elif len(tex_strings) == 1:
            tex_string = tex_strings[0]
        else:
            tex_string = arg_separator.join(str(s) for s in tex_strings)
        
        # Handle tex_template (ignored in simple version)
        if tex_template is not None:
            warnings.warn(
                "maniml: tex_template parameter ignored. Using GL defaults.",
                UserWarning
            )
        
        # GL uses different parameter names
        gl_kwargs = kwargs.copy()
        if color is not None:
            gl_kwargs['color'] = color
            
        # Initialize with GL backend
        super().__init__(tex_string, font_size=font_size, **gl_kwargs)
        
        # Store parts for CE compatibility
        self.tex_strings = tex_strings
        self.arg_separator = arg_separator
    
    def get_part_by_tex(self, tex_string):
        """CE compatibility method to get submobject by tex string."""
        # This is a simplified version
        if hasattr(self, 'submobjects') and len(self.submobjects) > 0:
            # Try to find the part
            for i, ts in enumerate(self.tex_strings):
                if tex_string in str(ts):
                    if i < len(self.submobjects):
                        return self.submobjects[i]
        
        # Return self if not found
        warnings.warn(
            f"maniml: Could not find tex part '{tex_string}'. Returning full object.",
            UserWarning
        )
        return self
    
    def set_color_by_tex(self, tex_string, color):
        """CE compatibility method to color part by tex string."""
        part = self.get_part_by_tex(tex_string)
        part.set_color(color)
        return self
    
    def get_parts_by_tex(self, *tex_strings):
        """CE compatibility method to get multiple parts."""
        parts = []
        for ts in tex_strings:
            parts.append(self.get_part_by_tex(ts))
        return VGroup(*parts)


class MathTex(Tex):
    """
    CE-compatible MathTex using GL backend.
    
    In GL, Tex and MathTex are essentially the same.
    """
    
    def __init__(self, *tex_strings, arg_separator=" ", substrings_to_isolate=None,
                 tex_to_color_map=None, font_size=48, **kwargs):
        # Handle CE-specific parameters
        if substrings_to_isolate:
            warnings.warn(
                "maniml: substrings_to_isolate not fully supported. "
                "Use multiple MathTex objects for complex formatting.",
                UserWarning
            )
        
        # Initialize as Tex
        super().__init__(*tex_strings, arg_separator=arg_separator, 
                        font_size=font_size, **kwargs)
        
        # Apply color map if provided
        if tex_to_color_map:
            for tex_string, color in tex_to_color_map.items():
                self.set_color_by_tex(tex_string, color)


class SingleStringMathTex(MathTex):
    """CE compatibility class - just uses MathTex."""
    
    def __init__(self, tex_string, **kwargs):
        if not isinstance(tex_string, str):
            raise TypeError("SingleStringMathTex requires a single string")
        super().__init__(tex_string, **kwargs)


# Utility functions for CE compatibility

def create_tex_with_colors(tex_parts):
    """
    Helper to create multi-colored LaTeX (replaces tex_to_color_map).
    
    Example:
        create_tex_with_colors([
            (r"\alpha", RED),
            ("+", WHITE),
            (r"\beta", BLUE)
        ])
    """
    parts = []
    for tex, color in tex_parts:
        parts.append(Tex(tex, color=color))
    
    result = VGroup(*parts)
    result.arrange(RIGHT, buff=0.1)
    return result


def create_aligned_math(*lines, alignment="&"):
    """
    Helper to create aligned equations.
    
    Since GL doesn't support CE's alignment, we create a VGroup.
    """
    equations = []
    for line in lines:
        # Remove alignment characters
        clean_line = line.replace(alignment, " ")
        equations.append(MathTex(clean_line))
    
    result = VGroup(*equations)
    result.arrange(DOWN, buff=0.5)
    
    # Try to align at equals signs
    for eq in equations[1:]:
        if "=" in str(eq.tex_strings):
            # Rough alignment
            eq.align_to(equations[0], LEFT)
    
    return result