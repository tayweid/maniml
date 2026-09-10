"""Compare full-frame and bounded winding fills on the same GPU and pixels.

Run from a checkout with wgpu installed: python -m benchmarks.vector_fill.
Uses the self-contained B0 regression fixture; no course files or GL context.
Timings include submission and one-pixel readback, not pure GPU timestamps.
"""

import argparse
from copy import deepcopy
import json
from statistics import median
from time import perf_counter
from types import SimpleNamespace

import numpy as np

from maniml import Square, VGroup
from tests.winding_reference_geometry import parse_geometry_message, serialize_scene
from tests.winding_reference_renderer import WgpuRenderer
from tests.test_fill_bounds import _wordmark


def payload(mobject):
    # Same 2160x1080 output and 24x12 camera used for the original dogfood
    # measurement. Its width keeps all 211 squares visible in spacing controls.
    camera = SimpleNamespace(
        uniforms={
            "view": tuple((np.eye(4) * [2 / 3, 2 / 3, 2 / 3, 1]).T.flatten()),
            "frame_scale": 1.5, "frame_rescale_factors": (2 / 16, 2 / 8, 0.1),
            "pixel_size": 12 / 1080,
            "camera_position": (0, 0, 20), "light_position": (0, 0, 10),
        },
        refresh_uniforms=lambda: None, background_rgba=[33 / 255] * 3 + [1],
        draw_fbo=SimpleNamespace(size=(2160, 1080)), samples=0,
    )
    return parse_geometry_message(serialize_scene(
        SimpleNamespace(render_groups=[mobject], camera=camera)))


def frame(renderer, header, data):
    renderer._ensure_targets(tuple(header["resolution"]), 1)
    renderer._fill_targets_used.clear()
    start = perf_counter()
    encoder = renderer.device.create_command_encoder()
    renderer._out_pass(encoder, header["background"]).end()
    for batch in header["batches"]:
        renderer._encode_vmobject(encoder, header, batch, data, 1)
    command = encoder.finish()
    encoded = perf_counter()
    queue = renderer.device.queue
    queue.submit([command])
    queue.read_texture(
        {"texture": renderer.out_texture, "mip_level": 0, "origin": (0, 0, 0)},
        {"offset": 0, "bytes_per_row": 4, "rows_per_image": 1}, (1, 1, 1))
    done = perf_counter()
    return {
        "encode_ms": (encoded - start) * 1000,
        "submit_through_completion_ms": (done - encoded) * 1000,
        "total_ms": (done - start) * 1000,
    }


def compare(mobject, samples):
    header, data = payload(mobject)
    legacy = deepcopy(header)
    for batch in legacy["batches"]:
        batch.pop("fill_rect", None)
    variants = {"full_frame": legacy, "bounded": header}
    renderer = WgpuRenderer()
    measurements = {key: [] for key in variants}
    for iteration in range(samples + 3):
        names = list(variants)
        if iteration % 2:
            names.reverse()
        for name in names:
            result = frame(renderer, variants[name], data)
            if iteration >= 3:
                measurements[name].append(result)
    images = [np.asarray(renderer.render(h, data), dtype=int)
              for h in variants.values()]
    differences = np.abs(images[0] - images[1])
    medians = {name: {key: median(row[key] for row in rows)
                      for key in rows[0]}
               for name, rows in measurements.items()}
    return {
        "batches": len(header["batches"]), "samples_per_variant": samples,
        "median": medians,
        "render_speedup": medians["full_frame"]["submit_through_completion_ms"]
                          / medians["bounded"]["submit_through_completion_ms"],
        "maximum_pixel_channel_difference": int(differences.max()),
        "changed_pixel_count": int(np.any(differences != 0, axis=2).sum()),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=8)
    args = parser.parse_args()
    if args.samples < 1:
        parser.error("--samples must be positive")
    word = _wordmark().set_stroke(color="#212121")
    for index, square in enumerate(word):
        square.set_fill(("#3377AA", "#88BBEE", "#225588")[index % 3], opacity=1)
    large = VGroup(Square(side_length=10, fill_color="#3377AA", fill_opacity=1))
    print(json.dumps({
        "resolution": [2160, 1080],
        "timing": "Submission through one-pixel output readback; excludes animation, serialization, browser, and full-image readback. Encoding is reported separately.",
        "touching_wordmark": compare(word, args.samples),
        "large_single_batch": compare(large, args.samples),
    }, indent=2))


if __name__ == "__main__":
    main()
