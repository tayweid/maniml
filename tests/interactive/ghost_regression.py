"""Regression scenario for the ghost-mobject bug: animating a group
whose .animate builders were stored in a namespace variable must not
leave a stale duplicate behind (checkpoint deepcopy identity).

Run directly:  python -m tests.interactive.ghost_regression
"""
import os
import sys

from tests.interactive.harness import WindowDriver, finish

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "ghost_scene.py")


def script(d: WindowDriver):
    scene = d.scene
    d.pump(0.3)
    d.right()  # flash loop (one source unit, two play checkpoints)
    ns = scene._live_namespace
    d.check("one content mobject after flash loop",
            len(d.content_mobjects()) == 1)

    d.right()  # group.animate.to_edge(UP)
    mobs = d.content_mobjects()
    d.check("still one content mobject after group move (no ghost)",
            len(mobs) == 1)
    ns = scene._live_namespace
    group = ns.get("group")
    d.check("namespace group is the on-screen group",
            any(group is m for m in mobs))
    d.check("namespace squares[0] is a child of the group",
            any(ns["squares"][0] is c for c in group.get_family()))
    d.check("group actually moved up", group.get_center()[1] > 1)

    # The reported failure required moving backward and then forward over
    # the retained checkpoint.  RIGHT must restore that checkpoint, not
    # re-run the source and leave the pre-move group beside a fresh copy.
    d.left()
    d.check("one content mobject after moving back",
            len(d.content_mobjects()) == 1)
    d.right()
    mobs = d.content_mobjects()
    d.check("one content mobject after retained forward navigation",
            len(mobs) == 1)
    group = d.scene._live_namespace.get("group")
    d.check("retained forward state is the moved group",
            group is not None and group.get_center()[1] > 1)


def main() -> int:
    driver = WindowDriver(FIXTURE, "GhostScene")
    return finish(driver.run(script))


if __name__ == "__main__":
    sys.exit(main())
