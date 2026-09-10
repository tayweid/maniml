# CE-compat notes from the ECON 0100 episode ports (2026-09-01/02)

Field report from porting Episodes A2 and A3 (`econ-0100/Blocks/A2_Advantage`,
`A3_Trade`) — every divergence from manim CE that actually bit during real
episode work, in rough order of pain. Repro pointers reference those two
`03_Code.py` files, which carry the workarounds in comments.

## Divergences (bugs or missing pieces)

1. **Group draw order / z_index in the play path.** Fixed for direct adds on
   2026-09-02 (groups now sort CE-style), but mobjects introduced via
   `play(FadeIn(group))` still bypassed the z-sort in the last A3 render:
   an `autarky_marker` VGroup (dot `z_index=15`, dashed drop-lines z 0)
   faded in with the dashes drawn over the dot, and `bring_to_front(dot)`
   after the play was still required. Confirm the play/add paths sort
   identically. Repro: A3 `03_Code.py`, `autarky_marker()` + the
   `bring_to_front(mark_m[0], mark_a[0])` calls.

2. **`Transform` between mismatched point counts crashes.** Interpolating
   toward a rebuilt `always_redraw` target raises
   `could not broadcast input array from shape (31,3) into shape (123,3)`
   (`mobject.py` `interpolate`). CE's `align_data` resamples families and
   paths first. Hit during the A3 stage-1 merge (FadeIn of a live-redraw
   group mid-animation).

3. **`TracedPath` is missing.** Legacy CE episode code uses it
   (`_Assets/Video.py`, `circle_it`). A2/A3 carry a local `trail_behind()`
   polyline substitute. A shim (updater appending corners, with
   `dissipating_time` support) would let old code run unmodified.

4. **Tex dash ligatures are off.** `---` / `--` render as literal hyphens,
   not em/en dashes; episodes spell `\textemdash` / `\textendash`. CE (LaTeX
   defaults) ligates. Found on the "--- David Ricardo, 1817" attribution.

5. **Size commands don't survive `{{...}}` isolation.** A
   `{\small (Rate: {{1}} {{C}} ...)}` group rendered full-size — the
   isolation split re-renders pieces outside the `\small` scope. CE keeps
   the group's typesetting. Workaround: build mixed-size lines from
   separate Tex pieces (A3 caption parentheticals).

6. **The CameraFrame lives in `scene.mobjects`.** It is seeded there, and
   every `play(camera.frame.animate...)` re-adds one; checkpoint replay can
   leave several identities. Any `VGroup(*scene.mobjects)` stage-grab
   (the shared `exercise_card()` helper) raises
   `Only VMobjects can be passed into VGroup`. CE never exposes the camera
   in `mobjects`. Both A2 and A3 carry a `drop_frame()` workaround; A2's
   spares `ImageMobject` (the office-hours photo).

7. **`--render` emitted no per-checkpoint PNGs** for EpisodeA2/A3 in
   `econ-0100/Blocks/*` despite the CLI help ("each checkpoint to a PNG") —
   `Episode*_checkpoints/` stayed empty; frames were recovered by ffmpeg
   seeks against `*.pausepoints.json` stop times. maniml-internal rather
   than CE-compat, but the animator's look-at-frames loop depends on it.

## Ergonomic footguns (arguably by design; worth documenting)

8. **`ValueTracker`s linger in `scene.mobjects`** after being animated —
   the same `VGroup(*mobjects)` explosion as (6). Episodes now
   `self.remove(tracker)` after every sweep.

9. **GL stroke/fill compositing:** strokes draw over translucent fills, so
   a dim-overlay rectangle cannot cover a stage — the reason
   `exercise_card()` dims the stage mobjects themselves (noted in A1).

10. **`always()` applies only once** (A1-era note); `add_updater` is the
    reliable path for live layout chains.

## Deliberate supersets — document as features

- `camera.frame` works on plain `Scene` (CE needs `MovingCameraScene`).
- `Table` (including CE entry indexing and `line_config`), `CurvedArrow`,
  `DecimalNumber`, `Indicate`, `AddTextWordByWord` all match CE closely.
- Pause anchoring (`self.pause()`, `loop=True`) and `add_sound` in the
  viewer are maniml-only and load-bearing for the course.
