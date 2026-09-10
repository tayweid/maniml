"""Reproduce the archived warm CPU projection-memo comparison.

Run from the repository with the optional dependency overlay and Lyon helper;
see projection_memo_profile.json for the original environment command.
This script reports fresh results to stdout; it does not overwrite evidence.
"""

import json
from pathlib import Path
import statistics
import sys
import time
from unittest.mock import patch

# Keep direct script execution on this worktree, not the installed main checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from benchmarks.triangle_scene import prepare_triangle_frame, TriangleMeshCache, _MeshEntry
from benchmarks.triangle_wordmark import build_wordmark_scene
from tests.renderer_quality_fixtures import build_quality_frame
from maniml.web.triangle_geometry import LyonFillTessellator


def recompute_error(entry, source, uniforms, resolution):
    return entry.geometry.pixel_error(source, uniforms, resolution)


def main():
    tessellator = LyonFillTessellator()
    optimized = _MeshEntry.pixel_error
    results = {}
    scenes = [
        ("B0", build_wordmark_scene()[0]),
        ("TeX", build_quality_frame("tex", border_policy="zero_for_aa").scene),
    ]
    for name, scene in scenes:
        cache = TriangleMeshCache()
        for _ in range(3):
            prepare_triangle_frame(scene, tessellator, mesh_cache=cache, diagnostic=True)
        timings = {"recompute_projection": [], "memoized_projection": []}
        for iteration in range(40):
            order = list(timings) if iteration % 2 else list(reversed(timings))
            for variant in order:
                method = optimized if variant == "memoized_projection" else recompute_error
                with patch.object(_MeshEntry, "pixel_error", method):
                    started = time.perf_counter()
                    frame = prepare_triangle_frame(
                        scene, tessellator, mesh_cache=cache, diagnostic=True)
                    timings[variant].append(1000 * (time.perf_counter() - started))
        results[name] = {
            variant: {"median_ms": statistics.median(values),
                      "p95_ms": sorted(values)[37], "samples_ms": values}
            for variant, values in timings.items()
        }
        results[name]["last_frame_cache_stats"] = frame.mesh_cache_stats
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
