from manim import *

class TestStateDebug(Scene):
    def construct(self):
        # Create circle  
        circle = Circle(color=RED)
        circle.name = "test_circle"
        self.add(circle)
        self.play(Create(circle))
        
        # Get checkpoint
        checkpoint = self.animation_checkpoints[-1]
        
        # Debug what's in the state
        print(f"\nOriginal State contents:")
        if hasattr(checkpoint['state'], 'mobjects_to_copies'):
            print(f"  Number of mobjects: {len(checkpoint['state'].mobjects_to_copies)}")
            for i, (mob, cop) in enumerate(checkpoint['state'].mobjects_to_copies.items()):
                mob_name = getattr(mob, 'name', 'unnamed')
                print(f"  [{i}] {type(mob).__name__} '{mob_name}': orig={id(mob)} -> copy={id(cop)}")
                
        # Deepcopy checkpoint
        from manim.scene.scene_utils import deepcopy_namespace
        checkpoint_copy = deepcopy_namespace(checkpoint)
        
        print(f"\nCopied State contents:")
        if hasattr(checkpoint_copy['state'], 'mobjects_to_copies'):
            print(f"  Number of mobjects: {len(checkpoint_copy['state'].mobjects_to_copies)}")
            for i, (mob, cop) in enumerate(checkpoint_copy['state'].mobjects_to_copies.items()):
                mob_name = getattr(mob, 'name', 'unnamed') if hasattr(mob, 'name') else 'no name attr'
                cop_name = getattr(cop, 'name', 'unnamed') if hasattr(cop, 'name') else 'no name attr'
                print(f"  [{i}] {type(mob).__name__} '{mob_name}' -> {type(cop).__name__} '{cop_name}'")
                print(f"       mob={id(mob)} -> cop={id(cop)}")
                
        print(f"\nNamespace circle: {id(checkpoint_copy['namespace']['circle'])}")
        print(f"Does any state mobject match? Let's check...")
        
        circle_from_namespace = checkpoint_copy['namespace']['circle']
        found = False
        for mob, cop in checkpoint_copy['state'].mobjects_to_copies.items():
            if mob is circle_from_namespace:
                print(f"  ✓ Found as key: mob={id(mob)}")
                found = True
            if cop is circle_from_namespace:
                print(f"  ✓ Found as value: cop={id(cop)}")
                found = True
                
        if not found:
            print(f"  ✗ Not found in state!")
            
        self.wait()