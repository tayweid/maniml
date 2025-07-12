from manim import *
import copy

class TestCheckpointDeepCopy(Scene):
    def construct(self):
        # Create circle
        circle = Circle(color=RED)
        circle.name = "test_circle"
        self.add(circle)
        self.play(Create(circle))
        
        # Get checkpoint
        checkpoint = self.animation_checkpoints[-1]
        
        print(f"\nOriginal checkpoint structure:")
        print(f"  Type: {type(checkpoint)}")
        print(f"  Keys: {list(checkpoint.keys())}")
        print(f"  Circle in namespace: {id(checkpoint['namespace']['circle'])}")
        
        # Test what deepcopy_namespace does with a checkpoint dict
        from manim.scene.scene_utils import deepcopy_namespace
        
        print("\nCalling deepcopy_namespace(checkpoint)...")
        result = deepcopy_namespace(checkpoint)
        
        print(f"\nResult:")
        print(f"  Type: {type(result)}")
        print(f"  Keys: {list(result.keys()) if isinstance(result, dict) else 'N/A'}")
        
        if isinstance(result, dict) and 'namespace' in result:
            print(f"  Circle in result['namespace']: {id(result['namespace'].get('circle', 'NOT FOUND'))}")
        else:
            print(f"  Circle in result: {id(result.get('circle', 'NOT FOUND')) if isinstance(result, dict) else 'N/A'}")
            
        # Also test just the namespace
        print("\nCalling deepcopy_namespace(checkpoint['namespace'])...")
        ns_result = deepcopy_namespace(checkpoint['namespace'])
        print(f"  Circle in ns_result: {id(ns_result.get('circle', 'NOT FOUND'))}")
        
        self.wait()