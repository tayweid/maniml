"""
Text mobjects with CE compatibility.

Simplifications:
- t2c, t2f, t2g, t2s, t2w are ignored (use multiple Text objects instead)
- gradient parameter is ignored (use color interpolation instead)
- line_spacing works differently but is approximated
"""

import manim
from manim.mobject.svg.text_mobject import Text as GLText
from manim.mobject.types.vectorized_mobject import VGroup
from manim.constants import DOWN, UP, LEFT, RIGHT, ORIGIN
import warnings

class Text(GLText):
    """
    CE-compatible Text using GL backend.
    
    Simplified: Advanced text formatting (t2c, t2f, etc.) is not supported.
    Use multiple Text objects for different colors/fonts.
    """
    
    # Font mapping for CE compatibility
    FONT_MAP = {
        'serif': 'Times New Roman',
        'sans-serif': 'Arial',
        'sans': 'Arial',
        'monospace': 'Courier New',
        'mono': 'Courier New',
    }
    
    def __init__(
        self,
        text,
        font="",
        font_size=48,
        line_spacing=-1,
        color=None,
        weight=None,
        gradient=None,
        slant=None,
        t2c=None,
        t2f=None,
        t2g=None,
        t2s=None,
        t2w=None,
        **kwargs
    ):
        # Handle CE-specific parameters
        if any([t2c, t2f, t2g, t2s, t2w]):
            warnings.warn(
                "maniml: Advanced text formatting (t2c, t2f, etc.) not supported. "
                "Use multiple Text objects for different formatting.",
                UserWarning
            )
        
        if gradient:
            warnings.warn(
                "maniml: gradient parameter not supported. "
                "Use color interpolation or multiple objects.",
                UserWarning
            )
        
        # Map CE font names to system fonts
        if font in self.FONT_MAP:
            font = self.FONT_MAP[font]
        elif not font:
            font = "Arial"  # Default font
        
        # Handle weight
        if weight == "BOLD":
            # Some system fonts have bold variants
            if font == "Arial":
                font = "Arial Bold"
            elif font == "Times New Roman":
                font = "Times New Roman Bold"
        
        # Convert slant to GL parameter if supported
        gl_kwargs = kwargs.copy()
        if 'font' not in gl_kwargs:
            gl_kwargs['font'] = font
        
        # Color handling
        if color is not None:
            gl_kwargs['color'] = color
            
        # Initialize with GL backend
        super().__init__(text, font_size=font_size, **gl_kwargs)
        
        # Apply line spacing if different from default
        if line_spacing != -1:
            self._apply_line_spacing(line_spacing)
    
    def _apply_line_spacing(self, line_spacing):
        """Approximate CE line spacing."""
        # GL handles line spacing differently
        # This is a rough approximation
        if hasattr(self, 'submobjects') and len(self.submobjects) > 1:
            # Adjust spacing between lines
            for i in range(1, len(self.submobjects)):
                self.submobjects[i].shift(DOWN * line_spacing * 0.1)


class MarkupText(Text):
    """
    Simplified MarkupText - just uses regular Text.
    
    CE's MarkupText supports Pango markup. We ignore markup and render as plain text.
    """
    
    def __init__(self, text, **kwargs):
        warnings.warn(
            "maniml: MarkupText rendered as plain Text. Pango markup ignored.",
            UserWarning
        )
        # Strip basic markup tags
        import re
        clean_text = re.sub(r'<[^>]+>', '', text)
        super().__init__(clean_text, **kwargs)


class Paragraph(VGroup):
    """
    CE-compatible Paragraph - a VGroup of Text objects.
    """
    
    def __init__(self, *text, line_spacing=0.3, alignment="left", **kwargs):
        # Create Text objects for each line
        lines = []
        for line in text:
            if isinstance(line, str):
                lines.append(Text(line, **kwargs))
            else:
                lines.append(line)
        
        super().__init__(*lines)
        
        # Arrange lines
        self.arrange(DOWN, buff=line_spacing)
        
        # Handle alignment
        if alignment == "center":
            for line in self:
                line.move_to(self.get_center()[0] * RIGHT)
        elif alignment == "right":
            for line in self:
                line.move_to(self.get_right()[0] * RIGHT)


# Utility function for CE compatibility
def create_text_with_colors(text_parts):
    """
    Helper to create multi-colored text (replaces t2c functionality).
    
    Example:
        create_text_with_colors([
            ("Hello", RED),
            (" ", WHITE),
            ("World", BLUE)
        ])
    """
    parts = []
    for text, color in text_parts:
        parts.append(Text(text, color=color))
    
    result = VGroup(*parts)
    result.arrange(RIGHT, buff=0)
    return result