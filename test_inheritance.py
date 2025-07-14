#!/usr/bin/env python
"""Test inheritance."""

from manim.scene.scene import Scene
from manim.renderer.opengl.scene.scene import Scene as GLScene

print("=== Inheritance Test ===")

print("\n1. Our Scene:")
print(f"   Has play: {'play' in Scene.__dict__}")
print(f"   Play id: {id(Scene.play) if 'play' in Scene.__dict__ else 'N/A'}")

print("\n2. GL Scene:")  
print(f"   Has play: {'play' in GLScene.__dict__}")
print(f"   Play id: {id(GLScene.play) if 'play' in GLScene.__dict__ else 'N/A'}")

print("\n3. Creating instance and checking:")
scene = Scene()
print(f"   scene.play: {scene.play}")
print(f"   Type of play: {type(scene.play)}")

# Try calling it
print("\n4. Manually calling scene.play:")
Scene.play(scene, "dummy_animation")

print("\n5. Check if something is overriding after init:")
# Create new instance
scene2 = Scene()
original_play = scene2.play
print(f"   Original: {original_play}")

# Import rest of manim
from manim import *
print(f"   After import: {scene2.play}")
print(f"   Same? {original_play == scene2.play}")