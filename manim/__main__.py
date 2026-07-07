"""Main entry point for maniml command."""

import sys
import os
import importlib.util


USAGE = """
maniml - ManimCE-compatible API on an OpenGL backend

Usage: maniml [file] [Scene]

Options:
  --help, -h       Show this help message

Interactive controls (in the preview window):
  RIGHT arrow      Run the next animation (re-executed from source)
  LEFT arrow       Step back to the previous checkpoint
  UP/DOWN arrows   Jump between checkpoints
  Saving the scene file auto-reloads from the last safe checkpoint

Examples:
  maniml example.py MyScene
"""


def main():
    """Main entry point for maniml command."""
    args = [a for a in sys.argv[1:] if not a.startswith('-')]

    if not args or '--help' in sys.argv or '-h' in sys.argv:
        print(USAGE)
        sys.exit(0)

    script_file = args[0]
    scene_name = args[1] if len(args) > 1 else None

    if not os.path.exists(script_file):
        print(f"Error: File '{script_file}' not found")
        sys.exit(1)

    run_scene(script_file, scene_name)


def load_scene_module(script_file):
    """Load the user's scene file as a real module registered in sys.modules.

    Registering the module is what lets the checkpoint system find the
    scene file's namespace later (Scene._create_checkpoint_zero scans
    sys.modules by __file__).
    """
    script_file = os.path.abspath(script_file)
    module_name = os.path.splitext(os.path.basename(script_file))[0]
    spec = importlib.util.spec_from_file_location(module_name, script_file)
    module = importlib.util.module_from_spec(spec)

    # Pre-populate with manim's public names so plain scene files work
    # even without `from manim import *`.
    import manim
    module.__dict__.update({k: v for k, v in manim.__dict__.items() if not k.startswith('_')})

    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def run_scene(script_file, scene_name):
    module = load_scene_module(script_file)

    if scene_name is None:
        from manim.scene.scene import Scene
        scenes = [
            name for name, obj in vars(module).items()
            if isinstance(obj, type) and issubclass(obj, Scene)
            and obj.__module__ == module.__name__
        ]
        if len(scenes) == 1:
            scene_name = scenes[0]
        else:
            print("Error: Specify a scene name. " +
                  (f"Available scenes: {', '.join(scenes)}" if scenes
                   else f"No scenes found in {script_file}"))
            sys.exit(1)

    scene_class = getattr(module, scene_name, None)
    if scene_class is None or not callable(scene_class):
        print(f"Error: Scene '{scene_name}' not found in {script_file}")
        sys.exit(1)

    from manim.rendering.window import Window
    window = Window()
    scene = scene_class(window=window)
    scene._scene_filepath = os.path.abspath(script_file)
    scene.run()


if __name__ == '__main__':
    main()
