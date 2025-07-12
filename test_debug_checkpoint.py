from manim import *

class TestDebugCheckpoint(Scene):
    def construct(self):
        # Create circle
        circle = Circle(color=RED).shift(LEFT)
        self.add(circle)
        
        # Print object IDs before play
        print(f"\nBefore play: circle id = {id(circle)}")
        
        self.play(Create(circle))
        
        # Check what's in the checkpoint
        checkpoint = self.animation_checkpoints[-1]
        print(f"\nAfter play checkpoint:")
        print(f"  - circle in namespace: {id(checkpoint['namespace'].get('circle', 'NOT FOUND'))}")
        if hasattr(checkpoint['state'], 'mobjects_to_copies'):
            for mob, copy in checkpoint['state'].mobjects_to_copies.items():
                print(f"  - state has mobject id={id(mob)} -> copy id={id(copy)}")
        
        # Create square
        square = Square(color=BLUE).shift(RIGHT) 
        print(f"\nBefore second play: square id = {id(square)}")
        self.play(Create(square))
        
        print("\nPress ← to go back, then → to play forward")
        print("Watch the console for ID mismatches")
        
        self.interactive_embed(terminal=False)