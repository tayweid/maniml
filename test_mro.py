#!/usr/bin/env python
"""Test method resolution order."""

from manim.scene.scene import Scene
from manim.renderer.opengl.scene.scene import Scene as GLScene

print("Method Resolution Order:")
for i, cls in enumerate(Scene.__mro__):
    print(f"{i}: {cls}")
    if hasattr(cls, 'play') and 'play' in cls.__dict__:
        print(f"   -> defines play()")

# Check play method
print(f"\nScene.play method: {Scene.play}")
print(f"GLScene.play method: {GLScene.play}")
print(f"Are they the same? {Scene.play == GLScene.play}")

# Check which play is being used
scene = Scene()
print(f"\nInstance play method: {scene.play}")
print(f"Is it Scene's play? {scene.play.__func__ == Scene.play}")
print(f"Is it GLScene's play? {scene.play.__func__ == GLScene.play}")