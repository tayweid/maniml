#!/usr/bin/env python3
"""Test BarChart implementation."""

from manim import *

class TestBarChart(Scene):
    def construct(self):
        # Create a bar chart with positive and negative values
        chart = BarChart(
            values=[-5, 40, -10, 20, -3],
            bar_names=["one", "two", "three", "four", "five"],
            y_range=[-20, 50, 10],
            y_length=6,
            x_length=10,
            x_axis_config={"font_size": 36},
        )

        # Add bar labels
        c_bar_lbls = chart.get_bar_labels(font_size=48)

        self.add(chart, c_bar_lbls)
        self.wait(2)
        
        # Change values (without animation for now)
        new_values = [10, -20, 30, -15, 25]
        chart.change_bar_values(new_values)
        new_labels = chart.get_bar_labels(font_size=48)
        self.remove(c_bar_lbls)
        self.play(FadeIn(new_labels))
        self.wait(2)

class TestBarChartSimple(Scene):
    def construct(self):
        # Simple bar chart with default settings
        chart = BarChart(
            values=[10, 9, 8, 7, 6, 5, 4, 3, 2, 1],
            y_range=[0, 10, 1]
        )
        
        # Add labels with different color
        labels = chart.get_bar_labels(
            color=WHITE,
            label_constructor=MathTex,
            font_size=36
        )
        
        self.add(chart, labels)
        self.wait()