import sys
sys.path.append('/Users/taylorjweidman/PROJECTS/ManimLive/maniml')

from manim import Text, Circle, VMobject

# Quick test to understand text structure
text = Text("Test")
circle = Circle()

print("=== TEXT STRUCTURE ===")
print(f"Text type: {type(text)}")
print(f"Text is VMobject: {isinstance(text, VMobject)}")
print(f"Text submobjects: {len(text.submobjects)}")
print(f"Text family size: {len(text.get_family())}")

print("\n=== CIRCLE STRUCTURE ===")
print(f"Circle type: {type(circle)}")
print(f"Circle is VMobject: {isinstance(circle, VMobject)}")
print(f"Circle submobjects: {len(circle.submobjects)}")
print(f"Circle family size: {len(circle.get_family())}")

# Check if text has multiple paths
if len(text.submobjects) > 0:
    print("\n=== TEXT SUBMOBJECTS ===")
    for i, sub in enumerate(text.submobjects):
        print(f"Submob {i}: type={type(sub).__name__}, has_points={len(sub.points) > 0}")