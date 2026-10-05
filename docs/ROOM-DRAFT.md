# The room draft

Two more steps toward one system with Knuth and Plass, on the branch
`ux/room` (2026-10-04, the `maniml-perf` worktree). Taylor: "right now
there's the frame for the app, then an inner region, then inside that is
the manim video. instead i'd like the video to take up that entire inner
region, beveling the corner radius to match knuth and plass, and then
eventually think about how to make the nav bar on the bottom match the
scroll bar for knuth and plass. i think that second one is a little less
important and i'm not even sure it'll work."

And, while this was being drafted: "the window should be forced into
the shape that makes the scene canvas the right dimensions to match
what's in manim. so if i make the app wider, it adjusts the height to
match, so that a 2 by 1 animation is always positioned correctly in the
app and shows exactly the full animation."

The first is built on the branch and measured below; the third is
built on both sides (the page here, the shell on claerbout's
`ux/shape`) and run in a window, short of a drag by hand. The second is two mockups and
a reading, not a build: it changes what the presenter's bar *is*, and
that is Taylor's call.

## 1. The room is the picture

Since the Zen draft (`docs/ZEN-DRAFT.md`) the viewer had three nested
things: the frame (#18181a), the room (a 12 px rounded panel in #2b2a2d)
and, inside it, the canvas (5 px corners, a shadow, 22 px in and 78 px
clear of the presenter's bar). Knuth and Plass have two: the frame and
the room, and the room holds the document. ManimLive's document is the
scene's picture, so now the room *is* the picture.

**What moved** (`maniml/web/static/viewer.html`):

- **The opening** (`#stage-area`, new): the part of the frame a room may
  fill — under the bar, the 8 px edge in from the window's left and
  right, and above the presenter's bar's band on the frame's foot.
- **The room** (`#stage`) is the largest box of the picture's shape in
  the opening, centred in it, 12 px corners, the white 5 % rim, black
  before the first frame. Its shape is `--aspect`, 16:9 by default; the
  page writes it from what is drawn (`fitStage`: the canvas as the
  driver sizes it from the engine's resolution, the recording's
  `videoWidth × videoHeight` while one plays), so a scene whose config
  says 4:3 gets a 4:3 room. The fit is CSS alone — container units on
  the opening, `width: min(100cqw, calc(100cqh * var(--aspect)))` with
  `aspect-ratio` — so a resize runs no script.
- **The canvas and the recording fill the room** (`#view`,
  `#playback-video`: `width: 100%; height: 100%`). The 5 px corners, the
  shadow and the rim they carried are gone; the room's are theirs.
- **The presenter's bar stands on the frame's foot** instead of floating
  over the scene: unchanged in markup and script, 12 px above the
  frame's edge as it was, and the opening stops 12 px above its pods
  (the band: 12 + the pods + 12 + the 8 px edge; 74 px with the 42 px
  pods this was first measured with, 60 with the 28 px pods of
  section 4). The scene no longer needs 78 px of padding to keep clear
  of it.
- **The console** was first a column of the opening at its right, the
  room giving up its width; since Taylor's last round (2026-10-05) it is
  a card of glass over the picture, 12 px inside the room's top and
  right edges and clear of the presenter's bar, sliding in from the
  right when opened and out when closed, the same in every mode:
  nothing reflows, and the window keeps its shape (section 7).
- **Full screen**: the opening is the display, black beyond the picture
  as a projector's is (the frame's grey would show as bars on a
  16:10 display), the room's corners square, the chrome floating over
  the picture as before.

The room's grey (`--bg`, #2b2a2d) is no longer seen in the viewer; the
landing page keeps it. The scene's own background is what fills the
room now, so with maniml's default (a dark grey near the frame's) the
room reads by its rim and its corners, and a scene with a white
background is a white panel in the frame, as a Plass paper is.

**Measured** (Chromium page captures at 2×, a tab's layout — no lights,
the File tile 8 px in; `docs/room-1100.png`, `docs/room-1500.png`, the
dogfood scene after two steps; the band of section 4, 60 px):

| | 1100 × 800 | 1500 × 900 |
|---|---|---|
| the opening | (8, 44) 1084 × 696 | (8, 44) 1484 × 796 |
| the room | (8, 87) 1084 × 610 — width-bound, 43 px of frame above and below | (42, 44) 1415 × 796 — height-bound, 42 px of frame either side |
| the presenter's bar | 28 tall at y 752, 20 px up | 28 tall at y 852 |
| with the console (C), at the first measure | — | the room 1132 wide; the console (1152, 44) 340 wide, to the band — since section 7 the room is unchanged and the card lies over it |

(With the 42 px pods this was first built with, the opening was 18 px
shorter: 1084 × 682 and 1484 × 782, the rooms (8, 80) 1084 × 610 and
(55, 44) 1390 × 782.)

Before, at 1100 × 800 the canvas was 1040 × 585 at (30, 97.5) inside a
1084 × 748 room; the picture is 4 % wider now and the frame is what
surrounds it. At 640 × 400, the minimum, the room is 501 × 282 at
(69, 44).

**Checks**: `tests.test_static_assets` (`test_the_room_is_the_picture`
replaces `test_the_stage_is_the_room`) and `tests.test_shell_config`,
47 tests, pass on the branch. In the browser pane on the running scene:
the numbers above at three sizes, the console open and closed, the
scene stepped and its picture filling the room to the corners.

**Not checked live**: full screen (the pane refuses
`requestFullscreen`; the rules are a straight translation of the old
ones and are pinned by the tests), and Present's recorded playback (no
recording was rendered; the video's rule is the canvas's). The 2×
records should be retaken in the app with Playwright's `_electron`, as
the Zen draft's were, once the branch is on main.

**The alternative not taken.** Keep Knuth's box exactly — the room
filling the opening — and letterbox the picture inside it on black. It
keeps the three apps' rooms the same box, but the picture's corners are
square where they meet the bars, a scene with a non-black background
shows its bars, and the presenter's bar is back over the room's foot.
Taylor's words were that the video is the inner region, so the room
takes the picture's shape and the frame takes up the difference, as a
mount does.

**Open**:

1. **Where the slack goes** — in a tab, or a maximized or full-screen
   window, the only places the window is not held to the picture's
   shape (section 3): there the room is centred in the opening, 36 px
   of frame above and below at 1100 × 800. It could instead sit at the
   bar (Knuth's room starts there) with the slack under it. In the app
   the window's shape leaves no slack, so this is a tab's question.
2. **The 1 px rim** (`box-shadow: 0 0 0 1px rgba(255,255,255,.05)`) is
   now the only thing between a dark scene and the frame. It is Zen's,
   so it stays; a shade of it is worth a look on a real display.
3. **The Zen draft's measured table** gives the canvas's old box
   (1040 × 585 at (30, 97.5)); this document's supersedes it.

## 2. The presenter's bar in the scroll rail's shape

Plass's scroll rail (its `src/scroll-rail.ts`; Knuth took the same rail
on 2026-10-02) is the whole paper top to bottom in a 20 px gutter of the
frame at the window's right, outside the room: marks placed by their
fraction of the paper's length (hairlines at page breaks, dots sized by
heading level, squares for figures and tables, the caret's blue bar), a
faint rounded band for the visible span that brightens while the paper
moves, a dark-glass label for the mark under the pointer, the nearest
mark within 7 px taking the gutter's whole width, arrows between marks,
drag to travel.

Everything on it has a counterpart in the rail ManimLive has today:

| Plass's rail | the presenter's rail |
|---|---|
| the paper's length | the scene's length in seconds (each checkpoint's `run_time`, which the state does not yet carry) |
| a heading's dot | a pausepoint's dot (5 px); the start the 7 px title dot; an interior play of a pause-anchored file a 3 px dot |
| a figure's square | a unit whose count is not knowable until it runs — the rail's stacked chip — as a stack of three |
| the caret, the one coloured mark | the current pausepoint, the accent dot with its soft ring |
| marks outside the band a step quieter | past marks brighter, future ones hollow |
| the band: the visible span | the band: the stretch you are on, from the current pausepoint to the next — what RIGHT plays. At rest it says where you are; while a move crosses it, it lights in the accent, as the rail's link lights today |
| the hover label: section, heading, page | the pausepoint's number and its source line, and the stretch's seconds to the next |
| a click jumps, a drag travels | a click is the chip's click; a drag is not offered (a scene has no scroll position between pausepoints — UP/DOWN are the fine steps) |

What has no counterpart is the transport: Start, Back, the position,
Next, Present and Full screen live in the pods today, and a 20 px gutter
has no room for tiles. Knuth keeps its run tools in its rail beside the
document; ManimLive has no side rail, so in both mockups they go up to
the bar as its tiles — Start, Back, the position as the bar's quiet
text, Next, after Stills; Present and Full screen at the right end
before the renderer's pill. Every key is as it is; the arrows never
touched the pods.

Two mockups, self-contained as Plass's design round's were
(`docs/mockups/scroll-rail.md`): open them in a browser, hover the
rail, click a mark, use the arrows. Captures at 1100 × 760, at rest,
with a mark hovered, and a step in:

- **The foot gutter** (`docs/mockups/nav-rail-foot.html`,
  `nav-rail-foot-{rest,hover,moving}.png`): the frame's bottom edge
  widens from 8 to 20 px and the rail lives in it, under the room, the
  scene's time running left to right as the rail's chips do today and as
  every scrubber does. The track is exactly the room's width, so the
  scene's start is level with the picture's left edge and its end with
  the right. The label stands above the gutter over the picture's foot.
- **The right gutter** (`docs/mockups/nav-rail-gutter.html`,
  `nav-rail-gutter-*.png`): exactly where Plass's and Knuth's is, the
  frame's right edge widened to 20 px, time running top to bottom, the
  track the room's height, the label hanging to the rail's left as
  Plass's hangs over the paper's margin.

**A reading.** The foot gutter is the one to build, if either is. It
keeps the three apps' *frames* the same system (a 20 px gutter of the
frame beside the room, Plass's values, Plass's marks) while keeping what
is true of a scene: it runs left to right, and the rail has always said
so. The 12 px it takes from the opening's height cost nothing in a
width-bound window (at 1100 × 800 the room has 72 px of slack there),
where the right gutter's 12 px of width come straight off the picture.
Its band is honest in a way the right gutter's cannot be: a vertical
band in a scroll rail's place says "this much of the document is on
screen", and a scene has no such thing. And it is where the presenter's
bar is now, so the eye that looks down for the rail still finds it.

What it costs, and Taylor's doubt: the pods are 42 px of glass with
11 px chips and 32 px buttons; the gutter is 20 px of frame with 5 px
dots. The rail's hit test (the nearest mark across the gutter's width)
makes the dots easy to hit, but at a lectern the rail is read, not
clicked — the keys and a clicker do the moving — and a 5 px dot at the
back of a room is a dot. The pods also sleep (contents at 40 % until
the pointer nears), which the rail does without: its marks are there at
rest, at Plass's awake values, as both of Plass's judges asked. In full
screen the rail would recede with the chrome as the pods do.

**What the build would be**, for the foot gutter:

- The state carries each checkpoint's `run_time` (`viewer.py`'s state
  payload; the checkpoints already hold it), so marks place by seconds;
  a unit not yet run has no seconds, so the future marks are laid at an
  even stride after the last known one, as the rail's dashed future links
  are today, and settle as it runs.
- `rail.js` keeps its author (the presenter's three methods,
  `stateChanged` / `moveStarted` / `moveEnded`, which the live engine
  and the recorded video both feed) and changes what it draws: marks
  by `--f` instead of chips in a flex row, the band in place of the lit
  link, `.in`-style class writes only on what changed. `tests/rail_sim.mjs`
  replays the same message sequences against the new classes.
- `viewer.html` loses the pods and gains the transport tiles in the
  bar, the gutter (`--edge-bottom: 20px` while a scene is open; the
  landing page keeps 8), the label; `shell.css`'s pod rules stay for
  nothing and go.
- The track is the room's box, not the opening's: a ResizeObserver on
  `#stage` writes the rail's left and right (the mockup reads it on
  resize), since the room does not always fill the opening (above).
- `tests/test_static_assets.py` pins the new shape; the shell's smoke
  reads only `#file-name` and is untouched.

**What to decide**: whether the presenter's bar should be a rail at
all (the pods are Plass's old toolbar, and Plass itself has since moved
to the frame), and if so which gutter. The build is a day's work on the
page and the rail; the engine's part is one field.

## 3. The window takes the picture's shape

A paper and a notebook have no shape of their own; a scene's picture
does, and Taylor wants the window to keep it: drag it wider and it
grows taller to match, so the room is always exactly the picture and a
2:1 scene shows whole, positioned as in manim. That is the window's to
do, so it is a shell feature with a page that asks for it:

- **The shell** (claerbout `ux/shape`, in `main.js` beside `zoomTo`, and
  the README's request list): a `shape {ratio, extra: {width, height}}`
  request. `ratio` is the room's, `extra` the chrome round the opening
  the ratio must not include, in the page's px. The shell holds the
  window's content to the ratio less the extra (Electron's
  `setAspectRatio(ratio, extraSize)`: macOS keeps a content aspect
  natively, so a drag of the width sets the height), scales the extra
  by the zoom (the page's px are zoomed px) and again when the zoom
  changes, and resizes the window at once to meet the shape — the width
  kept, or the height where the width's height would run past the
  display's work area — nudged back onto the display, so the room fills
  from this moment and not from the next drag. A maximized or
  full-screen window is left alone (the shape holds for its return), and
  a shape the window's minimum could not meet is kept but not fitted.
  `{ratio: null}` lifts it. Since 0.2.7; an older shell answers null.
- **The page** (`bar.js` `setShape`, both pages): the ratio and the
  chrome *measured* — the window less the opening's box — rather than
  declared, so the bar's height (the lights' band in the app, 44 in a
  tab), the edges, the presenter's band (74; 54 under 620 px) and an
  open console (352 more) are whatever the page is laying out; told once
  per change. The viewer tells it when the picture's shape is known
  (`fitStage`, from the first frame; the recording's while one plays),
  when the console opens or closes, and on leaving full screen (the
  console may have moved while the display was ours); the landing page
  lifts it beside telling the shell it holds no document. At 1100 × 800
  the viewer measures 16 × 118, and 368 × 118 with the console open
  (checked in the browser pane). In a tab there is no shell and the CSS
  fit of section 1 does the same job inside whatever window there is.

With the shape held, section 1's room fills the opening exactly in the
app: no slack above or below, the presenter's bar 12 px under the
picture, the frame 8 px either side — Knuth's box, with the picture's
proportions. The CSS fit stays as the ground truth under it: it is what
draws the room correctly while the window is still being resized to
meet the shape, in full screen, maximized, and in a tab.

**Run** (Playwright's `_electron` on the `ux/shape` shell with this
checkout as its unpackaged app, the installed app's engine venv, the
dogfood scene opened from the command line; `docs/room-app-900.png`,
the window as the shell remembered it, 900 wide):

| | the window's content | the opening | the room |
|---|---|---|---|
| after the first frame | 900 × 615 (fitted from 900 × 700) | (8, 44) 884 × 497 | the same box |
| console open (C) | 1252 × 615 | (8, 44) 884 × 497 | the same box |
| console closed | 900 × 615 | (8, 44) 884 × 497 | the same box |
| after `setContentSize(900, 700)` from the main process | 900 × 700 | (8, 44) 884 × 582 | (8, 86) 884 × 497, centred by the CSS fit |

So the room is exactly the opening once the shape is held, the console
widens the window by its column and leaves the picture as it was (the
first draft kept the width and squeezed the room to 912 × 513; the rule
is now: the same ratio with a changed chrome keeps the room, a new ratio
keeps the width), and a size the shape does not hold (a programmatic
resize, which macOS's aspect lock does not constrain) still draws the
room right by the CSS fit. **Checked by hand by Taylor**: a drag of the
window's edge kept the ratio but jumped smaller at the grab and left
the pointer outside the window. The cause is in Electron: on macOS
`setAspectRatio(ratio, extra)` sets AppKit's content aspect ratio to the
plain ratio (extra and all) beside its own delegate's rule (the ratio
less the extra), and the two fight. The shell now holds the shape with
its own `will-resize` rule (`shapeResize`): the dimension the pointer
moves is taken as given, the other follows it, and the edges not being
dragged stay put; `setAspectRatio` is not called at all. Playwright
cannot drag a window's frame, so this too is Taylor's to try (the dev
shell has to be started again to pick it up). That is the one thing to try in the dev
shell (`CLAERBOUT_APP=app/maniml.json electron ~/Projects/claerbout` on
this checkout, with the `ux/shape` checkout in place of the pinned
tarball).

## 4. The chrome, thinned

Taylor, on the record of section 3 (2026-10-04): six changes, the
window's basic setup kept. Built on the branch:

1. **The bar's left end.** Measured in the dev shell: the lights' room
   is 88 px (`navigator.windowControlsOverlay`), the File tile at
   (100, 6), the name pill at 138 — Knuth's and Plass's numbers to the
   pixel (their Zen drafts' tables; the padding formula is theirs). So
   nothing was moved: what differs from Knuth is the rail column under
   its lights, which ManimLive has none of, and the record that prompted
   this is a page capture without the lights drawn. Open: what Taylor
   sees as not left-aligned — the File tile could come right after the
   lights (x 72) in all three apps, or over the room's edge where there
   are no lights, as in a tab.
2. **The renderer's pill** (`#renderer-pod`) is unseen until the pointer
   finds it or it has a warning to show: `opacity: 0`, 1 on hover, on
   focus and with `#glwarn.on`. Still in the layout, so the right end's
   width is as it was.
3. **The engine's status is the mark beside the name**: Knuth's and
   Plass's 6 px save dot (`.doc-mark`, shell.css), green while the
   engine answers (`rgba(110,165,118,.9)`), red while it does not
   (`rgba(205,100,82,.95)` under `body.disconnected`), in the separator's
   place between the file's name and the scene's; its words (Connected,
   Reconnecting, Engine unavailable) in its title and behind it for a
   reader without a screen (`setConnection`). The status pill at the
   right end is gone; the landing page keeps its own.
4. **The console's toggle shows the scene's error**: the engine's state
   carries `unit_error` (`checkpoints.describe_scene_error`: the error's
   name and message and the scene's line, set when a unit raises in
   `run_next_animation`, cleared when one runs clean) beside
   `load_error`; while either stands the toggle has a red dot at its
   centre (`body.scene-error #console-toggle::after`, the glyph stepped
   back) and the error in its title, and the console opens itself once
   when a new error arrives — never in present mode, recorded playback
   or full screen, where the dot alone says. Checked in the pane on a
   scene whose second unit raises NameError: the dot, the title
   "NameError: name 'undefined_name' is not defined (line 8)", the
   console open on the traceback; the file mended, the watcher's replay
   ran clean and the dot went.
5. **The presenter's bar, thin**: first 24 px pods (Plass's old 42
   halved), then, Taylor finding the glyphs too small, 28 px: 24 px
   buttons with 16 px glyphs, the run's ends 14 px stadiums. The bar's
   own tiles keep their 32 px. The band under the room is 60 px (12,
   the pods, 12, the edge), and the opening and the console stop 52 px
   above the frame's edge. The rail is the pod's inner 26 px with 8 px
   of padding either side, so the end chips' glow is drawn whole — the
   cut in the record was the scroller clipping at its 2 px padding.
   The rail itself is redrawn in section 5.
6. **Full screen shows the presenter's bar and the console's toggle,
   never the bar across the top** (`body.fullscreen #toolbar { display:
   none }`): the toggle always, at (display − 44, 12); the presenter's
   bar floating over the picture's foot, receding when the pointer
   settles and back when it nears an edge; the console, opened, stays
   (it no longer recedes with the bar; `top: 56px; right: 12px; bottom:
   48px`). F, Escape and the bar's Full screen button leave. Measured in
   the dev shell on a 1470 × 923 display: the bar `display: none`, the
   toggle at (1426, 12), the presenter's bar at y 887 and then hidden
   once the pointer settled, the picture 1470 × 827 at y 48 on black.

**The shell, with it**: leaving full screen had the window come back at
its minimum (900 × 597 out, 640 × 451 back): AppKit applied the aspect
lock to the sizes of the leaving transition. The lock is now lifted on
`enter-full-screen` and put back with a fit on `leave-full-screen`
(`shapeHooked` in claerbout's `main.js`); a window resized to 1000 × 700
by hand, taken into full screen and out, comes back fitted to its width.

**Records** (`docs/room-app-900.png`, the dev shell at the size it
remembered; `docs/room-app-fullscreen.png`; `docs/room-1100.png` and
`docs/room-1500.png` retaken in a tab).

## 5. The rail, as bars

Taylor, on section 4 (2026-10-04): the glyphs a little small; the rail
to take the whole length of the bottom but the nodes never too far
apart nor too close; it plain when there are more nodes than fit; bars
rather than dots, as Plass's and Knuth's scroll rails mark positions,
white for loaded and grey for not yet loaded; the dash shown large
through the current node and barely or not at all between the others.
Built, on the same `rail.js` (its chips, links and classes are as they
were: the page restyles them):

- **The bar is sized to its ticks** (Taylor's sixth pass, over "take
  the whole length": "we just shrink the rail to fit. no need to have
  all that extra space"): the three pods are one run centred on the
  frame's foot, the rail pod as wide as its ticks want (`flex: 0 1
  auto`) and giving way, folding, when the window is narrower; and the
  bar stands the frame's edge above the window's bottom with the room
  the edge above it — the same 8 px as the room's sides (12 in full
  screen, where there is no frame). The band is 44 px.
- **The nodes are 2 px ticks**, 12 px tall, 1 px of margin either side:
  white (`rgba(235,231,225,.82)`) where a checkpoint stands — past or
  ahead of the position after a jump back — grey
  (`rgba(150,145,153,.45)`) where the unit has not run; the current one
  the accent, 16 px, with a soft glow. A stack (a loop's chip) is a tick
  with two copies receding to the right, in its own colour.
- **The links are 1 px lines between every pair**, stopping 3 px short
  of the ticks at both ends as the dots' links did (Taylor's second and
  third passes: the first draft had them all but unseen, which "doesn't
  show clearly the connecting lines", and a line that touches its marks
  reads as one bar): white at 42 % where the stretch is loaded, 30 %
  between loaded ticks ahead of the position, grey where it is not yet
  run, and the same whatever the position is; the lit dash a move draws
  is unchanged (the accent fill grows along it).
- **The space is what the position changes**, in three stages (Taylor's
  words, 2026-10-04: "the size of the rail should continue to get larger
  to fit the number of nodes until there are too many at regular
  length. then the dashes beside all the non-current nodes should get
  smaller to fit, until there are too many to fit even the minimum dash
  length. then we go to the ... for some. the ... would be on both sides
  unless we can fit all the nodes between the current node and the
  first / last node on half of the rail, then the ... is only on one
  side"): the rail grows with its ticks at the regular 32 px link until
  the bar has no more room; then the links pack, as far as 2 px, each
  in proportion to its distance from the current chip (`--away`, written
  by the page, as the link's `flex-shrink`: 0 for the two beside the
  current chip, which never shrink, 1 for the next, and so on, so the
  lengths taper outward from the position instead of stepping — "progressively
  get smaller on either side of the current node"); and past that the
  middle folds (below), the window round the current tick as wide as
  half the rail each side, a side whose run to the start or the end fits
  in its half kept whole and its spare handed to the other; and the row
  fades toward a fold (`--edge`, the page's count of ticks to the gap on
  that side: the last eight before a gap go from full to 30 %, the
  brackets and the gap itself exempt — "nodes would sort of fade out ...
  as they get closer to the ..."). Measured on a seventy-four-play scene
  (77 chips): at 1100 px, with 889 px of room (976 wanted packed), one
  fold of 8 ticks on the far side of the current, the links from the
  current outward 32, 32, 18, 4, 2 ...; at 640 px two folds, 31 ticks
  before the window and 15 after, the links 32, 32, 9, 2 ..., the eight
  ticks before each gap at 0.88, 0.75, 0.63, 0.5, 0.38, 0.3, 0.3.
- **The brackets grow by height alone** under the pointer (Taylor:
  "grotesque growth of the top and bottom flanges"): a scaled bracket
  swelled its arms sideways; now the arms keep their 2 px and the
  bracket stands taller, by the same nearness.
- **The stack is a loop** (Taylor: "that stacking thing of nodes, where
  they sort of bunch up together ... why is that?"): the rail draws one
  chip per source statement, and a `for` loop of plays is one statement
  whose pausepoint count is not known until it runs — and which, drawn
  as its own ticks once it has, would add ticks to the rail and move
  every chip you were aiming at as you stepped through it. So it is one
  chip holding several pausepoints, drawn as a tick with two copies
  behind it, stepped through with the up and down keys; its title says
  so. The copies now stand 5 px apart (4 before) and a step dimmer, so
  it reads as several rather than a smudge. Whether a run loop should
  unfold into its real ticks instead is Taylor's call; the rule against
  it is the rail's oldest.
- **A move glides** (Taylor's ninth pass: "the nodes sort of jump into
  their new place after a move forward or back, making it hard to see
  which way the animation went"): the taper and the fold's window go
  with the position, so a move re-lays the row out; the links' shrink
  factor is a number and transitions (280 ms), the row laid out again
  each frame of it, so the ticks shift to their new places. A tick that
  folds or unfolds as the window moves still appears or goes at once.
- **A link is sized by width, not flex-basis** (Taylor's eighth pass,
  from the app: "the dash lengths are smaller on either side. there's
  plenty of room"): a rail pod sized to its content takes its width from
  the links' intrinsic size, and a shrinkable flex item with no content
  counts for nothing in that measure, so the pod came out narrow and
  squeezed exactly the links allowed to shrink, with the bar empty round
  it; `width: 32px; flex: 0 1 auto` is what the pod measures, and a
  four-tick rail has its three links at 32 again.
- **Centred, and no Start button**: the sequence sits in the middle of
  the track (`justify-content: safe center`, so a row that still
  overflows starts at the left where it can be reached), and the
  transport's Start button is hidden — the start bracket is always
  there to click, and Home still jumps (the button stays in the markup,
  hidden, as `rail.js` keeps its state).
- **The fold is the page's, and it must not see itself**: the first
  draft undid and redid the fold on each of its own mutation records and
  never settled (the pane hung); the observer is disconnected while the
  page writes, and whether to fold is computed (12 n + 52 px unfolded)
  rather than measured by unfolding first — against the room the bar
  leaves the rail (`railRoom`: the bar's width less the other pods, the
  gaps and the paddings), since a rail sized to its ticks says nothing
  of the room with its own width (a second draft folded 73 ticks to 5 on
  a 1100 px bar for that), and laid out again when the bar's width
  changes, never when the rail's own does.
- **A landed move finishes forward**: the lit fill still grows out of
  the chip the move left, but when the move lands it collapses into the
  chip it reached (the fill's resting transform origin is its far end;
  it was its near end, so the exit ran back to the node just left, which
  "throws off the intuition of what's going on"). A backward move
  (`back`, never sent today) would need the mirror.
- **The ticks answer the pointer and the position**: each grows as the
  pointer nears it, up to 2.5× as wide and half again as tall within
  36 px (`--near`, written by the page from the pointer's distance along
  the rail; a transform, so nothing moves), over a hit zone 10 px wide
  and taller than the tick (`::before`), so a 2 px mark is easy to find
  and to click. Ordinary ticks are 9 px (Taylor's fifth pass: "all the
  other nodes a little shorter"); the start, the end and the current one
  stand taller, 12, 12 and 16 (`--tall`), so the ends and the position
  read at a glance and the rest is texture. (A first draft had the
  ticks beside the current one taller too; those are other nodes, so
  they are 9 now.)
- **The pitch is clamped**: a link is `width: 32px; min-width: 2px`
  with 3 px of margin each side, so ticks stand 42 px apart at most and
  12 px apart at least, the links round the position excepted; the
  numbers are one each in the CSS to taste. Past that the rail scrolls, as before, with the
  current kept in view (`rail.js` scrolls it into view on every state),
  and the page fades the cut edges (`markRailEdges`: `.cut-left`,
  `.cut-right` from the rail's scroll position, read after a scroll, a
  resize and every redraw) so it is plain there are more; the position
  readout says how many.

**Measured in the pane** (1100 × 800, with the first 28 px link): the
dogfood scene's four ticks at x 163, 195, 227, 259 (a 32 px pitch,
44 now) on an 868 px rail, the bar 28 px
tall with 16 px glyphs; a scene of seventy plays, a loop and a tail (73
chips) fits the same rail at an 11.6 px pitch with no cut; at 700 px the
same scene overflows, the rail fades its right edge at the start and
both edges once the position is inside, and a click on the 46th tick
runs the scene there and brings it to the middle of the track.

## 6. The pause, a frame early

Taylor, presenting on the branch: "in present mode, the pause isn't
quite in the right spot. it seems to be just one frame ahead." It was.
The pausepoints table records each checkpoint's `time` as the scene's
clock at the checkpoint (`present_bundle.build_meta`), and the clock
advances by one step as each frame is written (`Scene.update_frame`
increments before `emit_frame`), so that time is the frame *after* the
checkpoint's last one; `presentation.js` seeked straight to it and
showed the next animation's first frame. The bundle's own test knew the
rule (`test_present_bundle` extracts ffmpeg's frame at `time − 0.5 /
fps` and compares it to the checkpoint still); the player did not
apply it. Now it does (`frameTime`): every seek, the scrub's target and
a loop's lap range go half a frame back, and the first checkpoint stays
at the movie's start. Pinned in Node (`tests/presentation_seek.cjs`,
`tests/test_presentation_seek.py`): checkpoints at 0, 1, 2 and 3 s of a
24 fps recording land on frames 0, 23, 47 and 71 — the last frame of
each play, where they landed on 24, 48 and 72 before. The table's
format is unchanged, so every recording already rendered is right
without a re-render. Checked by hand in the app by Taylor before the
fix; the fix itself is the Node pin, the pane's Present having left
playback on its own in this session for a reason not chased (it works
in the app).

## 8. A clean move

Taylor, 2026-10-05, on the glide: "the nodes sort of bounce around a
little bit ... reacting to the movement of the nodes around them and
getting reoriented after a first move." Two causes. The taper was
animated by transitioning each link's flex-shrink factor, and flex
solves the row as one: while one link's factor was mid-change its
neighbours' widths moved with it, so a link could set off one way and
come back. And the fold's window shifted by a tick at each end with
`display: none`, so a tick vanished or appeared at once while the rest
were still gliding. Now the page computes every link's width itself
(`packLinks`: 32 px while the row fits, else each giving way in
proportion to its distance from the current chip, the two beside it
never, down to 2 px, the clamped ones held and the rest sharing what is
left — flex's own arithmetic, done so that each width is its own number)
and the CSS transitions `width`, so each link moves straight from its
old width to its new one and nothing else moves it; a folded tick
collapses to zero width and margin by the same transition rather than
disappearing. Whether to fold is decided by the same arithmetic
(`packed`), no longer by measuring the row. Two more things moved the
row: `rail.js` rebuilt its DOM whenever a future chip became a known
one, so every move at the frontier was a jump however the CSS
transitioned (it updates in place now; `updateChip` rewrites everything
about a chip), and a folded loop stack kept its 11 px margin, which with
the room rounded up overran the rail by a few pixels, and the rail's
scroll of the current chip into view then nudged the row on every state
(the stack's margin is zeroed when folded, the room measured a pixel
short). And the room has a shadow behind it now, the canvas's old one.

## 7. Three last things before the push

Taylor, 2026-10-05, on the finished rail:

1. **No gap mark.** The row fades *out* toward a fold now — the eight
   ticks before a gap go from full to nothing and the last is gone
   (`opacity: clamp(0, calc((var(--edge, 99) - 1) / 8), 1)`) — so the
   dotted gap that stood for the folded run is no mark at all, a 10 px
   empty link with the count still in its title.
2. **Quieter ticks.** Loaded ticks at 55 % (from 82), unrun at 32 %
   (from 45), the brackets at 70 %, the links at 30 / 22 / 22 % (from
   42 / 30 / 32), the stack's copies in step; the current tick keeps the
   accent.
3. **The console is a card.** The same hovering card in every mode, as
   it was in full screen: 12 px inside the room's top and right edges
   and clear of the presenter's bar, sliding in from the right (a
   discrete `display` transition with `@starting-style`, Chromium 117+;
   the shell's Electron 44 is Chromium 132) and out again. The room
   keeps its box, so opening it no longer changes the opening's chrome
   and the window keeps its shape — the shell's "same ratio, new extra
   keeps the room" rule has nothing left to do, and stays for any chrome
   that might. The rule hiding the console under 860 px is gone with the
   column.
