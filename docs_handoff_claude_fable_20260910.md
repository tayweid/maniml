# ManimLive handoff to Claude Fable

Prepared 2026-09-10. Code baseline: **`00d8e854` on local `main`**.
This document records the current implementation, Taylor's direction, the
evidence behind it, and recommended next work. It is intended to be usable
without the preceding conversation. Recommendations below are distinguished
from decisions already made; writing this handoff does not implement them.

## Start here

ManimLive is an interactive Manim-compatible animation environment. The Python
package and GitHub repository are named `maniml`. The browser is its live
viewer; scene checkpoints, source editing, replay and course production are
central features, not a secondary demo around the renderer.

The recent project was to unify 2D and 3D drawing, then move point evaluation
**and the geometry generation it requires** to the GPU. The shared renderer
is now the default on main. The latest increment also generates vector fill
borders on the GPU. Public source points and general fill triangulation
remain on the CPU. The larger GPU engine is still planned.

The immediate job is to validate this baseline in real use, address measured
remaining costs and compatibility gaps, and prepare the GPU source/geometry
migration without breaking Manim's array semantics. There is no need to redo
the seven renderer follow-ups: they are committed and integrated.

Read these in order:

1. [Workspace guide](/Users/taylorjweidman/Projects/ManimLive/CLAUDE.md), then
   [repository guide](/Users/taylorjweidman/Projects/ManimLive/maniml/CLAUDE.md)
   and [TODO](/Users/taylorjweidman/Projects/ManimLive/maniml/TODO.md).
2. [Implementation after the sixth review](/Users/taylorjweidman/Projects/ManimLive/maniml/docs_unified_triangle_renderer_review_response.md#implementation-after-the-sixth-review-2026-09-10),
   especially section 7. This is the latest implementation account.
3. [GPU border evidence](/Users/taylorjweidman/Projects/ManimLive/maniml/benchmarks/results/triangle_followup_20260910/gpu_borders/README.md)
   and [Phase A contract](/Users/taylorjweidman/Projects/ManimLive/maniml/docs_unified_triangle_renderer_phase_a.md).
4. [Phase B specification](/Users/taylorjweidman/Projects/ManimLive/maniml/docs_gpu_geometry_generation_plan.md),
   then the broader [renderer plan](/Users/taylorjweidman/Projects/ManimLive/maniml/docs_unified_triangle_renderer_plan.md).
   Earlier sections and measurements in these documents are historical.

## Taylor's direction and important boundaries

- Keep **Phase A as the default** for the live viewer, native movie/checkpoint
  output and new baked geometry exports.
- Keep **Original 2D selectable in the viewer**, at the same checkpoint,
  without changing source arrays or camera state.
- Keep **Native GL in the package** as the explicit `NativeGLCamera` reference,
  including its shaders, public `ShaderWrapper` and dependencies. An earlier
  interpretation permitting its removal was incorrect and has been corrected.
- Build a general Manim renderer. Text is an important performance control;
  it is not authorization for a text-only rendering architecture.
- The eventual GPU move includes source-point updates and correct current
  triangle generation. Reusing stale connectivity through an arbitrary morph
  is unacceptable. An affine optimization alone is not general GPU support.
- Reviewer comments are useful second opinions. Taylor explicitly does not
  automatically agree with every suggestion. Verify findings and explain
  tradeoffs; do not turn every reviewer proposal into a requirement.
- Preserve the CPU and historical references while validating the new path.
  Do not silently switch renderers for unsupported content or widen image
  thresholds to claim an unmet gate passes.
- Continue routine authorized work autonomously, validate meaningful changes,
  and ask when a real semantic choice needs Taylor's input. Explain renderer
  concepts through the points/arrays and visible behavior Taylor knows.

## Repository and running environment

| Location | Purpose |
| --- | --- |
| `/Users/taylorjweidman/Projects/ManimLive/maniml` | Canonical checkout; stays on `main`. |
| `/Users/taylorjweidman/Projects/ManimLive/maniml-perf` | Branch worktree; currently `plan/ordered-fill-atlas`, also at `00d8e854`. The branch name is historical; the atlas approach was superseded. |
| `/Users/taylorjweidman/Projects/ManimLive/simlab` | Workspace-only GPU architecture/sequence and experiments; not a Git repository. |
| Siblings `manimce`, `manimgl` | Reference checkouts, not implementation targets. Current CE is the compatibility reference. |
| Sibling `dogfood` | Scratch scenes and regenerable output. |

At this handoff's baseline, the branch worktree was clean. Main had two
unrelated untracked documents: `docs_ce_compat_notes.md` and
`docs_dogfood_2026-09-09.md`. Preserve them. Recheck status before editing;
another reviewer may be working concurrently. Do not overwrite their
`docs_unified_triangle_renderer_code_review.md`; put implementation responses
in the separate response document. This handoff is a documentation-only
addition after the stated code baseline.

Make changes in the branch worktree, then integrate validated commits into
canonical main. Commits have no model attribution/footer. The recent sequence
was integrated locally; no remote push or remote CI result is claimed here.
The repository is [tayweid/maniml](https://github.com/tayweid/maniml). A handoff
on another machine must obtain the local commits and adapt the absolute paths
in this document. The untracked field reports and non-Git `simlab` documents
will not travel with an ordinary repository checkout; share those separately
if needed.

Both the canonical venv and `/opt/miniconda3/bin/python` were verified to import
canonical main from outside the repository. The user's CLI is
`/opt/miniconda3/bin/maniml`. Verify this before debugging a live symptom:

```sh
cd /private/tmp
/opt/miniconda3/bin/python -c 'import maniml; print(maniml.__file__)'
```

Expected package file:
`/Users/taylorjweidman/Projects/ManimLive/maniml/maniml/__init__.py`.
Checking from inside a checkout can hide an incorrect installed copy. Repair
an editable install only if necessary, using `--no-deps` to avoid incidental
dependency upgrades. Existing scene processes must restart to import changed
engine code. The prior work left user app/scene processes and ports
8685/8687/5197 untouched; inspect current ownership before running or stopping
anything. Use isolated profiles and ephemeral ports for tests, and avoid
concurrent GPU timing jobs.

## What is already complete

The default cutover is `67f779dc`. Taylor then approved, and the implementation
completed, this exact follow-up order:

| Commit | Completed change |
| --- | --- |
| `7324ce89` | Restored packaged Native GL, real `ShaderWrapper`, GLSL assets and runtime dependencies. Resources are camera-owned and excluded from checkpoints. |
| `092cfcb8` | Fixed indexed digest reuse by preserving equivalent contiguous little-endian index arrays. Mutable data still hashes its actual bytes. |
| `440656f8` | Renderer readiness waits for authoritative server selection; explicit choices use acknowledgments. Reload/reconnect no longer changes every tab's renderer. |
| `893c3f69` | Original 2D retires absent GPU textures after submission and rolls back failed-frame allocations. |
| `ff2691b9` | Isolated and documented ordering: Original 2D retains stable z/add order; Phase A and Native GL retain their fixed-frame-last policy. |
| `746e9bd2` | Independent binary paint definitions, shared GPU coefficient buffers and recording reconstruction. Large-field fallback is reported as a limitation. |
| `00d8e854` | General GPU fill-border generation, retained sources/output, format 5 recording/seek support, lifecycle checks and four-reference measurements. |

The latest reviewer file's sixth round audits the earlier `67f779dc` cutover.
The reviewer's approval of the implementation order is not a subsequent code
audit or acceptance of all results in `00d8e854`. Check for newer feedback
before starting another round.

Other substantial work already on main:

- The browser replaced the pyglet viewer. The engine serves its own frontend;
  native output is headless WebGPU. There is no native image streamed behind
  the live browser renderer.
- The checkpoint ledger reuses unchanged frozen graphs, shares glyph source
  data and skips thaw at the execution frontier. `MANIML_VERIFY_LEDGER=1`
  detects revision misses in checkpoint reuse.
- RIGHT replays previously visited animations; LEFT jumps instantly to the
  previous pausepoint; UP/DOWN jump individual checkpoints. Replay preserves
  saved history and execution frontier. Do not restore the old instant-RIGHT
  behavior accidentally.
- Curve corner construction and plot coordinate conversion were batched.
  Scalar function callbacks retain their order/semantics. The recorded local
  redraw control improved roughly 47→20→5 ms; this is CPU construction timing,
  not end-to-end viewer FPS.
- Both formerly failing AppShell tests were fixed by isolating ports and
  announcing geometry readiness. These test fixes do not establish that every
  reported live disconnect or reload race is solved.

## Current rendering architecture

```text
Python scene, authoritative points and styles
    ↓
CPU source inspection, retained Lyon fill mesh, paint and border-source records
    ↓
Format 5 ordered operations + independently retained definitions
    ↓
WebGPU compute expands changed border vertices
    ↓
Shared triangle/material/coverage drawing, then AA resolve
    ↓
Browser canvas OR native movie/image output
```

Planar fills support concavity, holes and intersections with nonzero winding.
Ordinary 2D painter operations disable depth reads/writes. Depth-enabled
objects use the shared depth attachment. Default AA is 4× MSAA at twice the
final width and height, followed by a four-texel resolve; it is independent of
the older `Camera.samples=0` default. Native images convert premultiplied
internal pixels to straight RGBA.

Fill and border share per-object stencil sample ownership, preventing double
opacity where triangles overlap. Only depth-enabled coverage draws replay
depth. Proven compatible opaque constant-color operations can coalesce; the
101-glyph text control remains one scene draw plus one resolve. One backend
does not imply every scene can be one draw without respecting order/materials.

The GPU border input is 176 bytes per active quadratic, derived from three
canonical source records plus density/flags and RGBA. Each curve reserves
64 output vertices and 186 static indices. Unused samples clamp to a
zero-area tail. This is bounded fixed capacity, not compact count/scan/emit.
The output uses the existing 40-byte surface layout. Input definitions are
separate from output buffers; outputs belong to draw occurrences as well as
source identities, so different uniforms cannot overwrite shared results.

Small camera-only updates reuse fill/source uploads. Genuine fill-quality
refinement still replaces geometry. Source/recipe retention shares the fill
cache's 64 MiB host budget; accounting includes pinned immutable references.
Successful submission commits reuse state and retires absent resources.
Failed frames roll back new allocations. Checkpoints contain no GPU objects.
Format 5 recordings reconstruct definitions for arbitrary seeks; formats 1–4
remain readable.

| Concern | Main implementation files under `maniml/` |
| --- | --- |
| Scene/checkpoints/replay | `scene/scene.py`, `scene/checkpoints.py`, `scene/interaction.py`, `scene/source_map.py` |
| Public source arrays | `mobject/mobject.py`, `mobject/types/vectorized_mobject.py` |
| Fill preparation/cache | `web/triangle_scene.py`, `web/triangle_geometry.py`; native helper `tools/lyon_fill/` at repo root |
| GPU border recipes/kernel | `web/gpu_border_geometry.py`, `web/static/wgsl/border_compute.wgsl` |
| Independent CPU border oracle | `web/border_geometry.py` |
| Paint fields | `web/fill_paint.py`, `web/static/wgsl/paint.wgsl` |
| Wire/resources | `web/geometry.py`, `web/generated_geometry.py` |
| Both drivers | `web/wgpu_renderer.py`, `web/static/webgpu.js`, shared `web/static/wgsl/` |
| Recording/export | `web/static/geometry_recording.js`, `web/static/player.js`, `web/export.py` |
| Live selection/transport | `web/viewer.py`, `web/server.py`, `web/static/renderer_selection.js`, `web/static/viewer.html` |
| Explicit historical paths | `camera/native_gl_camera.py`, `rendering/shader_wrapper.py`, `rendering/shaders/`, `web/winding_geometry.py`, `web/static/winding_webgpu.js` |

## What the measurements actually show

Final warmed native complete-frame medians on Apple M3, Python 3.13.9, Metal:

| Control | GPU-border Phase A | CPU-border Phase A | Original 2D | Native GL |
| --- | ---: | ---: | ---: | ---: |
| B0, 211 touching squares | 24.35 ms | 25.12 ms | 66.95 ms | 265.57 ms |
| Static 101-glyph text | 6.96 ms | 7.74 ms | 5.54 ms | 7.76 ms |
| Text pan | 8.80 ms | 9.86 ms | 5.57 ms | 7.77 ms |
| Repeated 5% frame-height reduction | 10.65 ms | 14.37 ms | 5.49 ms | 8.24 ms |
| Text 1→4→1 zoom | 10.72 ms | 17.14 ms | 5.75 ms | 8.06 ms |
| Changing paths | 5.03 ms | 4.68 ms | 3.04 ms | 3.73 ms |

The full eight-case report also includes tilt and resize; one resize median
was slightly slower with GPU borders. These results establish a strong square
win and a smaller text regression. They do not establish universal speedup.

Timing includes serialization through full RGBA readback/PIL construction,
after three warmups and twelve rotated/reversed samples. Source evaluation is
separate. Original 2D timing uses the shipped serializer with the frozen
native WebGPU comparison driver, not browser presentation. Historical AA
policies differ from Phase A. No GPU timestamps were taken.

With an actual uncompressed loopback WebSocket echo, small text zoom improves
16.09→11.06 ms against CPU borders. This is two network traversals, not
one-way delivery or live browser latency. Small-zoom packets become
1,077–1,138 bytes instead of up to 1,468,384 bytes. The 4× zoom really refines
fills and can send 2,671,229 bytes, so do not promise 1 KB at every zoom.

Static text retains 11.54 MB of GPU geometry versus 1.24 MB with CPU borders:
about **9.82 MiB extra** due mainly to padded output/indices. The host cache
accounts for 6.58 MB versus 3.30 MB, conservatively counting some shared
references again. AA targets are additional; these figures are not peak
GPU memory or process RSS.

Independent paint retention reduced the large static gradient packet from
94,308 to 1,140 bytes and Phase A's measured frame from 16.31 to 11.40 ms.
Original 2D was 3.33 ms and GL 3.75 ms in that after-run. The 800-node
inverse-distance fragment loop remains expensive. Retaining coefficients
does not solve shader cost or make the new spatial paint match historical
fan interpolation. See response section 6 and the sibling `paint_before/`,
`paint_after/`, `paint_comparison.json` artifacts for the qualified comparison.

## What remains open and what should come next

The following order is a recommendation for the next engineer, not a claim
that Taylor selected a particular new algorithm.

### 1. Establish the live baseline and read the next review

Confirm the running interpreter/code before judging performance. Reproduce
Taylor's course workflow with the new build: text zoom/pan, mixed vectors,
Write/Transform, fixed overlays, transparent fills, reverse/jump, source
reload and switching Original 2D at the same checkpoint. Record problems
against the current commit and measure with `MANIML_PERF_PATH`.

Read the two untracked main-checkout field reports, but treat their old
numbers and diagnoses as historical. The September 9 dogfood report targets
`4aa37fe6`; curve construction has improved since then. Its disconnect,
edit/navigation ghost and uneven-appearance reports still deserve current
reproduction. Current source still has the 1,024-event queue overflow close
and three-retry client limit; that establishes relevant code remains, not
proof of the reported failure chain. Separate engine/updater time, checkpoint
time, transport and browser rendering before choosing a fix.

### 2. Profile the remaining text and changing-path costs

Use the archived four-reference harness before optimizing. The former CPU
border regeneration/large small-zoom upload has been addressed. Remaining
candidate costs include exact source inspection, retained recipe/index work,
the padded GPU output and the chosen AA workload. Measure them independently;
do not assume that moving one more stage guarantees Original 2D speed.

A bounded comparison of current padding versus compact allocation/indirect
drawing could be worthwhile if memory or GPU work dominates. It adds
complexity and is not already approved as the next implementation. Preserve
opaque batching, fill/border order, single-owner coverage and both-host
resource recovery. Retain the CPU border reference until replacement evidence
is complete. Keep changing-path and resize controls in every comparison.

### 3. Keep the unresolved quality and compatibility decisions explicit

**A2 performance remains unmet.** The dogfood default was accepted with a
documented text regression. Faster squares and lower zoom bandwidth do not
close that gate.

**Zero-border zoomed text still misses the historical AA threshold.** The
earlier run had 0.8829% of pixels over the 24/255 difference threshold against
a 0.5% limit. Independent coverage evidence favors the selected AA, but that
is a separate result. Production border tests passing does not waive this.

**Nonplanar ordinary filled contours still raise explicitly.** They have no
unique interior surface. The implementation declined blanket silent fallback;
use a representative scene to establish required projection/depth/paint
semantics before adding support. Existing `Surface`/`VMobject3D` and explicit
historical renderers are available where appropriate.

**Large non-affine paint remains expensive and visually different.** Define
the desired field semantics and compare against an independent reference
before selecting an acceleration or changing interpolation. Affine fields
already have a cheap route. Do not replace general paint with a text shortcut.

### 4. Instrument reads before changing source ownership

Use the existing `maniml/performance.py` recorder to distinguish raw array
reads (`get_points`, direct `data['point']`) from reductions such as center,
bounds, endpoints and trackers. Tag whether reads occur during a play, inside
an updater or between plays. This is a stated Phase B prerequisite, not
implemented merely because stage timing exists. Course traces should guide
where eager Python reads require synchronization.

The serializer still must see direct in-place public-array edits that bypass
revision counters. The older TODO suggestion to skip all unchanged batches
using only `(id, geometry_revision)` is unsafe without a complete mutation
contract. Current digest reuse is restricted to immutable derived arrays;
do not weaken that boundary for a benchmark.

### 5. Begin Phase B with a bounded shadow implementation and feasibility gate

The approved destination is GPU source evaluation plus valid current geometry
through the same renderer. Start with source/generated resource identities,
dependency stamps, capacities/status and CPU-oracle comparisons. Affine point
operations and bounded generators are useful first cases; they are not the
general topology milestone.

For general paths, prove a convex-to-concave diagonal flip, holes,
self-intersections, changing contour counts and degeneration with coherent
vertices/indices/materials. Specify float32 classification and overflow
recovery. Count/scan/emit and indirect draws are allocation/delivery tools,
not a general fill algorithm. The existing Lyon implementation remains the
CPU generator; a portable production GPU replacement is not selected.

Flip ownership only for operation/generator combinations that pass source,
coverage, pixel, lifetime and total-frame checks. Do not build the normal path
as GPU point updates followed by CPU readback/tessellation/upload. Supported
GPU playback should have no ordinary per-frame point/mesh readback or upload.
Explicit raw reads may synchronize. Keep evaluated GPU state reconstructible
when evicted, and do not retain every generated mesh in every checkpoint.

Then extend reductions, supported updaters and the GPU clock; stateful
simulation needs its own saved-state/replay policy. The Phase B document's
2–4 focused weeks is an initial feasibility timebox, not a delivery promise.
Vello, Skia and MathBox links in that document are research references, not
adopted drop-in generators. Revalidate their current APIs if using them.

### Other backlog; do when evidence makes it worthwhile

- Checkpoint thaw reuse remains open; backward navigation still copies the
  restored graph. Avoid a major new copy-on-write system that duplicates the
  future resource/recipe architecture.
- Global child `z_index` across top-level families remains limited. The
  deliberate fixed-frame ordering policy is not a fix for global sorting.
- `AddTextWordByWord`, multi-part MathTex typography and the older CE field
  reports need targeted current-version repros, not blanket compatibility claims.
- App/relay/launch-agent failure-path coverage and Windows/Linux packaging
  remain follow-ups. The locally tested platform is macOS arm64.
- Cell-style source files and a Typst backend remain design possibilities;
  they are not the current renderer/GPU implementation plan.

## Validation that exists, and how to continue it

At `00d8e854`, full discovery with real GPU tests and ledger verification ran
**704 tests in 207.674 seconds, no failures/errors, one existing skip**.
The first run found a stale wire snapshot assertion counting GPU output as
uploaded vertices. Its replacement validates complete payload spans,
definitions, output capacity and indices; the full rerun passed. This is
recorded evidence from the implementation round, not a new test run performed
just to write this handoff.

Actual isolated Chrome checks passed 35 direct-driver and 20 production-player
frames, including paint/border cache recovery, reinitialization and seeks,
with no observed GPU validation errors. CPU/GPU borders matched exactly at
the two browser poses. The browser archive states its launch flags, opaque
canvas scope and limited fixtures; it does not establish general browser
performance or a fresh multi-tab selector test.

Eight production native border image controls were byte-exact locally.
Some benchmark large-zoom/tilt frames differ by up to 15/255 in one channel;
other controls are exact. Existing old/new AA and paint differences remain.
Offline wheel/source builds, Twine, compilation and extracted-wheel GL/GPU
captures passed. The wheel tests block development imports and use packaged
Lyon/WGSL. Remote CI/Python-matrix and Windows/Linux runs are not claimed.

From the branch repository root, with installed dependencies and built Lyon:

```sh
cd /Users/taylorjweidman/Projects/ManimLive/maniml-perf
MANIML_TEST_GPU=1 MANIML_VERIFY_LEDGER=1 \
  /Users/taylorjweidman/Projects/ManimLive/maniml/.venv/bin/python \
  -m unittest discover -s tests -t .
```

Use the **absolute interpreter path**: an earlier relative-path invocation
caused a subprocess test artifact. Without `MANIML_TEST_GPU=1`, GPU-gated
tests skip and the result must not be described as GPU validation. Full
integration needs local WebSocket access. Native rendering needs GPU access.
Run affected tests first, then the required broader checks after real changes.

The previous source-worktree run used these optional scratch paths:

```sh
export MPLCONFIGDIR=/private/tmp/maniml-triangle-mpl
export MANIML_LYON_LIBRARY=/private/tmp/maniml-triangle-target/release/libmaniml_lyon_fill.dylib
```

Check that the helper still exists before using that override; it is not a
portable dependency. The [Lyon build guide](/Users/taylorjweidman/Projects/ManimLive/maniml/tools/lyon_fill/README.md)
and locked build configuration are authoritative. Source/editable installs
need Cargo and a linker; tested Rust is 1.97.0. Compatible wheels include the
helper. Do not make it optional while the default renderer requires it.

Useful commands, from the repo root with its Python environment:

```sh
python -m benchmarks.gpu_borders --samples 12 --warmups 3 --output /tmp/fable-borders
python -m benchmarks.gpu_borders --samples 12 --warmups 3 --transport --output /tmp/fable-borders-ws
python -m benchmarks.curve_redraw --samples 20
python tests/check_wheel.py --load-native --load-gl --load-wgpu /absolute/path/to/built.whl
```

For an isolated scene run, set `MANIML_PERF_PATH` to a temporary JSON path
(it accepts `{pid}`) to record `geometry.*`, `checkpoint.*` and other stages.
Browser presentation uses a different clock; measure it in the browser rather
than combining timestamps silently.

Focused regression entry points include `tests.test_gpu_border_geometry`,
`tests.test_border_compute`, `tests.test_gpu_border_audit`,
`tests.test_gpu_border_quality`, `tests.test_generated_geometry`,
`tests.test_generated_wgpu`, `tests.test_generated_webgpu_commands`,
`tests.test_native_gl_camera`, `tests.test_renderer_ordering`,
`tests.test_renderer_selection`, `tests.test_web_viewer`,
`tests.test_static_assets` and `tests.test_export_publication`. The CI workflow
contains explicit module lists; keep new tests discoverable there too.

## Avoid these stale-document traps

The broad renderer plan contains multiple review rounds. The A0 and A1
documents record earlier prototypes/opt-in behavior; they do not describe the
current default or its current timings. `PERFORMANCE.md` is an older record.
Use commit/date-qualified measurements and the latest response sections.

The workspace-only
[instruction-stream sequence](/Users/taylorjweidman/Projects/ManimLive/simlab/INSTRUCTION_STREAM_PLAN.md)
still contains a prerequisite saying native GL must be deleted before any
work, and an opening statement anticipating winding retirement. Those conflict
with the current retained-reference direction and with the already shipped
GPU border increment. Do not delete either reference to satisfy old wording.
Reconcile that roadmap before using it to schedule production ownership
changes; read instrumentation, correctness and both-host generation remain
real prerequisites.

The Phase B specification's remaining “native-GL cutover” prerequisite should
refer to shared WebGPU output readiness, not deletion of the retained GL
reference. The older TODO description of 3D still needing borders/gradients
before replacing 2D also predates the implementation summarized here.

The older TODO revision-only caching suggestion and field reports also need
the qualifications above. This handoff identifies their conflicts rather than
silently rewriting reviewer-owned or workspace-only documents.

## Suggested first session for Claude Fable

Check HEAD, local edits, installed imports and any new review notes. Read the
latest implementation response and final benchmark evidence. Confirm one
representative current course scene on Phase A and Original 2D, preserving
the same checkpoint. Produce a short, measured list separating visible bugs,
remaining CPU preparation, GPU draw cost and source-read synchronization
needs. Pick a bounded next change from that evidence, keep all references
available, and update the decision/response record with what it proves and
what remains open.
