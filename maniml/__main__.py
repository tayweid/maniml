"""Main entry point for maniml command."""

import sys
import os
import traceback
import importlib
import importlib.abc
import importlib.machinery
import importlib.util

USAGE = """
maniml - ManimCE-compatible API on an OpenGL backend

Usage: maniml [file] [Scene] [mode]
       maniml app [dir]
       maniml agent [install [dir] | open | status | uninstall]

App:
  maniml app       Persistent local app: a landing page listing the
                   scene files under [dir] (default: cwd); each scene
                   opens in the browser viewer, one process per scene
  --allow-outside-root
                   Allow the app to open explicitly entered scene paths
                   outside [dir] (off by default)
  maniml agent install [dir]
                   Keep the app running as a macOS login agent, so
                   http://localhost:8685 is always there
  maniml agent open | status | restart | uninstall

Modes:
  (default)        Interactive development: window + hot-reload
  --web            Same interactive development, viewed in the browser
                   instead of a native window (combines with --present)
  --present        Presentation: pre-runs every animation up front
                   (validating the whole scene), disables the file
                   watcher, then starts at the first checkpoint
  --render         No window: write the scene to a video file and
                   each checkpoint to a PNG, under ./media/
  --export         Bake the scene into a self-contained web player
                   (./media/SceneName_web/) — a static folder anyone
                   can open in a browser with no Python; host it on
                   GitHub Pages to share
  --help, -h       Show this help message

Interactive controls (in the preview window):
  RIGHT arrow      Run the next animation (re-executed from source)
  LEFT arrow       Reverse to the previous checkpoint (animated)
  UP/DOWN arrows   Jump between checkpoints instantly
  Saving the scene file auto-reloads from the last safe checkpoint
  Timeline         (--present) move the mouse to the bottom edge for
                   a clickable checkpoint timeline

Examples:
  maniml example.py MyScene
  maniml example.py MyScene --present
  maniml example.py MyScene --render
"""


def main():
    """Main entry point for maniml command."""
    flags = {a for a in sys.argv[1:] if a.startswith("-")}
    args = [a for a in sys.argv[1:] if not a.startswith("-")]

    if args and args[0] == "agent":
        from pathlib import Path

        from maniml import agent as agent_module

        action = args[1] if len(args) > 1 else "status"
        target = args[2] if len(args) > 2 else None
        port = agent_module.DEFAULT_APP_PORT
        for flag in flags:
            if flag.startswith("--port="):
                port = int(flag.split("=", 1)[1])
        if action == "install":
            sys.exit(agent_module.install(target, port))
        if action == "serve":
            sys.exit(agent_module.serve(target or str(Path.home()), port))
        if action == "uninstall":
            sys.exit(agent_module.uninstall())
        if action == "status":
            sys.exit(agent_module.status())
        if action == "restart":
            sys.exit(agent_module.restart())
        if action == "open":
            sys.exit(agent_module.open_app())
        print(
            "Usage: maniml agent "
            "[install [dir] | open | status | restart | uninstall]"
        )
        sys.exit(1)

    if args and args[0] == "app":
        from maniml.web.app import run_app

        run_app(
            root=args[1] if len(args) > 1 else ".",
            open_browser="--no-browser" not in flags,
            allow_outside_root="--allow-outside-root" in flags,
            # Only the command a person typed may reuse a running engine or
            # ask about the login agent; `maniml agent serve` is the agent.
            offer_agent=True,
        )
        return

    if not args or "--help" in flags or "-h" in flags:
        print(USAGE)
        sys.exit(0)

    unknown = flags - {"--present", "--render", "--web", "--no-browser", "--export"}
    if unknown:
        print(f"Unknown option(s): {', '.join(sorted(unknown))}")
        print(USAGE)
        sys.exit(1)

    script_file = args[0]
    scene_name = args[1] if len(args) > 1 else None

    if not os.path.exists(script_file):
        print(f"Error: File '{script_file}' not found")
        sys.exit(1)

    run_scene(
        script_file,
        scene_name,
        present="--present" in flags,
        render="--render" in flags,
        web="--web" in flags,
        export="--export" in flags,
        open_browser="--no-browser" not in flags,
    )


class _CEAliasLoader(importlib.abc.Loader):
    """Loader that hands back an existing maniml module unchanged."""

    def __init__(self, module):
        self.module = module

    def create_module(self, spec):
        return self.module

    def exec_module(self, module):
        pass


class _CEAliasFinder(importlib.abc.MetaPathFinder):
    """Resolve `manim` and `manim.*` imports to the maniml package.

    Installed only inside the maniml CLI process so unmodified ManimCE
    scene files (`from manim import *`) run under maniml, while a real
    ManimCE install on the same machine is untouched everywhere else.
    Aliased submodules are the *same objects* as the maniml ones, so
    nothing executes twice and isinstance checks agree.
    """

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "manim" and not fullname.startswith("manim."):
            return None
        real_module = importlib.import_module("maniml" + fullname[5:])
        return importlib.machinery.ModuleSpec(fullname, _CEAliasLoader(real_module))


def install_ce_import_alias():
    import maniml

    if sys.modules.get("manim") is not maniml:
        sys.modules["manim"] = maniml
        sys.meta_path.insert(0, _CEAliasFinder())


def load_scene_module(script_file):
    """Load the user's scene file as a real module registered in sys.modules.

    Registering the module is what lets the checkpoint system find the
    scene file's namespace later (Scene._create_checkpoint_zero scans
    sys.modules by __file__).
    """
    install_ce_import_alias()
    script_file = os.path.abspath(script_file)
    module_name = os.path.splitext(os.path.basename(script_file))[0]
    spec = importlib.util.spec_from_file_location(module_name, script_file)
    module = importlib.util.module_from_spec(spec)

    # Pre-populate with maniml's public names so plain scene files work
    # even without an import line.
    import maniml

    module.__dict__.update(
        {k: v for k, v in maniml.__dict__.items() if not k.startswith("_")}
    )

    sys.modules[module_name] = module
    # Compile the source directly instead of spec.loader.exec_module():
    # the loader's bytecode cache validates by (mtime, size) with
    # one-second granularity, so a quick same-size edit (e.g. changing a
    # constant) can silently reload stale bytecode during auto-reload.
    with open(script_file) as f:
        source = f.read()
    exec(compile(source, script_file, "exec"), module.__dict__)
    return module


def _run_web_scenes(viewer, script_file, scene_name, scene_class, present):
    """Serve one scene after another through a single browser viewer.

    Picking another scene from the file sets a pending switch and ends the
    current scene's interaction loop. The viewer itself is deliberately not
    destroyed in between, so the next scene reuses the same server and the same
    connected tab — the client sees the scene change, not a disconnect.

    The module is re-imported per scene for the same reason `_restart_from_source`
    does it: the previous scene may have mutated module-level state.
    """
    source_path = os.path.abspath(script_file)
    while True:
        scene = scene_class(window=viewer)
        scene._present_mode = present
        scene._scene_filepath = source_path
        scene.run()

        pending = viewer.take_pending_scene()
        if pending is None:
            return
        try:
            module = load_scene_module(script_file)
            next_class = getattr(module, pending, None)
        except Exception:
            traceback.print_exc()
            next_class = None
        if next_class is None or not callable(next_class):
            print(f"Error: Scene '{pending}' could not be loaded; keeping {scene_name}")
            return
        scene_name, scene_class = pending, next_class


def run_scene(
    script_file,
    scene_name,
    present=False,
    render=False,
    web=False,
    export=False,
    open_browser=True,
):
    module = load_scene_module(script_file)

    if scene_name is None:
        from maniml.scene.scene import Scene

        scenes = [
            name
            for name, obj in vars(module).items()
            if isinstance(obj, type)
            and issubclass(obj, Scene)
            and obj.__module__ == module.__name__
        ]
        if len(scenes) == 1:
            scene_name = scenes[0]
        else:
            print(
                "Error: Specify a scene name. "
                + (
                    f"Available scenes: {', '.join(scenes)}"
                    if scenes
                    else f"No scenes found in {script_file}"
                )
            )
            sys.exit(1)

    scene_class = getattr(module, scene_name, None)
    if scene_class is None or not callable(scene_class):
        print(f"Error: Scene '{scene_name}' not found in {script_file}")
        sys.exit(1)

    if export:
        from maniml.web.export import export_scene

        media_dir = os.path.join(os.path.dirname(os.path.abspath(script_file)), "media")
        scene = scene_class(window=None)
        scene._scene_filepath = os.path.abspath(script_file)
        out_dir = export_scene(scene, os.path.join(media_dir, f"{scene_name}_web"))
        print(f"Exported web player: {out_dir}")
        print(
            "Serve it with any static host, e.g. "
            f"cd {out_dir} && python3 -m http.server"
        )
        return

    if render:
        media_dir = os.path.join(os.path.dirname(os.path.abspath(script_file)), "media")
        scene = scene_class(
            window=None,
            file_writer_config=dict(
                write_to_movie=True,
                output_directory=media_dir,
                file_name=scene_name,
            ),
        )
        scene._render_mode = True
    elif web:
        from maniml.web import WebViewer

        viewer = WebViewer(open_browser=open_browser)
        _run_web_scenes(viewer, script_file, scene_name, scene_class, present)
        return
    else:
        from maniml.rendering.window import Window

        window = Window()
        scene = scene_class(window=window)
        scene._present_mode = present

    scene._scene_filepath = os.path.abspath(script_file)
    scene.run()


if __name__ == "__main__":
    main()
