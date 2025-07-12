from manim import *
import copy

class TestDebugDeepCopy(Scene):
    def construct(self):
        # Test what happens when we deepcopy individual items
        circle = Circle(color=RED)
        circle.name = "test_circle"
        
        print(f"\nOriginal circle ID: {id(circle)}")
        
        # Test 1: Can we deepcopy a circle?
        try:
            circle_copy = copy.deepcopy(circle)
            print(f"✓ Circle deepcopy succeeded: {id(circle_copy)}")
        except Exception as e:
            print(f"✗ Circle deepcopy failed: {e}")
            
        # Test 2: What about a dict with a circle?
        test_dict = {'circle': circle}
        try:
            dict_copy = copy.deepcopy(test_dict)
            print(f"✓ Dict deepcopy succeeded")
            print(f"  Original circle: {id(test_dict['circle'])}")
            print(f"  Copied circle: {id(dict_copy['circle'])}")
        except Exception as e:
            print(f"✗ Dict deepcopy failed: {e}")
            
        # Test 3: What's in our deepcopyable dict?
        from manim.scene.scene_utils import deepcopy_namespace
        
        # Manually check what gets filtered
        namespace = {'circle': circle, 'self': self, 'number': 42}
        
        # Simulate first pass of deepcopy_namespace
        deepcopyable = {}
        non_deepcopyable = {}
        
        for name, value in namespace.items():
            if name in ['__builtins__', '__loader__', '__spec__', '__cached__', 'self']:
                continue
                
            try:
                test_copy = copy.deepcopy(value)
                deepcopyable[name] = value
                print(f"✓ {name} is deepcopyable")
            except Exception:
                non_deepcopyable[name] = value
                print(f"✗ {name} is NOT deepcopyable")
                
        print(f"\nDeepCopyable items: {list(deepcopyable.keys())}")
        print(f"Non-deepcopyable items: {list(non_deepcopyable.keys())}")
        
        self.wait()