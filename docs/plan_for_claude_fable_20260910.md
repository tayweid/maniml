# Plan for the next Claude Fable session

Prepared 2026-09-10 by the reviewing session, for a fresh Claude Fable
instance taking over implementation. Read it together with the coder's
[handoff](handoff_claude_fable_20260910.md). The handoff describes what
exists and why. This document says what to do, in what order, with what
acceptance criteria, and where the handoff is incomplete.

Baseline: `main` in `/Users/taylorjweidman/Projects/ManimLive/maniml` at
`8a5bb7f0`, one commit past the handoff's stated `00d8e854`. That extra commit
is the seventh review round in `unified_triangle_renderer_code_review.md`,
which the handoff does not yet reflect. The handoff itself is untracked in the
`maniml-perf` worktree; commit it first.

## 1. Boundaries that override everything below

These come from Taylor directly. They are not recommendations.

- **Never `git push`.** Commit and merge locally. Taylor pushes.
- **No attribution lines in commits.** No `Co-Authored-By`, no generated-with
  footers, in trailer or body.
- **Native GL stays in the package** as `NativeGLCamera`, with its shaders,
  the public `ShaderWrapper`, and runtime `moderngl` and `PyOpenGL`. It is the
  ground truth for a while longer. An earlier session removed it on an
  authorization Taylor never gave; it was restored in `7324ce89`. Do not
  remove, deprecate, or make it optional.
- **Phase A stays the default** for the live viewer, native output, and new
  exports. **Original 2D stays selectable** in the viewer at the same
  checkpoint.
- **Do not attribute approvals to Taylor** that Taylor did not state. Two
  prior records did this ("Taylor authorized GL removal", "Taylor approved
  the sequence"). Record what Taylor said, quote it if possible, and mark
  your own inferences as yours.
- **Do not widen image thresholds** to make an unmet gate pass, and do not
  silently switch renderers for unsupported content.
- **Reviewer documents are not yours to edit.** Put implementation responses
  in `unified_triangle_renderer_review_response.md`. The reviewer writes
  `unified_triangle_renderer_code_review.md` and the reviewer notes in
  the plan.
- **Ask Taylor** when a change alters visible semantics for existing scenes.
  Proceed autonomously on measured engineering work inside the direction above.

## 2. Session start checklist

Run these before any edit. Each takes under a minute except the suite.

1. `git -C maniml log --oneline -3` and `git -C maniml status --short`. Expect
   `8a5bb7f0` and two untracked field reports, `ce_compat_notes.md` and
   `dogfood_2026-09-09.md`. Preserve both.
2. `git -C maniml-perf status --short`. Expect the untracked handoff. Commit
   it on its own: "Add the Claude Fable handoff record".
3. From `/private/tmp`, confirm the interpreter imports the canonical
   checkout: `/opt/miniconda3/bin/python -c 'import maniml; print(maniml.__file__)'`
   must print the path under `maniml/maniml/`.
4. Confirm the packaged Lyon helper exists:
   `ls maniml/maniml/web/maniml_lyon_fill*.so`.
5. Check for a newer reviewer round: `grep -n '^## ' maniml/docs/unified_triangle_renderer_code_review.md | tail -3`.
6. Run the focused suites, then the full suite in the background with the
   absolute interpreter path:

```bash
cd /Users/taylorjweidman/Projects/ManimLive/maniml && MPLCONFIGDIR=/private/tmp/maniml-mpl MANIML_TEST_GPU=1 MANIML_VERIFY_LEDGER=1 /Users/taylorjweidman/Projects/ManimLive/maniml/.venv/bin/python -m unittest discover -s tests -t .
```

Expected: 704 tests, 0 failures, 31 skips. Thirty of those skips are the A0
experiment tests gated on `MANIML_LYON_LIBRARY`; passing the packaged helper's
path makes them run and pass. Work package 2 fixes that gate.

## 3. Work packages, in order

Each package has a goal, the files involved, acceptance criteria, and the
measurement that proves it. Do them in this order unless Taylor says
otherwise. Packages 1 through 4 are engineering inside the current
architecture. Package 5 is the Phase B prerequisite. Package 6 is roadmap
hygiene. Package 7 is Phase B itself and does not start before 1 through 5.

### WP1. Establish the live baseline on a real course scene

**Goal.** Know what Taylor actually experiences on the current build before
optimizing anything.

**Do.** Run `econ-0100/Blocks/B0_Markets/03_Code.py` scene `EpisodeB0` (and one
A-block episode) in the live viewer on Phase A, then switch to Original 2D at
the same checkpoint. Exercise text zoom and pan, Write and Transform, fixed
overlays, translucent fills, reverse and jump navigation, source reload while
the viewer is open, and the renderer switch. Record stages with
`MANIML_PERF_PATH=/private/tmp/maniml-perf-{pid}.json`.

**Known issues to reproduce first**, from the 2026-09-09 dogfood report and
its follow-up memory. Every one was identified, none was fixed:

| Symptom | Identified cause | Where |
|---|---|---|
| Live viewer slow and laggy | `always_redraw` rebuilds two `ax.plot` curves every frame, 359 ms per update; `ParametricCurve.init_points` samples 2001 points in a Python loop | `mobject/mobject_update_utils.py`, `mobject/functions.py` |
| Viewer disconnects while a Claude session edits the file | Scene server closes with 1013 when `_events` reaches 1024; drain runs only from `on_frame_rendered`, which a skip-animations replay never reaches; queue never cleared on close; page gives up after 3 retries | `web/viewer.py`, `web/server.py` |
| Removed `Tex` stays on screen after an edit lands during navigation | Unverified ledger miss; run with `MANIML_VERIFY_LEDGER=1` | `scene/checkpoints.py` |
| Mobjects faded in by one `play` appear at different times | Not diagnosed | |
| `AddTextLetterByLetter` not importable, alias is per-word | Alias only, not exported, chunks at `time_per_word` | `animation/creation.py:268`, `maniml/__init__.py` |

**Deliverable.** A short measured list in the response document separating:
visible bugs, CPU preparation cost, GPU draw cost, transport, and browser
presentation. No fixes in this package. Ask Taylor which of the field-report
items to take in WP3; Taylor asked for them to be noted during the dogfood
pause, not fixed unprompted.

**Acceptance.** Each row above has a current-commit reproduction or a note
that it no longer reproduces.

### WP2. Take the seventh-round findings on GPU borders

**Goal.** Remove the fixed-capacity costs that will bite course scenes with
several paragraphs, and the artificial ceiling.

Files: `web/gpu_border_geometry.py`, `web/generated_geometry.py`,
`web/static/wgsl/border_compute.wgsl`, `web/wgpu_renderer.py`,
`web/static/webgpu.js`, `web/border_geometry.py`, `tests/test_earcut_probe.py`,
`tests/test_renderer_motion.py`, `tests/test_triangle_renderer.py`,
`tests/test_triangle_scene.py`.

1. **Stop sending the padded border index pattern.** The first TeX frame is
   3.1 MB, of which 2.4 MB is 607,842 indices that follow a deterministic
   pattern: curve index times 64 plus a fixed strip layout. It is also most of
   the 2.67 MB fill-refinement packet. Either generate the border tail with a
   non-indexed draw and vertex-index arithmetic in the vertex stage, or build
   the index buffer once per driver from the curve count. Send only fill
   indices. Keep the fill-A, border-A, fill-B, border-B order.
2. **Size border capacity from actual step counts.** Static text retains
   11.5 MB of GPU geometry against 1.24 MB with CPU borders because every
   curve reserves 64 vertices. Most glyph curves never reach 32 steps.
   Reserve per object from the maximum step count at the current zoom, with
   headroom matching the fill cache's 2× policy, and regenerate only when the
   headroom is exceeded. Compact count/scan/emit stays future work.
3. **Remove the CPU triangle budget from the GPU path.** `BorderSource.read`
   still raises `TessellationLimitError` at 87,381 estimated triangles. GPU
   output is fixed capacity and already allocated, so the budget protects
   nothing and turns a deep zoom into a render error. Gate on the buffer and
   binding limits the drivers already check.
4. **Key border outputs by uniform state, not draw ordinal.** Inserting an
   earlier object currently churns every later bordered object's buffer.
5. **Gate the A0 experiment tests on packaged helper discovery**, not the
   environment variable.

**Measurement.** `python -m benchmarks.gpu_borders --samples 12 --warmups 3 --output /tmp/borders` before and after, plus the transport variant with `--transport`.

**Acceptance.**

| Metric, 101-glyph TeX | Now | Target |
|---|---:|---:|
| First-frame packet | 3.1 MB | under 1 MB |
| Fill-refinement packet at 1 to 4 zoom | 2.67 MB | fill bytes only |
| Retained GPU geometry, static text | 11.5 MB | under 4 MB |
| 5% zoom step packet | 1.2 KB | unchanged |
| Deep zoom into large text | render error | renders or reports a limitation |

All eight `gpu_borders` controls stay pixel-exact against the CPU border
reference, which stays selectable with `MANIML_BORDER_GENERATOR=cpu`.

### WP3. Engine fixes from the field reports, with Taylor's go

**Goal.** The items Taylor hits in production that are engine bugs, not
renderer work. Take only those Taylor confirms after WP1.

| Item | Fix shape | Acceptance |
|---|---|---|
| `ParametricCurve` sampling | Vectorize `init_points`; keep scalar callbacks in order | `always_redraw` of two plots under 5 ms per update on EpisodeB0 |
| Event queue overflow | Drain during replays; clear on close; bound the producer in `broadcast()` | No 1013 close during a source edit plus navigation; reconnect succeeds first try |
| `AddTextLetterByLetter` | Export it; make it a per-glyph subclass | Importable via `from manim import *`; reveals per character |
| `Transform` between mismatched point counts | Port CE's `align_data` resampling | A3 stage-1 merge no longer raises |
| Draw order through `play(FadeIn(group))` | Make the play path sort like `add` | A3 `autarky_marker` draws the dot over the dashes without `bring_to_front` |
| Ghost after edit during navigation | Reproduce under `MANIML_VERIFY_LEDGER=1`; fix the missed bump | The verify run names no stale attribute on B0 and A3 |

Do not start `TracedPath`, Tex ligatures, or `{{...}}` size scoping unless
Taylor asks; they are CE-compat items, not dogfood blockers.

### WP4. The per-frame source validation cost

**Goal.** Close most of the remaining text gap. An unchanged text frame still
costs about 5.9 ms to prepare with nothing to send, and repeated zoom is
10.65 ms on Phase A against 5.49 ms on Original 2D. The cost is the byte
comparison of every source array on every frame.

**This is a decision for Taylor, not a unilateral change.** The coder has
declined revision-based reuse twice on the grounds that public arrays can be
edited in place without a revision bump. The reviewer's position is that the
checkpoint ledger already trusts `Mobject.revision` for correctness and
catches bypass writes with `MANIML_VERIFY_LEDGER=1`, so the renderer can adopt
the same contract with the same verify mode. Present both positions to Taylor
with the measured numbers and implement whichever Taylor picks.

If revision-based: key cache validity on `(id, revision)` behind a flag, keep
the byte comparison as the verify mode that raises naming the attribute, run
both course episodes under it, and default it on only when the verify runs
are clean.

**Acceptance.** Unchanged text frame preparation under 1.5 ms; repeated 5%
zoom within 25% of Original 2D on the same harness; verify mode clean on
EpisodeB0 and A3.

### WP5. Read instrumentation, the Phase B prerequisite

**Goal.** Know which Python reads would need synchronization if points lived
on the GPU. This has been a stated prerequisite since 2026-09-03 and is still
not implemented.

**Do.** Add `performance` counters for raw point reads (`get_points`, direct
`data["point"]` access) versus reduction reads (bounding box, center,
endpoints, tracker values), tagged by whether they happen inside a play,
inside an updater, or between plays. Run EpisodeB0, A2, A3 and the dogfood
scenes. About a day.

**Acceptance.** A table per episode of read counts by category and phase,
in the response document, with the sites that dominate named.

### WP6. Reconcile the roadmap documents

**Goal.** Stop three documents from contradicting Taylor's direction.

- `../simlab/INSTRUCTION_STREAM_PLAN.md` says native GL must be deleted
  before any Phase B work and anticipates winding retirement. Reword the
  prerequisite to "shared WebGPU output exists in both hosts", which is now
  true, and note that GL and Original 2D are retained references.
- `gpu_geometry_generation_plan.md` has the same "native-GL cutover"
  prerequisite. Same fix.
- `TODO.md` item 2 still proposes skipping unchanged batches by
  `(id, geometry_revision)` alone. Replace it with a pointer to the WP4
  decision.

`simlab` is not a git repository; edit in place and say so in the response
document. Do not touch the reviewer-owned documents.

### WP7. The open quality gates

These stay open until evidence closes them. Record status, do not paper over.

- **A2 text performance.** Closed only when the harness shows Phase A within
  the plan's gate on the text controls. WP2 and WP4 are the levers.
- **Zero-border zoomed text AA.** 0.88% of pixels over the 24-level
  threshold against a 0.5% limit. The 16× coverage reference favors the new
  sampler; that is a separate result. Keep both statements.
- **Nonplanar filled contours raise.** Build one representative scene, a
  filled closed 3D curve, and put the choice to Taylor: explicit error, a
  warning plus camera-projected fill, or the old behavior behind the GL
  camera. Do not decide this alone; existing scenes that used to run are
  affected.
- **Large non-affine paint.** The 800-node inverse-distance loop is
  expensive and visibly different from historical fan interpolation. Define
  the intended field semantics with Taylor before choosing an acceleration.

### WP8. Phase B, Phase 0 feasibility, timeboxed

Do not start before WP1 through WP5 are done and Taylor has seen their
results. Then follow `gpu_geometry_generation_plan.md` section 4 and the
instruction-stream plan's Phase 0, as a shadow implementation with the CPU
generator as oracle.

Exit criteria are already written there: a convex-to-concave diagonal flip,
holes, self-intersections, changing contour counts, and degeneration with
coherent vertices, indices, and materials; float32 classification specified;
forced capacity failure never presenting a partial scene. The 2 to 4 week
figure is a feasibility timebox. Report at the end of it whether a portable
GPU generator exists, with numbers, and re-estimate. Do not build the normal
path as GPU points followed by CPU readback and re-upload.

## 4. Measurement rules

Every timing claim in this project has been checked by the reviewer. Keep
them checkable.

- Use the absolute interpreter path in subprocess tests; a relative path
  produced a false failure once.
- One-pixel readback completion times are bimodal on this machine, roughly
  1.4 ms or 12.8 ms. Report the minimum and the fractions under 3 ms and
  over 10 ms alongside medians; never a median alone at small scenes.
- Three warmups, twelve rotated samples, alternate variants, fresh sources
  per variant. Do not run two GPU timing jobs at once.
- Separate source evaluation, CPU preparation, encoding, submission through
  completion, transport bytes, and browser presentation. Browser presentation
  is measured in the browser, on its own clock.
- Compare against all three references when the change touches drawing:
  GPU-border Phase A, CPU-border Phase A, Original 2D, and `NativeGLCamera`.
- Archive reports under `benchmarks/results/<name>_<date>/` with source
  hashes, as the existing harnesses do. Prefer summaries over multi-megabyte
  per-frame dumps.

## 5. Reporting and commits

- One commit per work package, message describing the change and its
  reasoning, no attribution lines.
- After each package, append a dated section to
  `unified_triangle_renderer_review_response.md` with what changed,
  what it measured, and what remains open. Update `DECISIONS.md` only for
  decisions Taylor made, quoting the direction.
- Integrate validated commits from the `maniml-perf` worktree into the
  canonical `maniml` checkout by fast-forward. Do not push.
- When a finding from the reviewer turns out wrong, say so with the evidence,
  as the coder did for the fixed-frame ordering. When it turns out right,
  say that too.

## 6. Quick reference

```bash
# Focused suites after a renderer change
MANIML_TEST_GPU=1 ./.venv/bin/python -m unittest tests.test_gpu_border_geometry tests.test_border_compute tests.test_gpu_border_audit tests.test_gpu_border_quality tests.test_generated_geometry tests.test_generated_wgpu tests.test_generated_webgpu_commands tests.test_native_gl_camera tests.test_renderer_ordering tests.test_renderer_selection
```

```bash
# Four-reference border harness, native and with WebSocket transport
./.venv/bin/python -m benchmarks.gpu_borders --samples 12 --warmups 3 --output /tmp/borders
./.venv/bin/python -m benchmarks.gpu_borders --samples 12 --warmups 3 --transport --output /tmp/borders-ws
```

```bash
# Render one scene with each renderer for a pixel comparison
./.venv/bin/python -m maniml scene.py SceneName --render          # Phase A default
# set camera_class = NativeGLCamera on a subclass in the scene file for the GL reference
```

```bash
# Wheel build and check, needs cargo 1.97
uv build --wheel --out-dir /tmp/wheel && ./.venv/bin/python tests/check_wheel.py --load-native --load-gl --load-wgpu /tmp/wheel/*.whl
```

Key files by concern are tabulated in the handoff's "Current rendering
architecture" section; that table is accurate at `8a5bb7f0`.
