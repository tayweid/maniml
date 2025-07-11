#!/usr/bin/env python3
"""Test ChangingDecimal and ChangeDecimalToValue animations."""

from manim import *
import numpy as np

class TestChangeDecimalToValue(Scene):
    def construct(self):
        # Create decimal number
        number = DecimalNumber(0, num_decimal_places=2).scale(2)
        self.add(number)
        
        # Animate from 0 to 100
        self.play(ChangeDecimalToValue(number, 100), run_time=2)
        self.wait()
        
        # Animate from 100 to -50.5
        self.play(ChangeDecimalToValue(number, -50.5), run_time=2)
        self.wait()
        
        # Animate to pi
        self.play(ChangeDecimalToValue(number, PI), run_time=1)
        self.wait()

class TestChangingDecimal(Scene):
    def construct(self):
        # Create decimal with more precision
        number = DecimalNumber(0, num_decimal_places=3).scale(2)
        label = Text("sin(t):", font_size=48).next_to(number, LEFT)
        self.add(VGroup(label, number))
        
        # Animate following sine wave
        self.play(ChangingDecimal(
            number,
            lambda t: np.sin(t * TAU),
            run_time=4
        ))
        
        # Animate following custom function
        self.play(ChangingDecimal(
            number,
            lambda t: t**2 * 10,
            run_time=2
        ))
        self.wait()

class TestCountingAnimation(Scene):
    def construct(self):
        # Create multiple counters
        counter1 = DecimalNumber(0, num_decimal_places=0).scale(1.5)
        counter2 = DecimalNumber(0, num_decimal_places=1).scale(1.5)
        counter3 = DecimalNumber(0, num_decimal_places=2).scale(1.5)
        
        counters = VGroup(counter1, counter2, counter3).arrange(DOWN, buff=1)
        
        labels = VGroup(
            Text("Integer:"),
            Text("1 decimal:"),
            Text("2 decimals:")
        ).scale(0.8)
        
        for label, counter in zip(labels, counters):
            label.next_to(counter, LEFT, buff=0.5)
        
        self.add(counters, labels)
        
        # Animate all counters to different values
        self.play(
            ChangeDecimalToValue(counter1, 42),
            ChangeDecimalToValue(counter2, 3.7),
            ChangeDecimalToValue(counter3, 1.41),
            run_time=3
        )
        self.wait()

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestChangeDecimalToValue(window=window)
    scene.run()