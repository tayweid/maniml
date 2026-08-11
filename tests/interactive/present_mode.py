"""Present-mode scenario: pre-run, timeline reveal/click/hide, and
navigation with the overlay live, in a real window.

Run directly:  python -m tests.interactive.present_mode
"""
import os
import sys

from tests.interactive.harness import WindowDriver, finish

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "nav_scene.py")


def script(d: WindowDriver):
    scene = d.scene
    d.pump(0.5)

    n = len(scene.animation_checkpoints)
    d.check("all checkpoints pre-built (6 incl. 0 and tail)", n == 6)
    d.check_index("rewound to checkpoint 0", 0)
    d.check("file watcher disabled", not scene.auto_reload_enabled)

    d.mouse_move(d.bottom_edge_point())
    group = scene._timeline_group
    d.check("timeline appears at bottom edge", group is not None)
    # parked timeline: n rings + (n-1) line segments + 1 pip
    d.check("parked timeline has rings, lines and pip",
            group is not None and len(group) == 2 * n)

    d.right()
    d.check_index("RIGHT advances", 1)
    d.check("timeline survives RIGHT without mouse move",
            scene._timeline_group is not None)
    d.check("pip returns after the unit finishes",
            scene._timeline_group is not None
            and len(scene._timeline_group) == 2 * n)

    scene._show_timeline(active_segment=(1, 2))
    d.check("animating timeline drops the pip",
            len(scene._timeline_group) == 2 * n - 1)
    scene._show_timeline()

    d.mouse_press(d.bottom_edge_point(scene._timeline_xs[3]))
    d.check_index("timeline click jumps", 3)
    d.check("timeline still visible after click",
            scene._timeline_group is not None)

    d.mouse_move([0.0, 0.0, 0.0])
    d.check("timeline hides away from the edge",
            scene._timeline_group is None)

    d.right()
    d.check_index("RIGHT re-executes after timeline jump", 4)
    d.check("timeline stays hidden", scene._timeline_group is None)


def main() -> int:
    driver = WindowDriver(FIXTURE, "NavScene", present=True)
    return finish(driver.run(script))


if __name__ == "__main__":
    sys.exit(main())
