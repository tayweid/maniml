#!/usr/bin/env python3
"""Run scene with GL backend directly."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Import manim
from manim import *

# Import the GL runner
from manim.renderer.opengl.config import manim_config
from manim.renderer.opengl.window import Window

def run_scene_from_file(file_path, scene_name):
    """Run a scene from a file."""
    # Import the file as a module
    import importlib.util
    spec = importlib.util.spec_from_file_location("user_scene", file_path)
    module = importlib.util.module_from_spec(spec)
    
    # Import manim into module namespace
    import manim
    for name in dir(manim):
        if not name.startswith('_'):
            setattr(module, name, getattr(manim, name))
    
    # Execute the module
    spec.loader.exec_module(module)
    
    # Get the scene class
    if hasattr(module, scene_name):
        scene_class = getattr(module, scene_name)
        
        # Create window and run scene
        window = Window()
        scene = scene_class(window=window)
        scene.run()
    else:
        print(f"Scene {scene_name} not found in {file_path}")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        run_scene_from_file(sys.argv[1], sys.argv[2])
    else:
        print("Usage: python run_scene.py <file> <SceneName>")