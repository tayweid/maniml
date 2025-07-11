#!/usr/bin/env python3
"""Test only pathops without manim."""

try:
    from pathops import Path, PathVerb, intersection
    print("Successfully imported pathops")
    
    # Create two simple paths
    path1 = Path()
    path1.moveTo(0, 0)
    path1.lineTo(1, 0)
    path1.lineTo(1, 1)
    path1.lineTo(0, 1)
    path1.close()
    print("Created path1")
    
    path2 = Path()
    path2.moveTo(0.5, 0.5)
    path2.lineTo(1.5, 0.5)
    path2.lineTo(1.5, 1.5)
    path2.lineTo(0.5, 1.5)
    path2.close()
    print("Created path2")
    
    # Try intersection
    result = Path()
    intersection([path1], [path2], result.getPen())
    print("Intersection successful!")
    
    # Print result
    for verb, points in result:
        print(f"Verb: {verb}, Points: {points}")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()