from manim import *

class TestCheckpointIds(Scene):
    def construct(self):
        # Animation 1: Create a circle
        circle = Circle()
        circle.set_fill(BLUE, opacity=0.8)
        print(f"\nBefore play: circle id = {id(circle)}")
        self.play(Create(circle))
        print(f"After play: circle id = {id(circle)}")
        
        # Check checkpoint 1
        checkpoint = self.animation_checkpoints[-1]
        print(f"\n=== Checkpoint 1 Analysis ===")
        print(f"SceneState mobjects:")
        for mob, copy in checkpoint['state'].mobjects_to_copies.items():
            print(f"  Original: {type(mob).__name__} id={id(mob)}")
            print(f"  Copy: {type(copy).__name__} id={id(copy)}")
        
        print(f"\nNamespace variables:")
        for name, value in checkpoint['namespace'].items():
            if isinstance(value, Mobject):
                print(f"  {name}: {type(value).__name__} id={id(value)}")
        
        # Animation 2: Transform to square
        square = Square()
        square.set_fill(RED, opacity=0.8)
        print(f"\n\nBefore transform: square id = {id(square)}, circle id = {id(circle)}")
        self.play(Transform(circle, square))
        print(f"After transform: circle id = {id(circle)}")
        
        # Check checkpoint 2
        checkpoint = self.animation_checkpoints[-1]
        print(f"\n=== Checkpoint 2 Analysis ===")
        print(f"SceneState mobjects:")
        for mob, copy in checkpoint['state'].mobjects_to_copies.items():
            print(f"  Original: {type(mob).__name__} id={id(mob)}")
            print(f"  Copy: {type(copy).__name__} id={id(copy)}")
        
        print(f"\nNamespace variables:")
        for name, value in checkpoint['namespace'].items():
            if isinstance(value, Mobject):
                print(f"  {name}: {type(value).__name__} id={id(value)}")