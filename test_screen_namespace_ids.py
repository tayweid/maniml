from manim import *

class TestScreenNamespaceIds(Scene):
    def construct(self):
        # Animation 1: Create a circle
        circle = Circle()
        circle.set_fill(BLUE, opacity=0.8)
        print(f"\n=== BEFORE PLAY ===")
        print(f"circle in namespace: id={id(circle)}")
        
        self.play(Create(circle))
        
        print(f"\n=== AFTER PLAY ===")
        print(f"circle in namespace: id={id(circle)}")
        print(f"Mobjects on screen:")
        for mob in self.mobjects:
            if type(mob).__name__ == 'Circle':
                print(f"  Circle on screen: id={id(mob)}")
                print(f"  Same as namespace circle? {id(mob) == id(circle)}")
        
        # Animation 2: Transform to square
        square = Square()
        square.set_fill(RED, opacity=0.8)
        print(f"\n\n=== BEFORE TRANSFORM ===")
        print(f"circle in namespace: id={id(circle)}")
        print(f"square in namespace: id={id(square)}")
        
        self.play(Transform(circle, square))
        
        print(f"\n=== AFTER TRANSFORM ===")
        print(f"circle in namespace: id={id(circle)}")
        print(f"square in namespace: id={id(square)}")
        print(f"Mobjects on screen:")
        for mob in self.mobjects:
            if type(mob).__name__ in ['Circle', 'Square']:
                print(f"  {type(mob).__name__} on screen: id={id(mob)}")
                print(f"    Same as namespace circle? {id(mob) == id(circle)}")
                print(f"    Same as namespace square? {id(mob) == id(square)}")
        
        # Animation 3: Move
        print(f"\n\n=== BEFORE MOVE ===")
        print(f"circle in namespace: id={id(circle)}")
        
        self.play(circle.animate.shift(RIGHT * 2))
        
        print(f"\n=== AFTER MOVE ===")
        print(f"circle in namespace: id={id(circle)}")
        print(f"Mobjects on screen:")
        for mob in self.mobjects:
            if type(mob).__name__ in ['Circle', 'Square']:
                print(f"  {type(mob).__name__} on screen: id={id(mob)}")
                print(f"    Same as namespace circle? {id(mob) == id(circle)}")