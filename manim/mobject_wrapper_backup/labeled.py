"""Labeled geometric objects."""

from __future__ import annotations

__all__ = ["LabeledLine", "LabeledArrow", "LabeledDot"]

from typing import TYPE_CHECKING, Any, Optional

from manim.constants import *
from manim.mobject.types.vectorized_mobject import VGroup
from manim.mobject.geometry import Line as GLLine, Arrow as GLArrow, Dot as GLDot
from manim.mobject.text.tex_mobject import MathTex, Tex
from manim.mobject.text.text_mobject import Text

if TYPE_CHECKING:
    from manim.mobject.mobject import Mobject
    from manim.typing import Vect3


class LabeledLine(GLLine):
    """A line with a label attached.

    Parameters
    ----------
    label
        The label for the line, can be any mobject (Text, MathTex, etc).
    label_position
        The position along the line where the label is placed, from 0 to 1.
    label_frame
        If True, adds a frame around the label.
    label_buff
        Distance between the label and the line.
    label_constructor
        Constructor to use if label is a string.
    label_kwargs
        Additional keyword arguments for the label constructor.
    kwargs
        Additional keyword arguments passed to :class:`~.Line`.

    Examples
    --------
    .. manim:: LabeledLineExample
        :save_last_frame:

        class LabeledLineExample(Scene):
            def construct(self):
                # Simple labeled line
                line1 = LabeledLine(
                    label="L",
                    start=2*LEFT,
                    end=2*RIGHT,
                )
                
                # Line with math label
                line2 = LabeledLine(
                    label="2\\pi r",
                    label_constructor=MathTex,
                    start=2*LEFT + DOWN,
                    end=2*RIGHT + DOWN,
                    label_position=0.3,
                )
                
                # Line with framed label
                line3 = LabeledLine(
                    label="Distance",
                    label_frame=True,
                    start=2*LEFT + 2*DOWN,
                    end=2*RIGHT + 2*DOWN,
                    label_position=0.7,
                    color=BLUE,
                )
                
                self.add(line1, line2, line3)
    """
    
    def __init__(
        self,
        label: str | Mobject,
        label_position: float = 0.5,
        label_frame: bool = False,
        label_buff: float = MED_SMALL_BUFF,
        label_constructor: type[Mobject] = None,
        label_kwargs: dict[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        
        # Create the label
        if isinstance(label, str):
            if label_constructor is None:
                # Default to Text unless it looks like math
                if any(c in label for c in ['\\', '^', '_', '$']):
                    label_constructor = MathTex
                else:
                    label_constructor = Text
            
            label_kwargs = label_kwargs or {}
            self.label = label_constructor(label, **label_kwargs)
        else:
            self.label = label
        
        # Position the label
        point = self.point_from_proportion(label_position)
        self.label.next_to(point, UP, buff=label_buff)
        
        # Add frame if requested
        if label_frame:
            from manim.mobject.shape_matchers import SurroundingRectangle
            frame = SurroundingRectangle(
                self.label,
                color=self.get_color(),
                buff=SMALL_BUFF,
            )
            self.label_group = VGroup(frame, self.label)
        else:
            self.label_group = self.label
            
        # Make label a submobject
        self.add(self.label_group)
        
    def get_label(self) -> Mobject:
        """Get the label mobject."""
        return self.label


class LabeledArrow(GLArrow):
    """An arrow with a label attached.

    Parameters
    ----------
    label
        The label for the arrow, can be any mobject (Text, MathTex, etc).
    label_position
        The position along the arrow where the label is placed, from 0 to 1.
    label_buff
        Distance between the label and the arrow.
    label_constructor
        Constructor to use if label is a string.
    label_kwargs
        Additional keyword arguments for the label constructor.
    kwargs
        Additional keyword arguments passed to :class:`~.Arrow`.

    Examples
    --------
    .. manim:: LabeledArrowExample
        :save_last_frame:

        class LabeledArrowExample(Scene):
            def construct(self):
                # Simple labeled arrow
                arrow1 = LabeledArrow(
                    label="v",
                    start=ORIGIN,
                    end=2*RIGHT,
                    label_constructor=MathTex,
                )
                
                # Arrow with positioned label
                arrow2 = LabeledArrow(
                    label="Force",
                    start=ORIGIN + DOWN,
                    end=2*UR + DOWN,
                    label_position=0.7,
                    color=RED,
                )
                
                # Arrow with complex label
                arrow3 = LabeledArrow(
                    label="\\vec{F} = ma",
                    label_constructor=MathTex,
                    start=ORIGIN + 2*DOWN,
                    end=2*LEFT + 2*DOWN,
                    label_position=0.3,
                    color=BLUE,
                )
                
                self.add(arrow1, arrow2, arrow3)
    """
    
    def __init__(
        self,
        label: str | Mobject,
        label_position: float = 0.5,
        label_buff: float = MED_SMALL_BUFF,
        label_constructor: type[Mobject] = None,
        label_kwargs: dict[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        
        # Create the label
        if isinstance(label, str):
            if label_constructor is None:
                # Default to Text unless it looks like math
                if any(c in label for c in ['\\', '^', '_', '$']):
                    label_constructor = MathTex
                else:
                    label_constructor = Text
            
            label_kwargs = label_kwargs or {}
            self.label = label_constructor(label, **label_kwargs)
        else:
            self.label = label
        
        # Position the label
        point = self.point_from_proportion(label_position)
        
        # Get perpendicular direction for label placement
        direction = self.get_unit_vector()
        perp_direction = np.array([-direction[1], direction[0], 0])
        
        self.label.move_to(point)
        self.label.shift(perp_direction * label_buff)
        
        # Make label a submobject
        self.add(self.label)
        
    def get_label(self) -> Mobject:
        """Get the label mobject."""
        return self.label


class LabeledDot(GLDot):
    """A dot with a label attached.

    Parameters
    ----------
    label
        The label for the dot, can be any mobject (Text, MathTex, etc).
    label_dir
        Direction to place the label relative to the dot.
    label_buff
        Distance between the label and the dot.
    label_constructor
        Constructor to use if label is a string.
    label_kwargs
        Additional keyword arguments for the label constructor.
    kwargs
        Additional keyword arguments passed to :class:`~.Dot`.

    Examples
    --------
    .. manim:: LabeledDotExample
        :save_last_frame:

        class LabeledDotExample(Scene):
            def construct(self):
                # Simple labeled dots
                dot1 = LabeledDot("A")
                dot2 = LabeledDot("B", point=2*RIGHT, label_dir=UR)
                dot3 = LabeledDot("C", point=2*UP, label_dir=LEFT, color=RED)
                
                # Dots with math labels
                dot4 = LabeledDot(
                    "P_0",
                    point=2*LEFT,
                    label_constructor=MathTex,
                    color=BLUE,
                )
                
                # Dot with custom label
                custom_label = Text("Origin", font_size=20)
                dot5 = LabeledDot(
                    custom_label,
                    point=2*DOWN,
                    label_dir=DOWN,
                    radius=0.1,
                    color=GREEN,
                )
                
                self.add(dot1, dot2, dot3, dot4, dot5)
    """
    
    def __init__(
        self,
        label: str | Mobject,
        label_dir: Optional[Vect3] = UP,
        label_buff: float = SMALL_BUFF,
        label_constructor: type[Mobject] = None,
        label_kwargs: dict[str, Any] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        
        # Create the label
        if isinstance(label, str):
            if label_constructor is None:
                # Default to Text unless it looks like math
                if any(c in label for c in ['\\', '^', '_', '$']):
                    label_constructor = MathTex
                else:
                    label_constructor = Text
            
            label_kwargs = label_kwargs or {}
            # Default to smaller font for dot labels
            if 'font_size' not in label_kwargs and label_constructor == Text:
                label_kwargs['font_size'] = 24
            
            self.label = label_constructor(label, **label_kwargs)
        else:
            self.label = label
        
        # Position the label
        self.label.next_to(self, label_dir, buff=label_buff)
        
        # Make label a submobject
        self.add(self.label)
        
    def get_label(self) -> Mobject:
        """Get the label mobject."""
        return self.label