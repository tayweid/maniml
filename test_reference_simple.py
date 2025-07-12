from manim import *

class TestReferenceSimple(Scene):
    def construct(self):
        # Create circle  
        circle = Circle(color=RED)
        circle.name = "test_circle"  # Give it a name to find it later
        self.add(circle)
        self.play(Create(circle))
        
        # Get checkpoint
        checkpoint = self.animation_checkpoints[-1]
        
        print(f"\nBEFORE deepcopy:")
        circle_id = id(checkpoint['namespace']['circle'])
        print(f"  Circle in namespace: {circle_id}")
        
        # Find circle in state by checking all mobjects
        state_circle_id = None
        if hasattr(checkpoint['state'], 'mobjects_to_copies'):
            for mob, cop in checkpoint['state'].mobjects_to_copies.items():
                if hasattr(mob, 'name') and mob.name == "test_circle":
                    state_circle_id = id(mob)
                    print(f"  Circle in state (original): {state_circle_id}")
                    break
        
        # Simulate what run_next_animation does
        from manim.scene.scene_utils import deepcopy_namespace
        checkpoint_copy = deepcopy_namespace(checkpoint)
        
        print(f"\nAFTER deepcopy:")
        copied_circle_id = id(checkpoint_copy['namespace']['circle'])
        print(f"  Circle in namespace: {copied_circle_id}")
        
        # Find circle in copied state
        copied_state_circle_id = None
        if hasattr(checkpoint_copy['state'], 'mobjects_to_copies'):
            for mob, cop in checkpoint_copy['state'].mobjects_to_copies.items():
                if hasattr(cop, 'name') and cop.name == "test_circle":
                    copied_state_circle_id = id(cop)
                    print(f"  Circle in state (copy): {copied_state_circle_id}")
                    break
                    
        print(f"\n🔍 RESULT:")
        if copied_circle_id == copied_state_circle_id:
            print(f"  ✓ SUCCESS! Both reference the same object: {copied_circle_id}")
        else:
            print(f"  ✗ FAIL! Different objects:")
            print(f"    Namespace: {copied_circle_id}")  
            print(f"    State: {copied_state_circle_id}")
            
        self.wait()