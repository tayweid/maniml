#!/usr/bin/env python
"""Debug imports."""

# First, let's check what happens with basic imports
print("=== Import Analysis ===")

print("\n1. Importing from manim directly:")
from manim import Scene as MainScene
print(f"   manim.Scene: {MainScene}")
print(f"   Module: {MainScene.__module__}")
print(f"   Has play: {hasattr(MainScene, 'play')}")
print(f"   Play method: {MainScene.play}")

print("\n2. Importing from manim.scene.scene:")
from manim.scene.scene import Scene as DirectScene
print(f"   Direct Scene: {DirectScene}")
print(f"   Module: {DirectScene.__module__}")
print(f"   Has play: {hasattr(DirectScene, 'play')}")
print(f"   Play method: {DirectScene.play}")

print("\n3. Are they the same?")
print(f"   MainScene is DirectScene: {MainScene is DirectScene}")

print("\n4. Method resolution order:")
print(f"   MRO: {DirectScene.__mro__}")

print("\n5. Where is play defined?")
for cls in DirectScene.__mro__:
    if 'play' in cls.__dict__:
        print(f"   {cls} defines play")

print("\n6. Testing instance:")
scene = DirectScene()
print(f"   Instance play: {scene.play}")
print(f"   Instance dict keys: {[k for k in scene.__dict__ if 'animation' in k]}")