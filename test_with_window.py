#!/usr/bin/env python3
"""Test Table with window display."""

from manim import *

class TestTable(Scene):
    def construct(self):
        # Test basic table
        table = Table(
            [["First", "Second"],
             ["Third", "Fourth"]],
            row_labels=[Text("R1"), Text("R2")],
            col_labels=[Text("C1"), Text("C2")])
        table.add_highlighted_cell((2,2), color=GREEN)
        
        self.play(Create(table))
        self.wait(2)

if __name__ == "__main__":
    # Run the scene directly
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestTable(window=window)
    scene.run()