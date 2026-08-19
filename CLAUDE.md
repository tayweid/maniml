# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**maniml** is a ManimCE-compatible API running on ManimGL's fast OpenGL backend, with an interactive checkpoint system for rapid iteration. Installed editable (`pip install -e .`) as the `maniml` command.

The package is `maniml` (`import maniml`), so it does not shadow a real ManimCE install. Unmodified CE scene files still work: the CLI installs a process-local import alias (`_CEAliasFinder` in `maniml/__main__.py`) mapping `manim`/`manim.*` to maniml, so `from manim import *` resolves correctly under the `maniml` command while leaving any installed ManimCE untouched elsewhere.

The forward roadmap is `TODO.md`; the record of what was decided, shipped, or tried-and-deleted — with reasoning — is `DECISIONS.md`.

### Names, and the install trap

Three names for one project, and they do not move together: **ManimLive** is the product (page titles) and the name of the local checkout directory; **maniml** is the Python package (`import maniml`) and the GitHub repo (`tayweid/maniml`). Renaming the checkout renames neither the package nor the remote.

**Verify the install before debugging anything user-visible.** `pip install -e .` links this working tree, but the install command in the README uses `--force-reinstall` from git, which *replaces that link with a copy* under `site-packages`. Once that happens, the `maniml` command silently runs the copy, edits here do nothing, and the symptoms look like unfixable frontend bugs. Check first:

```bash
cd /tmp && python -c "import maniml; print(maniml.__file__)"   # must be this repo
```

Run it from **outside** the repo. A checkout directory named `maniml` — any capitalisation, since macOS filesystems are case-insensitive — is importable as the package from its parent directory, so the same command run from `~/Projects` can report the working tree while the installed copy is what actually runs everywhere else. Restore with `pip install -e . --no-deps` (`--no-deps` so a reinstall cannot quietly upgrade numpy out from under the rest of the environment).

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

# Baked web export (headless): records the geometry stream into
# ./media/SceneName_web/, a self-contained static player folder
maniml script.py SceneName --export

# Browser viewer: same interactive development (checkpoints, watcher,
# click-to-inspect), viewed in a browser tab instead of the pyglet
# window; combines with --present. --no-browser skips the auto-open.
# The viewer bar has a three-way renderer control: Pixel (server
# stream), WebGL2, WebGPU (client-rendered), plus a split toggle.
maniml script.py SceneName --web

# The app: persistent local server. The landing page is an Open action and
# the files you opened before — not a directory listing. A file opens at its
# first scene, as its own --web subprocess (crash isolation), in the viewer
# above; the viewer's scene picker switches scenes within that process.
maniml app [dir]

# Keep it running as a macOS login agent at http://localhost:8685. `maniml
# app` offers this once, on first run, so the terminal need not stay open;
# it also hands off to an engine already on the port rather than binding a
# second one, and restarts an agent still serving pre-upgrade code.
maniml agent install [dir]

# Full display-independent suite (~98s; test_web_viewer is a headless
# end-to-end drive of --web over a real WebSocket). CI's job definitions
# in .github/workflows/ci.yml are the canonical module lists.
python -m unittest discover -s tests -t .

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

6. **File watcher** (`scene/file_watcher.py` + `_handle_file_change` in `scene/checkpoints.py`): polling thread diffs the file on save and reports the earliest changed line. The handler re-anchors against the new source map: checkpoints from units before the edited unit survive; later ones are discarded and replayed — fast-forwarded via `temp_skip()`, with the edited unit played at real speed (`_replay_to_unit`). Edits **outside** construct() (imports, constants, helpers, other methods) trigger `_restart_from_source()`: reload the module (bypassing the bytecode cache — see `load_scene_module`), rebuild checkpoint 0, fast-forward back to where the user was. Integration-tested headlessly in `tests/test_checkpoint_reload.py`.

## The web layer (`maniml/web/`)

The browser viewer (`--web`) is an additive frontend that stands in for
the pyglet window; the pyglet path is unchanged and remains the default
until the WebGPU transition retires it (`TODO.md`). Module map:

- `server.py` — the one-port server (WebSocket + plain GETs) and `ClientLease`.
- `viewer.py` — `WebViewer`, the Window stand-in; streaming policy; the console tap.
- `app.py` — `AppServer` and its `SceneProcess` children: the relay, the control protocol.
- `library.py` — what the app knows about scene files: the AST scene scan, the recents list. Pure filesystem functions; `viewer.py`'s scene picker imports from here without touching the app machinery.
- `cli.py` — `run_app`, `running_engine`, and the handoff to an engine already on the port. What `maniml app` runs.
- `assets.py` — static serving from `web/static/`, the CSP, version-stamping.
- `security.py` — the Origin check, scene-root confinement, bounded JSON parsing.
- `geometry.py`, `reference_renderer.py`, `wgpu_renderer.py`, `export.py` — Stage 2 client rendering and the baked player (below).
- `static/` — `viewer.html` and `app.html` (each one file; shared tokens, the pod run, *and the controls a pod holds* — slug, icon button, word tag — in `shell.css`, since the landing page is the same bar as the viewer's — the chrome is Plass's toolbar with its metrics, not an imitation: 60px bar, 42px pods pressed into a run with stadium ends, contents asleep until the pointer nears, flyouts as pills laid over their trigger), `gl.js`/`glsl/` (WebGL2), `webgpu.js`/`wgsl/` (WebGPU), `player.*` (the baked player, deliberately standalone — no `shell.css`), `manifest.webmanifest` + `sw.js` (the installable local app).

### The viewer

`viewer.py`'s `WebViewer` duck-types the small Window interface Scene uses (`init_for_scene`, `is_closing`, `has_undrawn_event`, `is_key_pressed`, `focus`, `_window.dispatch_events`), so `InteractionMixin` and the checkpoint system run unmodified; `scene.py` detects it via the `is_web_viewer` attribute (`scene._web_viewer`) and gives the camera `window=None` — rendering happens on the standalone (windowless) GL context, the same tested path `--render` uses.

`server.py` runs one daemon thread: a `websockets` server that answers plain GETs for `static/viewer.html` and its assets (`web/assets.py`, via `process_request`) on the very port that carries the frame/event protocol — page and socket are one origin, so the client derives `wsUrl` from `window.location`. The WebSocket handshake requires the server's exact Origin — the page it served — before it sends frames or accepts events (`web/security.py`); there is no token and no authentication message, so the first thing a connected client receives is `{"type": "ready", "capabilities": [...]}`.

**Wire protocol.** Server→client: binary frames — 1 header byte, 0x01 JPEG / 0x02 PNG (image GL-bottom-up, so the client flips via canvas transform), 0x03 geometry — plus state JSON `{current, count, lines, units, future}` and move JSON `{from, to, back, unit}`. Client→server: key/pointer/chip JSON, pointer coords normalized to the frame [0,1] y-up, so no window-size bookkeeping.

**Moving between pausepoints.** `current_animation_index` only advances when `play()` saves its checkpoint, so a rail driven by state alone sits still for a whole animation and then teleports. `begin_animation`/`end_animation` (already called from `pre_play`/`post_play`) therefore send their own `{"type": "move", "from", "to", "back"}` — its own message for two reasons: a *state* change forces a lossless PNG under the streaming policy below, and this has to reach the client when the play starts rather than on whatever frame is sent next. It names the stretch being crossed and says nothing about progress through it: the animation is on screen at full size already, and any claim would have to hold up through `_play_reverse_to`'s morph (which has landed the index on its destination, hence `back`) and through skipped fast-forwards, which are suppressed entirely. The client lights the link between the two chips and lifts the position ring off the chip being left.

**A chip is a source statement, not a checkpoint.** The rail groups consecutive checkpoints sharing a `unit_index` into one chip, so a loop that stood as one stacked chip before it ran is still one stacked chip after — otherwise the rail swells as you step through it and every chip you were aiming at moves. That is why the state carries `units` and the move carries `unit`: a forward play's destination checkpoint does not exist yet, so only the statement being played can say whether the move stays inside the stack (the chip pulses, there being no stretch between two chips to light) or crosses to the next one.

**Streaming policy**, in `WebViewer.on_frame_rendered` (hooked after every `camera.capture`): JPEG while animating / input events arriving / any top-level mobject `has_updaters()`; one lossless PNG once quiet; a forced PNG on any checkpoint-state change (covers present-mode prep and watcher replays, which repaint without input events); nothing when no client is connected. Input events drain inside `on_frame_rendered` — the same place pyglet dispatches (during the render tick) — with a re-entrancy guard so a RIGHT-key `run_next_animation` doesn't recursively drain.

**The console.** Output rides the same socket: `OutputTap` tees `sys.stdout`/`sys.stderr` in the scene process (writes still reach the real stream, so the app can scrape the launch line) into a bounded `LogBuffer`, and `_broadcast_logs` sends new lines as `{"type": "log", "lines": [...]}` — deliberately *before* the "has anything changed" test, since an idle scene can still be printing, and with the full backlog on connect. This is the only way to see a running scene's output in app mode at all: the child's stdout is a pipe into the app process, read only when a scene fails to start. The panel is toggle-only (`C`), never automatic — stepping a scene prints on every arrow key. In full screen it rides with the rest of the chrome rather than being suppressed, overlaying rather than reflowing so the frame is not resized every time the pointer nears an edge.

End-to-end tested headlessly in `tests/test_web_viewer.py`.

### Client-side rendering (Stage 2)

The client's renderer toggles request a geometry snapshot (message 0x03: JSON header with camera/mobject uniforms + the raw interleaved VMobject vertex structs) and render it with the browser's own GPU beside — or instead of — the pixel stream. The native geometry shaders are re-expressed as instanced vertex shaders (one instance per bezier triple, `gl_VertexID` picks the strip vertex).

Two backends against the same payload: WebGL2 (`static/gl.js` + `static/glsl/`, mirrored on desktop GL by `web/reference_renderer.py` — **edit gl.js and reference_renderer.py together**, pixel-diffed in `tests/test_gl_port.py`) and WebGPU (`static/webgpu.js` + `static/wgsl/`, mirrored natively by `web/wgpu_renderer.py` — **keep all three in sync**, pixel-diffed in `tests/test_wgpu_port.py`). The live viewer starts on WebGPU and falls back visibly to Pixel. WebGPU is the decided endgame; the WebGL2 path retires after dogfooding (`TODO.md`). Anything unsupported is declared in the payload's `unsupported` list and stays on the pixel stream.

## Delivery: one artifact, local only

The interface is served by the engine that runs the scenes. `maniml app` (and
`maniml agent`) binds **one** loopback port, serves `web/static/` from the
installed package, and accepts the page's control WebSocket on that same port.
There is no hosted origin, no deployment step, and no version negotiation:
frontend and engine are the same pip install, so they cannot drift.

**One port, one origin — including scenes.** The page and its socket share an
origin exactly, so the client says `ws://${location.host}/` and is told
nothing at launch — no port parameter, no allowlist of a second origin, no
port-pair arithmetic. That is also what makes the `connect-src 'self'` in
`web/assets.py`'s CSP a real restriction rather than a comment.
`bind_loopback()` (in `server.py`) binds before the server is configured,
because the Origin allowlist needs the resolved port at that moment. A scene
runs in its own subprocess (crash isolation: scene files are arbitrary code)
and that process is a complete server in its own right — which is what
`maniml file.py Scene --web` uses — but a scene opened *through the app* must
not move the browser to that process's port, because **the port is the
installed app's identity**: a PWA installed from `http://localhost:8685` is
scoped to it, and navigating elsewhere would pop the browser out of the app
window. So `app.py` serves the viewer page itself and relays `/scene/<id>` to
the process backing it, connecting as an ordinary client. The browser only
ever sees one port.

This replaced an architecture where the UI was a PWA on GitHub Pages talking
to localhost; everything that bridged that gap — roughly 1,400 lines — is
gone. **Do not reintroduce a public origin that talks to loopback**; that seam
caused essentially every delivery bug in this project's history. The full
story and the Knuth-convergence notes are in `DECISIONS.md`.

What remains, and why:

- **The Origin check, and nothing else.** Each server accepts a socket only
  from the origin it serves its own page on. Browsers set `Origin` and a page
  cannot forge it, so no website can drive the engine. There is **no capability
  token**: one that reaches the page through the served HTML is readable by any
  local program with a `GET /`, so it defends nothing the Origin check did not
  already cover, and one delivered out of band makes launching a delivery
  problem and recovery a terminal command — against an attacker who could just
  run `python` anyway. Do not reintroduce a token without first re-reading
  `SECURITY.md`'s table: *embedding a token and keeping a token are different
  decisions, and doing the first without noticing turns the second into
  decoration.*
- **The launchd agent** (`maniml/agent.py`) keeps `http://localhost:8685` up
  without a terminal. It owns the default port for the login session, so a
  foreground `maniml app` started alongside it lands on an OS-assigned port and
  opens a page on *that* origin — which then talks to itself, not the agent,
  because the page only ever speaks to where it came from.
- **The native file dialog** (`maniml/desktop.py`, now only
  `choose_python_file`). The engine shows the platform dialog and gets a real
  path, which the watcher and the scene's `__file__`-relative imports both need.
  A browser file handle cannot provide one.

### The installed app is the local one

`web/static/manifest.webmanifest` + `sw.js` make `http://localhost:8685` an
installable app: its own icon, a window without a tab strip, and — because the
worker caches the shell — a window that still opens when the engine is not
running, says so, and heals itself when it starts (the page reconnects on its
own). `app.html` offers the install once the browser says it can.

- **The port is the identity.** A PWA is scoped to the origin it was installed
  from, which is why a scene opened through the app is relayed rather than
  navigated to (above), and why `run_app` says so out loud when the default
  port was taken and it landed elsewhere.
- **The worker is version-stamped as it is served** (`assets.py` replaces
  `__MANIML_VERSION__`). A browser installs a new worker only when the bytes
  differ, and the cache name carries the same stamp, so `pip install --upgrade`
  cannot leave an old shell in front of a new engine.
- **No `file_handlers` yet, deliberately.** A `.py` double-click arrives
  through `launchQueue` as a browser file handle, which has no filesystem path
  — and the watcher and the scene's own `__file__`-relative imports both need a
  real one (that is why `desktop.py`'s native dialog exists). Registering
  handlers would claim every `.py` on the machine and then fail to open them.

### The hosted origin is a preview, and only a preview

`site/` publishes to `maniml.tayweid.io` (`.github/workflows/site.yml`). It
shows what ManimLive is and how to install it, and it **reaches nothing** — no
socket, no manifest, no file handlers. `tests/check_site.py` enforces that in
CI and in the test run, because two invariants meet there:

- A public origin must never talk to loopback. That is the rule above.
- **Only one app may own the `.py` double-click.** If the hosted build were
  installable it would compete with the local one for every file the user
  opens, so the install offer belongs to `http://localhost:8685` alone.

`site/sw.js` is a kill switch rather than a worker: the pre-collapse hosted
build registered a caching service worker, and a browser that has it keeps
running it until a replacement at the same URL unregisters it. It must keep
existing. `site/app.html` redirects for the same reason — an old installed
shell still opens that path.

### Roadmap constraint: a zero-install browser build

A future Pyodide target would run the engine in the page with no local process.
Two things are kept deliberately intact for it, and should not be entangled with
the local transport:

- **The client-side renderers** — `static/gl.js`, `static/webgpu.js`,
  `static/glsl/`, `static/wgsl/`, `web/geometry.py`, `web/reference_renderer.py`,
  and the baked player (`web/export.py`, `static/player.*`). These already draw
  scenes with no Python in the loop; they are the basis of a browser-only build.
- **The transport seam in `viewer.html`.** The WebSocket is confined to `wsUrl`,
  `send()`, and the message pump; everything else speaks only in protocol
  messages. An in-page engine should be able to replace those three things.
  This is also why `viewer.html` stays a single file, and why
  `tests/test_static_assets.py` pins its source shape.

A hosted build would need its own manifest and service worker again — both were
deleted rather than kept, because a Pyodide app's would differ anyway (no
loopback, no file handlers, a different scope).

## Known weak spots (as of 2026-08)

- `deepcopy_namespace` falls back to per-value copies with a shared memo when batch deepcopy fails, and keeps live references (with a named warning) for values that cannot copy at all; a scene holding non-picklable state degrades checkpoint isolation.
- LEFT-arrow reverse is a per-object morph, not a true reversal of the original animation; complex changes blend rather than retrace. (It filters out `CameraFrame` before morphing — the frame lives in `self.mobjects` but can't be Transformed.)
- CE `color=` kwarg compatibility was fixed piecemeal (2026-08): classes must not pin `stroke_color=`/`fill_color=` defaults in `__init__` — that silently overrides a user's `color=` (VMobject resolves `stroke_color or color`, `fill_color or color`). Circle, Dot, Arrow, ArrowTip, StrokeArrow, AnnularSector, Annulus, and StringMobject (all Tex/Text) were converted; other classes may still have the pattern.
- `z_index` is CE-compatible via a stable draw-order sort of top-level mobjects (`assemble_render_groups`); within-family z_index is not sorted.

ManimGL's IPython embed mode was removed in 2026-07 (see `DECISIONS.md`); `self.embed()` remains as a stub that logs a warning.

## 3D Scenes

`ThreeDScene` supports CE-style camera control (`set_camera_orientation`, `begin_ambient_camera_rotation`) and 3D mobjects (`Sphere`, `Cube`, `Torus`, `ThreeDAxes`, ...).

**3D fill rendering (fixed 2026-08-11)**: `ThreeDScene.add` calls `apply_depth_test()` on added mobjects, which switches filled VMobjects to **triangulated fill** (`render_triangulated_fill` in `rendering/shader_wrapper.py`): real triangles with real z, so depth intersections against surfaces and other VMobjects are per-pixel correct (beyond upstream ManimGL's z=0 fill composite). The triangulated path renders every mobject of a render batch with its own fill color (`batch_mobjects` on the wrapper), and triangulation caches invalidate on point changes. Remaining constraints:

- Triangulated fill flattens each submobject to one flat fill color (no gradients) and skips the anti-aliased fill border; live-window MSAA is capped at 4 samples on macOS (offline supersampled rendering is the quality path — see TODO.md).
- Mobjects animated under depth test re-triangulate each frame the points change (earclip cost; fine for typical scenes, measurable for huge Text).
- `Camera.blit_letterboxed` resolves the MSAA fbo (ThreeDScene uses samples=4) into `draw_fbo` before the scaled window blit — an MSAA source may only blit to an equal-sized rect.

Regression-tested in `tests/interactive/three_d.py` (windowed).
