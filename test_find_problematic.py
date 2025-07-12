from manim import *
import copy

class TestFindProblematic(Scene):
    def construct(self):
        # Create circle
        circle = Circle(color=RED)
        self.add(circle)
        self.play(Create(circle))
        
        # Try to find what's causing deepcopy to fail
        checkpoint = self.animation_checkpoints[-1]
        
        print("\nTesting deepcopy on individual items:")
        for name, value in checkpoint['namespace'].items():
            if name == 'self':
                continue
            try:
                copy.deepcopy(value)
                print(f"  ✓ {name}: {type(value).__name__}")
            except Exception as e:
                print(f"  ✗ {name}: {type(value).__name__} - {e}")
        
        # Try deepcopying the state separately
        print("\nTesting state deepcopy:")
        try:
            copy.deepcopy(checkpoint['state'])
            print("  ✓ State can be deepcopied")
        except Exception as e:
            print(f"  ✗ State failed: {e}")
            
        self.wait()