# Surfaces are nets by default, judged against the true surface (2026-09-29)

B5.9 (`docs/phase_b4_plan.md`, "The flips"). After B5.7's numbers
(`../b57_net_runs_20260929/`) Taylor was asked "Make smooth 3D surfaces the
default? ... The one pixel 'failure' is because the test compares against
the faceted version; against a true sphere, smooth is more accurate", and
chose "Flip it (Recommended)": "Smooth surfaces become the Default (and in
rendered movies). Phase A in the dropdown keeps the faceted grids. Also
change the pixel test to measure against a supersampled true surface, so it
measures accuracy, not sameness to the old look." **The nets pixel gate is
now accuracy against the true surface, nets pass it on every scene of the
timed set and every Surface fixture, and `geometry.DEFAULT_SURFACE` is
`nets`** (`summary.json`: `default_flipped`, `pixel_gate_passes`). The
gate's timing part fails where B5.7 measured it (`timing_gate_passes`), the
cost the decision accepted; it was not retaken.

## Runs

From `/Users/taylorjweidman/Projects/ManimLive/maniml-b59` (branch
`b5-nets-default`, 5c16c898, B5.7's commit, plus B5.9's working tree),
interpreter `maniml/.venv/bin/python` (Python 3.13.9, wgpu 0.32.0, numpy
2.5.2), Apple M3, Metal, macOS 26.6.2. Pixels only: nothing here is timed
(another agent was timing on the machine). Per scene of the timed set
(`flip_gates.TIMED_SCENES`), then the fixtures and the gate:

```bash
python -m benchmarks.flip_gates accuracy --scene $S --play-frames 3 --output <d>/<scene>
python -m benchmarks.flip_gates fixtures --output <d>/fixtures
python -m benchmarks.flip_gates gate --flip nets --complete <B5.7 pass 3>/{orbit,b3,b4,orbs,lattice}/complete \
    --fixtures <d>/fixtures --accuracy <d>/{orbit,b3,b4,orbs,lattice} --output <d>/gate
```

The scenes are B5.7's: the workspace's `dogfood/orbit_demo.py` OrbitDemo,
econ-0100's `Blocks/B3_Equilibrium/B3_Animation.py` EpisodeB3 and
`Blocks/B4_Efficiency/B4_Animation.py` B4, and
`benchmarks/surface_scenes.py`'s `OrbsScene` and `LatticeScene`; each run's
frames are `select_frames`' (as `serialize` and `episode_frames` choose
them) and three frames spread strictly inside the play into each. The
complete runs are B5.7's pass 3 (its tree, efcb262c with B5.7's working
tree); the accuracy runs and the fixtures run are of one tree, every source
file they hashed (the reference, the serializer and driver,
`bezier_net.py`, `surface.py`, the WGSL, the scene) hashing as it does in
the tree committed. Three passes were taken: two before review (22:57-23:24
local), and the archived one after it (23:55-00:08 local), on the tree
whose reference draws grids' order from the surface's own triangle indices,
counts a frame where grids and nets are within 24/255 everywhere as a tie,
and whose gate checks each reference and each run's frames; nets read as
before on every frame and fixture, grids moved by at most 153 pixels a
scene (the order of a cell's two triangles).

## Results

Pixels over 24/255 from the true surface (each stack against the reference
drawn in its own triangle order), summed over each scene's frames; a tie is
a frame where grids and nets are nowhere more than 24/255 apart, which
counts for neither:

| Scene | frames (pausepoints + inside plays) | ties | grids | nets | the frames not ties: grids; nets | nets vs grids, worst frame (diagnostic) | pixels where grids and nets differ: nets nearer / grids nearer |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Orbit demo | 8 (2 + 6) | 6 | 0.0245% (4,059) | 0.0244% (4,049) | 72; 70 | 0.291% | 1,689 / 2,329 (2,014 equal: the draw order) |
| EpisodeB3 | 45 (12 + 33) | 6 | 0.0263% (27,632) | 0.0114% (11,969) | 26,406; 10,743 | 0.026% | 12,138 / 83 |
| B4 | 48 (12 + 36) | 25 | 0.0122% (13,621) | 0.0066% (7,351) | 11,232; 4,962 | 0.023% | 5,508 / 78 |
| Orbs, 70 spheres | 12 (3 + 9) | 0 | 0.390% (96,968) | 0.102% (25,326) | 96,968; 25,326 | 0.344% | 74,407 / 391 |
| Lattice, 480 spheres | 12 (3 + 9) | 0 | 1.378% (342,834) | 0.673% (167,348) | 342,834; 167,348 | 0.979% | 206,975 / 6,194 |

No frame of the 125 has nets the further. Every reference is within its
tolerance (1/32 of a pixel; at most 0.031), every surface of every frame
fitted its function (`net_defined` 0) and none was sorted. The orbit demo
is a tie: its nets-against-grids frame mid-fade is the draw order, and the
others are ties or 1 pixel apart. The lattice's checkpoint 1 reads 1.587%
and 0.808% (B5.7's reference, eight times the patches drawn once at the
frame's own resolution, read 1.596% and 0.858%).

The Surface fixtures, pixels over 24/255 from the true surface, grids;
nets: port_surfaces 148; 148, sphere_1x 0; 0, sphere_4x 49; 49, sphere_16x
459; 204, sphere_64x 1,018; 111, ce_saddle 579; 579, textured_flat 0; 0,
orbs 2,834; 1,006, orbit_demo 16; 16, cobb_douglas 381; 173, fill_by_value
76; 76, textured_zoom 586; 586, translucent 0; 0. Eight are ties, grids and
nets within 1/255 everywhere (their nets evaluate at two steps there); nets
are the nearer on the 16× and 64× spheres, the orbs and Cobb-Douglas; nets
against grids is at most 0.28% (the orbs), reported, not judged.

The gate (`gate/summary.md` in `summary.json`'s `gate`): the pixels pass;
the timing fails on the orbs' and the lattice's still and camera classes in
both formats, 1.063-1.243, B5.7's pass 3 exactly.

## The reference

`tests/surface_fixtures.py`, `against_reference`. Every Surface of the
frame is drawn as its true surface: `uv_func` (a TexturedSurface's
uv_surface's, with its ranges) carried into the frame by the affine map
fitted from the construction's samples of it to the surface's own sample
grid, which must fit to float32 rounding; sampled patch by patch at k_u ×
k_v times its samples, grown until the facet error estimated from the
projected samples (an eighth of the second differences along u and v, a
quarter of the twist, over the facets past the near plane that meet the
frame) is within 1/32 of a pixel; normals from the function's derivatives
(the surface's own where they vanish), every other field the surface's net
evaluated there; triangles that draw no pixel left out. It is drawn by
Phase A's grid path (no net is evaluated) in 4×4 tiles of the frame's size
placed by the uniforms' clip transform and box-filtered back, 16 times the
samples per pixel over the driver's own. The tiles return the plain frame
to its edges' antialiasing (4 and 8 pixels over 24/255 on the orbs and the
orbit demo fixtures); a quarter of the tolerance (the orbs' 702,136
triangles 2,667,600) moves no pixel over 24/255, the largest channel 6/255.

**The draw order.** A translucent surface that overlaps itself is drawn
with the depth test on in index order, so which triangle comes first
decides what shows; grids draw the grid's triangles in the surface's own
index order (cell by cell, row by row, unless its faces were sorted), nets
patch by patch. `translucent_orders_crop.png` (the translucent fixture's
torus, enlarged 2×): top, the reference in grids' order, grids, the
reference in nets' order, nets; below, grids' and nets' differences from
their own reference, four times brighter. The bands follow the order, true
surface or not, so each stack is measured against the reference in its own
order; the order alone moves 409 of the fixture's pixels and 6,068 of the
orbit demo's frame mid-fade (the 0.29-0.31% nets against grids B5.4 and
B5.7 measured there).

**A sort** (`summary.json`, `sorted_faces`). `sort_faces_back_to_front`
(`always_sort_to_camera`'s updater) reorders the grid's triangle indices,
which grids draw and a net does not. The translucent fixture sorted to its
camera: grids move 7,886 pixels over 24/255, nets none; the Default after
the flip is 7,542 pixels (1.45% of the frame) from the Default before it,
against 405 unsorted. The reference's grid order follows the indices
(sorted grids are 0 pixels from it, 8,036 from a reference in the cells'
order). Accepted, not fixed: no course or dogfood scene sorts, and
`MANIML_SURFACE=grids` or Phase A draws the sort.

`lattice_true_surface_crop.png`: the lattice's checkpoint 1, the 96 × 54
window with the most pixels where grids and nets differ (B5.7's window),
enlarged 8×: the reference, grids and nets, and below each stack's
difference from the reference, four times brighter. Grids' error is the
polygon's silhouette and the shading of its coarse vertices; nets' what is
left of theirs at a quarter of a pixel's chord tolerance.

## Tests

With the flip: the whole suite with `MANIML_EPISODES` at the PriceDiscovery
link tree, 1,097 tests OK, 61 skipped, 325 s; the golden pin
(`test_retained_frame`, `test_patch_rows`, `MANIML_TEST_GPU=1`) 83 OK in
each of the default, `MANIML_VERIFY_LEDGER=1` and
`MANIML_RETAINED_FRAME=0`, nothing re-recorded; the GPU-gated modules and
those that draw a surface (26 modules, `MANIML_TEST_GPU=1`) 461 OK, 1
skipped.
