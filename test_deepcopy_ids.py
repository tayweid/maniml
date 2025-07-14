from manim import *
import sys

class TestDeepCopyIds(Scene):
    def construct(self):
        # Create a circle
        circle = Circle()
        circle.set_fill(BLUE, opacity=0.8)
        
        print(f"\n=== BEFORE DEEPCOPY ===")
        print(f"Original circle id: {id(circle)}")
        print(f"self.get_state() mobjects:")
        state = self.get_state()
        for mob, copy in state.mobjects_to_copies.items():
            print(f"  {type(mob).__name__}: original={id(mob)}, copy={id(copy)}")
        
        # Create namespace with state
        namespace = {'circle': circle, '__checkpoint_state__': state}
        
        # Deepcopy
        # Import deepcopy_namespace from the scene module
        from manim.scene.scene import deepcopy_namespace
        copied_namespace = deepcopy_namespace(namespace)
        copied_state = copied_namespace.pop('__checkpoint_state__')
        
        print(f"\n=== AFTER DEEPCOPY ===")
        print(f"Copied circle id: {id(copied_namespace['circle'])}")
        print(f"Copied state mobjects:")
        for mob, copy in copied_state.mobjects_to_copies.items():
            print(f"  {type(mob).__name__}: original={id(mob)}, copy={id(copy)}")
        
        # Check if the circle in namespace matches any in state
        circle_in_namespace = copied_namespace['circle']
        print(f"\n=== ID MATCHING ===")
        print(f"Circle in namespace: {id(circle_in_namespace)}")
        
        found_match = False
        for mob, copy in copied_state.mobjects_to_copies.items():
            if id(mob) == id(circle_in_namespace):
                print(f"  ✓ Found match as original: {type(mob).__name__}")
                found_match = True
            if id(copy) == id(circle_in_namespace):
                print(f"  ✓ Found match as copy: {type(copy).__name__}")
                found_match = True
        
        if not found_match:
            print(f"  ✗ No match found in state!")
            
        # Now play animation to see what happens
        self.play(Create(circle))
        print(f"\n=== AFTER PLAY ===")
        print(f"Circle id after play: {id(circle)}")