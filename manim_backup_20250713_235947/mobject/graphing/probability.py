"""Mobjects representing objects from probability theory and statistics."""

from __future__ import annotations

__all__ = ["BarChart"]

from collections.abc import Iterable, MutableSequence, Sequence
from typing import TYPE_CHECKING

import numpy as np

from manim.constants import *
from manim.mobject.geometry import Rectangle
from manim.mobject.types.vectorized_mobject import VGroup, VMobject
from manim.utils.color import color_gradient
from manim.mobject.coordinate_systems import Axes
from manim.mobject.text.tex_mobject import Tex, MathTex
from manim.config import manim_config

if TYPE_CHECKING:
    from manim.typing import ManimColor


class BarChart(Axes):
    """Creates a bar chart. Inherits from :class:`~.Axes`, so it shares its methods
    and attributes. Each axis inherits from :class:`~.NumberLine`, so pass in ``x_axis_config``/``y_axis_config``
    to control their attributes.

    Parameters
    ----------
    values
        A sequence of values that determines the height of each bar. Accepts negative values.
    bar_names
        A sequence of names for each bar. Does not have to match the length of ``values``.
    y_range
        The y_axis range of values. If ``None``, the range will be calculated based on the
        min/max of ``values`` and the step will be calculated based on ``y_length``.
    x_length
        The length of the x-axis. If ``None``, it is automatically calculated based on
        the number of values and the width of the screen.
    y_length
        The length of the y-axis.
    bar_colors
        The color for the bars. Accepts a sequence of colors (can contain just one item).
        If the length of``bar_colors`` does not match that of ``values``,
        intermediate colors will be automatically determined.
    bar_width
        The length of a bar. Must be between 0 and 1.
    bar_fill_opacity
        The fill opacity of the bars.
    bar_stroke_width
        The stroke width of the bars.

    Examples
    --------
    .. manim:: BarChartExample
        :save_last_frame:

        class BarChartExample(Scene):
            def construct(self):
                chart = BarChart(
                    values=[-5, 40, -10, 20, -3],
                    bar_names=["one", "two", "three", "four", "five"],
                    y_range=[-20, 50, 10],
                    y_length=6,
                    x_length=10,
                    x_axis_config={"font_size": 36},
                )

                c_bar_lbls = chart.get_bar_labels(font_size=48)

                self.add(chart, c_bar_lbls)
    """

    def __init__(
        self,
        values: MutableSequence[float],
        bar_names: Sequence[str] | None = None,
        y_range: Sequence[float] | None = None,
        x_length: float | None = None,
        y_length: float | None = None,
        bar_colors: Iterable[str | ManimColor] = [
            "#003f5c",
            "#58508d",
            "#bc5090",
            "#ff6361",
            "#ffa600",
        ],
        bar_width: float = 0.6,
        bar_fill_opacity: float = 0.7,
        bar_stroke_width: float = 3,
        **kwargs,
    ):
        # Handle old string format
        if isinstance(bar_colors, str):
            bar_colors = list(bar_colors)

        # Get default dimensions from config
        frame_height = manim_config.camera.frame_height
        frame_width = manim_config.camera.frame_width
        
        y_length = y_length if y_length is not None else frame_height - 4

        self.values = values
        self.bar_names = bar_names
        self.bar_colors = bar_colors
        self.bar_width = bar_width
        self.bar_fill_opacity = bar_fill_opacity
        self.bar_stroke_width = bar_stroke_width

        x_range = [0, len(self.values), 1]

        if y_range is None:
            y_range = [
                min(0, min(self.values)),
                max(0, max(self.values)),
                round(max(self.values) / y_length, 2),
            ]

        elif len(y_range) == 2:
            y_range = [*y_range, round(max(self.values) / y_length, 2)]

        if x_length is None:
            x_length = min(len(self.values), frame_width - 2)

        # Default x_axis config
        x_axis_config = kwargs.pop("x_axis_config", {})
        # Extract font_size for labels, not for the axis itself
        self.x_axis_font_size = x_axis_config.pop("font_size", 24)
        # Store label_constructor separately
        self.x_axis_label_constructor = x_axis_config.pop("label_constructor", Tex)

        self.bars: VGroup = VGroup()
        self.x_labels: VGroup | None = None
        self.bar_labels: VGroup | None = None

        super().__init__(
            x_range=x_range,
            y_range=y_range,
            x_length=x_length,
            y_length=y_length,
            x_axis_config=x_axis_config,
            tips=kwargs.pop("tips", False),
            **kwargs,
        )

        self._add_bars()

        if self.bar_names is not None:
            self._add_x_axis_labels()

        self.y_axis.add_numbers()

    def _update_colors(self):
        """Initialize the colors of the bars of the chart.

        Sets the color of ``self.bars`` via ``self.bar_colors``.

        Primarily used when the bars are initialized with ``self._add_bars``
        or updated via ``self.change_bar_values``.
        """
        # Convert colors list to actual colors
        colors = list(self.bar_colors)
        if len(colors) < len(self.bars):
            # Interpolate colors if we don't have enough
            colors = color_gradient(colors, len(self.bars))
        
        for bar, color in zip(self.bars, colors):
            bar.set_fill(color)

    def _add_x_axis_labels(self):
        """Essentially :meth`:~.NumberLine.add_labels`, but differs in that
        the direction of the label with respect to the x_axis changes to UP or DOWN
        depending on the value.

        UP for negative values and DOWN for positive values.
        """
        val_range = np.arange(
            0.5, len(self.bar_names), 1
        )  # 0.5 shifted so that labels are centered, not on ticks

        labels = VGroup()

        for i, (value, bar_name) in enumerate(zip(val_range, self.bar_names)):
            # to accommodate negative bars, the label may need to be
            # below or above the x_axis depending on the value of the bar
            direction = UP if self.values[i] < 0 else DOWN
            bar_name_label = self.x_axis_label_constructor(bar_name)

            if hasattr(bar_name_label, "font_size"):
                bar_name_label.font_size = self.x_axis_font_size
            bar_name_label.next_to(
                self.x_axis.number_to_point(value),
                direction=direction,
                buff=self.x_axis.line_to_number_buff,
            )

            labels.add(bar_name_label)

        self.x_axis.labels = labels
        self.x_axis.add(labels)

    def _create_bar(self, bar_number: int, value: float) -> Rectangle:
        """Creates a positioned bar on the chart.

        Parameters
        ----------
        bar_number
            Determines the x-position of the bar.
        value
            The value that determines the height of the bar.

        Returns
        -------
        Rectangle
            A positioned rectangle representing a bar on the chart.
        """
        # bar measurements relative to the axis

        # distance from between the y-axis and the top of the bar
        bar_h = abs(self.c2p(0, value)[1] - self.c2p(0, 0)[1])
        # width of the bar
        bar_w = self.c2p(self.bar_width, 0)[0] - self.c2p(0, 0)[0]

        bar = Rectangle(
            height=bar_h,
            width=bar_w,
            stroke_width=self.bar_stroke_width,
            fill_opacity=self.bar_fill_opacity,
        )

        pos = UP if (value >= 0) else DOWN
        bar.next_to(self.c2p(bar_number + 0.5, 0), pos, buff=0)
        return bar

    def _add_bars(self) -> None:
        for i, value in enumerate(self.values):
            tmp_bar = self._create_bar(bar_number=i, value=value)
            self.bars.add(tmp_bar)

        self._update_colors()
        self.add_to_back(self.bars)

    def get_bar_labels(
        self,
        color: ManimColor | None = None,
        font_size: float = 24,
        buff: float = MED_SMALL_BUFF,
        label_constructor: type[VMobject] = Tex,
    ):
        """Annotates each bar with its corresponding value. Use ``self.bar_labels`` to access the
        labels after creation.

        Parameters
        ----------
        color
            The color of each label. By default ``None`` and is based on the parent's bar color.
        font_size
            The font size of each label.
        buff
            The distance from each label to its bar. By default 0.4.
        label_constructor
            The Mobject class to construct the labels, by default :class:`~.Tex`.

        Examples
        --------
        .. manim:: GetBarLabelsExample
            :save_last_frame:

            class GetBarLabelsExample(Scene):
                def construct(self):
                    chart = BarChart(values=[10, 9, 8, 7, 6, 5, 4, 3, 2, 1], y_range=[0, 10, 1])

                    c_bar_lbls = chart.get_bar_labels(
                        color=WHITE, label_constructor=MathTex, font_size=36
                    )

                    self.add(chart, c_bar_lbls)
        """
        bar_labels = VGroup()
        for bar, value in zip(self.bars, self.values):
            bar_lbl = label_constructor(str(value))

            if color is None:
                bar_lbl.set_color(bar.get_fill_color())
            else:
                bar_lbl.set_color(color)

            if hasattr(bar_lbl, "font_size"):
                bar_lbl.font_size = font_size

            pos = UP if (value >= 0) else DOWN
            bar_lbl.next_to(bar, pos, buff=buff)
            bar_labels.add(bar_lbl)

        return bar_labels

    def change_bar_values(self, values: Iterable[float], update_colors: bool = True):
        """Updates the height of the bars of the chart.

        Parameters
        ----------
        values
            The values that will be used to update the height of the bars.
            Does not have to match the number of bars.
        update_colors
            Whether to re-initalize the colors of the bars based on ``self.bar_colors``.

        Examples
        --------
        .. manim:: ChangeBarValuesExample
            :save_last_frame:

            class ChangeBarValuesExample(Scene):
                def construct(self):
                    values=[-10, -8, -6, -4, -2, 0, 2, 4, 6, 8, 10]

                    chart = BarChart(
                        values,
                        y_range=[-10, 10, 2],
                        y_axis_config={"font_size": 24},
                    )
                    self.add(chart)

                    chart.change_bar_values(list(reversed(values)))
                    self.add(chart.get_bar_labels(font_size=24))
        """
        for i, (bar, value) in enumerate(zip(self.bars, values)):
            chart_val = self.values[i]

            if chart_val > 0:
                bar_lim = bar.get_bottom()
                aligned_edge = DOWN
            else:
                bar_lim = bar.get_top()
                aligned_edge = UP

            # check if the bar has height
            if chart_val != 0:
                quotient = value / chart_val
                if quotient < 0:
                    aligned_edge = UP if chart_val > 0 else DOWN

                    # if the bar is already positive, then we now want to move it
                    # so that it is negative. So, we move the top edge of the bar
                    # to the location of the previous bottom

                    # if already negative, then we move the bottom edge of the bar
                    # to the location of the previous top

                bar.stretch_to_fit_height(abs(quotient) * bar.get_height())

            else:
                # create a new bar since the current one has a height of zero (doesn't exist)
                temp_bar = self._create_bar(i, value)
                self.bars.remove(bar)
                self.bars.insert(i, temp_bar)

            bar.move_to(bar_lim, aligned_edge)

        if update_colors:
            self._update_colors()

        self.values[: len(values)] = values