# Changelog

Notable user-facing changes are recorded here. ManimLive is currently alpha;
interfaces may still change before the first public release.

## Unreleased

### Shared renderer

- A frame that changes nothing costs the viewer's Python less, on every
  renderer (docs/phase_b4_plan.md, "Phase B as the default", B5.10): when
  every object on screen is kept and the camera has not moved (a still
  pausepoint, an idle tick), the serializer reuses the last frame's
  batches as they were grouped and, once they have all been sent, the
  last message itself, instead of walking and encoding every batch again.
  What is sent is unchanged, byte for byte. EpisodeB2's ticks at 3.i
  cost 0.82 ms where they cost 1.06 (Phase A) and 0.84 where they cost
  1.32 (Phase B).
- **Phase B was measured as the Default and stays a selection.** Taylor's
  condition for making it the Default for testing was that it be nowhere
  dramatically slower and faster in most situations, the page's and the
  GPU's costs measured in a real browser (Chrome's WebGPU) rather than
  natively. On the two lecture episodes it is within 9% of Phase A at
  rest and 0.64-1.07× in plays, but on scenes that are mostly 3D surfaces
  a camera move or a jump between pausepoints costs 1.5-2.7× Phase A's
  (the smooth surfaces' drawing, which the Default already does), and
  EpisodeB3's idle ticks 1.38×; fewer than half the cases were faster.
  `benchmarks/device_frames.py` and `benchmarks/device_frames.html` are
  the new measuring tools.
- The **Phase B** selection finalizes the paths a frame changed in one GPU
  dispatch in the page and in native output, where it made one a path, and
  sends a path's colours apart from its shape (docs/phase_b4_plan.md, "The
  flips", B5.8): dimming or restoring objects at a pausepoint sends their
  new colours, a few bytes shared by paths that look alike, and none of
  their shapes. Pixels are unchanged. A jump to a pausepoint no longer
  costs the native driver 15-28% more than the packed records it replaced:
  on EpisodeB2 it now costs 1-4% less on a quiet GPU, on PriceDiscovery
  from 2% less to 8% more (its drawing, not its Python; the most on a busy
  GPU). The page issues a third to
  a quarter of the compute dispatches it did for such a jump, but its
  JavaScript still reads above the records' at the median in the
  negotiated stream (on PriceDiscovery 1.5 → 2.05 ms, more than before
  this change's 1.73), a cost not yet explained. The heavy play into
  EpisodeB2's 8.a sends 545 KB a frame instead of 602, its Python 4 ms a
  frame dearer for the split; a still frame's full message is 13 KB larger
  there, each batch now naming its colours.
- **3D surfaces are smooth by default** (docs/phase_b4_plan.md, "The
  flips", B5.9): the Default renderer, `--render` movies, checkpoint stills
  and `--export` draw a `Surface` as its Bézier net, evaluated by the GPU
  at screen density, so a sphere shows no facets at any zoom. The **Phase
  A** selection and `MANIML_SURFACE=grids` keep the faceted CPU grids.
  Measured against the true surface (supersampled), nets are as accurate
  as grids or more on every scene and fixture the gate draws: on 480 small
  spheres 0.67% of the frame is visibly off against grids' 1.38%. Frames
  that are mostly surfaces cost more to redraw at rest and on camera moves
  (1.06-1.24× grids on 70 and 480 spheres) and less in plays (0.61-0.73×).
  A translucent surface that overlaps itself shows its draw-order bands in
  other places than it did, and `sort_faces_back_to_front` /
  `always_sort_to_camera` no longer reorder a surface on the Default: a net
  is drawn in the order of its patches (a translucent sphere and torus
  sorted to the camera draw as they do unsorted, 1.5% of the frame
  otherwise than grids drew them). Sorting still works under **Phase A**
  and `MANIML_SURFACE=grids`.
- Surfaces drawn as Bézier nets (the **Phase B** selection, or
  `MANIML_SURFACE=nets`) are cheaper to redraw (docs/phase_b4_plan.md,
  "The flips", B5.7): each net draws only the triangles of the steps it is
  evaluated at, a quarter of what it drew on the benchmark spheres, and
  consecutive surfaces that share a look are drawn together, one draw
  where there was one a surface, as grids are. Pixels are unchanged. On a
  scene of 480 small spheres a still or camera frame now costs 1.11-1.24×
  what grids cost (1.37-1.52× before), a play 0.61× (0.80×), and the
  native redraw of that frame halved. The nets gate now covers two scenes
  that are mostly surfaces beside the three it was set on, and those two
  still fail it, as do the lattice's silhouettes (where the nets are the
  rounder, and nearer the true sphere, the pixel test measures distance
  from the grid), so the Default renderer, `--render`, checkpoint stills
  and `--export` keep drawing surfaces as CPU grids.
  `MANIML_NET_RUNS=0` draws each net on its own, for comparison.
- The **Phase B** selection sends each filled or stroked path as its rows,
  which the page and the native driver finalize themselves, instead of
  the curve records Python packed (docs/phase_b4_plan.md, "The flips",
  B5.6); so does any stack that draws fills as patches
  (`MANIML_FILL=patches`). The pixels are exactly what they were. A play
  that moves many paths the GPU programs do not take costs Python about
  half (EpisodeB2's 8.a: serialize 105 → 52 ms, the frame 127 → 81), other frames
  within half a millisecond, while a jump to a pausepoint, where every path
  arrives at once, costs the native driver 15-28% more on the course
  episodes, until the drivers finalize a frame's rows together and stop
  resending a path whose paint alone changed. `MANIML_PATCH_SOURCE=records`
  sends the packed records again, for comparison. Phase A, the Default and
  Original 2D are unchanged.
- Surfaces drawn as Bézier nets (the **Phase B** selection, or
  `MANIML_SURFACE=nets`) no longer cost a camera move a GPU pass per
  surface (docs/phase_b4_plan.md, "The flips", B5.5): each driver
  evaluates only the nets whose step count moved, all of them in one
  dispatch, so a pan, an orbit or a small zoom evaluates nothing, and what
  surfaces add to the serializer's work on a camera move fell to about a
  third. Pixels are unchanged. On the three scenes the nets gate is set on,
  every kind of frame is now within 5% of grids (camera moves
  0.997-1.046×, where they were 1.23-1.34×), but on scenes that are mostly
  surfaces nets still cost more to redraw (70 spheres 1.16-1.31× grids on
  still and camera frames, 480 spheres 1.37-1.52×): a net draws its
  capacity's triangles, each surface a draw of its own, where grids
  coalesce. So the Default renderer, `--render`, checkpoint stills and
  `--export` keep drawing surfaces as CPU grids.
- `python -m benchmarks.test_point` measures what a lecture frame costs the
  page (docs/phase_b4_plan.md, "The final test point"): Python's serialize,
  the page's JavaScript and the GPU of the same frames, the bytes sent and
  the pixels, per kind of frame, for the state `main` teaches from, Phase A
  retained, the Default and Phase B. On the course episodes a still
  pausepoint costs 0.8 ms where it cost 8-11 ms and sends nothing where it
  sent 21-69 KB, a pausepoint whose updaters tick 1-3 ms where it cost
  12-31, and a play frame 8-15 ms where it cost 14-23 (the GPU part as the
  native driver draws the frame; the page's GPU pays less). It also found
  that the Phase B selection's GPU programs drew one of PriceDiscovery's
  fading plays wrong (rays drawn opaque in another line's colour, 2% of the
  pixels), as measured before a fix now in progress; the Default and Phase
  A are unaffected.
- The viewer's **Scene renderer** selector offers **Default**, **Phase A**,
  **Phase B** and **Original 2D** (docs/phase_b4_plan.md, "The flips").
  Default is the default stack, whatever the generators' defaults are and
  what `MANIML_FILL`, `MANIML_SURFACE` and `MANIML_PROGRAMS` say, and it is
  what `--render`, checkpoint stills and `--export` draw; Phase A and
  Phase B force the two ends whatever the defaults or the environment say,
  so Phase A stays selectable whichever way a default goes. `MANIML_RENDERER`
  and the viewer take the names `triangles` (the default), `phase_a`,
  `phase_b` and `winding`. Phase A's frames are byte for byte what Phase A
  always sent, and the serializer's golden digests pin Phase A and Phase B
  by these forced names, so a default that flips moves none of them.
  The three flips were then measured against their gates (2026-09-28) and
  none passed, so the defaults are unchanged: surfaces as nets match the
  grids' pixels but cost 23-34% more of the page's complete frame on camera
  moves (13-33% with the GPU timed without per-pass timestamps, which
  overstate a frame of many passes), since a zoom evaluates every net on
  screen again, each in a pass of its own;
  fills as patches cost 15-48% more on the course episodes' plays; and
  strokes animated as GPU programs make those plays' Python no cheaper
  (within half a percent either way) while costing the GPU a pass a
  program. `python -m
  benchmarks.flip_gates` measures the browser-side complete frame a flip is
  judged on (Python, the page's JavaScript and the GPU of the same frames),
  `benchmarks/episode_frames.py --camera-moves` gives a camera move GPU
  rows of its own, and `benchmarks/play_frames.py --every-play` measures
  every play of an episode.
- The viewer sends the browser only what changed (docs/phase_b4_plan.md,
  B4.8, geometry format 8). A page announces format 8 in its mode message;
  once every tab connected has, each geometry message after the first is a
  delta against the one before it (the batches that changed, a play's
  program scalars, the camera when it moved), and a frame that changes
  nothing is not sent at all. On a 531-object course diagram a tick of its
  updaters that moves nothing sends 0 bytes where it sent 183 KB, a pan
  456 bytes, and the page runs no JavaScript at rest; a play under the
  Phase B stack sends about a kilobyte a frame. A tab that has not
  announced it (and native capture, and `--export`) is sent format 7 full
  frames, byte for byte as before; recordings stay format 7, and the
  player reads formats 1-8. A delta the page cannot apply (a dropped
  frame, a reconnect) asks for a full frame through the existing reset.
- The serializer keeps each drawn object's draws across frames, by default
  (docs/phase_b4_plan.md, tier 1; `MANIML_RETAINED_FRAME=0` turns it off): a
  frame prepares again only the objects whose rows or own uniforms changed,
  whose mesh, border reservation or stroke count a camera move changes,
  whose cache entries were evicted, whose depth test or stroke-behind flag
  was reassigned, or whose rows come through a getter of their own (a
  subclass's `get_shader_data` or `get_points`, say), and reuses a coalesced
  run and its encoded descriptor while its members are unchanged, across
  camera moves too. A revision that moves over the same bytes, as most
  updaters' do, keeps the object's draws, and an object that leaves the
  frame is kept by its content, so the equal copy that a step between
  checkpoints, a replay or a watcher's restart puts back reuses its mesh
  rather than tessellating again. The message is byte-for-byte the one the
  switch off writes for the same history, asserted frame by frame, so the
  browser, native capture and recordings see nothing new. On a 531-object
  course diagram a still frame serializes in ~1.7 ms instead of ~19, a frame
  of its updaters ticking in ~3.7 ms instead of ~31, a pan or zoom in ~4 ms
  instead of ~20, and a step between checkpoints in ~8 ms instead of ~100;
  a play that moves most of the diagram costs what it did, and one that
  moves all of it ~16% more (the bookkeeping on objects it cannot keep). An
  in-place write to an object's arrays or uniforms that bumps no revision is
  not seen until the revision moves (the switch off draws it on the next
  frame): under `MANIML_VERIFY_LEDGER=1` the frame keeps what it keeps
  without it and reads every kept object again, and such a write raises
  `RenderCacheStale` naming the object and what moved (or, where the
  retained frame judged a moved revision or a camera move harmless, naming
  its own rule), and `MANIML_RENDER_CACHE=bytes` keeps nothing.
  `benchmarks/episode_frames.py` measures it as the variant `retained`; the
  other harnesses (`gpu_borders`, `paint_retention`, `generated_output`)
  keep measuring the whole-frame path unless told otherwise.
- The serializer's bytes are pinned. `tests/test_retained_frame.py` asserts
  blake2b digests of every frame's message over the renderer fixtures,
  scripted synthetic sequences (among them a real `Scene`'s render groups,
  textures, a run split at its output cap, uniforms-only plays and GPU
  program draws) and frames of two course episodes, for Phase A and
  Phase B, through one persistent geometry cache per case, recorded
  before the first increment of the retained frame (docs/phase_b4_plan.md,
  B4.0). The render caches read the cache policy and the verify switch once
  per frame rather than once per leaf.
- A surface net cache no longer loses count of its bytes when a replaced
  surface inherits a dead one's id between frames; the leak filled the
  64 MiB budget until every live net was evicted each frame.
- The native renderer can time its GPU passes. `MANIML_GPU_TIMESTAMPS=1`
  requests Metal/WebGPU timestamp queries when the adapter offers them and,
  after every frame, `WgpuRenderer.gpu_timings` gives each pass's span and
  its exclusive share of the frame (Metal starts a render pass's vertex
  work before the previous pass's fragments finish, so spans overlap;
  the exclusive figures add up to the frame). Off by default and inert.
  `benchmarks/gpu_borders.py --gpu-timestamps` reports the columns; the
  new `benchmarks/episode_frames.py` measures the renderers on frames of a
  real course episode (`--tick-updaters`, `--play-frames`); the recipe and
  the caveats are in `benchmarks/README.md`.
- Phase A is the default WebGPU renderer for the live viewer, movies,
  checkpoint images and new baked exports. The viewer's renderer control
  switches to **Original 2D** for comparison at the same checkpoint.
- Planar vector fills use retained triangle meshes with explicit painter
  order, shared antialiasing and single-contribution fill/border coverage.
  Source point arrays and general fill tessellation remain on the CPU.
- General fill borders now expand retained curve inputs on the GPU. Small
  camera zooms update uniforms without resending expanded border triangles.
  `MANIML_BORDER_GENERATOR=cpu` selects the preserved CPU-border reference;
  public point updates and general fill topology are still future GPU work.
- The player opens existing winding recordings as well as new triangle
  recordings. Unsupported live content and corrupt recordings display an
  error and permit navigation to valid content.
- Unchanged fill-paint coefficients are retained by content hash in both
  drivers and restored independently when seeking recordings. Large static
  gradients no longer repeat their full coefficient arrays in every frame.
- The baked geometry player plays recordings made with the Phase B switches
  (`MANIML_FILL=patches`, `MANIML_SURFACE=nets`, `MANIML_PROGRAMS`): the
  recording indexer carries patch object tables, surface nets and program
  sources into every reconstructed frame, so a seek in either direction
  restores them as it does paints and borders.
- Native OpenGL is retained as the explicit `NativeGLCamera` reference, with
  its original shaders and public `ShaderWrapper`. Source/editable installs
  now require Cargo and a linker for the Lyon fill helper; compatible wheels
  include it. `wgpu` is a required runtime dependency. Nonplanar ordinary
  vector fills fail explicitly; use `Surface` or `VMobject3D` for a defined
  surface. See the [cutover record](docs/unified_triangle_renderer_phase_a.md)
  for validation, measured performance and compatibility limits.

### The viewer

- The **Scene renderer** selector gains **Phase B**: the Phase A driver fed
  the whole Phase B stack — patch fills, net surfaces and GPU programs —
  regardless of the `MANIML_FILL` / `MANIML_SURFACE` / `MANIML_PROGRAMS`
  environment, which keeps governing Phase A and every export. A comparison
  switch for measuring the stack on real scenes; the defaults do not move.
- In a `ThreeDScene` a plain drag now orbits the camera about its centre;
  shift-drag pans, scroll still zooms, and alt-press grabs a mobject (a plain
  press no longer does there, because a set of 3D axes contains nearly every
  point the pointer can reach). The orbit is a look around, not an edit: any
  navigation restores the authored camera. 2D scenes are unchanged, and
  `drag_to_orbit` on the scene class turns the gesture on or off.
- `mobject.set_draggable()` marks a handle the pointer may move: it is
  grabbed before anything else under the pointer, in a presentation as well
  as in development (where every mobject can still be grabbed), and the
  viewer names it in a chip by the cursor on hover. `along=` keeps it on a
  curve or a line, `on_drag=` reports each move (the place to set a
  `ValueTracker`). A scene with handles presents from the live stage rather
  than its recording. Drags are never saved: navigation restores the
  checkpoint.
- The chrome is now Plass and Knuth's toolbar rather than a resemblance of
  it: one 60px bar of glass pods pressed into a run with stadium ends, their
  contents asleep until the pointer comes near, and flyouts that lay a group's
  labelled icons over their trigger in a pill. The landing page's header
  shares it, so the three apps read as one family.
- Everything you touch while presenting is on one bar at the bottom — step
  back and forward, the pausepoint readout, the timeline, full screen — and
  the top bar is down to two slugs: the file, and the tools.
- **The timeline shows the animation it is playing.** Moving between
  pausepoints used to jump only once the animation had finished, because the
  position advances when a checkpoint is saved. The stretch between the two
  pausepoints now lights as the animation starts, and the position marker
  leaves the pausepoint it is departing.
- **A loop of plays no longer claims to be one pausepoint.** A loop or a
  branch produces a number of pausepoints that is not knowable until it runs,
  so the timeline draws those as a stack rather than as a single dot — and
  the stack stays closed once it has run, rather than unpacking into a chip
  per pausepoint and shifting everything downstream of it.
- The landing page's bar is now the viewer's: ManimLive takes the document
  slug, Open rides at its end as the scene's File button does, and the
  connection status closes the slug behind a hairline. The tagline is gone.
- The landing page's contents sit in the middle of the window rather than
  under the bar with the height below them left empty.
- The session panel now sits between the two bars instead of running under
  the timeline, and it stays available in full screen, receding and returning
  with the rest of the chrome.

### Delivery

- **ManimLive.app** (macOS, `app/`): ManimLive without a terminal, on the
  Claerbout shell shared with Knuth and Plass (Electron). `npm run
  app:build` puts it in Applications; its first launch installs a Python of
  its own with uv and the engine's packages, pinned by
  `app/engine-requirements.txt`; the engine runs as the app's child
  (`maniml app --port N --parent PID`) and stops with it; a scene
  double-clicked in Finder opens in its own window. The first version, a
  launcher script that opened the page in the installed Chromium browser's
  app window, is retired; its `maniml app --exit-when-idle` stays for an
  engine a script starts. `maniml app` started with a bare PATH (from
  Finder or launchd) now finds latex, dvisvgm and ffmpeg in their usual
  places, as the agent did.
- **The login agent and the installable page are retired** (2026-10-01).
  `maniml agent` — the launchd job that kept `http://localhost:8685` up
  without a terminal, and `maniml app`'s first-run offer of it and hand-off
  to it — and the landing page's Install button, with its manifest and
  caching service worker, are gone: ManimLive.app is the installed app,
  with a window, an icon, a port and an engine lifetime of its own. The
  engine still serves `sw.js`, as a kill switch: a browser that installed
  the old worker keeps running it until a worker at the same URL
  unregisters it. A terminal's `maniml app` is otherwise as it was
  (`--port`, `--parent`, `--exit-when-idle`, `--allow-outside-root`,
  `--no-browser`); when the port it asked for is taken it says which one
  it landed on.
- **The dependency list is what the app uses** (DECISIONS.md, "The
  dependency trim"): scipy, matplotlib, screeninfo, rich and tqdm are gone
  (rotations, the banded solve behind smooth handles and the assignment
  behind Tex glyph labelling are maniml's own, held to scipy's numbers in
  tests), and moderngl/PyOpenGL are the `gl` extra for the reference GL
  camera. The app's first-launch install is 85 MB where it was 243. Named
  colormaps (`get_color_map("viridis")`) now need matplotlib installed.
- New `--export-present`: renders the scene and writes
  `media/<Scene>_present/`, a self-contained folder — a page that steps
  through the episode by pausepoint, both directions, plus the mp4 —
  for hosting on a course site so students can click through an episode
  with no engine anywhere. Opens from `file://` too. The viewer's own
  presentation cache (mp4 + pausepoints table) is unchanged.
- The bundle's page carries the viewer's presenter bar — the same
  rail.js, the same chips/stacks/lit-stretch discipline, the glass pods
  — with the styles copied in rather than linked, so the folder stays
  self-contained. Plus a fullscreen control.
- The viewer presents from the bundle too: the Present button resolves
  the root cache (`<Scene>.mp4` + pausepoints table) or the student
  bundle, whichever is newer — so once a bundle exists, the root pair
  can simply be deleted.
- `--export-present` leaves only the bundle: the rendered mp4 moves
  into it, and any stale flat cache files are cleaned up. Plain
  `--render` still writes the flat mp4 + pausepoints pair.
- The viewer's Download button now runs that export: one click renders
  the mp4, refreshes the pausepoints cache the Present button plays,
  and writes the student bundle.

- ManimLive is a local application again. The interface is served by the
  engine that runs your scenes, from the same pip install, so there is nothing
  to deploy and no way for the two to be out of step. The hosted UI, its
  service worker and manifest, the versioned wire handshake, and the macOS
  desktop launch bridge built on them (`install-desktop`, `maniml open FILE`,
  the `maniml://` URL scheme) are all removed.
- The app and each scene viewer now serve their page and accept their
  WebSocket on **one** port, so the page derives its connection from its own
  address. `maniml app` no longer exposes `/api/files` or `/api/open`.
- Replaced the landing page's typed absolute-path field with a native file
  picker that grants only the selected file outside the app root.

### Security

- **`http://localhost:8685/` is now a plain address with no capability in
  it.** Each server accepts a WebSocket only from the exact origin it served
  its own page on — which a website cannot forge — and that Origin check is
  now the whole browser boundary. The capability token, `~/.maniml/capability`
  and `maniml agent rotate-token` are gone: a token embedded in the served
  page defends nothing the Origin check did not, and one delivered out of band
  made launching a delivery problem. It never defended against another program
  running as your user, which can forge any header and can run Python
  directly. See `SECURITY.md` for the full trust model.
- Served pages now carry `default-src 'self'; connect-src 'self'`, which the
  one-port move above turns into a real restriction: there is no second
  origin, host, or port a page is permitted to reach.
- Confined `maniml app DIR` scene execution to `DIR` by default, including
  protection against symlink escapes.
- Added bounded, strict JSON parsing for localhost control protocols.
- Replaced the generated-SVG pickle cache with a bounded, atomic text cache.
- Made the app accept a scene's viewer address only from the child process's
  exact launch-handshake line, so a wrapped terminal log cannot be mistaken
  for one.
- Removed shell-based Windows sound playback and keep filenames out of
  PowerShell source.
- Restricted URL-backed assets to bounded HTTP(S) downloads with socket and
  overall deadlines, sanitized failures, and atomic cache promotion. Complete
  cache entries are now reused; failed or truncated transfers leave no artifact.
- Isolated app-launched scenes in dedicated process groups and terminate their
  descendant processes on normal exit, Ctrl-C, or SIGTERM, with bounded
  escalation when graceful shutdown stalls.

### Compatibility and reliability

- A style set on a path or group that has no points yet is checkpoint
  state: colour, opacity, stroke width, border width and `stroke_behind`
  written there bump its revision. Only members with points were bumped,
  so the save after such a write reused the frozen copy, and a seek back
  and a replay drew the path grey, thin and unfilled. A `Surface`'s
  per-revision grid cache is render state the ledger's verify mode no
  longer names.
- A seek back no longer hands back a live object whose references point
  outside the restored checkpoint. A mobject kept alive off screen while
  the one it follows (`tent.follow = body`) was restored as a newer copy
  came back pointing at that copy's later state; the thaw now reuses a
  live object only when its submobjects and references are the objects
  standing in for its frozen copy's.
- A play that moves only uniforms (`.animate.set_anti_alias_width`,
  `set_shading`) bumps the revision every frame, as a play that moves rows
  does.
- `PGroup.sort_points` and `filter_out` bump the revision of every member
  they rewrite, a member filtered down to no points included. Only the
  group was bumped, so the save after either reused each member's old
  frozen copy.
- maniml parses its command line only when it is the program. The config
  is read at import, so a host program's flags were taken as maniml's:
  `python -m unittest discover -s tests -t .` gave every scene the suite
  built a transparent background. `python -m maniml`, as the app and the
  viewer launch a scene, and the `maniml` command parse the same one.
- `Surface` accepts CE's spelling — `Surface(func, u_range, v_range,
  resolution=32, fill_color=..., fill_opacity=...)` — beside GL's (colour
  first, `uv_func` a method); CE's stroke, checkerboard and piece options
  are accepted and dropped.
- Checkpoints now restore the camera's orientation and field of view,
  not only its center and size. A backward seek across a beat that
  orbited the camera (`set_theta`, `set_phi`, `set_focal_distance`)
  used to land on the live orientation; zooms were already restored.
- A namespace variable bound to the camera frame stays live across
  navigation. Checkpoints deep-copied the frame like any mobject, so
  after a backward seek `self.play(Restore(frame))` animated a detached
  copy and the camera snapped at the end of the beat. Freeze and thaw
  keep the frame by reference (`Mobject.checkpoint_by_reference`); its
  state travels in the scene snapshot.
- `z_index` now layers correctly in the browser renderers and baked
  exports. The geometry payload used to merge every same-state mobject
  into one batch regardless of the scene's z_index draw order, and a
  batch draws all its fills before any of its strokes — so a raised
  filled shape (a `Dot` marking a point) rendered behind a lower
  stroked one (the curve it sits on) in WebGL2/WebGPU, while the pixel
  stream and `--render` were correct. Batches no longer merge across
  the native render-group boundaries.
- Y-axis numbers now stand upright, as in CE. The y-axis was rotated
  into place after its numbers were attached, so every label came out
  90 degrees over; the axis now rotates before its numbers are added
  (CE's own order), and labels lay out against the vertical line.
- Added CE-compatible `Table` and `MathTable`: entries on a fixed grid,
  row and column labels joining the grid, separator lines drawn midway
  between neighbours, and the `get_columns`/`get_rows`/`get_entries`
  family of accessors.
- Repeated `Transform`s of the same mobject no longer slow a scene to a
  crawl. Alignment used to leave its padding (subdivided points,
  duplicated submobjects) on the source mobject, compounding on every
  play; a Transform that lands on its target's appearance now adopts the
  target's clean structure instead.
- Axes now cross inside their ranges, as in CE: when 0 lies outside an
  axis range the crossing clamps to the nearer range edge, so an axis no
  longer renders far off screen — and lines drawn to it no longer grow
  without bound.
- Made package imports, star imports, and CLI help safe without a desktop
  display while preserving the existing native Pyglet window backend.
- Decoupled shared scene and browser input handling from Pyglet imports, with
  regression checks that its key and mouse values remain native-compatible.
- Added bounded TeX tool execution, actionable converter failures, explicit
  ffmpeg status checks, and subprocess-pipe cleanup. Failed encodes are no
  longer promoted as completed movies.
- Made scene teardown failure-safe across file writers, watchers, and viewers.
  Movie, audio-mux, and final-image work now uses collision-resistant staging
  and atomically replaces final paths only after successful completion;
  interrupted movies are preserved separately. Render, present, and export
  modes now fail visibly on scene execution or source-parsing errors instead
  of silently publishing partial output.
- Made web exports transactional. Player assets and scene data are assembled in
  collision-resistant sibling staging, existing unrelated deployment files are
  preserved, and publication failures restore the last complete export.

### Packaging and release engineering

- Scoped the initial developer preview and release-candidate workflow to
  macOS; Windows and Linux support resumes after the WebGPU renderer and
  cross-platform packaging settle.
- Replaced inherited ManimCE publishing workflows with project-specific CI,
  CodeQL, Pages, and manual release-candidate workflows.
- Added a non-executing weekly check for public-API drift on ManimCE `main`.
- Added validation of wheel metadata and bundled browser assets.
- Aligned declared and tested Python support with current ManimCE at Python
  3.11 through 3.14.
- Restored audio support on Python 3.13+ through `audioop-lts`.
