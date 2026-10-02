# Decisions

The record of what was decided, what shipped, and what was tried and
deleted — with the reasoning, so none of it gets re-litigated by
accident. The forward roadmap lives in `TODO.md`; the architecture as
it stands lives in `CLAUDE.md`. Commit messages carry the finer grain.

## The login agent and the PWA are retired (2026-10-01)

Taylor, asked whether to retire `maniml agent` and the installable page
now that ManimLive.app is the app: "yeah lets retire", "yeah clean that
all up". Both existed to make a terminal command feel like an application.
The launchd agent (`maniml/agent.py`) kept `http://localhost:8685`
up across logouts, `maniml app` offered it on first run and handed off to
an engine already on the port (restarting one serving pre-upgrade code),
and the manifest with a caching service worker gave that origin an icon, a
window without a tab strip and a shell that opened when the engine was
down. ManimLive.app on the Claerbout shell (2026-10-01) does all of it as
an app does: its own window and icon, its own port (8690), an engine that
is its child and stops with it, updates from the site. The two older paths
were the second and third system Taylor had already named as the problem
(`docs/app_plan.md`: "the fact that it needs both the pwa and the terminal
maintained separately is annoying and feels janky"), and Knuth's port
retired its equivalents at the same step.

What went: `maniml/agent.py` and the `agent` command; `run_app`'s
`offer_agent` and `state_path` with the hand-off (`running_engine`,
`hand_off_to_a_running_engine`); `~/.maniml` (`security.CONFIG_DIR`, the
agent's state folder, which nothing else used); `manifest.webmanifest`, the
Install button and the worker registration in `app.html`; their tests and
CI entries; the README's "Background engine" section. What stayed, and
why: `search_path`, now in `web/cli.py`, because a Finder-launched engine
has launchd's bare PATH and must find latex, dvisvgm and ffmpeg; the
version stamp in `app.html`'s `<meta name="maniml">`, because a GET of a
running engine should say what it serves; and `sw.js`, rewritten as a kill
switch in the shape of `site/sw.js` — a browser that installed the old
worker keeps running it until a worker at the same URL unregisters it, so
the file keeps existing at that URL, serves nothing, clears the caches,
unregisters itself and reloads the window. `tests/test_static_assets.py`
holds the page uninstallable and the worker to that shape. Decided in the
same conversation: no Intel Mac build; the deploy stays Apple silicon only.

## The dependency trim, and the app as the product (2026-09-30)

Taylor, on the Claerbout experiment's install figures (243 MB of
dependencies for a 2.4 MB package): "i think there are a lot of
dependencies we can cut down, right?", and the same day: "i don't think i
need a maniml command from the terminal. that's not how it's intended to
be used. it'll all be done in the app." The app's first launch installs
the dependency list into a venv of its own, so every megabyte there is
paid once per machine, and a terminal's conveniences serve nobody.

What left, and what replaced it:

- **scipy** (73 MB) for `Rotation` in the camera frame and `space_ops`,
  `linalg.solve_banded` and `solve` behind smooth handles, and
  `linear_sum_assignment` + `cdist` labelling Tex glyphs. Replaced by
  `utils/rotation.py` (scalar-last quaternions in scipy's conventions,
  Euler angles by scipy's own algorithm, Bernardes & Viollet's),
  `utils/banded.py` (LU with partial pivoting in the band, Numerical
  Recipes' shape, so a long path smooths in O(n)), and
  `utils/assignment.py` (the Hungarian algorithm in its potentials form).
  `tests/test_trimmed_dependencies.py` holds each to scipy's numbers on
  random inputs where scipy is installed (the dev group keeps it, for
  that and for `test_fill_paint`'s interpolator) and to independent checks
  always.
- **matplotlib** (24 MB) for named colormaps in `utils/color.py`: imported
  lazily now, with an error that names it, so `get_color_map("viridis")`
  needs it installed and the 3b1b colormap needs nothing.
- **screeninfo** (and the 26 MB of PyObjC it pulled on macOS): imported
  nowhere.
- **moderngl** and **PyOpenGL** (28 MB, with Cython): the reference GL
  camera's, which the app's window never draws. They are the `gl` extra
  (`maniml[gl]`; `NativeGLCamera` says so when they are missing), which
  CI installs for the frozen GL references under `tests/`. This reverses
  the 2026-09 code review's "return to runtime dependencies": that
  decision predates the app being the product.
- **rich** and **tqdm**: a terminal's log rendering and progress bars.
  `logger.py` is a plain handler; `utils/progress.py` keeps the shape the
  callers use and displays nothing (the viewer's console shows the log;
  a render's progress is the log's).

The app's install is 85 MB where it was 243 (`uv pip install` of the
requirements alone, Python 3.13, this Mac; the Claerbout doc has the
before). `tests/check_wheel.py` refuses a wheel that names any of the
five again. Still on the list and small: colour, addict, validators,
appdirs, pydub, isosurfaces, svgelements, pygments, PyYAML; the pieces
that are the engine: numpy, Pillow, wgpu, websockets, manimpango,
fontTools, mapbox-earcut. The `maniml` console script stays for now: the
shell runs `python -m maniml app`, the scene subprocesses do the same,
and removing it is a README change more than a code one.

**The icon** (same day): Knuth's tile grid with the red tiles at the
lower left, lower right and upper right (Taylor's placement), drawn by
`tools/make_icon.py` from the sampled geometry and colours of Knuth's
`knuth-tiles-512.png`; the favicon, the manifest and the shell's app icon
all read the same two files under `web/static/icons/`.

## Phase B as the default: measured on the device, not flipped (2026-09-30)

B5.10 (`docs/phase_b4_plan.md`, "Phase B as the default";
`benchmarks/results/phase_b_default_20260929/`). Taylor, 2026-09-29, on
making the whole Phase B stack the Default: "i want to try it first before
it becomes the only option ... so long as it's not dramatically slower in
any situation and is faster or much faster in most, then i want it to be
the default for testing." Phase A and Original 2D stay selectable either
way. The gate as stated to him: the browser-side complete frame (Python
serialize + page JavaScript + GPU), the page and the GPU measured on the
page's own device (Chrome's Dawn on this M3) rather than the native
driver, whose GPU column overcharges Phase B; five classes (pausepoint,
ticked, camera, play, navigation) on EpisodeB2, PriceDiscovery, EpisodeB3
and the two scenes that are mostly surfaces; PASS iff no (scene, class)
cell is above 1.25× Phase A forced and more than half of the cells are at
or below 1.0×, pixels within 0.5% of Phase A but the surfaces'
silhouettes (B5.9's accuracy rule).

**It failed, so the defaults stay** (`DEFAULT_FILL` `meshes`,
`programs.DEFAULT_MODE` `off`; surfaces nets). In the format 8 stream
every page negotiates, five cells are above 1.25×: OrbsScene's camera
moves 2.741× and navigations 1.744×, LatticeScene's 1.631× and 1.546×,
and EpisodeB3's ticked frames 1.380×; and 9 of the 23 cells are at or
below 1.0× (every play but PriceDiscovery's, at 0.52-0.66×; PriceDiscovery's
still, camera and navigation; EpisodeB2's and EpisodeB3's navigations).
EpisodeB2 and PriceDiscovery are within 1.087× in every class. The
surface scenes' cells are the nets' cost on the device, which the Default
has paid since B5.9 (in diagnostic runs, nets over grids 1.44-1.58× on
those cells and Phase B over Phase A with nets 1.02-1.07×, but for the
orbs' camera moves, 1.68×, a remainder the messages do not explain); EpisodeB3's is 40 dashes an
updater leaves with the joint-angle flag set and their ends cached, which
the retained frame re-prepares every tick in both stacks and Phase B
re-encodes as 73 runs to Phase A's 10. Both are for Taylor: whether a
default is judged against Phase A or against the Default it replaces, and
whether the nets' device cost on surface-heavy camera moves and
navigations (1.5-2.7× Phase A's grids, where B5.7 measured 1.06-1.24×
with the native GPU) stands. Taylor decided on 2026-09-30, shown
these numbers: "Keep Phase A default for now". Phase B stays the viewer's
selection; the Default keeps Phase A's fills with B5.9's nets, whose
device cost on the surface scenes is small in time (camera moves 1.3 → 1.9
ms on 70 spheres, 2.3 → 3.5 ms on 480; revisits 4.3 → 5.7 and 18.5 →
28.5 ms; first visits faster, 7.2 → 5.7 and 33.9 → 28 ms). The fix pass
that was re-taking the device cells to answer the review's repeatability
finding was stopped at that decision; the cells stand as measured once,
without an interval.

Taken on the way, both stacks: the retained frame reuses the last frame's
runs when every leaf is kept under the same camera, and returns an idle
frame's message untouched (the wire byte for byte the same), which took
EpisodeB2's 3.i ticks from 1.24× to 1.02× and every still frame of the
episodes to within 11% of Phase A's (EpisodeB2 1.007×, PriceDiscovery
0.959×, EpisodeB3 1.105×). Pixels pass: Phase B against Phase A with
nets at worst 0.0002% over 24/255.

## Surfaces are nets by default (2026-09-29)

B5.9 (`docs/phase_b4_plan.md`, "The flips";
`benchmarks/results/b59_nets_default_20260929/`). After B5.7's numbers
Taylor was asked "Make smooth 3D surfaces the default? ... The one pixel
'failure' is because the test compares against the faceted version;
against a true sphere, smooth is more accurate", and chose "Flip it
(Recommended)": "Smooth surfaces become the Default (and in rendered
movies). Phase A in the dropdown keeps the faceted grids. Also change the
pixel test to measure against a supersampled true surface, so it measures
accuracy, not sameness to the old look."

So `geometry.DEFAULT_SURFACE` is `nets`: the Default renderer, native
capture (`--render`, checkpoint stills) and `--export` draw a Surface as
its net evaluated at screen density; Phase A forced and
`MANIML_SURFACE=grids` draw the grid. The cost that decision accepted is
B5.7's: on the scenes that are mostly surfaces a still or camera frame
costs 1.06-1.15× grids (70 spheres) and 1.11-1.24× (480), a play
0.61-0.73×; the gate's three course scenes are within 1.05 in every
class. It was not retaken.

**The accuracy rule.** The nets pixel gate measures each stack against a
reference of the same frame drawn from the true surface: each Surface's
`uv_func`, carried into the frame by the affine map its construction's
samples fit (a surface that is no affine image of its function would be
its own net, densely; none was), sampled patch by patch until its facets
are within 1/32 of a pixel (their normals the function's, their colours
and image coordinates the net's), drawn by Phase A's grid path with 16
times the samples per pixel. Nets must be no further from it than grids,
by the pixels over 24/255, on every scene of the timed set (its measured
frames and three inside each play into them) and every Surface fixture;
nets against grids is reported and no longer judged. A frame where grids
and nets are nowhere more than 24/255 apart is a tie and counts for
neither: their counts against the references differ there by noise at the
threshold's edge. The gate also requires every reference within its
tolerance and drawn from its surfaces' functions (one drawn from its own
net is what nets converge to), and each scene's run over the frames the
serialize command measures and frames inside its plays. The reference is
drawn in each stack's order of a surface's triangles, since where a
translucent surface overlaps itself the order decides what shows (grids
the surface's own triangle indices, row by row unless sorted; nets patch
by patch): measured against one order, the translucent fixture's 409
pixels of order alone would count against nets. Nets pass everywhere, no
frame of 125 further than grids: the lattice 0.67% of its pixels against
grids' 1.38%, the orbs 0.10% against 0.39%, EpisodeB3 0.011% against
0.026%, B4 0.0066% against 0.012%. The orbit demo is a tie: 6 of its 8
frames are ties, and over the other two grids are 72 pixels from the true
surface and nets 70 (its 0.29-0.31% against grids mid-fade is the order:
at the frame measured here 6,031 pixels between grids and nets, 6,068
between the two references). Of the 13 fixtures, 8 are ties, the two
stacks within 1/255 everywhere; nets are the nearer on 4 (the 64× sphere
111 pixels against 1,018, the orbs 1,006 against 2,834); the translucent
one is exact in each order. The gate's timing part fails where B5.7
measured it and was accepted; `flip_gates gate` now says which part
failed.

No golden was re-recorded: the pin holds the forced stacks, and it passes
untouched in its three modes. No test pins the Default stack's surface
pixels, and the tests that compare nets with grids state their stack, so
none moved; the flip is pinned by its stacks, a native capture and a
Default export replayed through the player and the browser driver. What
is left visible that is not accuracy is order. A translucent surface that
overlaps itself shows its order bands in other places than under grids.
And a net ignores a sort: `sort_faces_back_to_front` (and
`always_sort_to_camera`, whose updater calls it) reorders the grid's
triangle indices in place, which grids draw and a net does not, so on the
Default a translucent surface sorted back to front draws as it does
unsorted (the translucent fixture sorted to its camera: grids move 7,886
pixels, nets none, and the Default after the flip is 7,542 pixels from
the Default before it, against 405 unsorted). Accepted rather than fixed
here: a sorted surface falling back to its grid on the Default would
change what the forced Phase B draws or make the two stacks' nets differ,
and the retained frame's rule for a net with them (the pin records a
sorted net as compared, not prepared); no course or dogfood scene sorts,
and `MANIML_SURFACE=grids` or Phase A draws the sort.
`test_a_default_net_is_drawn_in_its_own_order_whatever_the_sort` pins it.

## Nets drawn as grids are; the nets gate over a timed set; surfaces stay grids (2026-09-29)

B5.7 (`docs/phase_b4_plan.md`, "The flips";
`benchmarks/results/b57_net_runs_20260929/`) took the three things B5.5
named before the nets gate could be taken again. A driver draws a net
with the index pattern of the steps it evaluated it at, not its
capacity's (the kernel repeats the rows past the steps, so the extra
triangles had zero area); consecutive nets that can share a draw, by the
rule grids already follow, are one batch whose `net` lists its members,
each evaluated into its span of one output, drawn in one draw in both
drivers and read by the player; and the gate is judged over a timed set
(`flip_gates.TIMED_SCENES`, `flip_gates gate`) that holds two scenes that
are mostly surfaces beside the three it was set on, so it cannot pass
without them, nor (since the review) on a run reduced with a looser
`--limit`, one lacking a class its serialize run measured (the camera and
play classes always), or runs of more than one tree. The golden pin states `MANIML_NET_RUNS=0`, as its nets were
recorded, rather than being re-recorded (23 of PriceDiscovery's phase_b
digests would move for a change that moves no pixel).

Pixels did not move (every fixture, zoom walk and play frame compared
against `main`'s driver), so the lattice's 0.98% of pixels over 24/255
stands. It was measured against a supersampled sphere: nets are off it in
0.86% of the frame, grids in 1.60%, and where the two differ nets are the
nearer at 97.5% of the pixels. The gate measures distance from the grid,
and it was not changed. Taken three times (pass 3, every run started on
an idle GPU, is the verdict): the three scenes pass every class; the orbs
fail still and camera frames at 1.06-1.15× grids (B5.5: 1.16-1.31×) and
the lattice at 1.11-1.24× (1.37-1.52×) and its pixels. So
`geometry.DEFAULT_SURFACE` stays `grids`. What is left is mostly the
triangles that make a net round (2.25-3.7× grids'), which no redraw lever
removes; whether the pixel test should measure against a reference
surface, and whether such frames may cost more for no facets, are
Taylor's to decide.

## A path's rows travel as their geometry and their paint (2026-09-29)

B5.8 (`docs/phase_b4_plan.md`, "The flips";
`benchmarks/results/b58_rows_one_dispatch_20260929/`) took the two levers
B5.6 named. Each driver finalizes a frame's changed rows in one dispatch
over a table, into an output each batch owns, rather than a dispatch a
rows and a buffer shared by name. And a row source is sent as two
arrays: its geometry (point, stroke width, joint angle, base point or
normal, fill border width), which names the batch and is keyed on those
columns alone, and its paint (stroke and fill RGBA), one row where uniform
and so shared by every path that looks alike. The alternative, taking the
colour from the object table as the records' patch fill could, was set
aside: the finalized records and stroke instances carry each path's paint
(a record's colour words and its active flag, which reads the fill's
alpha), so the drivers still refinalize a batch whose paint moved, but on
the GPU and in the frame's one dispatch; what the change removes is the
wire's resend of rows whose geometry did not move. A recording made before
B5.8 (seventeen-column rows, no `row_paints`) stays readable in both
drivers and the player.

The gate was not met as written (measured twice, on a GPU the desktop apps
kept busier than the recipe allows, so GPU parts are read only within a
run). A navigation's native frame is below records on EpisodeB2 and above
on PriceDiscovery by its render (B5.6: 15-28% above on both), and the
page's WebGPU calls for it at or below records'; but the median of its
JavaScript still reads above records' in format 8 on both episodes, on
PriceDiscovery more than B5.6's rows did, for a reason not isolated (it is
the delta path's: format 7 sends the same definitions without it); 8.a's
play read 86.1 and 83.7 ms against B5.6's 80.5, its serialize 4.2 ms
dearer for the split; and every batch naming its paints makes a still
frame's full message 13 KB larger on EpisodeB2. Rows stay the patch
source; the numbers are recorded for Taylor.

## Phase B sends a patch as its rows (2026-09-29)

B5.6 (`docs/phase_b4_plan.md`, "The flips";
`benchmarks/results/b56_rows_source_20260929/`). B5.1 built rows on the
wire under patches and proved them pixel for pixel the records' and about
half the serialize on heavy plays, but kept them behind a switch so the
Phase B measured on 2026-09-26/27 stayed reproducible. Taylor, having
driven the Phase B selection (sharper surfaces zoomed in, no difference
felt in zooms and pans), asked whether its open issues could be fixed
before both stacks go to main behind the selector; this increment is one
of those. So `geometry.DEFAULT_PATCH_SOURCE` is `rows`: wherever patches
are drawn (the forced Phase B, any stack that selects them) a path is sent
as its rows, and `MANIML_PATCH_SOURCE=records` is the override. The forced
stacks fix the fill, the surface and the programs, not how the bytes are
made: they read the patch source as they read the border generator.

The golden pin was not re-recorded: it states
`MANIML_PATCH_SOURCE=records`, as its phase_b digests were recorded, beside
`MANIML_PROGRAMS=off`. It clears its switches, so without the statement 246
of its 251 phase_b digests would have followed the default for a change
that moves no pixel; a first pass re-recorded them and the review sent it
back, since a golden is never re-recorded. Every pin frame was drawn both
ways, identical. The harnesses' instruments named for the selection follow
it (their forced Phase B takes the patch source out), and `_records` twins
reproduce B6's Phase B, so the test point reads five stacks. The program
tests' CPU path states records, so a fault in `row_finalize.wgsl` cannot
cancel on both sides.

The cost moved rather than vanished. B6's test point retaken: 8.a's play,
whose movers are not programs, 127.3 → 80.5 ms (format 8); every class's
median within 0.5 ms of records on both episodes. A navigation costs the
native driver more (29.9 → 38.3 ms on EpisodeB2, 25.0 → 28.8 on
PriceDiscovery), for two reasons: a dispatch per changed rows, and rows
keyed with their paint, so a dim at a pausepoint resends and refinalizes
paths whose records would stay cached (EpisodeB2 258 → 277: 176 of 463
batches cached under records, none under rows). One dispatch for a frame's
rows and finalized geometry keyed on the geometry columns alone are the
levers; the records override stays for that comparison.

## A frame's nets in one dispatch; surfaces stay grids by default (2026-09-28)

B5.5 (`docs/phase_b4_plan.md`, "The flips";
`benchmarks/results/b55_nets_one_dispatch_20260928/`). B5.4 measured the
nets flip failing only on camera moves, 1.25-1.34× grids' complete frame,
because a zoom re-evaluated every net on screen, each in a compute pass of
its own, though the kernel read the camera only to choose a net's integer
step count. So each driver now decides the steps itself, by one rule in
double precision from the same inputs, and keys an output's evaluation on
exactly what it reads (its control points, capacity and steps); and the
nets whose state moved are evaluated in one dispatch over a table, their
inputs gathered into one scratch buffer and their vertices copied into
the outputs their slots own, rather than an arena the render pass would
have to address (tier 2's slot ownership stays as it was). A net alone is
read and written in place. The gate taken again as B5.4 took it then
failed only on the serializer's per-net Python (the orbit demo's still,
B4's camera moves and format 7 plays), which was made cheaper byte for
byte, and taken once more: every class within 1.05 in both formats on its
three scenes, pixels within 0.31%.

The default was not flipped. A default reaches every scene the Default,
`--render`, checkpoint stills and `--export` draw, and the gate's three
scenes are ones where surfaces are a small share of the frame. On scenes
that are mostly surfaces the same recipe fails: the orbs fixture as a scene
(70 spheres) 1.16-1.31× grids on still and camera frames, a lattice of 480
small spheres 1.37-1.52× and 0.98% of its pixels over 24/255 (silhouettes
where the net is the rounder, drawn the same by B5.4's driver). The cost
left is the redraw, not the evaluation: a net draws its capacity's
triangle pattern (the reservation is twice the steps, so three quarters of
the orbs' net triangles have zero area) in a draw of its own, where grids
coalesce into one. So `geometry.DEFAULT_SURFACE` stays `grids`; nets are
what the Phase B selection draws and what `MANIML_SURFACE=nets` selects.
Before the gate is taken again: a surface-dominated scene in its timed
set, each net drawn with the index pattern of its current steps, and net
batches that share a pipeline and uniforms coalesced as grids are. The
lattice's pixels are a question for the gate as much as for nets: a net
rounder than the grid fails a gate that measures distance from the grid.

## The test point: this branch's Default is Phase A's stack, retained and streamed (2026-09-28)

B6 (`docs/phase_b4_plan.md`, "The final test point";
`benchmarks/results/phase_b_test_point_20260927/`) is the table B4 and B5
built toward: per class, the browser-side complete frame (Python's
serialize, the page's JavaScript, the GPU), the wire and the pixels, for
today's state (Phase A without the retained frame, format 7, `main`'s page),
Phase A retained, the Default and Phase B forced, on both gate episodes.
It records the state; it decides nothing Taylor has not.

**What it shows.** A lecture frame on this branch, against today: a still
pausepoint 11.10 → 0.78 ms (EpisodeB2) and 8.26 → 0.78 (PriceDiscovery),
nothing sent; a pausepoint whose updaters tick 31.24 → 3.02 and 12.29 →
1.05, nothing sent; a play frame 22.75 → 14.83 and 13.52 → 7.86. The
Default is Phase A's stack because no flip passed its gate (B5.4); its
pixels are Phase A's exactly and its costs Phase A's to the noise. Phase B
forced is cheaper than the Default on EpisodeB2's plays (0.84×, its GPU
programs taking the serialize from 7.46 to 2.58 ms while the GPU rises
5.39 → 9.70) and dearer on PriceDiscovery's (1.79×) and on both episodes'
ticked frames (1.24×, 1.13×). The GPU part is the native driver's, as the
gate defines it, and the page's is far smaller: on this machine's WebGPU a
redraw of 8.a sustains 1.29-1.35 ms (Phase A) and 1.74-1.78 (Phase B), GPU
and all, where the table charges 4.85 and 6.44 ms natively. So the play
ratios and every format 7 ratio carry GPU cost the page does not pay (at
8.a at least 3.5 ms a drawn frame; natively Phase A's GPU is ~4.1 ms even
at 46 draws); the page's GPU per class was not measured.

**What it found.** Phase B's GPU programs draw a PriceDiscovery play wrong
(2.02% of the pixels, measured before the fix: rays fading in drawn opaque
in a neighbouring dashed line's paint), which neither the retained frame,
the patch fill nor nets cause; the fix is its own session's, not in B6's
commit, and every B6 figure was measured without it (the archive's README
says so number by number). Of the plan's two conditional increments, B5.2's
condition (the draw count mattering once the draw list is retained) is not
met: ~0.8 ms of native GPU out pass and ~0.8 ms of page per drawn Phase B
frame, none at rest, while Phase B's play gap is its per-program passes.
B4.9's (Dawn's per-draw cost above 1 ms at 911 slots) is not shown either
way: the page's side of Dawn's wire is 0.89 ms a redraw of 911 slots at
the median (0.10 at 444), its rounds 0.64-1.19 ms, taken at load 5-9; the
GPU process's side was not isolated. It is settled by a quiet retake with
the GPU process's time isolated (a redraw at a tiny resolution, or a
Chrome trace). Nothing at rest is redrawn under format 8 either way.

**What stands between this and the end state.** On the wire and in the
browser a frame that changes nothing costs nothing; Python does not yet
stay silent. Its measured per-frame costs: the walk that finds nothing
changed (0.8-2.4 ms a still frame); the episode's own updaters (20.7 ms a
tick at 8.a, four and a half times its serialize); the revision counter's
over-signalling (415 of 531 leaves compared per 8.a tick, 1.83 ms); in
plays Lyon on Phase A movers (11 ms of 8.a's play), the rest of a Phase A
mover's preparation (~200 µs a leaf) and, under Phase B, a program's
encode or a non-program mover's packed records. Each is named with its
size in the plan's reading, which is where the next increment is chosen
from. Nothing is merged; `main` stays frozen until Taylor chooses, and the
plan's section ends with the merge command.

## Deltas are negotiated; full frames stay format 7 (2026-09-27)

B4.8 (`docs/phase_b4_plan.md`, "B4.8: shipped") makes the geometry a stream
for a page that asks for it: format 8 messages carry an epoch and a frame
number, and after an epoch's full frame each is a delta against the one
before, or nothing when nothing changed. Three choices, each on evidence.

**Negotiated per client, one cache.** The page announces format 8 in its
mode message, and the viewer streams deltas only while every connected
client has: a delta against a frame a tab never drew is a corrupt picture,
and one cache with one broadcast is what the viewer is (a second tab's
connect already resets everyone). A tab that has not announced it gets
format 7 full frames, and so do its neighbours until it goes.

**Full frames keep format 7 until a client negotiates.** The alternative,
every full frame format 8 with the golden pin's digests taken of normalised
messages, would have put a frame number into every message of every
consumer that never reads one (native capture, the recorder, a tab that has
not negotiated), which makes no two messages of such a stream equal: B4.7's
byte-identical redraw (0.09 against 0.85 ms at 8.a) would have gone for
them, and recordings would have changed for nothing. Instead a cache that
has not negotiated writes format 7's bytes exactly, so the pin stands with
no normalisation, and a format 8 full frame is the format 7 frame with its
two keys: the pin streams every golden case as format 8 too and holds each
full frame to its pinned bytes with the keys taken out, and each delta,
expanded against the frame before it, to the pinned bytes exactly.

**The diff is the encoder's, not the retained frame's.** The plan named it
`RetainedFrame.diff`. It is `generated_geometry.diff_runs`, used by both
serializer paths, so `MANIML_RETAINED_FRAME=0` streams the same deltas byte
for byte and stays the path the retained frame is held to; and it compares a
run by its content hash and held descriptor rather than its `RunMemo`,
because a program run is a new memo every frame and must still resolve to
its slot and travel as a scalars op. A kept run hands the same text object
back each frame, so the comparison costs what identity would.

## The frame is retained in Python (2026-09-27)

Taylor's direction for Phase B4, quoted in `docs/phase_b4_plan.md`: "maniml
uses python to send to the gpu the bezier control points, and then the gpu
does everything else. and it only ever directs the gpu what to change", and,
on the way there, "keep Phase A as solid and build toward a final test point
in Phase B." The measurement that set the order was
`benchmarks/results/gpu_timestamps_20260926/`: a still frame of EpisodeB2's
531-object 8.a cost ~37 ms natively, ~20 of them Python preparing and
serializing a frame nothing had changed, ~4 GPU.

So the frame is retained in Python first (tier 1, B4.0-B4.5, the default
since this date; `web/retained_frame.py`): a `GeometryCache` keeps each drawn
leaf's draws and what they were made under, and a frame prepares again only
the leaves it cannot keep. A still 8.a frame serializes in ~1.7 ms against
~19, a tick of its updaters in ~3.7 against ~31, a pan in ~3.8, a seek in ~8
against ~100; a play where most things move costs what it did, and one
where every leaf moves ~16% more, tier 1's bookkeeping on leaves it cannot
keep. The flip takes that cost as measured (a `--render` of whole-scene
moves pays it too); whether it stands is Taylor's to weigh, and the plan's
"B4 tier 1: shipped" names the fast path that would take it back.
`MANIML_RETAINED_FRAME=0` is the whole-frame path.

**Why tier 1 before tier 2.** Tier 2, the browser owning the frame and
Python sending deltas, is where "if nothing changes, python isn't even
talking to the gpu" is met, and it is next (B4.6-B4.9). It comes second
because the Python cost was the measured cost, and tier 1 removes it without
changing anything any consumer reads: no wire format, no driver, no
recorder, no player, no negotiation, so it could ship alone and pay for
itself. Tier 2 also needs it: the kept leaves, their identities and the run
memos are what a delta is computed from (`RetainedFrame.diff`, B4.8), and a
delta against the wrong base is a new class of failure better introduced over
a base already proven. The rejected minimal-delta design went the other way,
moving the wire grammar, both drivers, the recorder and the player in one
increment, and still left a seek at ~100 ms of regenerations for zero wire
bytes.

**Why byte identity is the gate.** Every tier 1 message is the one the
whole-frame path writes for the same cache history, byte for byte, asserted
frame by frame (the golden digests recorded before the first increment, and
lockstep tests driving two scenes, flag on and flag off, through scripted
histories, seeks, replays and restarts). Equal bytes are equal pixels in
every consumer at once, so the retained frame needed no pixel test of its
own and the default could flip without moving a Phase A pixel. The check is
exact: a difference is a bug with a first differing byte to show, never a
tolerance to argue. And it made every trust decision answer to what
`prepare_leaf` would actually read, including the caches' history (recency,
evictions, reservations), which is why the caches gained `keep` and `adopt`
methods that mirror their reads rather than approximate them. Held to that,
the reviews found what a looser gate would have shipped: a leaf read through
a getter of its own, rows a cached read hands back without looking, a
reservation whose source the budget let go; and the pin found flag-off bugs
of its own (style written to an empty path, a thaw handing back an object
whose references pointed outside the thawed graph, uniform-only plays that
bumped nothing).

**Digest adoption over ledger lineage.** A seek thaws copies of the
checkpoint's objects, so almost every leaf on screen is a new object equal
to one the last frame drew. The ledger knows which frozen copy each thawed
object came from, and the retained frame could have followed that lineage
back to the leaf it drew. It follows content instead: a path that leaves
the frame is parked under a blake2b digest of its type name, the text of its
own uniforms, its flags and its non-derived columns, and a new path of equal
digest adopts the entry once its rows compare equal in full and the caches
would make nothing different for it (the mesh generated at this camera, the
first reservation at this zoom, the stroke count at this scale). Content
covers every way an equal path comes back, not only a thaw: a watcher's
restart rebuilds every mobject from source and adopts all of them, and an
edit's replay does the same. It keeps the renderer's correctness off the
checkpoint system's bookkeeping, whose hand-back of live objects depends on
when the collector last ran and whose copies may carry derived columns and
refresh flags the frozen copy does not; a lineage match would need the same
full comparison anyway. The cost is ~12 µs a new leaf (its uniforms' text,
the digest, the full comparison, its cache entries installed), about 6 of a
seek's 8 ms at 8.a.

**The trust surface**, accepted: a kept leaf skips its reads, so an
in-place write that bumps no revision is not drawn until the revision
moves, where the whole-frame path draws it on the next frame. Under
`MANIML_VERIFY_LEDGER=1` the frame keeps what it keeps without it, reads
every kept leaf again before anything is written or stamped for it, and
raises `RenderCacheStale` naming the leaf and what moved, and whether a
write that bumped nothing or the retained frame's own rule is to blame; it
prepares what it would adopt and compares. `MANIML_RENDER_CACHE=bytes`
keeps nothing. The suite runs green three ways (flag off, on, on under
verify), and CI runs the pin all three.

## The fan closes an open subpath through its own start (2026-09-11)

B1's patch fill drew every curve's fan triangle from one base point per
object, the anchors' centroid, on the argument that any fixed point gives
the same winding count. That holds for closed subpaths only: the fan sums
to the winding of the polygon closed through the base, so an open subpath
was closed through the centroid, and a partial path under `ShowCreation`
was closed through a point that moved with it. Phase A's fill (Lyon, and
the earclip before it) closes an open subpath with the chord from its end
to its start. So the fan now takes each curve's base from its own record,
the base point rows the mobject carries (its path's first point): closed
subpaths count as before, an open one closes through its start, the
chord. The object table keeps its base words for the format; nothing
reads them. Found by B3b's gate on `ShowCreation`.

Beside it, a CPU fix that the same gate found and that is on `main`: a
partial path now carries its source's unit normal as it already carried
its joint angles (`pointwise_become_partial`). `DrawBorderThenFill` sets
the outline's data at its first frame, which dirties the normal flag; the
renderer then computed the normal from that frame's points, all one
point, and cached DOWN for the whole border phase, so the outline of every
`Write` was drawn edge-on. The source's normal is the path's.

## A CPU mutation supersedes a pending program (2026-09-11)

B3b's programs compose with the CPU path by one rule: every legitimate
mutation of a mobject's rows calls `note_changed_data`, and that drops a
pending program after the read behind the mutation materialized it. So a
`VFadeIn` on top of a `Transform` in one play, an updater's write, or a
scene's `set_fill` mid-play leave the rows what the CPU path would have
made them, and the renderer draws the rows. Recording a program bumps the
revision without dropping it (`_bump_revision`), and a child's change
bumps its parents the same way, since a parent's own rows are untouched.
The alternative, chaining programs (a paint over a blend), is a program
composition the plan does not need yet: "last program wins" is what the
CPU path does for full-row animations, and the CPU fallback covers the
rest exactly.

## A pending program materializes on read (2026-09-11)

B3a's flip stops writing a mobject's rows during a supported `Transform`:
the GPU blends the two endpoints, Python sends a scalar. The plan's
guarantee was that `get_points` on such a mobject evaluates the program
on the CPU first, and named an audit of the nine files that read
`data[...]` directly. Built instead: `Mobject.data` is a property over
`_data`, and the property materializes a pending program before returning
the array. Every accessor and every direct read go through it, so the
guarantee holds without the audit, and it is one attribute test on the
class-level `None` when nothing is pending. The costs accepted: counts
(`get_num_points`, `has_points`, `family_members_with_points`) read the
array behind the property so a frame's bookkeeping materializes nothing
(a test renders a whole play with materialization forbidden); copies and
checkpoints materialize first and carry rows only; assigning `data`
supersedes the program; and `finish` always writes the final rows, so the
ledger's checkpoint after a play is byte-identical to the CPU path's. The
alternative, materializing only in the accessors, would have left a
direct `data["point"]` read mid-play stale; the property closes that.

## Phase A stays the renderer until the patch fill is faster (2026-09-11)

Decided by Taylor on the B1 prototype's numbers (`docs/phase_b1_plan.md`,
"Prototype results"): the patch fill renders every fixture within the pixel
gate and at or within 2% of Original 2D on the text controls, but about
1.5 ms per text frame behind today's Phase A at the minimum, all of it GPU
completion from the second pass a count-then-cover design needs. Quoted:
"lets keep Phase A as the main renderer till we get it faster."

So `MANIML_FILL=meshes` stays the default, the patch fill stays behind the
switch in the native mirror, and the browser mirror and the default flip
wait on the GPU-side tuning the plan lists. Phase B's direction is
unchanged: paths (B1) and surfaces (B2) both become control points the GPU
evaluates, and B3 animates control points whichever kind they are.

## Fills are a fan and a count, not a mesh (2026-09-11)

Decided by Taylor at the start of B1, after the two candidates in
`docs/phase_b_plan.md` were laid out plainly. The mesh he had in mind, "which
just sort of fills in the triangles between mesh points, no stick out", is a
tiling of the interior that needs the whole outline at once to decide what
is inside, which is Lyon on the CPU and has no GPU equivalent; the GPU works
one curve at a time, so it draws a fan triangle per curve regardless and a
per-sample count answers the inside question afterward. On that: "got it.
then fan it is."

So B1 is B1-fan: the CPU hands over control points, the GPU makes the
triangles every frame, nothing is triangulated anywhere, and B1-mesh is not
the interim. The design, the mechanism probe that preceded the decision and
the prototype week are `docs/phase_b1_plan.md`; the verdict on the measured
GPU cost against Original 2D remains Taylor's.

## Everything is Bézier control points (2026-09-11)

Decided by Taylor in the Phase B planning conversation, quoted: "use the
path way of describing a surface (broadly defined) to define a Surface
(technical meaning), with control points instead of grid / mesh points" and,
on the alternative of exact GPU programs with Bézier as the fallback for
what cannot be expressed, "more important than perfect is simplicity and i
want there to be only one approach, not one with a fallback. so i think
that means besier."

So paths stay quadratic curves and surfaces become nets of control points
evaluated the same way in two parameters; the GPU evaluates control points
at screen density every frame and stores nothing that depends on zoom. The
tracer that would compile user Python into GPU programs is withdrawn, and
so are exact closed-form surface programs; rational weights are the
refinement if exact arcs or spheres are ever wanted, inside the same kernel.
Construction stays on the CPU (`ax.plot` samples a function into curves,
`Surface` samples one into a net), and arbitrary Python keeps running in
Python to produce control points. Accepted costs: a patch sphere is off by
hundredths of a percent, as the sixteen-curve circle is; a surface's
`points` are its net. The plan and increments are `docs/phase_b_plan.md`.

## A zoom step rebuilds nothing the camera did not change (2026-09-10)

Taylor's direction, quoted: "ok do the leftover fix". After the border
expansion moved to the GPU, two CPU costs stayed on every zoom step: each
curve's step count was recomputed and the object's border entry rebuilt
although the compute stage decides the count itself, and each retained
mesh's error bound was projected one object at a time. Now the border
reservation follows from a stored density summary in constant time per
object, and the retained meshes are bounded in one projection per camera
state. Repeated 5% text zoom: 8.9 ms → 5.9 ms against Original 2D's 5.7
ms; the still frame was already ahead. Same pixels. Measurements and the
harness's alternation artifact are in the response document, "The
zoom-step leftover".

## The renderer trusts the revision counter (2026-09-10)

Taylor's direction, quoted: "yeah lets do 4", after this explanation: every
frame the renderer re-read every mobject's arrays byte by byte to decide
whether anything changed; the checkpoint system already answers that with
`Mobject.revision`, a counter every mutation bumps, and has a verify mode
that catches a write that forgets to; the proposal was for the renderer to
trust the same counter with the same safety net.

Now a retained mesh source, GPU border source and per-object style
classification carry the revision they were read at, and a frame that finds
the same revision reuses them without touching the arrays
(`MANIML_RENDER_CACHE=revision`, the default). A changed revision takes the
old path: read, compare, regenerate only what differs, so an `always_redraw`
that rebuilds identical points still reuses its mesh. `MANIML_RENDER_CACHE=bytes`
is the old behavior throughout. Under `MANIML_VERIFY_LEDGER=1` every trusted
reuse still compares the arrays and a bypassing write raises `RenderCacheStale`
naming the attribute; the full suite runs that way, and the three course
episodes rendered under it without a raise. Custom source getters, custom
contour rules and dirty derived-state flags are never trusted. Uniforms are
still compared each frame: they are small, and the counter is only
promised for arrays.

The unchanged 101-glyph text frame prepares in 1.3 ms, from 3.1 ms; the
same objects with a moving camera prepare in about 1.4 ms against 2.9 ms.
The wider measurement is in the seventh-round response. The previous
implementer's reason for declining this twice, that public arrays can be
edited in place without a bump, is now the documented risk with the verify
mode as the detector; the tests that edit arrays in place on purpose run
under the bytes policy and say so.

## Border runs reserve from step counts and build their own indices (2026-09-10)

Taylor's direction, quoted: "go on 1 through 3", where 3 was taking the
seventh review's border findings. The first GPU border increment reserved 64
output vertices for every curve and sent its 186-index strip pattern with the
fill, which cost the 101-glyph text a 3.2 MB first frame, a 2.7 MB packet on
every fill refinement, and 11.5 MB of retained geometry against 1.2 MB for CPU
borders.

Now a run reserves two vertices per step its curves need at the current zoom,
doubled for headroom and capped at 64, sticky per object until the need
outgrows it. The wire (format 6) carries fill indices and, once per geometry,
a per-object layout; each driver expands the interleaved index buffer itself
and rebuilds it when the capacity changes. Capacity is not part of the
geometry identity, so growth resends nothing. Text: first frame 0.79 MB,
largest refinement 0.29 MB, retained 4.9 MB, idle packet unchanged, pixels
unchanged. The 4 MB target in the reviewer's plan is missed by exactly the
headroom, and the headroom stays: halving it would double regenerations on
zoom for a number no scene depends on.

The CPU emitter's triangle budget no longer applies to GPU recipes: their
output is sized and checked by the drivers, so on that path the budget only
turned a deep zoom into a render error. Border outputs are keyed by
occurrence of the same geometry rather than by batch ordinal. Format 5
recordings still load. Compact count/scan/emit remains future work; this is
still bounded fixed capacity per run.

## The 2026-09-09 dogfood report: what was already fixed, what was not (2026-09-10)

Taylor asked, on 2026-09-10, for the three engine items from the field
report to be taken before more renderer work. Measured and fixed against
`8a5bb7f0`:

**The 359 ms `always_redraw` rebuild was already gone.** The report was
written against `4aa37fe6`; the batched curve construction that landed
after it (`fcf7dc4f`, `d5cd0065`) brings the same two-curve PPF rebuild
to 5.1 ms per update on the same machine. Nothing to change; the report's
numbers are historical.

**The edit-time ghost was a crash in the edit handler, and the crash was
the ledger's read-only history doing its job.** Two paths thawed a
checkpoint's *state alone*: the re-anchor in `_handle_file_change` and the
exec-error rollback in `run_next_animation`. A state-only thaw skips
`_rebind_functions`, whose whole purpose is to re-point copied updaters at
the copies (`always_redraw` closes over its original `mob`). With an
`always_redraw` on screen, the first `update_frame` after the thaw called
`become` on the *frozen* copy, whose arrays are read-only, and the handler
died with the safe checkpoint on screen and no replay: exactly the
"removed Tex still there after an edit" symptom, and the same exception
took the interact loop with it, which is the disconnect. Both paths now
thaw namespace and state together through `_restore_checkpoint_for_display`.
Regression tests in `tests/test_checkpoint_reload.py`
(`TestEditWithLiveUpdaters`) fail on the old code with the exact error
and pass now; the headless edit-and-navigate probe of a B0-shaped scene
runs clean under `MANIML_VERIFY_LEDGER=1`, so the ledger itself was never
at fault.

**The event queue no longer closes the socket when full.** The old policy
closed with 1013 at 1,024 queued events; the deque was never cleared, so
the page's reconnect died on the same full queue, and after three tries the
page gave up on a scene that was alive and merely busy. Now: the oldest
pointer sample is evicted (a later sample restates it), the oldest event of
any kind only when no pointer sample is left; the queue empties when the
last client leaves; the page keeps retrying at a capped 5 s interval and
shows the overlay after the third failure without stopping. Draining
*during* a replay was considered and rejected: dispatching navigation
re-entrantly inside a fast-forward is a new class of bug for a case the
eviction policy already covers.

**`AddTextLetterByLetter` is a real animation and is exported.** It was an
unexported alias of `AddTextWordByWord`, which steps over isolated groups
(one group for a plain Tex). It now steps over every drawn glyph at
`time_per_char`, accepts Tex as well as Text, and is in the conformance
baseline. The A3/B0 `key_in` workaround can go.

## Retained GPU fill borders are the first generation increment (2026-09-10)

After restoring GL and fixing transport, lifetime, ordering and paint reuse,
move the general fill-border emitter into a shared WGSL compute stage. This
reuses Phase A's material, stencil ownership, ordered indices and opaque
batching. Public points and general fill triangulation stay on the CPU. A
future GPU point evaluator can produce the same curve inputs; this step does
not implement Phase B's general topology or compact variable-count allocation.

Retain fill vertices, static indices and independently hashed curve sources.
Camera-only border work changes uniforms and regenerates the output locally;
pan of flat borders reuses it. Fill-quality refinement still resends geometry.
Outputs belong to draw occurrences, so identical inputs used with different
uniforms cannot overwrite each other. New resources roll back on failure;
successful submission commits reuse state and retires absent resources.
Source/recipe retention shares the fill cache's bounded host memory budget.
Formats 1–4 still load; format 5 recordings restore sources for every seek.

Choose fixed capacity for this increment: 32 vertex pairs per curve and static
indices, with unused tails clamped to zero-area triangles. It keeps the
101-glyph opaque control at one scene draw and removes small-zoom border
uploads. It also adds about 9.82 MiB of retained geometry buffers over CPU
borders for that control (11.54 MB versus 1.24 MB, excluding AA attachments).
Compact allocation is a future measured optimization, not an implemented gain.

The eight-case, four-reference measurement records the trade: repeated 5%
text zoom takes 10.65 ms versus 14.37 ms for CPU-border Phase A, 5.49 ms for
Original 2D and 8.24 ms for packaged GL. With a real loopback WebSocket echo,
Phase A improves from 16.09 to 11.06 ms; the unchanged-source GPU packet is
1,077–1,138 bytes versus up to 1,468,384 for CPU borders. Large zooms still
refine fills. Static text and pan improve modestly; the changing-path control
and one resize measurement are slightly slower. Full distributions and scope
are in the [GPU border evidence](benchmarks/results/triangle_followup_20260910/gpu_borders/README.md).

Use GPU borders by default with the explicit `MANIML_BORDER_GENERATOR=cpu`
reference retained. Keep packaged `NativeGLCamera` and the Original 2D viewer
option. This is a measured reduction of the text regression, not closure of
A2, the zero-border AA gate, nonplanar fill support or large-field paint cost.

## Fixed-frame ordering belongs to each renderer (2026-09-10)

Before the triangle cutover, native GL stably partitioned fixed-frame groups
last, while the browser consumed stable z/add order. Moving that partition
into Scene preserved native output but changed the Original 2D browser
reference. Scene now provides the original z/add order again; Phase A performs
the native-aligned partition in shared triangle preparation, and GL retains
its own existing partition. Phase A rejoins adjacent compatible families
after partitioning, preserving its cutover child z-sort even when an overlay
previously separated those families. It remains consistent between native and
browser hosts. Original 2D preserves its historical order for comparison.

This applies to top-level render groups. It does not solve a child's z-index
or fixed-frame state crossing different top-level families. Tests record the
difference, including clipping, depth and ties.

## Phase A is shared; Original 2D remains a viewer comparison (2026-09-10)

Taylor requested the shared triangle renderer as the default on main and
Original 2D selectable at the current viewer checkpoint. I interpreted that
as permission to remove native GL from the package; the sixth review carries
Taylor's clarification that native GL must remain packaged as a reference.
The earlier claim of explicit removal authorization is withdrawn. Restore
native GL, its wrappers/shaders and runtime dependencies, while retaining the
Phase A default and the separate Original 2D browser option.

At `67f779dc`, native GL is test-only and native movies/images/new recordings
use Phase A. The follow-up restores `NativeGLCamera`, the real public
`ShaderWrapper`, original GLSL assets and runtime dependencies to the package.
Resources stay camera-owned; frozen test references stay independent. See the [sixth-round response](docs/unified_triangle_renderer_review_response.md#sixth-round-response-retain-native-gl-and-target-the-measured-regressions)
for the restoration scope and verified follow-up issues.

Use a shared 2× spatial resolve with 4× MSAA for predictable default fill AA.
Border triangles share per-sample stencil ownership with fills, avoiding both
repeated translucent paint and the discarded CPU polygon union. Opaque,
constant, unshaded painter fills can omit redundant ownership and batch when
their actual generated colors prove that overlapping fragments are identical.
Paint fields are independent of mesh diagonals. Original source arrays remain
CPU-owned; Phase B is a separate source-update/geometry-generation project.

The Lyon helper is a required build artifact now that the default needs it.
An optional extension would permit a successful install that cannot render.
Source/editable installs need Cargo and a linker; compatible wheels need
neither. Custom native GLSL wrappers are available through the explicit GL
reference. Ordinary nonplanar
filled outlines still need an explicitly defined surface rather than an
arbitrary fan. The [cutover record](docs/unified_triangle_renderer_phase_a.md)
contains the measured performance, quality exceptions and validation scope.

The default cutover accepts one measured performance regression for this
dogfood rollout: moving-camera TeX is 15.91 ms versus 6.87 ms, while the
original ordered-square control improves from 80.57 to 25.31 ms. This is an
implementation decision to permit the default dogfood rollout, not a passed
no-regression test or closure of A2. The text performance and zero-border AA
gates remain open. It is not a universal speed claim or credit for unfinished
Phase B work. Camera border preparation and its resubmitted geometry are the
remaining text cost.

## The browser is the viewer (decided 2026-08-12)

The pyglet window is the most alien inherited layer and the part of the
stack that feels wrong; the browser is the UI toolkit we're fluent in
(Plass). Move the VIEWER, not the renderer — staged so the UI
investment carries over completely and the shader port never happens at
the same time as a UI rebuild.

## Stage 1 — browser viewer, native renderer (shipped 2026-08-13)

Shipped as an additive `--web` flag (`maniml scene.py Name --web`,
combines with `--present`; `--no-browser` suppresses the auto-opened
tab). Built in `maniml/web/`: server (WebSocket + HTTP on one daemon
thread), WebViewer duck-typing the Window interface with the camera
running windowless on the standalone GL context (the `--render` path),
and a vanilla-JS client. Protocol as sketched: JPEG while animating or
input arriving, one lossless PNG at quiet; state JSON on change;
picking server-side. End-to-end tested headlessly in
`tests/test_web_viewer.py`. Measured streaming tax ~3.7ms/frame at
1080p (readback 1.4 + PIL JPEG 2.4).

Deliberately not done at the time, as risk containment — the pyglet
path stays untouched until `--web` earns trust in daily use. Those
holds are now roadmap items in `TODO.md`: deleting
`rendering/window.py` and the pyglet dependency, moving the `--present`
timeline from the GL overlay to DOM, porting `tests/test_interactive`
to a browser-driven harness.

## Stage 2 — the client learns to render (2026-08-13/14)

The portability payoff: the viewer requests a geometry snapshot
(message 0x03: camera/mobject uniforms plus the raw interleaved
VMobject vertex structs) and renders it with its own GPU next to the
pixel stream.

A correction that shaped the port: the pipeline is NOT
geometry-shader-free — maniml and current 3b1b/manim both have four
geometry shaders (quadratic_bezier fill/stroke/depth, true_dot), and
the stroke one carries the adaptive polyline + joints. The port
therefore re-expresses them as *instanced vertex shaders* (one instance
per bezier triple, `gl_VertexID` enumerating the emitted strip) rather
than transliterating. Shader sources are shared between the browser
(`static/glsl/`, `static/gl.js`) and `web/reference_renderer.py`, a
desktop-GL mirror that `tests/test_gl_port.py` pixel-diffs against the
native renderer (mean |diff| 4e-5/255 on a fill+stroke+winding+Text
scene).

The parity ledger closed 2026-08-13/14, in order: 3D VMobjects
(triangulated fill serialized as vertices+indices+flat color, depth
test, MSAA via multisampled renderbuffer + resolve; 3D fidelity mean
|diff| 0.003/255); DotCloud (billboard geometry shader as a 4-vertex
instanced strip; bit-perfect); ImageMobject (raw file bytes by content
hash, browser decodes natively; bit-perfect); Surface and
TexturedSurface (bit-perfect); clip planes (v_clip varying + fragment
discard, the pixel-resolution equivalent of gl_ClipDistance). The
winding-fill depth pre-pass is a FALLBACK BY DESIGN: unreachable
through the public API, since `ThreeDScene.add` / `apply_depth_test`
always switch fills to triangulated — declared `unsupported`, revisit
only if dogfooding ever surfaces it. `set_color_by_code` and the
fractal shaders are niche and likely permanent pixel-stream fallbacks.
Anything unsupported stays honestly declared in the payload's
`unsupported` list, with the pixel stream as the fallback throughout.

Delta encoding (2026-08-14): batches carry a blake2b content hash;
unchanged batches ship as `"cached": true` references (zero bytes)
while metadata stays fresh so zoom changes need no re-upload. Client
and reference renderer cache GPU buffers/VAOs by hash (LRU 512); a
client cache miss requests `geometry_reset`; the server-side sent-set
resets on connect and on mode-on. The remaining serialize CPU per frame
is the numpy get_shader_data walk — optimize via `_data_has_changed`
only if profiling ever demands.

Solo-GL view (2026-08-14): the renderer buttons cycle off →
side-by-side compare → solo. In solo the pixel stream stops entirely
(no per-frame readback/encode server-side) and the client canvas is the
viewer, fully interactive; unsupported content is surfaced loudly since
there is no pixel safety net. This is the Stage-2 burn-in state —
dogfood real course scenes here.

The baked player shipped 2026-08-14: `--export` records the geometry
stream headlessly (`web/export.py`, the same viewer hooks, unpaced)
into `./media/SceneName_web/` — a self-contained static folder (player
page + renderers + gzipped stream, ~7x compression; the dogfood Demo
bakes to 1.7MB) for sharing: scrub/play per animation segment, no
Python anywhere. Known cost: delta granularity is per merged batch, so
an animating batch re-ships whole frames — fine for hold-heavy
lectures, ~video-sized for animation-dense scenes; per-submobject
deltas if it ever matters.

## WebGPU is the endgame renderer (decided 2026-08-14)

One canonical renderer everywhere. Sequencing: finish parity on WebGL2
first — the payload format, protocol, serializer, and fidelity harness
are backend-agnostic and survive — THEN stand up a WebGPU backend
beside WebGL2 against the same payload and tests, migrate, and make it
canonical. wgpu runs the same code in-browser and natively (wgpu-py),
so at that point the reference renderer and the browser renderer become
literally the same code, `--render` moves onto it, and the
geometry-shader pipeline (and eventually pyglet) retires: one renderer
everywhere, no dual maintenance. WebGPU also restores GPU-side adaptive
tessellation via compute shaders — the elegant replacement for the
fixed-strip instancing compromise. Chrome is the app; browser support
is a non-issue.

Built 2026-08-14 in three passes: `static/wgsl/` +
`web/wgpu_renderer.py` render the full parity ledger from the same
payload — 3D/depth/MSAA, triangulated fill, dots, images, surfaces,
textured surfaces, clip planes — via a lazy pipeline cache keyed
(name, sample_count). WebGPU-specific handling: clip-space depth remap
in emit_gl_position (GL [-w,w] → WebGPU [0,w]), per-pipeline blend and
depth state, one packed 176-byte uniform struct (keep UNIFORM_FIELDS
and struct Uniforms in sync), top-down readback, and in the browser a
blit pass to present, since the canvas swapchain format is
platform-preferred. `static/webgpu.js` is the navigator.gpu mirror of
wgpu_renderer.py — same specs, layouts, uniform packing, pass structure;
**keep wgpu_renderer.py, webgpu.js, and wgsl/ in sync**.
`tests/test_wgpu_port.py` runs six fidelity scenes: 2D/clip/dots
bit-perfect (max 1/255); image/3D/surfaces differ on ~0.04% of pixels
at silhouette edges (implementation-defined MSAA sample positions and
texture-filtering precision, Metal vs GL — legitimate cross-API
variance). The live viewer starts on WebGPU and falls back visibly to
Pixel when WebGPU is unavailable.

Retiring `gl.js` + `glsl/` once WebGPU is canonical was **confirmed
2026-08-18**, with the trigger unchanged: burn-in on real course
scenes. The retirement steps live in `TODO.md`.

The retirement implementation was prepared on `review/retire-webgl2`
2026-08-26, but remains merge-gated on the A-series WebGPU fidelity bugs.
Until those close, the restored three-way live control keeps WebGL2 as a
differential diagnostic: a defect shared by WebGL2 and WebGPU implicates the
serializer, while a WebGPU-only defect localizes to the WGSL port. Once the
gate closes, the live product has one client renderer (WebGPU), Pixel remains
its complete-frame fallback, and the WebGL2 browser backend, shader tree,
desktop mirror, and dedicated fidelity module leave together. Backend-neutral
payload and z-order assertions move into the WebGPU suite rather than being
discarded with that harness.

The baked geometry player follows the same retirement: `--export` is
WebGPU-only and displays a clear unsupported-browser message rather than
shipping WebGL2 solely as an export fallback. This is acceptable because the
MP4 student bundle (`--export-present`) is the primary distribution artifact
and needs no GPU renderer; retaining an export-only backend would preserve the
maintenance burden after removing it from the live product.

Geometry exports are explicitly versioned from this retirement onward.
`GEOMETRY_FORMAT_VERSION` is written into both the binary geometry headers
and `scene.json`; the standalone player refuses a different or missing
version with a "Re-export this scene" message before it downloads or renders
the frame stream. Future resource/chunk formats increment that constant
rather than letting an old export fail as malformed GPU input.

## Stage 3 — the app (2026-08-14 onward)

`maniml app [dir]` (`web/app.py`, since split — see 2026-08-18 below):
a persistent local server; opening a scene spawns `maniml file.py Scene
--web` as its own subprocess (crash isolation — scene files are
arbitrary code; process reused for repeat opens; children terminated on
app exit). The viewer and landing shell were redesigned on 2026-08-16
in the shared Plass/Knuth visual language: warm graphite canvas, quiet
floating glass slugs, file-action and renderer flyovers, explicit
reverse/forward transport, a separate DOM pausepoint rail. The export
flyover saves the current frame or starts an isolated, one-at-a-time
video render / baked-web export, leaving the live scene and its
checkpoints intact.

The landing page became an Open action plus your recent files
(2026-08-18) — deliberately not a directory listing: the app is not a
file browser, and a listing of every scene class under a course tree
was noise in front of the one file you actually wanted. Opening no
longer auto-runs; a file opens at its first scene. The background
engine (`maniml agent`) is offered once, on first run — the only moment
worth asking — and `maniml app` hands off to an engine already on the
port rather than binding a second one, restarting an agent still
serving pre-upgrade code. The console panel shipped 2026-08-18:
toggle-only, never automatic, the only place a scene's output is
visible in app mode at all.

## Stage 3b — the hosted PWA: tried, then deleted (2026-08-17)

The frontend deployed to GitHub Pages and talked *across* origins to
the local engine. Everything that seam needed — a service worker and
manifest, a versioned wire handshake, URL-fragment pairing per daemon
session, an AppleScript launcher, a `maniml://` URL scheme, Launch
Services registration, Chrome PWA shim discovery, a public-origin
allowlist — cost roughly 1,400 lines and produced essentially every
delivery bug this project has had. "Collapse to a local, pip-only app"
removed all of it, along with the macOS desktop launch bridge built on
top of it (`install-desktop`, `maniml open FILE`, the `.py` Finder
association) and its public-release gates. The engine that runs the
scenes now serves the interface, from the same pip install, so they
cannot drift. **Do not reintroduce a public origin that talks to
loopback.**

Knuth (github.com/tayweid/knuth) spent 2026-08-17 arriving at the same
architecture from the same starting point, after a day of debugging its
own cross-origin pairing. Its inbound notes lived in
`SAME_ORIGIN_NOTES.md` (deleted 2026-08-18, absorbed here and in
`SECURITY.md`); two findings landed:

- **One port, not two.** The page was served on N and its socket lived
  on N+1, so "same-origin" was two origins bridged by an allowlist —
  paying for a port-pair search, a `?ws=` parameter, a `#control=`
  fragment, and a parent origin threaded into every scene subprocess.
  Both servers now answer plain GETs on their WebSocket port
  (`web/assets.py` via `process_request`), the client says
  `ws://${location.host}/`, and `connect-src 'self'` became a real
  restriction. The app's `/api/*` endpoints went with it.
- **No capability token.** It defended only against another program
  running as you, which can forge any header and can equally run
  `python` itself; keeping it meaningful meant delivering it out of
  band, which made launching a delivery problem and left a refused page
  needing a terminal to recover. The Origin check is now the whole
  boundary, and `http://localhost:8685/` is an address worth
  bookmarking. The attacker table is in `SECURITY.md`. The trap to
  remember: *embedding a token and keeping a token are different
  decisions* — doing the first without noticing turns the second into
  decoration.

Knuth's measurements that still matter here (Chrome 151, macOS 26):

- A PWA installed from a loopback origin **can** register OS file
  handlers, and a double-click delivers the file through `launchQueue`
  — even with the server stopped, since the service worker serves the
  shell and the file handle comes from the OS. This is what makes the
  `.py` double-click question in `TODO.md` answerable at all.
- `connect-src 'self'` **does** cover a WebSocket back to the same
  origin, verified on a non-default port.
- `open -a <App> <url>` cannot hand a URL to a Chromium PWA — the app
  shim silently discards it and loads the manifest `start_url`. Any
  future launcher that needs to deliver state through a URL will hit
  this.
- Do not let a client delete its own stored credential because one
  connection was refused; a refusal is not proof the credential is
  dead. (Moot while there is no credential; recorded because it was
  the single most expensive lesson.)

**The shape it settled into**, matching Knuth's first run:

1. `maniml.tayweid.io` is a preview (`site/`) — shows what this is,
   gives the install command, reaches nothing, cannot be installed.
   `site/sw.js` must keep existing as a kill switch: the pre-collapse
   hosted build registered a caching service worker, and a browser that
   has it keeps running it until a replacement at the same URL
   unregisters it. `site/app.html` redirects for the same reason.
2. `pip install` → `maniml app` starts the engine and opens
   `http://localhost:8685`.
3. The app offers **Install** for an icon and a tab-less window.
   Installing belongs to this origin alone, because only one installed
   app can own a `.py` and it should be the one with a Python process
   behind it. Scenes are relayed through the app's port rather than
   opened on their own, because the port is the installed app's
   identity — see `CLAUDE.md`.

## Removed: the IPython embed (2026-07)

ManimGL's embed mode (`scene_embed.py`, comment-keyed
`checkpoint_paste`) was removed — the checkpoint system is its
replacement. `self.embed()` remains as a stub that logs a warning. If a
live REPL is ever wanted again, build it on the arrow-key checkpoint
history rather than reviving the old module.

## The cleanup pass (2026-08-18)

After the 19-commit collapse arc, a systematic review (four scoped
subagent audits: dead code, docs-vs-code, test health, web-layer
structure) drove: deleting the transient-session path the desktop
bridge left behind; splitting `web/app.py` into `library.py` (file
knowledge) + `app.py` (the server) + `cli.py` (the command);
extracting `shell.css` after the two pages' "shared" palettes were
found drifting; retargeting CONTRIBUTING/SECURITY at the audience that
actually exists; and splitting the old TODO.md into this file and the
roadmap. `viewer.html` stays deliberately single-file: the transport
seam (wsUrl, send(), the message pump — verified still airtight) exists
so a future in-page engine can replace exactly those three things, and
the source-shape contract tests in `tests/test_static_assets.py` pin
its text. A shared websocket-bootstrap helper between `server.py` and
`app.py` was considered and deferred: real duplication, but the
abstraction only pays if that code is being touched anyway.

## Pausepoints are authored, not implied by play() (decided 2026-08-21)

Dogfooding surfaced the mismatch: a pause after every play makes live
presenting feel like clicking through bullets, and deriving
presentation structure from source structure (which plays live where —
helpers, loops) kept demanding smarter AST inference. The resolution
separates the two granularities the checkpoint had been serving at
once. A file that calls `self.pause()` (or CE's `next_section`)
anywhere becomes **pause-anchored**: pauses are the only checkpoint
savers and the only unit boundaries, plays between them run as one
stretch, and a pause works from a helper or a loop body because it
saves at call time — no call-graph inference needed. Files with no
pauses keep the per-play anchoring, which is what lets an unmodified CE
file be opened and stepped; that legacy path is one clearly-marked
branch, kept for CE compatibility and deletable later if the superset
argument wins. History note: the pre-repo prototype (preserved in the
early trees' `scene_backup.py`) checkpointed at *both* play and wait;
the 2025-07-14 rewrite cut wait when checkpoints grew namespaces.
Wait-as-pause stays rejected — `wait(0.5)` is rhythm inside a stretch,
not a hold. The `# %%` cell-marker idea in `TODO.md` is complementary,
not competing: cells would restructure *execution* units; `pause()`
decides where playback *holds*, and reaches the loop bodies and
helpers that comments cannot.

## Live sound is the system player; browser audio is deferred (decided 2026-08-22)

Audio arrived in two halves. The render half was inherited working:
`add_sound()` mixes pydub segments on the file writer's timeline (per-sound
gain, timestamp overlay) and ffmpeg muxes them into the mp4; pydub and
audioop-lts are packaged dependencies. The live half was a stub —
`utils/sounds.py`'s `play_sound()` (afplay/SoundPlayer/aplay) existed with
no call site, and the viewer had no audio at all.

**Tier 1 (shipped):** `add_sound()` now also plays the file immediately
through the system player whenever there is a live audience — a pyglet
window, or a web viewer with a client attached. The correctness of this
rests on the delivery decision above: *the viewer is loopback-only, so the
engine and the browser always share a machine*, and engine-side audio is
indistinguishable from browser audio to the person sitting there. The
`skip_animations` guard keeps fast-forwards (present prep, watcher
replays) silent; real-speed replays — `pause(loop=True)` laps included —
re-trigger the sound, which is the honest semantic. `time_offset` and
`gain` shape only the rendered mix; live playback is immediate and at
file volume. Render and headless runs have no window and stay silent;
export's `GeometryRecorder` stands in as `_web_viewer` without
`has_clients`, so it stays silent too — the audience predicate needs no
mode flags.

**Tier 2 (deferred, design recorded so it need not be rediscovered):**
browser-native audio, needed only when one of two things becomes real —
remote viewing (engine and speaker no longer share a machine) or sound in
the *baked player*, which has no engine at all and for which Tier 2 is
the only possible mechanism. The shape, respecting existing invariants:

- a `{"type": "sound", ...}` protocol message from `WebViewer`, kept
  inside the transport seam (`wsUrl`, `send()`, the message pump) so a
  future in-page Pyodide engine inherits it;
- the audio file served over the same one-port origin, confined by
  `security.py`'s scene-root machinery — no second origin, per the
  delivery rule;
- client-side `new Audio(url).play()` plus a mute control in the bar;
  browsers require a prior user gesture, so a sound fired before first
  interaction is swallowed — acceptable in the live viewer, but the baked
  player would need a start gesture anyway;
- the baked player additionally needs the sound files copied into the
  export folder and timeline-synced playback in `player.js`.

## Pausepoints are marks on play-checkpoints, not the checkpoints themselves (decided 2026-08-23)

One day of dogfooding overturned the previous entry's core mechanism
while keeping its purpose. Pause-only checkpointing quietly deleted the thing
that made LEFT feel like true reversal: with a checkpoint at every play,
a backward step crossed one small delta and the name-paired morph
retraced it faithfully; with checkpoints only at pauses, LEFT crossed a
whole stretch whose target predates everything built inside it, so
nothing paired and the scene crossfaded wholesale (first seen on
0_Welcome's unemployment timeseries).

Alternatives considered and rejected: state-only "breadcrumbs" stored
per play (memory lifecycle for something derivable); re-deriving
breadcrumbs at LEFT-time by fast-forward re-execution (rejected as
architecture smell — navigation shouldn't re-run code); recording the
render/geometry stream and playing it backward (correct and additive —
converges the live viewer with the baked player — but it is a *playback
layer* on top of the computation layer, not a substitute; deliberately
deferred, see the shape in the discussion of segment caches).

So the resolution is the simple hybrid: **every play saves a full
checkpoint again, exactly as before pause() existed; pause() saves one
more, flagged `stop`.** What pause() buys is purely the authored rest:
RIGHT runs play-to-play until the next flag, LEFT morphs back hop by
hop to the previous one (the pause-hop lands instantly — its checkpoint
duplicates the play before it), UP/DOWN keep per-play fine navigation,
and pause(loop=True) laps the stretch from the previous flag. Memory
returns to pre-pause levels, which a day of use had already shown was
acceptable — and cheaper navigation was never worth the reverse.
The rail keeps its wire protocol: the viewer maps each checkpoint to
its pausepoint chip server-side (`_chip_unit`), so interior play
checkpoints collapse into the pause chip and the client is untouched.

## Backward navigation is a jump (decided 2026-08-23, ~3am)

The reverse *morph* is gone. It was never a true reversal — from the
first prototype on, LEFT was a name-paired whole-scene morph between two
stored states, and states are photographs: nothing in them says how a
line was drawn, so a Create could only ever fade, and one night of
pausepoint dogfooding surfaced three separate failure modes (whole-
stretch crossfades, updater fights, trackers unpaired because they join
the scene only when first animated). Each was fixable — the last fix
proved a frame-exact tracker rewind — but the mechanism misleads
precisely when reverse matters most, and a presenter has to be able to
trust the key.

So LEFT now jumps: instant restore of the previous pausepoint's exact
state, the same trusted path UP/DOWN use. What was deleted:
`_play_reverse_to` (pairing, updater discipline, the ValueTracker
special case) and `_reverse_run_time` with its constants. What stays:
per-play checkpoints, `run_time` recorded on each (the playback layer
needs the spans), and the protocol's `back` field (a reverse *playback*
will light the rail the same way).

True reversal is a playback problem, not a state problem: it arrives
with the recorded render-stream layer (TODO.md, "Recorded playback"),
which replays what the GPU was actually sent, in reverse — exact for
any content, no heuristics. Until then the honest options were a jump
or a sometimes-beautiful, sometimes-lying morph; the jump won.

## The presentation cache is the mp4 (decided 2026-08-22)

The plan was to present from the baked geometry stream; a byte-level audit
killed it. Episode0 (~4 min) baked to 772 MB: the whole 2D scene merges
into one delta batch (`_MERGE_KEYS` carries no per-mobject identity), so
any motion re-ships every visible vertex; 99.5% of shipped bytes repeat
between consecutive frames but gzip's 32 KB window cannot see across
150-800 KB frames (measured: zstd 327x, XOR-delta+gzip 35x, shipped gzip
7.2x); 52 of 68 bytes per vertex are replicated constants; a 1.5x index
expansion on top. The best dependency-free re-format lands near 20 MB.
**The H.264 mp4 of the same scene is 7.7 MB.** A codec team has spent
twenty years on temporal compression; presenting is exactly its use case.

So Present runs off the video. The model is Taylor's own t1-web
(`t1-web/js/Present.js`): a <video>, an array of pausepoint timestamps,
and stepped scrubbing toward a target time — which plays **both
directions** with one file, no reversed encode. maniml generates the
inputs that t1-web hand-marked: every checkpoint already stores its
timestamp (`SceneState.time`), pause() supplies stop/loop flags and
names, and `chip_unit_for` (extracted to source_map.py) keeps the
presenter's rail identical to the live one. `--render` now always writes
`media/<Scene>_present/` — scene.mp4 (encoded with `-g fps`, a keyframe
per second, so every scrub seek lands instantly), present.json for the
viewer, present_meta.js + index.html + presentation.js for a standalone
page that opens from disk (fetch() does not exist under file://, which is
why the meta ships as a script — the same reason t1-web used a .js data
file). The viewer's Present button enters playback on the bundle, tells
the engine to send nothing ({"type":"mode", geometry:false, pixels:false}),
and shows a "stale" badge with one-click re-render when the source hash
no longer matches; a missing bundle renders first. Reverse is finally
honest: LEFT scrubs the recording backward, exactly.

The geometry-stream export stays for what only it can do — vector-crisp
zoom, the WebGPU endgame, Pyodide — and its size problem stays documented
in TODO.md with the audit numbers; revisit after the performance track's
per-submobject chunking changes the math.

**Follow-up (2026-08-26): the standalone page returns, as a different
artifact.** The 2026-08-22 slimming deleted `present.html` because the
*presentation cache* — what the viewer's Present button plays — needed
no page: mp4 + pausepoints.json, the no-engine fallback being the mp4 in
any video player. That decision stands. What returned is a *student
bundle*, `--export-present` → `media/<Scene>_present/` (index.html +
presentation.js + present_meta.js + scene.mp4): a self-contained folder
a course site hosts so students can click through an episode's
pausepoints with no engine anywhere — the replacement-for-slides use
case, where "the mp4 in any video player" loses exactly the thing that
matters (parking on beats, honest backward). It is opt-in, never written
by plain `--render`, and the cache the viewer plays is unchanged. The
table ships as `present_meta.js` because the page must open from
file://, where fetch() does not exist. Episode-sized reality check: all
of EpisodeA1 is a 4.3 MB folder.

**Follow-up (2026-08-26): recorded playback starts only after live endpoint
prebuild.** The viewer used to enter the movie immediately, even when the live
engine had built only a prefix of the movie's checkpoints. Exiting playback at
a later point could therefore fail to park the engine at the visible endpoint.
Present now has an explicit readiness handshake: prebuild every live endpoint,
rewind, advertise `presentation_ready`, require a fresh recording with the
same checkpoint count, then let the movie own motion. Exiting first restores
the corresponding live checkpoint and then leaves present mode. `--present`
uses the same path. A missing or stale movie is rendered only after the user
explicitly enters Present; ordinary live WebGPU still writes no media.

## Family draw order is CE's (decided 2026-09-02)

The symptom, reported from course production as "VGroup children render
in reverse order": a fill-only Dot placed last in a VGroup still drew
under an earlier DashedLine's dashes, and no reordering of children
changed anything. The A3 episode grew a workaround culture around it —
"bring_to_front the dots; z_index alone isn't honored across plays".

The diagnosis was not reversal. Same-kind children always drew in
order; the inversion was the batch pass sequence. The renderer merges
same-state family members into one batch, and a batch draws ALL its
fills before ANY of its strokes (the winding-number fill accumulates in
the float texture and composites once — that part is load-bearing, not
an optimization). So within a batch, any stroke beat any fill, whatever
the family order said. CE paints each member completely, in family
order, with the family stably sorted by z_index first.

Decision: match CE, and keep the batching. `assemble_draw_batches`
(utils/family_ops.py) is now the one place that turns a render group's
family into draw batches, used by both the native flatten
(Mobject.get_shader_wrapper_list) and the web serializer
(web/geometry.py) so the pipelines cannot disagree (pixel-diffed in
tests/test_wgpu_port.py). It stably sorts by z_index, merges same-key
neighbors, and starts a new batch when a member's early-pass content
(fill; stroke when stroke_behind) overlaps late-pass content already in
the batch — the only case where merging inverts CE's paint order. The
overlap test is a stroke-padded bounding box per late-pass member (not
a running union, which reads a wrapped grid row as covering everything
and splits members that overlap nothing painted), so text glyphs, bar
charts, and dense grids still merge into one draw: 500 packed
filled+stroked squares stay one batch, ~6ms to rebatch against ~2.5ms
before. A child's z_index change dirties the render caches up the
parent chain and takes effect next frame.

Not done, documented in TODO.md's quality tier: CE sorts one flattened
scene-wide list, so a high-z child of one top-level group cannot draw
over a later top-level group here. The 3D path is untouched — depth
test resolves occlusion per pixel, so batches there never split.

The course workarounds survive unchanged but are now mostly redundant:
z_index on a marker dot inside its VGroup is honored, so the
"first-child-on-top" child ordering (which never actually did anything)
and most of the bring_to_front calls can go when those files are next
touched.

**Follow-up (same day): the split has to trust bounding boxes, and
interpolate was poisoning them.** After the fix above, the A3 markers
still drew dashes-over-dot in the live viewer — but only after a play;
a plain add() rendered correctly. The cause was
`Mobject.interpolate`, which lerped the endpoints' RAW `bounding_box`
cache arrays: an animation-endpoint copy that never computed its box
still holds init-time zeros (with its dirty flag set), and lerping
that writes an origin box into the live mobject while the live flag
stays clean — real points, poisoned cache. The hazard split then saw
every dash "at the origin" and stopped splitting. Fixed by
interpolating `get_bounding_box()` (computes-if-dirty; the endpoints
are static, so it computes once per animation and caches). The
poisoning predates the draw-order work — click-to-inspect hit-testing
reads the same boxes — but rendering never consulted bounding boxes
until the hazard split did. Regression-tested in
tests/test_wgpu_port.py::FamilyDrawOrder.test_family_draw_order_survives_animation.

## One renderer: the beeline (decided 2026-09-02)

Taylor's call after the 2026-09-02 status review: everything goes
except native GL, which stays until after pyglet, with a pause before
it is removed. Concretely:

- **WebGL2 is retired** (`review/retire-webgl2`, merged 2026-09-02):
  `gl.js`, `glsl/`, the GL half of the reference renderer and the
  WebGL2 fidelity module are gone (-1,600 lines). The geometry player
  is WebGPU-only with an unsupported-browser message; exports carry a
  versioned format header. The burn-in hold was lifted because the
  z-order bug the WebGL2 comparator was kept to triage is fixed, and
  remaining triage compares against native render frames or CE.
- **CE is the arbiter.** When native GL and WebGPU disagree, the
  reference is what manim CE draws (the `manimce/` clone and the
  conformance suite), not the native pipeline. The draw-order bug was
  wrong in native GL too; "match native" would have enshrined it.
- **The Pixel stream goes next, then pyglet, then a pause, then
  `--render` on wgpu-py and native GL deleted.** Sequence and reasons
  in TODO.md's milestone section. The pyglet window is the last live
  consumer of the native pipeline; once it is gone native GL serves
  only headless `--render`, which is the one place a wrong-but-stable
  renderer costs least while the wgpu render is built beside it.
- **The shadow-mode gate is closed.** The 2026-08-26 gate review
  (PERFORMANCE_GATE_REPORT and the PROBLEM / ARCHITECTURE / MIGRATION
  proposals, then in the workspace root) approved two background
  investigations — a structural-sharing revision store with stable
  semantic identity, and bounded per-resource geometry chunks for
  large scenes — conditioned on beating a keyframe + skip-replay
  comparator and never taking priority over the WebGPU strip. Its
  measured evidence stands and is summarised here so the documents
  can go: on the course scene (`dogfood/03_Code.py`), solo WebGPU
  after the stabilisation layer reached 64.5 ms input-to-first-motion
  and 62 ms p50 retained-history endpoints against 79/86 ms on Pixel,
  with 238 of 240 native captures bypassed; checkpoint save/restore
  copies were 22/37 ms p50 and the visible navigation-boundary cost;
  a one-object change in a 2,000-square scene still shipped the whole
  merged batch (130 ms p50 to endpoint). Those large-scene numbers are
  real, but no course scene is near them; the decision is to finish
  the one-renderer strip first and re-open scale work only when a
  real scene demands it. The Phase-1 code (`revisions.py`, mobject
  hooks, the shadow Present work) is preserved as tag
  `archive/perf-systematic-viewer`; the priority-decision branch as
  `archive/performance-priority-decision`.

## Recorded video is tagged BT.709 (fixed 2026-09-02)

Taylor's one remaining fidelity report was "the background grey is a
slightly different grey between the web viewer and the rendered
video". Measured in the app's Chromium by drawing the decoded `<video>`
to a canvas beside a CSS swatch: the grey itself matched (26,26,26),
but a maniml BLUE square that is (89,197,223) live decoded as
(80,188,225) — the movie pipe wrote untagged yuv420p, swscale converted
RGB->YUV with its BT.601 default, and browsers decode untagged HD as
BT.709. The pipe now converts with `scale=out_color_matrix=bt709` and
tags the stream (`-colorspace/-color_primaries/-color_trc bt709`,
`-color_range tv`); the square decodes as (90,197,222). The always-on
`eq=saturation=1:gamma=1` filter was also dropped unless asked for: eq
works in YUV, so with RGBA input ffmpeg inserted an extra RGB->YUV pass
whose rounding tinted the grey to (24,26,26). Regression test:
`tests/test_external_processes.py::test_movie_pipe_tags_bt709`.

## The full-suite fidelity flake was a uniform mirror keyed by id() (fixed 2026-09-02)

For about a week the full `unittest discover` run failed one or two
native-vs-wgpu fidelity cases per run — a different case each time,
never in isolation, never with any single other module paired in, and
never in a six-iteration repeat inside one process. Dumping the failing
frames (`MANIML_FIDELITY_DUMP`) showed the NATIVE side was the wrong
one: a z_index case's native frame had lost its dot.

`set_program_uniform` skips a GL write when its mirror says the value
is already set, and the mirror lived in a module dict keyed by
`id(program)`. `get_shader_program` is an `lru_cache` of 128 entries,
so once a run has created enough scenes, programs are evicted and
freed, a new program lands on a freed address, inherits the stale
mirror, and silently skips its first uniform writes. Nothing short of
the whole suite allocates enough programs to reach eviction, which is
why every bisection came back clean. The mirror now lives in the
program's own `extra` slot and dies with it;
`tests/test_shader_uniforms.py` fails unfixed at the second iteration.
The same defect would have hit a long live session in the native
window, which is one more reason the native pipeline is on its way out.

## The browser is the only live viewer (decided 2026-09-02)

Milestone step 1 of the one-renderer beeline: the Pixel stream is
deleted. Until now `--web` kept two pictures — the browser's WebGPU
render of the geometry stream and, behind it, JPEG/PNG frames of the
native GL framebuffer streamed as a fallback and a comparison ("split")
— with a renderer switcher in the bar, a `renderer_fallback` protocol
that flipped a client back to Pixel when a scene held content the
serializer could not express, and a per-frame support preflight that
decided whether native capture could be skipped.

All of that is gone. The client reports `{"type": "mode", "geometry":
true}` once its WebGPU is up; from then on every frame is a geometry
payload and `Scene.update_frame` skips `camera.capture` outright. A
browser without WebGPU gets a notice on the stage (state and console
still flow, so the engine is not lost). Content the serializer cannot
express is declared in the payload's `unsupported` header, left out of
the picture, and named in the bar — there is no native frame behind it
to fall back to, and pretending otherwise is what the split view was
for. `--render`, `--export-checkpoints`, and the pyglet window still
use native GL; they are the next steps.

Why now rather than after pyglet: the stream was the only consumer of
the JPEG encoder, the readback, the `droppable` frame queue in the
server, and the updater-inference streaming costs that the performance
audit measured (20–60 ms per encode, most of a core on a parked scene
with updaters). Deleting it removes those costs rather than optimising
them, and it removes the last reason the viewer had to know whether the
native pipeline agreed with the browser.

## The pyglet window is retired (decided 2026-09-02)

Milestone step 2 of the one-renderer beeline. The browser viewer is
now the default and only live surface: `maniml scene.py Scene` opens
the browser (`--web` is accepted and means the same), and the pyglet
window, `rendering/window.py`, the `pyglet` and `moderngl-window`
dependencies, the window section of the config, and the `-f` full
screen flag are gone. `Scene.window` keeps its name because
`WebViewer` implements the interface the scene loop was built around;
the camera is always a standalone GL context now, which deleted the
window framebuffer, the letterboxed blit, and the `use_window_fbo`
toggling around offline capture.

The `--present` timeline overlay — rings drawn as scene mobjects near
the bottom edge, revealed by the mouse — went with it. It existed for
the window; the browser has had its own rail since 2026-08-16, in
live and Present alike, so the overlay was a second scrubber with its
own checkpoint-ignore plumbing (`get_state`/`restore_state` had to
exclude and re-attach it) and its own crowding bug past ~50
checkpoints. Both are deleted rather than fixed. In present mode a
click on the stage no longer grabs anything: navigation is the rail.

The key and mouse constants in `event_constants.py` are maniml's own.
Their values are still the ones pyglet delivered, so scene code and
`mobject/interactive.py` compare against the same numbers; nothing
imports pyglet, and `tests/test_headless_import.py` asserts that a
star import touches neither pyglet nor moderngl-window.

The windowed scenario suite (`tests/interactive/`, opt-in through
`MANIML_WINDOW_TESTS`) is deleted. Its ghost-mobject regression is
ported to `tests/test_checkpoint_reload.py::TestGhostMobjects`, driven
headlessly the way the rest of that file drives a scene; dev-mode
navigation and present-mode prebuild are covered by the headless
checkpoint and mode tests and by the end-to-end web viewer suite; the
3D depth/MSAA scenario is covered by the wgpu fidelity cases. The
MSAA letterbox blit it also checked no longer exists.

## The roadmap is pruned to the pause, the held step, and the instruction stream (2026-09-04)

`TODO.md` had grown into a record of every idea since August, most of
it written before the one-renderer strip and the instruction-stream
design (`../simlab/ARCHITECTURE.md`, 2026-09-03). On 2026-09-04 it was
cut to what is actually planned. Nothing removed was implemented —
this entry exists so that no one reads the removal as "done":

- **Superseded by the instruction stream** and removed: the
  `docs/performance_2026-08.md` delivery order (revision store, copy-on-write /
  delta checkpoints, bounded geometry chunks, transform deltas,
  keyframed exports — the engine core in the plan is all of these at
  once), the geometry-stream recorded-playback layer (the clock running
  backward over immutable buffers is the same thing), the parked-scene
  streaming rewrite and the "should idle frames be client-rendered"
  question (the GPU clock owns updaters), and the end-to-end
  presentation clock (the plan's clock). `docs/performance_2026-08.md` stays as the
  measurement record; its "Proposed delivery order" is no longer the
  plan.
- **Closed by deletion**: the 2026-08-18 duplicate-mobject bug entry.
  Its suspect, the display-only reverse morph, was deleted on
  2026-08-23, and the headless ghost regression that drives the same
  back-and-forward path passes. If it is seen again it is a new bug.
- **No longer planned**: promoting the installed-app measurement
  scratch harnesses (the files are not in the repo and the throttle
  they measured is fixed), checkpoint byte accounting on the current
  engine, `.py` double-click and the PWA install confirmation, process
  controls and multi-scene tabs on the landing page, splitting the
  fragile static-asset pins into their own file.
- **Kept, compactly**: the small fidelity gaps (cross-group z_index, 3D
  gradient fills, re-triangulation, MathTex join drift,
  `AddTextWordByWord`), the 2026-08-18 test debt (verified still
  untested), and two design questions that are not scheduled: cell
  markers (the one item that fixes whole-unit stepping and the blank
  opening frame) and the Typst text backend. Dropped from that list
  the same day, on Taylor's call: the function-rebinding redesign
  (the instruction stream removes copy-on-execute, so it lands
  there), the student-bundle notes track (authoring cost; re-add when
  a course page needs it), and the baked geometry player's restyle
  and site demo (no user; the mp4 bundle is the distribution format).
  The preamble split is not listed separately because it is the
  half-measure of cell markers, and 2x supersampling is one clause of
  the held wgpu-py render step.

Native GL removal (beeline step 4) is explicitly **held** by Taylor as
of the same day: it stays the next structural step and the
instruction-stream plan's prerequisite, but it waits for the dogfood
pause to produce confidence.

## Checkpoints are a ledger (2026-09-05)

The stall at every play boundary — TODO "Now" item 1, the thing dogfood
kept reporting — was the checkpoint copy, and on a real course episode
it was an order of magnitude worse than the August audit had measured
on the benchmark scene: 192 ms at the median and 2.9 s at worst for
the save after each play on EpisodeA3, plus the same again for the
thaw before each unit. Three measurements decided the shape of the
fix, all recorded in `docs/checkpoint_ledger_plan.md`:

- `copy.deepcopy` costs about 27 µs per mobject and nothing per byte
  (a 13 MB circle in 0.4 ms, a thousand squares in 27 ms). The cost is
  the traversal, so the only fix is to not visit unchanged mobjects.
- The namespace keeps every mobject ever made — 31 to 122 variables
  over the episode, all off screen by the end — and every one was
  copied at every play. Two thirds of the objects visited were the
  svgelements path caches every Tex glyph keeps from construction.
- Every unit paid twice: the thaw before exec, the save after.

What shipped, in order of payoff:

1. **Glyphs share their parsed svg path across copies**
   (`Mobject.__deepcopy__` with a per-class `_copy_by_reference`;
   `VMobjectFromSVGPath` names `path_obj`). Four-fold on its own.
2. **The ledger.** `Mobject.revision` is bumped by every mutation a
   checkpoint must see: the existing `note_changed_data` and
   `note_changed_family` choke points (both recurse up the parents,
   so a child change bumps every ancestor) and a new
   `note_changed_state` for uniforms, updaters, locks, targets, the
   `z_index` setter, tracker values, camera orientation. A save
   pre-seeds the deep copy's memo so a mobject whose revision is
   unchanged — and whose submobjects and referenced mobjects
   (`target`, `saved_state`, a `SurroundingRectangle.mobject`, any
   attribute holding one) are unchanged too — hands back the frozen
   copy it got last time. A mobject with updaters is never shared:
   its closures hold mobjects the walk cannot see. The per-play cost
   becomes what moved; history holds objects + changes instead of
   objects × checkpoints.
3. **Frozen graphs carry no parent links and read-only arrays.**
   Parent links would reach every dead group that ever held a
   mobject (the course's `VGroup(*scene.mobjects)` stage grabs), and a
   copy shared between checkpoints could not point at each one's
   parent. A thaw rebuilds the links from the submobject side. The
   read-only flag turns "someone mutated history" into an immediate
   error; the two paths that used to put a stored checkpoint's state
   on screen directly (edit re-anchor, exec-error rollback) go through
   a thaw now.
4. **No thaw at the frontier.** After a save, the live scene and
   namespace are exactly what the checkpoint was frozen from, and the
   checkpoint holds its own copies; the next unit runs against the
   live graph. Any restore clears that, so navigation still thaws.

Why the August revision store failed and this does not: it tried to
*detect* change after the fact (partial hooks, blake2b hashes of the
arrays, derived columns excluded by name) and every miss was silent.
Here the signal is an integer per mobject at the sites that already
mark data as changed, derived columns never pass those sites so they
cannot false-positive, and a miss is loud: `MANIML_VERIFY_LEDGER=1`
compares every reuse against the live object and raises naming the
attribute. The whole suite runs clean under it, and its first run on
the real episode caught one real miss — a `Table` keeps `mob_table`, a
list of lists of its entries, and the reference walk only looked one
container deep, so an entry that changed after leaving the table's
family would have left a stale table in history; the walk now follows
nested containers. Two writes it cannot see are recorded as such: a plain attribute reassigned to a different
mobject (an added or removed attribute is caught by an attribute
count on the entry), and a numpy view taken before a freeze — the
optional live-array freeze in the plan's Phase 4 would close the
second if dogfood ever finds it.

Measured on the same EpisodeA3 render, checkpoint copy per play:

| Run | Save p50 | Save max | Thaw p50 | Copy time over the episode |
| --- | ---: | ---: | ---: | ---: |
| Before | 192 ms | 2,898 ms | 188 ms | 64.5 s |
| Shared svg path | 46 ms | 1,010 ms | 48 ms | 18.6 s |
| + the ledger | 9 ms | 135 ms | 80 ms | 12.5 s |
| + no thaw at the frontier | 10 ms | 111 ms | skipped (92 of 93 units) | 1.3 s |

The thaw got slower under the ledger alone (each thaw enters a whole
new live generation in the ledger) and then vanished from forward
stepping. What is left is the save at 10 ms median, which is the
mobjects that actually moved in each play, and one thaw per
navigation.

Explicitly not done, on purpose: copy-on-write on the live objects
(the instruction-stream architecture makes checkpoints free by
construction), and reuse on thaw for backward navigation (the same
trick reversed; queued in the plan as Phase 2b's remainder).

## Curve redraw batches array work (2026-09-09)

The dogfood PPF's two-curve `always_redraw` updater spent its time
constructing curves and converting coordinates. Bulk corner construction
and direct point-array growth brought CPU redraw from about 47 ms to
20 ms. Batching coordinate conversion brings it to about 5 ms. These are
local medians from `python -m benchmarks.curve_redraw --samples 20`, which
compares all three implementations; they exclude transport and rendering.

`Axes.plot` / `get_graph` still call the equation once per scalar sample,
in the same order. Each sample records the current axis endpoints and
ranges, then NumPy converts the samples together before the existing
corner construction and smoothing. Those local snapshots preserve even
callbacks that directly edit the axes' point arrays. Custom mappings and
numeric types that need their original precision use scalar conversion.

This is an internal sampling optimization, with no scene-code changes or
persistent transform cache. `always_redraw` and `become` keep their existing
behavior. Vectorizing the user's equation is a separate capability; it is
not required for the engine to batch its own coordinate arithmetic.

## Right replays visited animations (2026-09-09)

The August 26 navigation stabilization made RIGHT restore an already
visited endpoint instantly. Taylor wants playback on RIGHT; UP/DOWN are
the instant per-checkpoint controls, and LEFT keeps its instant jump to
the previous pausepoint.

Retained playback re-executes source on a temporary live graph and restores
the exact saved destination afterward. It preserves all checkpoint objects
and the execution frontier. From inside a loop or helper, execution starts
at the source unit's entry, reconstructs the prefix without rendering,
pacing or sound, then visibly plays the requested span. The prefix uses
normal simulation timesteps: animation skipping would change updater and
random-number behavior. A checkpoint boundary stops execution even inside
a loop; replay errors restore the starting checkpoint and clear the
temporary playback flags.

## 2026-09-09: Bound winding-fill work to its screen footprint

B0's 211 touching raster squares become 135 batches to preserve fill/stroke
ordering. Processing full-frame winding textures for every batch measured
about 48 ms per frame on M3. Preserve those batches and their appearance;
send conservative screen rectangles and render their fills into pooled small
textures, then composite only the occupied region. Camera-only changes update
rectangles even when geometry is cached. Uncertain bounds retain full-frame
rendering; offscreen/transparent fills skip their fill passes.

Projection runs on batches of NumPy arrays without persistent caches or scene
API changes. Shader clipping preserves the original 2x sample grid, lighting,
and stroke sizing. Textures are reused and unused buckets released only after
submission/completion. Browser commands and the native mirror share the same
192-byte uniform layout and WGSL.

The original wordmark is pixel-identical and measures 48.2→23.4 ms (2.06x)
for submission through completion. This is an isolated renderer measurement,
not full viewer timing; command preparation and remaining per-batch overhead
are still material. Large single-batch output remains about 1.4–1.5 ms.
The plan and experiment history are in `docs/bounded_fill_plan.md`.

## The field reports, second pass: updaters, the camera frame, TracedPath (2026-09-11)

Taylor's direction, quoted: "get started from the top of the list with
things you can do. i'll start dogfooding tomorrow." The list was the
2026-09-11 assessment: reproduce the open field-report items on the current
build, take the CE-compat warts every episode works around, then the read
instrumentation. Everything here was reproduced headlessly first; the live
dogfood pass is Taylor's.

**Two symptoms had one cause.** The 2026-09-09 report's "mobjects faded in
by one play appear at different times" and the A2/A3 report's `Transform`
crash ("could not broadcast input array from shape (31,3) into shape
(123,3)") both came from updaters running on the mobject being animated.
maniml inherited ManimGL's `Animation` default of
`suspend_mobject_updating=False`; CE's default is `True`. With an
`always_redraw` on screen, the scene loop rebuilt it at full opacity after
every interpolation step, so a `FadeIn` snapped in (EpisodeB0 fades a still
copy to work around exactly this), and a rebuild whose point count differed
from the aligned endpoints broke `Mobject.interpolate`. Now the animated
mobject's own updaters pause for the play and resume at finish, as in CE,
`Rotating` included; the CE classes that read their updaters each frame
(`ShowIncreasingSubsets`, `MoveAlongPath`, `PhaseFlow`, `UpdateFromFunc`)
keep their explicit `False`. The endpoint copies still carry the
`always_redraw` closure and rebuild the original from
`Animation.update_mobjects`, exactly as CE does; CE survives that because its
interpolate replaces the point array, so ours now resizes to the endpoints'
length before writing.

**The camera frame is not one of the scene's mobjects.** ManimGL seeded
`scene.mobjects` with the frame; CE keeps the camera out of the list. Two
costs in production: every episode's "grab the stage" helper,
`VGroup(*scene.mobjects)`, raised on the bare `Mobject`, so A2, A3 and B0
each carry a `drop_frame()` workaround; and a thaw left a frozen copy of the
frame in the list beside the camera's real one, so a later `frame.animate`
added a second identity. The list now starts empty, the scene loop updates
the frame explicitly, `should_update_mobjects` counts its updaters (the
viewer's idle-streaming test uses that), and `begin_animations` never adds a
`CameraFrame`. Checkpoints already saved and restored the frame's points
separately. The `drop_frame()` helpers are now no-ops and can go.

**`TracedPath` and `AnimatedBoundary`** are ported from CE's
`animation.changing` (report item 3); a curve is two points on the quadratic
path, so a dissipating path trims two. Both join the conformance baseline.

**Verified and not changed.** The play-path draw order (report item 1) no
longer reproduces: a `z_index=15` dot in a `VGroup` with dashed lines draws
last whether the group arrives by `add`, by `play(FadeIn(group))`, or by
separate fade-ins; the 2026-09-02 family order covers it. Item 7 (`--render`
wrote no checkpoint PNGs) is by design since the stills became their own
`--export-checkpoints` export.

## Point reads are counted by kind and phase (2026-09-11)

TODO.md "Now", item 3, the instruction-stream plan's stated prerequisite:
which Python reads of source points would need synchronization if the points
lived on the GPU. Under `MANIML_PERF_PATH` every read is counted as `raw`
(`get_points`, the interpolation of two endpoints: the whole array comes
back) or `reduce` (bounding box, centre, endpoint, tracker value: a small
value), tagged `play` (between `pre_play` and `post_play`), `updater`
(inside `Mobject.update`) or `idle` (everything else, the exec of a unit
between plays included), with the calling site recorded so the report can
name what dominates. Nothing is paid unless profiling is on; `has_points`
and `get_num_points` read the array length, not the points, and no longer go
through `get_points`. `benchmarks/read_report.py` tabulates profiles; the
course episodes' tables are in `docs/read_instrumentation_2026-09-11.md`.

What the tables say: scene code reads points only through reductions and
the coordinate system, never as a raw array; the raw reads inside a play are
the engine's own (interpolation, alignment, the renderer), which Phase 1's
programs replace; the graph sampler's per-sample read of both axes'
endpoints is deliberate (a callback may write into the axis arrays
mid-sample, which bypasses the revision counter) and is a call count, not a
byte cost.

## A step back copies what changed (2026-09-11)

Taylor's direction, quoted: "go ahead with reuse on thaw." The ledger
(2026-09-05) made a save cost what moved; a navigation still deep-copied
the whole checkpoint before showing it (`checkpoint.restore_copy`, 59 ms at
the median and 147 ms at worst on EpisodeA3 stepping back four times), and
the RIGHT press after a step back paid the same again before exec.

Now a thaw runs the ledger's rule in reverse. The ledger keeps, for each
frozen copy, the live mobject it currently stands for. When checkpoint *C*
is thawed, a live mobject whose entry points at the very frozen object in
*C*, which is shareable (no updaters) and unchanged since (revision and
attribute count), is handed back through the deep copy's memo instead of
being copied, and so is everything it reaches, on the same all-or-nothing
closure rule the freeze uses. A reused object keeps its parent links only
where the parent is part of the thawed graph: a parent that the checkpoint
replaced with a fresh copy, or that did not exist yet, is dropped, and the
fresh copy links itself on the way in as thaws always did. Fresh copies are
entered in the ledger as before. Under `MANIML_VERIFY_LEDGER=1` every reuse
compares the live object with its frozen copy and raises `LedgerStale`
naming the attribute, so a bypassing write that would otherwise let a
stale live object stand in for history is a loud failure on the
navigation, not a silent one.

On EpisodeA3 (8 RIGHT, 4 DOWN, 4 RIGHT through the live harness):
`restore_copy` 58.9 to 8.5 ms at the median and 146.6 to 22.8 ms at worst;
`execution_copy` 36.2 to 7.0 ms; 8,903 mobjects reused against 344 copied;
saves unchanged. The plan's 2 ms exit is not met: what remains is the deep
copy of the changed subgraph and the closure walks over ten thousand
objects. Archive: `benchmarks/results/thaw_reuse_20260911/`.

## The zero-border AA gate is accepted as it stands (2026-09-11)

Taylor's direction, quoted: "ok AA is close enough. lets call that
finished." The Phase A acceptance kept one old-sampler exception open:
zoomed text with a zero fill border has 0.8829% of pixels over the 24/255
RGB threshold against native GL, above the old 0.5% limit. The evidence the
acceptance rests on is the 16× same-mesh coverage reference and the exact
triangle-area checks, both of which favour Phase A's 4× MSAA plus 2× resolve
over the GL image: the miss is the old reference's own edge, not a worse
edge. No threshold was widened and the quality harness still reports the
metric; Phase B's B1 measures it again because patch edges are new
geometry. Large non-affine paint stays open, unscheduled, and is not a
Phase B prerequisite: it is a paint-semantics question that no course scene
has raised.
