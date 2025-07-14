#!/usr/bin/env python
"""Test play directly."""

from manim import Scene, Circle, Create

# Create a scene instance
scene = Scene()

# Check initial state
print(f"Initial state:")
print(f"  _animations_to_play: {scene._animations_to_play}")
print(f"  _animations_played: {scene._animations_played}")
print(f"  play method: {scene.play}")

# Create a circle and animation
circle = Circle()
create_anim = Create(circle)

print(f"\nCalling play directly...")
result = scene.play(create_anim)

print(f"\nAfter play:")
print(f"  _animations_played: {scene._animations_played}")
print(f"  Result: {result}")