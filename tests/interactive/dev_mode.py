"""Interactive dev-mode scenario: arrow-key navigation, re-execution,
reverse morphs, and file-watcher reload, in a real window.

Run directly:  python -m tests.interactive.dev_mode
"""
import os
import shutil
import sys
import tempfile

from tests.interactive.harness import WindowDriver, finish

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "nav_scene.py")


def script(d: WindowDriver):
    scene = d.scene
    d.pump(0.5)
    d.check_index("first unit auto-played", 1)
    circle = scene._live_namespace.get("circle")
    d.check("circle stroke is BLUE on screen",
            circle is not None
            and str(circle.get_stroke_color()).upper() == "#58C4DD")

    for _ in range(4):  # remaining 3 plays + tail wait unit
        d.right()
    d.check("all units executed (6 checkpoints incl. 0 and tail)",
            len(scene.animation_checkpoints) == 6)
    d.check_index("at last checkpoint", 5)

    d.right()
    d.check_index("extra RIGHT is a no-op", 5)

    d.up()
    d.up()
    d.check_index("UPx2 jumps back", 3)
    d.down()
    d.check_index("DOWN jumps forward", 4)

    d.left()
    d.check_index("LEFT reverses", 3)
    # This LEFT crosses the label's creation: it must disappear, not
    # morph into another mobject
    d.left()
    d.check_index("second LEFT reverses past label creation", 2)
    d.check("label gone after reverse past its creation",
            all("checkpoint 3" not in str(getattr(m, "text", ""))
                for m in scene.mobjects))

    d.right()
    d.check_index("RIGHT after navigation restores retained state", 3)

    d.edit_scene_file("checkpoint 3", "EDITED label")
    labels = [m for m in scene.mobjects
              if "EDITED" in str(getattr(m, "text", ""))]
    d.check("edited label on screen after watcher replay", len(labels) == 1)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        scene_file = os.path.join(tmp, "nav_scene.py")
        shutil.copy(FIXTURE, scene_file)
        driver = WindowDriver(scene_file, "NavScene")
        return finish(driver.run(script))


if __name__ == "__main__":
    sys.exit(main())
