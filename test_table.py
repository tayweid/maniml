#!/usr/bin/env python3
"""Test file for Table implementation."""

from manim import *
import numpy as np

class TestTable(Scene):
    def construct(self):
        # Test basic table
        table = Table(
            [["First", "Second"],
             ["Third", "Fourth"]],
            row_labels=[Text("R1"), Text("R2")],
            col_labels=[Text("C1"), Text("C2")])
        table.add_highlighted_cell((2,2), color=GREEN)
        
        self.add(table)
        self.wait()

class TestMathTable(Scene):
    def construct(self):
        t0 = MathTable(
            [["+", 0, 5, 10],
             [0, 0, 5, 10],
             [2, 2, 7, 12],
             [4, 4, 9, 14]],
            include_outer_lines=True)
        t0.get_horizontal_lines()[:3].set_color(BLUE)
        t0.get_vertical_lines()[:3].set_color(BLUE)
        
        self.add(t0)
        self.wait()

class TestDecimalTable(Scene):  
    def construct(self):
        x_vals = np.linspace(-2, 2, 5)
        y_vals = np.exp(x_vals)
        t1 = DecimalTable(
            [x_vals, y_vals],
            row_labels=[MathTex("x"), MathTex("f(x)")],
            include_outer_lines=True)
        
        self.add(t1)
        self.wait()

class TestAllTables(Scene):
    def construct(self):
        # Basic table
        t0 = Table(
            [["First", "Second"],
             ["Third","Fourth"]],
            row_labels=[Text("R1"), Text("R2")],
            col_labels=[Text("C1"), Text("C2")],
            top_left_entry=Text("TOP"))
        t0.add_highlighted_cell((2,2), color=GREEN)
        
        # Decimal table
        x_vals = np.linspace(-2,2,5)
        y_vals = np.exp(x_vals)
        t1 = DecimalTable(
            [x_vals, y_vals],
            row_labels=[MathTex("x"), MathTex("f(x)")],
            include_outer_lines=True)
        
        # Math table
        t2 = MathTable(
            [["+", 0, 5, 10],
             [0, 0, 5, 10],
             [2, 2, 7, 12],
             [4, 4, 9, 14]],
            include_outer_lines=True)
        t2.get_horizontal_lines()[:3].set_color(BLUE)
        t2.get_vertical_lines()[:3].set_color(BLUE)
        
        # Mobject table
        cross = VGroup(
            Line(UP + LEFT, DOWN + RIGHT),
            Line(UP + RIGHT, DOWN + LEFT))
        a = Circle().set_color(RED).scale(0.5)
        b = cross.set_color(BLUE).scale(0.5)
        t3 = MobjectTable(
            [[a.copy(),b.copy(),a.copy()],
             [b.copy(),a.copy(),a.copy()],
             [a.copy(),b.copy(),b.copy()]])
        
        # Integer table
        vals = np.arange(1,21).reshape(5,4)
        t4 = IntegerTable(
            vals,
            include_outer_lines=True
        )
        
        # Arrange all tables
        g1 = Group(t0, t1).scale(0.5).arrange(buff=1).to_edge(UP, buff=1)
        g2 = Group(t2, t3, t4).scale(0.5).arrange(buff=1).to_edge(DOWN, buff=1)
        self.add(g1, g2)
        self.wait()

if __name__ == "__main__":
    # Run the test
    import os
    os.system("manim -p -ql test_table.py TestAllTables")