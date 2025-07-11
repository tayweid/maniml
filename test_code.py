#!/usr/bin/env python3
"""Test Code mobject implementation."""

from manim import *

class TestCode(Scene):
    def construct(self):
        # Test code from string
        code_str = '''def hello_world():
    print("Hello, World!")
    return 42

# Call the function
result = hello_world()
print(f"Result: {result}")'''

        code = Code(
            code_string=code_str,
            language="python",
            formatter_style="monokai",
            background="window",
            background_config={"stroke_color": YELLOW},
        )
        
        self.play(Create(code))
        self.wait(2)
        
        # Test without Pygments (simple version)
        code2 = Code(
            code_string="// Simple C++ code\nint main() {\n    return 0;\n}",
            language="cpp",
            add_line_numbers=False,
            background="rectangle",
        )
        code2.scale(0.8).next_to(code, DOWN, buff=0.5)
        
        self.play(Create(code2))
        self.wait(2)

if __name__ == "__main__":
    from manim.renderer.opengl.window import Window
    window = Window()
    scene = TestCode(window=window)
    scene.run()