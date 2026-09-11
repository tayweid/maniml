# Point reads by kind and phase (2026-09-11)

The measurement the instruction-stream plan asked for before any point
leaves Python (`TODO.md` "Now", item 3; `../simlab/INSTRUCTION_STREAM_PLAN.md`,
prerequisites): which reads of source points happen, from where, and in which
phase of the scene loop. It decides the Phase 2 sync policy. Recorded on the
`engine` branch at the commit that added the counters (`DECISIONS.md`, "Point
reads are counted by kind and phase"); the interpretation at the end is the
author's and is marked as such.

## What was counted

Every run with `MANIML_PERF_PATH` set counts each read of a mobject's source
points as one of two kinds:

- **raw**: the point array itself comes back to Python. `Mobject.get_points`
  and the interpolation of two endpoints in `Mobject.interpolate` (one count
  per call, both endpoints).
- **reduce**: a small value derived from the points. `get_bounding_box` (so
  every centre, edge, corner, width and `move_to`), `get_start`/`get_end`,
  and `ValueTracker.get_value`.

Each read is tagged with the phase it happened in: **play** (between
`pre_play` and `post_play`, so `wait` counts too), **updater** (inside
`Mobject.update`, which wins when an updater runs during a play), or
**idle** (everything else: the exec of a unit between plays, which is where
scenes build and position their mobjects). The calling site is the function
that called the accessor, so `transform.py:interpolate_submobject` is the
animation reading its endpoints and `triangle_scene.py:read` is the renderer
reading a changed object. Counts are calls, not bytes.

`has_points`, `get_num_points` and the family walks read the array length,
not the points, and count nothing. `compute_bounding_box` reads the array
directly because its caller already counted the reduction. Reads of the
camera frame's five points (`camera_frame.py:*`) are counted as raw like any
other; they are camera state, not scene content.

## How

Headless `--render` of scratch copies of the three course episodes and the
dogfood demo (never beside the course's own media):

```bash
MANIML_PERF_PATH=/tmp/reads_EpisodeB0.json python -m maniml 03_Code.py EpisodeB0 --render
python -m benchmarks.read_report /tmp/reads_EpisodeB0.json
```

A render runs every updater at the frame rate, the same as the live viewer
inside a play, but has no parked idle loop: the reads a scene makes while
sitting on a pausepoint with an `always_redraw` on screen are the updater
column repeated at the idle frame rate, and are not in these tables.

| Scene | units | frames | raw reads | reduce reads | wall s |
|---|---:|---:|---:|---:|---:|
| EpisodeB0 | 18 | 1,021 | 1,260,799 | 537,956 | 48 |
| EpisodeA2 | 136 | 7,920 | 1,166,431 | 1,022,707 | 325 |
| EpisodeA3 | 92 | 5,382 | 1,488,008 | 1,639,338 | 271 |
| Demo | 2 | 72 | 2,080 | 209 | 2 |

## Tables

### EpisodeB0

| reads | play | updater | idle | total |
|---|---:|---:|---:|---:|
| raw | 170,023 | 1,076,344 | 14,432 | 1,260,799 |
| reduce | 173,229 | 357,357 | 7,370 | 537,956 |

Top raw sites (play / updater / idle):

- `coordinate_systems.py:_get_graph_sample_points`: 0 / 1,072,428 / 6,008
- `transform.py:interpolate_submobject`: 82,389 / 0 / 0
- `triangle_scene.py:read`: 66,812 / 0 / 0
- `vectorized_mobject.py:get_last_point`: 10 / 714 / 6,060
- `vectorized_mobject.py:get_joint_angles`: 4,716 / 714 / 4
- `camera_frame.py:get_height`: 5,105 / 0 / 0
- `vectorized_mobject.py:get_subpath_end_indices`: 1,669 / 714 / 514
- `vectorized_mobject.py:align_points`: 2,846 / 0 / 0

Top reduce sites (play / updater / idle):

- `03_Code.py:Bowed_PPF`: 0 / 357,357 / 2,004
- `mobject.py:interpolate`: 170,128 / 0 / 0
- `mobject.py:apply_points_function`: 1,334 / 0 / 3,118
- `mobject.py:<genexpr>`: 1,727 / 0 / 1,038
- `mobject.py:get_bounding_box_point`: 40 / 0 / 746
- `mobject.py:length_over_dim`: 0 / 0 / 432
- `mobject.py:get_center`: 0 / 0 / 24
- `geometry.py:get_start`: 0 / 0 / 8


### EpisodeA2

| reads | play | updater | idle | total |
|---|---:|---:|---:|---:|
| raw | 986,354 | 58,462 | 121,615 | 1,166,431 |
| reduce | 901,181 | 63,146 | 58,380 | 1,022,707 |

Top raw sites (play / updater / idle):

- `transform.py:interpolate_submobject`: 391,019 / 0 / 0
- `triangle_scene.py:read`: 365,159 / 0 / 0
- `vectorized_mobject.py:get_last_point`: 0 / 2,526 / 83,174
- `vectorized_mobject.py:pointwise_become_partial`: 24,424 / 21,410 / 163
- `vectorized_mobject.py:get_joint_angles`: 41,526 / 0 / 9
- `vectorized_mobject.py:get_subpath_end_indices`: 31,945 / 9 / 8,524
- `camera_frame.py:get_height`: 39,600 / 0 / 0
- `vectorized_mobject.py:get_anchors`: 28,941 / 612 / 7,092

Top reduce sites (play / updater / idle):

- `mobject.py:interpolate`: 882,300 / 0 / 0
- `mobject.py:apply_points_function`: 10,732 / 41,972 / 36,875
- `mobject.py:<genexpr>`: 7,974 / 3,960 / 17,454
- `mobject.py:get_bounding_box_point`: 153 / 11,864 / 2,501
- `mobject.py:get_center`: 22 / 2,310 / 352
- `geometry.py:get_start`: 0 / 1,216 / 172
- `geometry.py:get_end`: 0 / 1,216 / 144
- `mobject.py:length_over_dim`: 0 / 0 / 880


### EpisodeA3

| reads | play | updater | idle | total |
|---|---:|---:|---:|---:|
| raw | 1,212,504 | 207,266 | 68,238 | 1,488,008 |
| reduce | 832,897 | 773,813 | 32,628 | 1,639,338 |

Top raw sites (play / updater / idle):

- `transform.py:interpolate_submobject`: 332,767 / 0 / 0
- `triangle_scene.py:read`: 327,612 / 0 / 0
- `vectorized_mobject.py:get_anchors`: 124,457 / 8,726 / 3,588
- `vectorized_mobject.py:get_joint_angles`: 133,865 / 0 / 5
- `vectorized_mobject.py:get_subpath_end_indices`: 124,507 / 5 / 4,549
- `number_line.py:number_to_point`: 0 / 109,386 / 750
- `vectorized_mobject.py:pointwise_become_partial`: 28,272 / 80,844 / 389
- `vectorized_mobject.py:get_unit_normal`: 84,287 / 0 / 117

Top reduce sites (play / updater / idle):

- `mobject.py:interpolate`: 803,172 / 0 / 0
- `mobject.py:apply_points_function`: 8,595 / 526,784 / 20,864
- `mobject.py:get_bounding_box_point`: 121 / 145,447 / 1,959
- `mobject.py:<genexpr>`: 20,981 / 71,007 / 8,746
- `mobject.py:get_center`: 28 / 18,330 / 249
- `geometry.py:get_start`: 0 / 4,362 / 121
- `geometry.py:get_end`: 0 / 4,362 / 101
- `03_Code.py:<lambda>`: 0 / 1,340 / 0


### Demo

| reads | play | updater | idle | total |
|---|---:|---:|---:|---:|
| raw | 1,493 | 0 | 587 | 2,080 |
| reduce | 104 | 0 | 105 | 209 |

Top raw sites (play / updater / idle):

- `vectorized_mobject.py:get_last_point`: 0 / 0 / 477
- `vectorized_mobject.py:pointwise_become_partial`: 416 / 0 / 0
- `camera_frame.py:get_height`: 360 / 0 / 0
- `triangle_scene.py:read`: 325 / 0 / 0
- `camera_frame.py:get_center`: 144 / 0 / 0
- `camera_frame.py:get_width`: 72 / 0 / 0
- `mobject.py:get_location`: 72 / 0 / 0
- `transform.py:interpolate_submobject`: 52 / 0 / 0

Top reduce sites (play / updater / idle):

- `mobject.py:interpolate`: 104 / 0 / 0
- `mobject.py:apply_points_function`: 0 / 0 / 66
- `mobject.py:<genexpr>`: 0 / 0 / 26
- `mobject.py:get_bounding_box_point`: 0 / 0 / 8
- `mobject.py:length_over_dim`: 0 / 0 / 4
- `mobject.py:get_center`: 0 / 0 / 1


## What dominates

**Between plays (idle) the scene reads little, and mostly reductions.** The
unit exec that builds and positions mobjects is 3 to 8 percent of all reads
in every episode. Its raw reads are path construction (`get_last_point` in
`add_line_to`, `get_anchors`) and its reductions are positioning
(`apply_points_function` computing the about-point of a shift or scale,
`get_bounding_box_point` for `next_to` and `align_to`). Scene code itself
appears only as a reduction site (`03_Code.py:Bowed_PPF` reading a tracker,
`03_Code.py:<lambda>`).

**Inside a play the raw reads are the engine's own.** In A3, the largest
episode, the play column is 1.2 million raw reads and every top site is
engine code: `Transform` interpolating its endpoints (`interpolate_submobject`),
the renderer reading objects whose revision changed (`triangle_scene.py:read`),
and the alignment and stroke-joint work a transform does at `begin`
(`get_anchors`, `get_joint_angles`, `get_subpath_end_indices`,
`get_unit_normal`, `align_points`). The reduce column there is almost
entirely `Mobject.interpolate` reading the two endpoints' cached bounding
boxes, twice per call. No user code reads points during a play.

**Updaters are where scene code reads, through the coordinate system.** In B0
the `always_redraw` of the two PPF curves is 1.07 million raw reads over 714
rebuilds: the batched graph sampler snapshots both axes' endpoints at every
sample (`coordinate_systems.py:_get_graph_sample_points` reads
`axis.get_points()` twice per sample so a callback that moves the axes is
honoured) and the user's `Bowed_PPF` reads the tracker once per sample. In A3
the updater reads are `number_to_point` (an `ax.c2p` per updater call),
`pointwise_become_partial` (a creation kept live), and half a million
bounding-box reductions from `move_to`/`shift` inside updaters.

## What it means for the sync policy (the author's reading)

1. **User code reads through reductions and the coordinate system, not raw
   arrays.** Across the three episodes no scene-file site reads a point array.
   A GPU-resident design therefore needs cheap reductions between plays and
   inside updaters (a bounding box, endpoints, a tracker value), which is a
   per-object 3×3 box kept current on the CPU or a tiny readback, not the
   array. This matches the plan's "map/reduce" split: reductions are the
   synchronization surface.
2. **The play-phase raw reads disappear with Phase 1's programs and the
   shared renderer, not with a sync policy.** Interpolation, alignment and the
   renderer's source read are exactly what the instruction stream replaces.
   They should not be counted as evidence that Python needs points during a
   play.
3. **The graph sampler's per-sample axis read is deliberate, and a call
   count overstates it.** The batched sampler snapshots both axes' endpoints
   at every sample so a callback that moves the axes mid-sample is honoured,
   including one that writes straight into the axis point array
   (`tests/test_coordinate_systems.py`,
   `test_callback_can_write_axis_points_between_samples`). An in-place write
   bypasses the revision counter, so a revision check cannot replace the
   read. What the read costs is a method call per sample, not an array copy;
   the 5 ms PPF rebuild (`DECISIONS.md`, "Curve redraw batches array work")
   is the reference number, and the counters here count calls, not bytes.
   For the GPU design the point stands: this is engine code reading
   two endpoints, a reduction in all but name.
4. **Parked, the live viewer repeats the updater column at 30 frames per
   second, and nothing else.** Measured through `benchmarks/live_profile.py`
   on EpisodeB0 held on B02b (the live PPF `always_redraw`), as the
   difference between a 3 s and a 13 s hold after each of three arrow
   presses, so 30 s of parked time: 900 frames, 901,485 raw reads (all
   `_get_graph_sample_points`) and 299,299 reductions (all the scene's
   `Bowed_PPF` reading its tracker), no play or idle reads at all, and 4.7 s
   of CPU, about 16 percent of one core. A probe scene confirmed the idle
   loop is paced at the camera's frame rate by `update_frame`'s sleep. So a
   parked scene costs one rebuild per frame of every live updater and no
   engine reads of its own; the archive is
   `benchmarks/results/read_instrumentation_20260911/`.

## Open

- Bytes are not counted, only calls; a raw read of a 5-point frame and of a
  2,001-point curve count the same. Add a byte counter if the policy needs
  it.
- Writes are not counted. A GPU-resident point store also needs to know which
  Python writes bypass the operation stream (`data["point"][:] = ...` sites);
  the ledger's `MANIML_VERIFY_LEDGER` already names those that forget the
  revision bump.
