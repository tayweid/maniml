# The Zen draft

ManimLive in Zen's shape, on the branch `ux/zen` (2026-10-02): the frame
Knuth and Plass have had on their mains since this afternoon (Knuth's
`docs/ZEN-DRAFT.md`, Plass's), with their numbers, so the three apps
read as one system. Taylor: "eventually id like maniml to have the same
kind of topbar as plass and knuth. basically everything will be nearly
the same. the only difference is i don't think there's any reason to add
a sidebar to maniml, just need to keep the nav rail at the bottom as is."

So: a dark grey frame (#18181a) — a 44 px bar across the top with the
traffic lights in it, one 8 px edge round the rest — holds the room, a
rounded 12 px panel in the grey the scene has always sat on (#2b2a2d).
No side rail: the room runs from the frame's left edge. The presenter's
bar at the bottom (`#navbar`: Start, Back, the position, Next, the rail,
Present, Full screen) is untouched in markup, script and look, and
floats over the room's foot as it floated over the window's.

The record is `docs/zen-1100.png` and `docs/zen-1500.png`: the shell
pinned in `node_modules/claerbout` (v0.2.1) on `app/maniml.json`, at
1100 × 800 and 1500 × 900, on a scene in `~/Projects/week-3` after two
steps. They are page captures (Playwright's `_electron`), so the traffic
lights, which the window draws over the page, are not in them: their room
is the empty 100 px left of the File tile. (Knuth's and Plass's records
have the same gap.) `~/Projects/week-3` was a real folder made for the
capture and removed after, not a link to a scratch folder as in Knuth's
record: the engine resolves a scene's path before it opens it
(`security.resolve_authorized_file`, the containment check), so through a
link the pill names the folder the link points to.

## What moved where

**The bar** (`#toolbar`, the window's title bar in ManimLive.app; a drag
region but for its controls), left to right, padded on the left by the
lights' room (`env(titlebar-area-x)`; 8 px in a tab or full screen, so
the File tile stands over the room's left edge — Knuth and Plass use 6,
which centres theirs over the rail ManimLive does not have):

- **File** (`#file-menu`) — the bar's 32 px tile with Knuth's folder
  glyph at 18 px. It was a hover flyout inside the name pod with one
  action; now it is Knuth's and Plass's click-to-open text menu
  (`#file-list`), dropped 10 px under the tile: **Open another scene…**
  (`#open-file`, the same handler: back to the landing page). Still two
  deliberate clicks to leave a scene, as the flyout was.
- **The name pill** (`#doc-pod`) — Knuth's and Plass's, 30 px: the scene
  file's name (`#file-name`, its text exactly the name, as the shell's
  smoke reads it) in 15 px STIX Two Text, then `·` and the scene in it
  (`#scene-name`, the picker as before, its menu `#scene-menu` now the
  bar's dark menu dropped under the pill), then the folder
  (`#doc-folder`): the scene file's, home as `~`, cut from its start when
  the pill is short, hidden under 760 px. There is no save dot: ManimLive
  never edits the file. The separator lost its rose colour, since a red
  dot beside the name is Knuth's and Plass's mark for unsaved changes.
- **Restart** (`#restart-scene`), **Download** and **Stills**
  (`#export-video`, `#export-checkpoints`), the bar's tiles, awake (the
  old bar's sleep-until-hover stays the presenter's bar's alone),
  captions in the frame's dark glass; then a render's **status**
  (`#job-status`), one line cut by its ellipsis, 6 px after Stills. It is
  the bar's own item, after the group rather than in it, so that it gives
  way with the name pill when the bar is short (a group's text cannot
  shrink without its tiles).
- At the right end (`.tb-end`): the **renderer** (`#renderer-select`, a
  pill of the bar's height; hidden under 760 px with the folder) and its
  warning (`#glwarn`, one line, 95 px at most under 860), the **update**
  (`#updatebtn`, a tile that appears when the shell knows of a newer
  ManimLive, as the landing page's button did — new in the viewer), and
  the **engine's status** (`#connection-pod`), Knuth's status pill. The
  right end keeps its width (`flex: none`): when the bar is short the
  folder gives way first, then the name, never the status, which in class
  is the one place that says whether the engine is still answering.
- After it, over the room's right edge: the **console's toggle**
  (`#console-toggle`), the bar's last tile, lit while the panel shows. It
  stays fixed and outside the bar, so it does not recede with the chrome
  in full screen, where it is the glass pill it was.

**The room** is the stage (`#stage`): under the bar, 8 px from the
window's left, right and bottom, rounded 12 px, a white 5 % rim. The
scene centres in it, clear of the presenter's bar (22 px padding, 78 at
the foot as before). The console panel sits inside it at the right; the
presenter's bar gives up the panel's width as it did.

**The presenter's bar** is the old one exactly; only its floor moved:
12 px above the room's bottom edge (20 from the window's) where it was
12 above the window's. In full screen there is no frame (`--edge: 0`), so
it is 12 px up, the stage is the display and the console where it was.

**The scene file's path** now rides in the engine's state (`"path"`,
absolute, as the engine opened it), and the page tells the shell which
file its window holds (the shell's `document` request); the folder is
the shell's answer, so it never names a file the shell refused. The
window's document follows the scene opened from the landing page (an
update's relaunch reopens it), and the landing page tells the shell its
window holds none (`{path: null}`), so after File → Open another scene…
the Window menu and a relaunch do not name the scene just left. In a tab
the folder is the path's own.

**The landing page** (`app.html`) is the same frame: the bar with File
(its menu: **Open a scene…**, `#openbtn`), the pill reading
*ManimLive*, the update tile and the status at the right; the page in
the room, centred, scrolling inside it. **The setup page** gets a drag
band the lights' height, as Knuth's, and its content is padded clear of
it.

**One file for the bar's behaviour**, `static/bar.js`, loaded by both
pages: the menus (Knuth's keys: the arrows, Home, End, a letter, Escape,
Tab; a click elsewhere or a second click closes; the focus goes back to
the stage on the viewer), the folder, the update. An open menu takes
every plain key in the capture phase, so nothing it is given reaches the
scene: the viewer forwards every key it hears to the engine.

**Keys**: every shortcut is as it was (the arrows, Home, Space, F, C,
Escape), checked in the app.

## Measured

Both apps from their own checkouts' pinned shells (v0.2.1), side by side
at 1100 × 800, each on a document in `~/Projects/week-3`:

| | Knuth | ManimLive |
|---|---|---|
| lights' room | x 88, 44 tall | x 88, 44 tall |
| bar | 44 px, padded 100 (the room + 12) and 8, 6 px gaps | 44 px, padded 100 and 46 (8 + the console tile + 6), 6 px gaps |
| File tile | 32 × 32 at (100, 6), 9 px corners, 18 px glyph at (107, 13) | same |
| name pill | 30 tall at (138, 7), 9 px corners, 10 px padding, 9 px gaps, #232326, white 8 % hairline, widest 550 (560 at 1500) | same |
| name | `wages.py`, 15 px STIX Two Text, 1.35 px tracking, white 80 %, at x 149 | `squares.py`, same, at x 149 |
| after the name | the save dot, 6 px | `·` and `Squares` in the same serif, white 55 % |
| folder | `~/Projects/week-3`, 12 px, y 13, 103.09 wide | same, at x 325 (after the scene) |
| right end | status pill, 30 tall at y 7, 9 px corners, ending at the room's right (1092) | status pill the same, ending at 1054; the console tile 32 × 32 at (1060, 6), ending at 1092 |
| room | (44, 44), 1048 × 748, 12 px corners, #2b2a2d | (8, 44), 1084 × 748, same |
| frame | #18181a | #18181a |
| zoom levels 0.5 and 1 | overlay x 80 / 73, the bar 41 / 37 | same |

At 1500 × 900 the same, Knuth's room 1448 × 848 at (44, 44) and
ManimLive's 1484 × 848 at (8, 44). The rooms differ by the rail alone.
STIX Two Text is the one macOS ships (Knuth and Plass bundle it; the same
widths to the thousandth, measured), so ManimLive does not bundle it.

ManimLive's own, at 1100 × 800: the canvas 1040 × 585 at (30, 97.5)
(1056 × 594 before the frame); the presenter's bar 42 tall, 20 px up;
the console panel 340 × 662 at (740, 56). In full screen (F): no overlay,
the stage the display, radius 0, the presenter's bar 12 px up, the bar
back with the pointer at the top, padded 8, the console's pill at
(display − 44, 6). In a window with no shell and a native title bar (a
tab, as far as the page knows): the bar 44, the File tile at (8, 6), the
room at (8, 44). The landing page: the File tile at (100, 6), the pill at
(138, 7), the status ending 8 px from the right, the room (8, 44)
1084 × 748. The setup page in a 400 px window: a 44 px drag band, the
icon 68 px down. At 640 × 400, the minimum, the bar holds File, the pill
(name and scene), Restart, Download, Stills, the status and the console
tile.

Narrower, the right end holds. On a long file and scene name in a long
folder, with the update tile, a render's status and the renderer's
warning added one by one, the status pill keeps its full width (102 px
for `Connected`), ends 6 px before the console tile and the bar never
overflows: in the app at 1500, 1100, 1024, 960, 860, 800, 760, 700 and
640 px, and on the page alone (the lights' 100 px simulated) every 4 px
from 640 to 1500 with all of them showing at once and `Engine
unavailable` as the status. Before, the status was cut to a dot under
about 1020 px (1024 with the update showing) or pushed under the console
tile, and a render's status wrapped down out of the bar. At 1100 and 1500
nothing moved but the render's status box, which starts 3 px later with
its text where it was.

## Checks

- `tests.test_static_assets` and `tests.test_shell_config`: the frame's
  numbers, the bar a drag region with its controls the page's, the stage
  as the room, the name exactly the file's name, the right end keeping
  its width, the bar's quiet text on one line, the menus taking their
  keys before the forwarder, the shared bar on both pages, the landing
  page holding no document, the setup page's band, the config's lights
  making a 44 px band.
- `tests.test_web_viewer`: the state carries the scene file's path.
- `npm run app:smoke` (uv): ok, with the shell's overlay check for a
  hidden title bar (x past the lights, 2·15 + 14 = 44 tall).
- In the app (Playwright's `_electron`): the window's document is the
  scene file; ArrowRight and Home reach the scene from the stage; File's
  menu under its tile on its first item, ArrowRight, ArrowDown and F
  while it is open reaching nothing, Escape closing it and the stage
  having the keyboard again; the scene menu under the pill on the current
  scene, ArrowDown and Enter switching scene with the name unchanged; C
  and the tile opening and closing the console; the drag region; F in
  and out of full screen; Restart back at the start with the pill as it
  was; the landing page's bar and room and its File menu; the window's
  represented file the scene's, none on the landing page after File →
  Open another scene…, and the new scene's after one is picked there. The
  console clean throughout.

## What is open

1. **Start and Present stay on the presenter's bar**, as Taylor's words
   have it ("keep the nav rail at the bottom as is"). If the top bar
   should also carry them (Knuth's run tools are by the document), they
   would be duplicates, not moves.
2. **The status pill ends 38 px short of the room's edge**, where
   Knuth's ends on it: the console's toggle is the bar's last tile. It is
   the only number in the bar that differs. The toggle could become the
   status pill itself (a click on Knuth's drops its Session card), but
   then it would recede with the bar in full screen.
3. **The update tile is new in the viewer.** Knuth and Plass keep the
   update in File's menu; ManimLive kept its visible button, as a tile on
   both pages. It only appears when the shell has a newer build.
4. **The renderer's pill hides under 760 px** with the folder: a
   comparison control, but then there is no way to switch below that.
5. **Full screen**: the console's pill moved from 14 to 6 px from the top
   (centred on the 44 px band the bar comes back as), and the bar comes
   back as a solid frame band, 44 px, not the old 60 px glass pods.
6. **The folder is the file as the engine opened it**, links resolved
   (above). Knuth names the folder as given.
7. **A render's status keeps its width from 1024 px up** (the
   re-verifier's finding: at 1100 with a long folder it was cut to
   "Vid…" while the folder kept 347 px). A media rule from 1024 gives the
   name pill `flex-shrink: 1000` with a 120 px floor and the status
   `flex-shrink: 0`, so the folder gives way first, then the name; checked
   live at sixteen widths from 640 to 1500 with long and short names, the
   update tile and the warning on and off, and three status texts: from
   1024 up the status is never cut and the bar never overflows, and with
   no render running every box is unchanged. Below 1024 the two still
   share the shortfall, the tile's colour saying working, done or failed.
8. **Merging**: the scene-environment work in progress on main touches
   `app.html` (other hunks), and adds to the tops of `DECISIONS.md` and
   `CHANGELOG.md` as this branch does: keep both.
