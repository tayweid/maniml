#!/usr/bin/env python3
"""Basic test without imports at module level."""

def test_imports():
    """Test imports inside function."""
    from manim import Scene, Table, Text, GREEN
    
    class BasicTable(Scene):
        def construct(self):
            table = Table(
                [["A", "B"], ["C", "D"]],
                row_labels=[Text("1"), Text("2")],
                col_labels=[Text("X"), Text("Y")]
            )
            table.add_highlighted_cell((1, 1), color=GREEN)
            self.add(table)
            self.wait()
    
    return BasicTable

# Only run if directly executed
if __name__ == "__main__":
    BasicTable = test_imports()
    print("Test successful! Table class created.")