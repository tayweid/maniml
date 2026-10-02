"""What the app knows about scene files, with no server anywhere in sight.

Pure functions over the filesystem: which classes in a file are scenes
(by AST, so opening the landing page never executes user code), and the
recents list that *is* the landing page. Both the app and the viewer's
scene picker need these, and neither should have to import the app's
subprocess and relay machinery to get them.
"""

from __future__ import annotations

import ast
import json
import os



def recents_path() -> str:
    """Where the recents list lives: named outright by MANIML_RECENTS_PATH,
    else inside MANIML_CONFIG_DIR (the folder the Claerbout shell gives its
    engine for everything it keeps; removing that folder returns the app to
    its first launch), else the home-folder file a terminal's `maniml app`
    has always used."""
    named = os.environ.get("MANIML_RECENTS_PATH")
    if named:
        return named
    config_dir = os.environ.get("MANIML_CONFIG_DIR")
    if config_dir:
        return os.path.join(config_dir, "recents.json")
    return os.path.expanduser("~/.maniml_recents.json")


RECENTS_PATH = recents_path()
RECENTS_MAX = 12


def find_scene_classes(path: str) -> list[str]:
    """Scene classes in a file via AST — no import, no side effects.
    Heuristic: a class whose base names end with 'Scene'."""
    try:
        with open(path) as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError):
        return []
    scenes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = getattr(base, "id", getattr(base, "attr", ""))
            if isinstance(name, str) and name.endswith("Scene"):
                scenes.append(node.name)
                break
    return scenes


def load_recents() -> list[str]:
    try:
        with open(RECENTS_PATH) as f:
            recents = json.load(f)
        return [p for p in recents if isinstance(p, str)]
    except (OSError, ValueError):
        return []


def remember_recent(path: str) -> None:
    recents = [p for p in load_recents() if p != path]
    recents.insert(0, path)
    try:
        with open(RECENTS_PATH, "w") as f:
            json.dump(recents[:RECENTS_MAX], f)
    except OSError:
        pass
