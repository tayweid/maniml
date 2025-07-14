"""Main entry point for maniml command."""

import sys
import os
import importlib.util

def main():
    """Main entry point for maniml command."""
    
    if len(sys.argv) < 2 or '--help' in sys.argv or '-h' in sys.argv:
        print("""
maniml - Standalone Manim without external dependencies

Usage: maniml [file] [Scene] [options]

Options:
  --help           Show this help message
  -p, --preview    Preview animation after rendering
  -e, --embed      Run in embed mode (interactive)

Examples:
  maniml example.py MyScene
  maniml example.py MyScene -p
""")
        sys.exit(0)
    
    # Get the file and scene name
    script_file = sys.argv[1]
    
    if not os.path.exists(script_file):
        print(f"Error: File '{script_file}' not found")
        sys.exit(1)
    
    # Use ManimGL's main runner which handles everything properly
    # First, modify sys.argv to match what ManimGL expects
    original_argv = sys.argv.copy()
    
    # Convert our simple args to ManimGL args
    gl_args = ['manimgl', script_file]
    if len(sys.argv) > 2:
        gl_args.append(sys.argv[2])  # Scene name
    
    # Check for embed mode
    if '-e' in sys.argv or '--embed' in sys.argv:
        gl_args.extend(['-e', '1'])  # Default to line 1 if not specified
    
    sys.argv = gl_args
    
    try:
        # Import and run ManimGL's main
        from manim.extract_scene import main as gl_main
        gl_main()
    except ImportError:
        # Fallback to our simple runner
        sys.argv = original_argv
        run_simple(script_file)
    finally:
        sys.argv = original_argv

def run_simple(script_file):
    """Simple runner when GL main is not available."""
    spec = importlib.util.spec_from_file_location("__main__", script_file)
    module = importlib.util.module_from_spec(spec)
    
    # Import manim into the module's namespace
    import manim
    module.__dict__.update({k: v for k, v in manim.__dict__.items() if not k.startswith('_')})
    
    # Execute the module
    spec.loader.exec_module(module)
    
    # If scene name provided, try to render it
    if len(sys.argv) > 2:
        scene_name = sys.argv[2]
        if hasattr(module, scene_name):
            scene_class = getattr(module, scene_name)
            if callable(scene_class):
                # Always create window for preview mode (default)
                from manim.window import Window
                window = Window()
                scene = scene_class(window=window)
                # Pass the script file path to the scene
                scene._scene_filepath = os.path.abspath(script_file)
                scene.run()
        else:
            print(f"Error: Scene '{scene_name}' not found in {script_file}")
            sys.exit(1)

if __name__ == '__main__':
    main()