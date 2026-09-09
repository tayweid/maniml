"""Compare original redraw, bulk corners, and batched coordinate conversion.

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


def scalar_graph_samples(axes, function, ts):
    return np.array([axes.c2p(t, function(t)) for t in ts])


def compare(operation, samples, *, graph=False):
    bulk_corners = VMobject.add_points_as_corners
    bulk_append = Mobject.append_points
    batch_samples = Axes._get_graph_sample_points
    stages = {
        "original": (scalar_corners, legacy_append, scalar_graph_samples),
        "bulk_corners": (bulk_corners, bulk_append, scalar_graph_samples),
    }
    if graph:
        stages["batch_coordinates"] = (bulk_corners, bulk_append, batch_samples)
    names = tuple(stages)
    timings = {name: [] for name in names}
    # Warm every path. Rotate and reverse the order across measured rounds
    # so none of the three stages consistently runs first, middle, or last.
    for iteration in range(samples + 1):
        offset = iteration % len(names)
        order = names[offset:] + names[:offset]
        if len(names) > 2 and iteration % 2:
            order = order[::-1]
        for name in order:
            corners, append, sample_points = stages[name]
            with (patch.object(VMobject, "add_points_as_corners", corners),
                  patch.object(Mobject, "append_points", append),
                  patch.object(Axes, "_get_graph_sample_points", sample_points)):
                start = perf_counter()
                operation()
                elapsed = (perf_counter() - start) * 1000
            if iteration:
                timings[name].append(elapsed)
    medians = {name: median(values) for name, values in timings.items()}
    results = {f"{name}_median_ms": round(value, 3) for name, value in medians.items()}
    results["bulk_corners_speedup_vs_original"] = round(
        medians["original"] / medians["bulk_corners"], 2,
    )
    if graph:
        results.update({
            "batch_coordinates_speedup_vs_bulk_corners": round(
                medians["bulk_corners"] / medians["batch_coordinates"], 2,
            ),
            "batch_coordinates_speedup_vs_original": round(
                medians["original"] / medians["batch_coordinates"], 2,
            ),
        })
    return results


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
        results[f"redraw_alpha_{value}"] = compare(
            lambda: group.update(1 / 30), args.samples, graph=True,
        )
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
