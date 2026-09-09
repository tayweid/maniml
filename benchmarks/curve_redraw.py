"""Compare bulk corner construction with the previous scalar append loop.

Runs mobject updates only: no scene, renderer, browser, or output files.
Run from the repository with ``python -m benchmarks.curve_redraw``.
"""

import argparse
import json
from statistics import median
from time import perf_counter
from unittest.mock import patch

import numpy as np

from maniml import Axes, Mobject, VGroup, VMobject, ValueTracker, always_redraw


def scalar_corners(mobject, points):
    for point in points:
        mobject.add_line_to(point)
    return mobject


@Mobject.affects_data
def legacy_append(mobject, points):
    n = mobject.get_num_points()
    mobject.resize_points(n + len(points))
    mobject.data[n:] = mobject.data[n - 1]
    mobject.data["point"][n:] = points
    mobject.refresh_bounding_box()
    return mobject


def compare(operation, samples):
    timings = {"scalar": [], "bulk": []}
    bulk_corners = VMobject.add_points_as_corners
    bulk_append = Mobject.append_points
    methods = {"scalar": scalar_corners, "bulk": bulk_corners}
    append_methods = {"scalar": legacy_append, "bulk": bulk_append}
    # Warm both paths, then alternate their order to reduce timing bias.
    for iteration in range(samples + 1):
        order = ("scalar", "bulk") if iteration % 2 == 0 else ("bulk", "scalar")
        for name in order:
            with (patch.object(VMobject, "add_points_as_corners", methods[name]),
                  patch.object(Mobject, "append_points", append_methods[name])):
                start = perf_counter()
                operation()
                elapsed = (perf_counter() - start) * 1000
            if iteration:
                timings[name].append(elapsed)
    scalar_ms, bulk_ms = (median(timings[name]) for name in ("scalar", "bulk"))
    return {
        "scalar_median_ms": round(scalar_ms, 3),
        "bulk_median_ms": round(bulk_ms, 3),
        "speedup": round(scalar_ms / bulk_ms, 2),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=20)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")

    axes = Axes(
        x_range=(0, 100, 100), y_range=(0, 100, 100), width=7, height=7,
    ).scale(0.7)
    alpha = ValueTracker(1)

    def bowed(x):
        a = alpha.get_value()
        return (100**a - x**a)**(1 / a)

    def curves():
        return VGroup(
            axes.plot(lambda x: 100 - x, x_range=(0, 100)),
            axes.plot(bowed, x_range=(0, 100, 0.1)),
        )

    x = np.linspace(0, 100, 1001)
    points = np.column_stack((x, 100 - x, np.zeros_like(x)))

    def corners():
        VMobject().start_new_path(points[0]).add_points_as_corners(points[1:])

    group = always_redraw(curves)
    results = {"samples": args.samples, "corners_1001": compare(corners, args.samples)}
    for value in (1.0, 1.5):
        alpha.set_value(value)
        results[f"redraw_alpha_{value}"] = compare(lambda: group.update(1 / 30), args.samples)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
