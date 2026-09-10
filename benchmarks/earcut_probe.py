"""A0 coverage comparison of the existing Earcut wrapper and optional Lyon.

Run with MANIML_LYON_LIBRARY set and `python -m benchmarks.earcut_probe`.
This tests the existing ring classifier as well as mapbox_earcut. It does not
claim that classifier implements nonzero fill for arbitrary compound paths.
Coverage is checked from source contours, independently of either output mesh.
"""

import argparse
from dataclasses import dataclass
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import time

import numpy as np
from mapbox_earcut import triangulate_float32

from maniml.mobject.types.vectorized_mobject import VMobject
from maniml.utils.space_ops import earclip_triangulation
from maniml.web.triangle_geometry import FillMesh, LyonFillTessellator
from tests.renderer_fixtures import closed_contours, concave_quad, get_fixture


@dataclass
class ProbeCase:
    name: str
    contours: list[np.ndarray]
    features: tuple[str, ...]
    input_contract: str


def path_contours(path):
    return [np.array(contour[:, :2], dtype=float, copy=True)
            for contour in path.get_subpaths()]


def flatten_contours(contours, tolerance):
    """Uniform per-quadratic steps with an exact chord-error upper bound.

    For a quadratic with second difference D, n equal parameter steps have
    error at most ||D||/(4*n*n) from their matching chord point. This bounds
    geometric displacement in these local coordinates, not screen-space AA.
    It is the same local-coordinate tolerance contract requested from Lyon;
    the subdivision algorithm and resulting vertex counts can differ.
    """
    if not np.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    result = []
    total = 0
    for raw in contours:
        points = np.asarray(raw, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise ValueError("contours must be finite Nx2 arrays")
        if len(points) and len(points) % 2 != 1:
            raise ValueError("quadratic contours require odd row counts")
        flat = []
        for i in range(0, len(points) - 2, 2):
            p0, p1, p2 = points[i:i + 3]
            count = max(1, math.ceil(math.sqrt(np.linalg.norm(p0 - 2*p1 + p2)
                                               / (4 * tolerance))))
            total += count
            if total > 262_144:
                raise ValueError("probe flattening exceeds 262144 points")
            t = np.arange(count, dtype=float)[:, None] / count
            flat.extend((1-t)**2*p0 + 2*(1-t)*t*p1 + t**2*p2)
        if len(points) >= 3:
            flat.append(points[-1])
        ring = np.asarray(flat, dtype=float).reshape(-1, 2)
        # Earcut closes polygons implicitly; preserve repeated traces while
        # removing only consecutive duplicates and the final closure point.
        if len(ring):
            ring = ring[np.r_[True, np.any(np.diff(ring, axis=0) != 0, axis=1)]]
        if len(ring) > 1 and np.array_equal(ring[-1], ring[0]):
            ring = ring[:-1]
        if len(ring) >= 3:
            result.append(ring)
    return result


def tessellate_existing_earcut(contours, tolerance=.001):
    rings = flatten_contours(contours, tolerance)
    vertices = np.asarray(np.concatenate(rings), dtype="f4") if rings else np.empty((0, 2), dtype="f4")
    # Production wrapper mutates its input to separate coincident endpoints.
    # Return those actual perturbed positions, without mutating source paths.
    # Exercise the actual production boundary, including its typed native call.
    indices = np.asarray(earclip_triangulation(vertices, np.cumsum([len(r) for r in rings]).tolist())
                         if rings else [], dtype="u4")
    return FillMesh(vertices, indices, np.empty((len(vertices), 0)), tolerance,
                    "existing wrapper ring nesting (not a general nonzero rule)",
                    "existing earclip ring classifier + typed mapbox_earcut call")


def tessellate_single_ring_earcut(contours, tolerance=.001):
    """Direct binding control, only where no ring classification is involved."""
    rings = flatten_contours(contours, tolerance)
    if len(rings) != 1:
        raise ValueError("direct control requires exactly one flattened ring")
    vertices = np.asarray(rings[0], dtype="f4")
    indices = triangulate_float32(vertices, np.asarray([len(vertices)], dtype="u4"))
    return FillMesh(vertices, indices, np.empty((len(vertices), 0)), tolerance,
                    "single-ring input; no general nonzero guarantee", "mapbox_earcut direct")


def _reference_segments(contours):
    """Independent dense source sampling plus a conservative sampling error."""
    starts, ends = [], []
    error = 0.
    for points in contours:
        dense = []
        for i in range(0, len(points) - 2, 2):
            p0, p1, p2 = points[i:i + 3]
            count = 128
            t = np.linspace(0, 1, count, endpoint=False)[:, None]
            dense.extend((1-t)**2*p0 + 2*(1-t)*t*p1 + t**2*p2)
            error = max(error, np.linalg.norm(p0-2*p1+p2)/(4*count*count))
        if len(points) >= 3:
            dense.append(points[-1])
        if len(dense) >= 2:
            dense = np.asarray(dense)
            starts.extend(dense)
            ends.extend(np.roll(dense, -1, axis=0))
    return np.asarray(starts).reshape(-1, 2), np.asarray(ends).reshape(-1, 2), error


def source_oracle(contours, samples, boundary_margin):
    """Signed ray-crossing nonzero coverage and exclusion near source edges."""
    samples = np.asarray(samples)
    winding = np.zeros(len(samples), dtype=int)
    nearest = np.full(len(samples), np.inf)
    starts, ends, sampling_error = _reference_segments(contours)
    for start, end in zip(starts, ends):
        delta = end - start
        if not np.any(delta):
            continue
        relative = samples - start
        cross = delta[0] * relative[:, 1] - delta[1] * relative[:, 0]
        winding += ((start[1] <= samples[:, 1]) & (samples[:, 1] < end[1]) & (cross > 0))
        winding -= ((end[1] <= samples[:, 1]) & (samples[:, 1] < start[1]) & (cross < 0))
        t = np.clip(relative @ delta / (delta @ delta), 0, 1)
        nearest = np.minimum(nearest, np.linalg.norm(relative - t[:, None]*delta, axis=1))
    return winding, nearest > boundary_margin + sampling_error


def mesh_coverage(mesh, samples):
    """Union coverage plus strict interior multiplicity, excluding zero-area triangles."""
    samples = np.asarray(samples)
    covered = np.zeros(len(samples), dtype=bool)
    multiplicity = np.zeros(len(samples), dtype=int)
    for triangle in mesh.positions[mesh.indices.reshape(-1, 3)].astype(float):
        ab, ac = triangle[1] - triangle[0], triangle[2] - triangle[0]
        area = ab[0]*ac[1] - ab[1]*ac[0]
        if abs(area) < 1e-14:
            continue
        edges = np.roll(triangle, -1, axis=0) - triangle
        relative = samples[:, None, :] - triangle
        cross = edges[None, :, 0]*relative[:, :, 1] - edges[None, :, 1]*relative[:, :, 0]
        covered |= (cross >= -1e-10).all(axis=1) | (cross <= 1e-10).all(axis=1)
        multiplicity += (cross > 1e-10).all(axis=1) | (cross < -1e-10).all(axis=1)
    return covered, multiplicity


def probe_cases(include_tex=True):
    result = []
    for name in ("annulus_hole", "nested_contours", "repeated_winding",
                 "reversed_winding", "curved_fill"):
        fixture = get_fixture(name)
        result.append(ProbeCase(name, path_contours(fixture.build().mobjects[0]),
                                fixture.features, "nonzero source-path coverage"))
    for alpha in (0, .25, .5, 2/3-.001, 2/3, 2/3+.001, .9, 1):
        result.append(ProbeCase(f"concave_morph_{alpha:.6f}", path_contours(concave_quad(alpha)),
                                ("morph", "concavity", "degeneracy"), "simple polygon including collinear vertices"))
    square = np.array([(0., 0.), (2, 0), (2, 2), (0, 2)])
    bowtie = square[[0, 2, 3, 1]]
    for alpha in (0., .25, .5, 2/3, .8, 1.):
        path = closed_contours((1-alpha)*square + alpha*bowtie)
        result.append(ProbeCase(f"crossing_morph_{alpha:.6f}", path_contours(path),
                                ("morph", "self_intersection", "degeneracy"),
                                "nonzero; intermediate paths can self-intersect, outside Earcut's simple-ring guarantee"))
    outer = [(-2, -2), (2, -2), (2, 2), (-2, 2)]
    inner = [(-1, -1), (1, -1), (1, 1), (-1, 1)]
    for name, rings, contract in (
        ("same_winding_nested", [outer, inner], "nonzero overlapping nested regions; inner ring is not a hole"),
        ("opposite_winding_nested", [outer, inner[::-1]], "simple outer ring and hole"),
        ("same_winding_duplicate", [outer, outer], "nonzero coincident contours; coverage once"),
        ("opposed_duplicate", [outer, outer[::-1]], "nonzero coincident opposing contours; empty coverage"),
        ("collapsed_line", [[(-1, 0), (0, 0), (1, 0), (0, 0)]], "degenerate zero-area path; empty coverage"),
    ):
        result.append(ProbeCase(name, path_contours(closed_contours(*rings)),
                                ("winding", "degeneracy"), contract))
    if include_tex:
        from tests.renderer_quality_fixtures import build_quality_frame
        frame = build_quality_frame("tex", border_policy="zero_for_aa")
        paths = [mob for obj in frame.scene.mobjects for mob in obj.get_family()
                 if isinstance(mob, VMobject) and mob.has_points()]
        # A bounded, deterministic sample including the most compound glyphs.
        selected = sorted(set([0, len(paths)//2, len(paths)-1] +
                              sorted(range(len(paths)), key=lambda i: len(paths[i].get_subpaths()),
                                     reverse=True)[:7]))
        for index in selected:
            result.append(ProbeCase(f"real_tex_glyph_{index:03d}", path_contours(paths[index]),
                                    ("real_tex", "glyph", "curves", "holes"),
                                    "actual production TeX glyph; classify from its contours"))
    return result


def evaluate_case(case, tessellator, tolerance=.001, grid_size=37):
    all_points = np.concatenate(case.contours)
    low, high = all_points.min(axis=0), all_points.max(axis=0)
    span = np.maximum(high-low, .1)
    low, high = low-.13*span, high+.13*span
    x = low[0] + (np.arange(grid_size)+.371)/grid_size*(high[0]-low[0])
    y = low[1] + (np.arange(grid_size)+.613)/grid_size*(high[1]-low[1])
    xx, yy = np.meshgrid(x, y)
    samples = np.column_stack((xx.ravel(), yy.ravel()))
    # Small glyphs use the same relative geometric quality as the larger paths.
    local_tolerance = tolerance * max(float(span.max()), .1)
    winding, safe = source_oracle(case.contours, samples, 4*local_tolerance)
    samples, expected = samples[safe], winding[safe] != 0
    if not len(samples):
        raise ValueError(f"no boundary-separated probes for {case.name}")
    results = {}
    generators = [
        ("earcut_ring_wrapper_typed", lambda: tessellate_existing_earcut(case.contours, local_tolerance)),
        ("lyon_nonzero", lambda: tessellator.tessellate(case.contours, tolerance=local_tolerance, fill_rule="nonzero")),
    ]
    if len(case.contours) == 1 and len(flatten_contours(case.contours, local_tolerance)) == 1:
        generators.append(("direct_earcut_single_ring", lambda: tessellate_single_ring_earcut(case.contours, local_tolerance)))
    for name, generate in generators:
        start = time.perf_counter()
        try:
            mesh = generate()
            elapsed = (time.perf_counter()-start)*1000
            coverage, counts = mesh_coverage(mesh, samples)
            mismatch = coverage != expected
            overlap = counts > 1
            bad = np.flatnonzero(mismatch | overlap)
            results[name] = {
                "status": "pass" if not len(bad) else "fail",
                "coverage_mismatches": int(mismatch.sum()), "overdraw_probes": int(overlap.sum()),
                "vertices": len(mesh.positions), "triangles": len(mesh.indices)//3,
                "generation_once_ms": elapsed,
                "witnesses": [{"point": samples[i].tolist(), "expected_covered": bool(expected[i]),
                                "mesh_covered": bool(coverage[i]), "strict_triangle_count": int(counts[i])}
                               for i in bad[:5]],
            }
        except Exception as exc:
            results[name] = {"status": "error", "error": f"{type(exc).__name__}: {exc}"}
    digest = hashlib.sha256()
    for contour in case.contours:
        digest.update(np.asarray(contour, dtype="<f8").tobytes())
    return {"name": case.name, "features": list(case.features), "input_contract": case.input_contract,
            "source_contours": len(case.contours), "source_points": sum(len(c) for c in case.contours),
            "source_sha256": digest.hexdigest(), "local_tolerance": local_tolerance,
            "grid_size": grid_size, "relative_tolerance": tolerance,
            "tested_probes": len(samples), "discarded_near_boundary": int((~safe).sum()),
            "generators": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("/private/tmp/maniml-earcut-a0/report.json"))
    parser.add_argument("--no-tex", action="store_true", help="explicitly omit the real-TeX subset")
    args = parser.parse_args()
    tess = LyonFillTessellator()
    results = [evaluate_case(case, tess) for case in probe_cases(not args.no_tex)]
    failures = [case["name"] for case in results
                if case["generators"]["earcut_ring_wrapper_typed"]["status"] != "pass"
                and case["generators"]["lyon_nonzero"]["status"] == "pass"]
    try:
        earclip_triangulation(np.array([[0., 0.], [1, 0], [1, 1], [0, 1]], dtype="f4"), [4])
        unadapted = "success"
    except Exception as exc:
        unadapted = f"{type(exc).__name__}: {exc}"
    report = {
        "purpose": "A0 required nonzero coverage vs existing ring wrapper plus Earcut; not a production tessellator selection",
        "python": platform.python_version(), "numpy": np.__version__,
        "mapbox_earcut": importlib.metadata.version("mapbox-earcut"),
        "unadapted_production_wrapper_square": unadapted,
        "earcut_call_adapter": "none; production wrapper now passes float32 vertices and uint32 ring ends at its native boundary",
        "source_files_sha256": {str(path.relative_to(Path(__file__).resolve().parents[1])):
                                 hashlib.sha256(path.read_bytes()).hexdigest()
                                 for path in (Path(__file__).resolve(),
                                              Path(__file__).resolve().parents[1]/"maniml/utils/space_ops.py")},
        "lyon_helper_sha256": hashlib.sha256(Path(tess.library_path).read_bytes()).hexdigest(),
        "oracle": "independent 128-sample/curve signed ray crossing; probes exclude 4x flattening tolerance plus oracle error near boundary",
        "timing_scope": "one untuned CPU generation call; not a performance comparison; oracle time excluded",
        "limitations": ["Passing sampled interior coverage does not prove arbitrary path correctness or AA quality.",
                        "Existing ring wrapper uses containment as holes without a general nonzero orientation policy.",
                        "Self intersections/coincident rings exceed Earcut's supported simple-ring contract.",
                        "Lyon passes here do not establish binary packaging, bounded heap use, or a GPU algorithm."],
        "case_count": len(results), "typed_existing_wrapper_fails_lyon_passes": failures,
        "direct_earcut_fails_lyon_passes": [case["name"] for case in results
            if case["generators"].get("direct_earcut_single_ring", {}).get("status") == "fail"
            and case["generators"]["lyon_nonzero"]["status"] == "pass"],
        "cases": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"report": str(args.output), "case_count": len(results),
                      "typed_existing_wrapper_fails_lyon_passes": failures,
                      "direct_earcut_fails_lyon_passes": report["direct_earcut_fails_lyon_passes"]}, indent=2))


if __name__ == "__main__":
    main()
