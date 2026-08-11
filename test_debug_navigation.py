from manim import *

class TestDebugNavigation(Scene):
    def construct(self):
        # Let's add debugging to see what's happening
        import inspect
        
        # Animation 1
        c = Circle()
        print(f"About to play animation 1 at line {inspect.currentframe().f_lineno}")
        self.play(Create(c))
        
        # Animation 2  
        print(f"About to play animation 2 at line {inspect.currentframe().f_lineno}")
        self.play(c.animate.shift(RIGHT))
        
        # Animation 3
        print(f"About to play animation 3 at line {inspect.currentframe().f_lineno}")
        self.play(c.animate.shift(LEFT * 2))
        
        # Animation 4
        print(f"About to play animation 4 at line {inspect.currentframe().f_lineno}")
        self.play(c.animate.scale(2))
        
        print("All animations complete")
        self.wait(1)