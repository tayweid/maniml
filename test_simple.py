#!/usr/bin/env python3
"""Simple test to check imports."""

import sys
print("Python path:")
for p in sys.path:
    print(f"  {p}")

print("\nTrying to import manim...")
try:
    import manim
    print(f"Success! manim imported from: {manim.__file__}")
    print(f"manim version: {manim.__version__}")
    
    print("\nChecking Scene...")
    print(f"Scene available: {'Scene' in dir(manim)}")
    if hasattr(manim, 'Scene'):
        print(f"Scene type: {type(manim.Scene)}")
    
    print("\nChecking Table...")
    print(f"Table available: {'Table' in dir(manim)}")
    if hasattr(manim, 'Table'):
        print(f"Table type: {type(manim.Table)}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

print("\nTrying direct imports...")
try:
    from manim import Scene, Table, MathTable
    print("Direct imports successful!")
    print(f"Scene: {Scene}")
    print(f"Table: {Table}")
    print(f"MathTable: {MathTable}")
except Exception as e:
    print(f"Direct import error: {e}")
    import traceback
    traceback.print_exc()