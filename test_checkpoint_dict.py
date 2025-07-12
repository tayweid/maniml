from manim import *
import copy

class TestCheckpointDict(Scene):
    def construct(self):
        # Create circle
        circle = Circle(color=RED)
        self.add(circle)
        self.play(Create(circle))
        
        # Get checkpoint
        checkpoint = self.animation_checkpoints[-1]
        
        print(f"\nCheckpoint structure:")
        print(f"  Keys: {list(checkpoint.keys())}")
        print(f"  State type: {type(checkpoint['state'])}")
        print(f"  Namespace has {len(checkpoint['namespace'])} items")
        
        # Try deepcopying just the namespace
        print("\nTrying to deepcopy just namespace:")
        try:
            ns_copy = copy.deepcopy(checkpoint['namespace'])
            print("  ✓ Namespace deepcopy succeeded")
        except Exception as e:
            print(f"  ✗ Namespace deepcopy failed: {e}")
            
        # Try deepcopying the whole checkpoint dict
        print("\nTrying to deepcopy whole checkpoint:")
        try:
            cp_copy = copy.deepcopy(checkpoint)
            print("  ✓ Checkpoint deepcopy succeeded") 
            print(f"  Circle in copied namespace: {id(cp_copy['namespace'].get('circle'))}")
            if hasattr(cp_copy['state'], 'mobjects_to_copies'):
                print("  State mobjects:")
                for mob, cop in cp_copy['state'].mobjects_to_copies.items():
                    print(f"    - {type(mob).__name__} id={id(mob)}")
        except Exception as e:
            print(f"  ✗ Checkpoint deepcopy failed: {e}")
            
        self.wait()