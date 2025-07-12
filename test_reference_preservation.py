from manim import *
from manim.mobject.geometry import Circle as CircleClass
import copy

class TestReferencePreservation(Scene):
    def construct(self):
        # Create circle
        circle = Circle(color=RED)
        self.add(circle)
        self.play(Create(circle))
        
        # Get checkpoint
        checkpoint = self.animation_checkpoints[-1]
        
        print(f"\nOriginal checkpoint:")
        print(f"  Circle in namespace: {id(checkpoint['namespace']['circle'])}")
        if hasattr(checkpoint['state'], 'mobjects_to_copies'):
            for mob, cop in checkpoint['state'].mobjects_to_copies.items():
                if isinstance(mob, Circle):
                    print(f"  Circle in state: original={id(mob)}, copy={id(cop)}")
        
        # Simulate what run_next_animation does
        from manim.scene.scene_utils import deepcopy_namespace
        checkpoint_copy = deepcopy_namespace(checkpoint)
        
        print(f"\nAfter deepcopy_namespace:")
        print(f"  Circle in copied namespace: {id(checkpoint_copy['namespace']['circle'])}")
        if hasattr(checkpoint_copy['state'], 'mobjects_to_copies'):
            print("  State mobjects:")
            for mob, cop in checkpoint_copy['state'].mobjects_to_copies.items():
                if isinstance(mob, Circle):
                    print(f"    Circle: original={id(mob)}, copy={id(cop)}")
                    
        # The key test: do they match?
        circle_in_namespace = checkpoint_copy['namespace']['circle']
        circle_in_state = None
        
        if hasattr(checkpoint_copy['state'], 'mobjects_to_copies'):
            for mob, cop in checkpoint_copy['state'].mobjects_to_copies.items():
                if isinstance(cop, Circle):
                    circle_in_state = cop
                    break
                    
        print(f"\n🔍 Key Test:")
        print(f"  Circle ID in namespace: {id(circle_in_namespace)}")
        print(f"  Circle ID in state copy: {id(circle_in_state) if circle_in_state else 'NOT FOUND'}")
        print(f"  ✓ MATCH!" if circle_in_namespace is circle_in_state else "  ✗ DIFFERENT OBJECTS!")
        
        self.wait()