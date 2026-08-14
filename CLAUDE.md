# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**maniml** is a ManimCE-compatible API running on ManimGL's fast OpenGL backend, with an interactive checkpoint system for rapid iteration. Installed editable (`pip install -e .`) as the `maniml` command.

The package is `maniml` (`import maniml`), so it does not shadow a real ManimCE install. Unmodified CE scene files still work: the CLI installs a process-local import alias (`_CEAliasFinder` in `maniml/__main__.py`) mapping `manim`/`manim.*` to maniml, so `from manim import *` resolves correctly under the `maniml` command while leaving any installed ManimCE untouched elsewhere.

Useful sibling checkouts (reference only, not tracked here — clone as needed):

```bash
git clone https://github.com/ManimCommunity/manim.git ../manimce   # current CE (conformance reference)
git clone https://github.com/3b1b/manim.git ../manimgl             # upstream GL (architecture reference)
```

Rule for CE compatibility work: target **current** ManimCE only (check `../manimce` for what current CE does); scene-side fixes belong in scenes, not in maniml.

## Commands

```bash
# Run a scene (opens interactive OpenGL window)
maniml script.py SceneName
python -m maniml script.py SceneName    # equivalent

# Presentation mode: pre-runs every unit up front (validates the whole
# scene, builds all checkpoints), watcher off, clickable timeline at the
# bottom edge of the window
maniml script.py SceneName --present

# Render mode (headless): writes ./media/SceneName.mp4 plus a PNG per
# checkpoint under ./media/SceneName_checkpoints/
maniml script.py SceneName --render

# Browser viewer: same interactive development (checkpoints, watcher,
# click-to-inspect), viewed in a browser tab instead of the pyglet
# window; combines with --present. --no-browser skips the auto-open.
# The viewer bar has a three-way renderer control: Pixel (server
# stream), WebGL2, WebGPU (client-rendered), plus a split toggle.
maniml script.py SceneName --web

# The app (Stage 3): persistent local server with a landing page
# listing scene files under [dir] (default cwd); each scene opens as
# its own --web subprocess (crash isolation), same viewer as above
maniml app [dir]

# Unit tests (stdlib unittest; test_web_viewer is a headless end-to-end
# drive of --web over a real WebSocket)
python -m unittest tests.test_source_map tests.test_checkpoint_reload tests.test_modes tests.test_ce_conformance tests.test_web_viewer tests.test_gl_port

# Windowed interactive tests (real OpenGL window; drives actual key/mouse
# handlers; needs a display, so opt-in)
MANIML_WINDOW_TESTS=1 python -m unittest tests.test_interactive
# ...or one scenario directly:
python -m tests.interactive.dev_mode

# CE API conformance: tests/ce_conformance/ce_api_names.txt is the CE
# public API (regenerate: python -m tests.ce_conformance.extract_ce_names ../manimce);
# after deliberately adding/removing CE compat, refresh the baseline:
python -m tests.ce_conformance.update_baseline

# Sanity check
python -c "import maniml"
```

## Architecture: the interactive checkpoint system

All of this lives in `maniml/`:

1. **Entry point** (`__main__.py`): loads the scene file as a real module registered in `sys.modules` (required for checkpoint-0 namespace capture), creates a window, sets `scene._scene_filepath`, and calls `scene.run()`.

2. **Source map** (`scene/source_map.py`): parses the scene file with AST and splits `construct()` into **animation units** — runs of consecutive top-level statements ending with a statement containing a `.play(...)` call. A play inside a for-loop/if keeps its whole enclosing statement. Trailing statements after the last play (e.g. `self.wait()`) form a tail unit with `has_play=False`. Unit-tested in `tests/test_source_map.py`.

3. **Scene / checkpoints** (`scene/scene.py` + `scene/checkpoints.py`): `Scene` is composed from mixins — `CheckpointMixin` (`checkpoints.py`: checkpoint save/restore, unit re-execution, watcher replay, `deepcopy_namespace`), `InteractionMixin` (`interaction.py`: key/mouse handlers, reverse morph, click-to-inspect/drag), `PresentationMixin` (`presentation.py`: present mode, timeline, render mode) — with `scene.py` keeping the core lifecycle, `SceneState`, and `ThreeDScene`.
   - `run()` never calls `construct()` directly; it creates checkpoint 0 (deep copy of the scene module's namespace) and executes one unit at a time via `run_next_animation()`.
   - Each `play()` saves a checkpoint `{index, line_number, unit_index, state, namespace}` — namespace and scene state are deep-copied *together* (`deepcopy_namespace`) so variable↔mobject references survive.
   - `run_next_animation()` deep-copies the current checkpoint, restores its state, and `exec`s the next unit's source (compiled with the real filename) with `__animation_line_number__` / `__animation_unit_index__` planted in the namespace as the anchor for the checkpoints play() will save. On exec error it rolls back to the last saved checkpoint.
   - Arrow keys (in `on_key_press`): RIGHT re-executes the next unit from source; UP/DOWN jump between stored checkpoint states; LEFT plays an animated morph back to the previous checkpoint (`_play_reverse_to` pairs mobjects by variable name: matched pairs Transform, unmatched fade; display-only, suppressed from checkpointing via `_no_checkpoints()`).
   - **Copy discipline**: `SceneState` stores direct references; isolation happens by deep-copying state+namespace *together* at save time. Anything restored for display (UP/DOWN/LEFT, undo/redo) goes through `SceneState.copy()` so on-screen mutation can never corrupt stored history. `run_next_animation` deep-copies the whole checkpoint before exec for the same reason.

4. **Run modes** (dispatched in `Scene.run()`): default interactive; `--present` → `_prepare_presentation()` (fast-forward all units via `temp_skip`, rewind to checkpoint 0, watcher off, mouse-at-bottom-edge timeline scrubber built from `_show_timeline`/`_handle_timeline_click`; overlay excluded from checkpoints via the ignore list in `get_state` and re-attached across restores in `restore_state`); `--render` → `_render_all()` headless (frames to `SceneFileWriter`, one PNG per checkpoint — intermediate loop checkpoints are restored individually for their snapshots). Note `config.py`'s import-time parser uses `parse_known_args` (and `add_help=False`) so maniml-only flags and `--help` pass through.

5. **Click-to-inspect / drag** (development mode): left-press hit-tests top-down via `point_to_mobject` (bbox + SMALL_BUFF; camera frame, timeline, fixed-in-frame excluded). Prints the variable name (scanned from `_live_namespace` — the exec namespace of the last-run unit, kept alive precisely for this; identity lookups against stored checkpoints fail because those are deep copies) and center; drag moves the mobject (pan is suppressed while grabbing); release prints a paste-ready `name.move_to([x, y, z])`. Navigation keeps names resolvable by restoring state+namespace together (`_restore_checkpoint_for_display`).

6. **Browser viewer** (`maniml/web/`, `--web` flag): an additive frontend that stands in for the pyglet window; the pyglet path is unchanged and remains the default. `viewer.py`'s `WebViewer` duck-types the small Window interface Scene uses (`init_for_scene`, `is_closing`, `has_undrawn_event`, `is_key_pressed`, `focus`, `_window.dispatch_events`), so `InteractionMixin` and the checkpoint system run unmodified; `scene.py` detects it via the `is_web_viewer` attribute (`scene._web_viewer`) and gives the camera `window=None` — rendering happens on the standalone (windowless) GL context, the same tested path `--render` uses. `server.py` runs two daemon threads: a stdlib HTTP server for `static/index.html` and a `websockets` server for the frame/event protocol (server→client: binary frames — 1 header byte, 0x01 JPEG / 0x02 PNG, image GL-bottom-up so the client flips via canvas transform — plus state JSON `{current, count, lines}`; client→server: key/pointer/chip JSON, pointer coords normalized to the frame [0,1] y-up, so no window-size bookkeeping). Streaming policy in `WebViewer.on_frame_rendered` (hooked after every `camera.capture`): JPEG while animating / input events arriving / any top-level mobject `has_updaters()`, one lossless PNG once quiet, a forced PNG on any checkpoint-state change (covers present-mode prep and watcher replays, which repaint without input events), nothing when no client is connected. Input events drain inside `on_frame_rendered` — the same place pyglet dispatches (during the render tick) — with a re-entrancy guard so a RIGHT-key `run_next_animation` doesn't recursively drain. End-to-end tested headlessly in `tests/test_web_viewer.py`.

7. **Client-side rendering experiment** (Stage 2, `maniml/web/geometry.py` + `static/glsl/` + `static/gl.js` + `reference_renderer.py`): the client's "GL" toggle requests a geometry snapshot (message 0x03: JSON header with camera/mobject uniforms + the raw interleaved VMobject vertex structs) and renders it with WebGL2 next to the pixel stream. The native geometry shaders are re-expressed as instanced vertex shaders (one instance per bezier triple, `gl_VertexID` picks the strip vertex); shader sources are shared between the browser and `reference_renderer.py`, a desktop-GL mirror of gl.js that `tests/test_gl_port.py` pixel-diffs against the native renderer — **edit gl.js and reference_renderer.py together**. 2D VMobjects only; depth-tested/triangulated fill, images, surfaces, dot clouds are listed `unsupported` and stay on the pixel stream.

8. **File watcher** (`scene/file_watcher.py` + `_handle_file_change` in `scene/checkpoints.py`): polling thread diffs the file on save and reports the earliest changed line. The handler re-anchors against the new source map: checkpoints from units before the edited unit survive; later ones are discarded and replayed — fast-forwarded via `temp_skip()`, with the edited unit played at real speed (`_replay_to_unit`). Edits **outside** construct() (imports, constants, helpers, other methods) trigger `_restart_from_source()`: reload the module (bypassing the bytecode cache — see `load_scene_module`), rebuild checkpoint 0, fast-forward back to where the user was. Integration-tested headlessly in `tests/test_checkpoint_reload.py`.

### Known weak spots (as of 2026-08)

- `deepcopy_namespace` falls back to per-value copies with a shared memo when batch deepcopy fails, and keeps live references (with a named warning) for values that cannot copy at all; a scene holding non-picklable state degrades checkpoint isolation.
- LEFT-arrow reverse is a per-object morph, not a true reversal of the original animation; complex changes blend rather than retrace. (It filters out `CameraFrame` before morphing — the frame lives in `self.mobjects` but can't be Transformed.)
- CE `color=` kwarg compatibility was fixed piecemeal (2026-08): classes must not pin `stroke_color=`/`fill_color=` defaults in `__init__` — that silently overrides a user's `color=` (VMobject resolves `stroke_color or color`, `fill_color or color`). Circle, Dot, Arrow, ArrowTip, StrokeArrow, AnnularSector, Annulus, and StringMobject (all Tex/Text) were converted; other classes may still have the pattern.
- `z_index` is CE-compatible via a stable draw-order sort of top-level mobjects (`assemble_render_groups`); within-family z_index is not sorted.

ManimGL's IPython embed mode (`scene_embed.py`, comment-keyed `checkpoint_paste`) was **removed** in 2026-07 — the checkpoint system is its replacement. `self.embed()` remains as a stub that logs a warning. If a live REPL is ever wanted again, build it on the arrow-key checkpoint history rather than reviving the old module.

## 3D Scenes

`ThreeDScene` supports CE-style camera control (`set_camera_orientation`, `begin_ambient_camera_rotation`) and 3D mobjects (`Sphere`, `Cube`, `Torus`, `ThreeDAxes`, ...).

**3D fill rendering (fixed 2026-08-11)**: `ThreeDScene.add` calls `apply_depth_test()` on added mobjects, which switches filled VMobjects to **triangulated fill** (`render_triangulated_fill` in `rendering/shader_wrapper.py`): real triangles with real z, so depth intersections against surfaces and other VMobjects are per-pixel correct (beyond upstream ManimGL's z=0 fill composite). The triangulated path renders every mobject of a render batch with its own fill color (`batch_mobjects` on the wrapper), and triangulation caches invalidate on point changes. Remaining constraints:

- Triangulated fill flattens each submobject to one flat fill color (no gradients) and skips the anti-aliased fill border; live-window MSAA is capped at 4 samples on macOS (offline supersampled rendering is the quality path — see TODO.md).
- Mobjects animated under depth test re-triangulate each frame the points change (earclip cost; fine for typical scenes, measurable for huge Text).
- `Camera.blit_letterboxed` resolves the MSAA fbo (ThreeDScene uses samples=4) into `draw_fbo` before the scaled window blit — an MSAA source may only blit to an equal-sized rect.

Regression-tested in `tests/interactive/three_d.py` (windowed).
