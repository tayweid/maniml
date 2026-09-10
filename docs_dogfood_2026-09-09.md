# maniml dogfood report, 2026-09-09

Diagnosis only; nothing in the repo was changed. Written to hand to another
engineer or model with no access to the session that produced it. Every file
path is relative to the maniml repository root at commit `4aa37fe6` (main,
2026-09-04, "Checkpoints are a ledger"). Line numbers are from that commit.

## Symptoms reported

Taylor, dogfooding the browser viewer on a real course episode
(`econ-0100/Blocks/B0_Markets/03_Code.py`, scene `EpisodeB0`, 178 lines,
11 plays/waits):

1. Rendering is "VERY slow and laggy".
2. The viewer often disconnects while a Claude Code session is editing the
   scene file at the same time.
3. A `Tex('Last Time...')` that an earlier unit had removed stayed on screen
   after a file edit landed at about the same time as a timeline/arrow-key
   move.
4. Mobjects that are faded in by the same `self.play(...)` sometimes appear
   at different times.
5. (Relayed from the session building the episode.) `AddTextLetterByLetter`
   is not importable via `from manim import *`, and the alias that exists
   is not per-character.

## Environment

| Item | Value |
|---|---|
| Machine | Apple M3, 8 cores, macOS Darwin 25.6.0 |
| Python | 3.13.9 (miniconda, `/opt/miniconda3`) |
| websockets | 17.0.1 |
| Install | editable, both the miniconda env and `maniml/.venv` point at the repo; local main equals origin/main |
| Agent | launchd `io.tayweid.maniml.agent`, `python -m maniml agent serve ~/Projects --port=8685`; scenes are spawned as `python -m maniml <file> <Scene> --web --no-browser` and relayed through the app on port 8685 to the scene's own server on port 8687 |
| Viewer | browser page `maniml/web/static/viewer.html`, rendering with WebGPU from the geometry stream |

Version drift was ruled out first: the running code is current.

## Finding 1: the scene is CPU-bound on an `always_redraw` rebuild (measured)

**What the scene does.** Lines 64-81 of the episode:

```python
alpha = ValueTracker(1)
def PPF_Group():
    linear_ppf = ax.plot(Linear_PPF, color=MUTED, x_range=(0, 100))
    bowed_ppf = ax.plot(Bowed_PPF, color=TRADE, x_range=(0, 100, 0.1))
    return VGroup(linear_ppf, bowed_ppf)
ppf_group = always_redraw(PPF_Group)
```

**What the engine does with it.**

- `always_redraw` (`maniml/mobject/mobject_update_utils.py:55-58`) adds an
  updater that calls the function and `become()`s the result on every
  update. There is no check for whether anything changed.
- The interact loop (`maniml/scene/scene.py:341-376`) calls
  `self.update_frame(frame_interval)` on every pass while a browser is
  attached, with no sleep of its own. `update_frame`
  (`scene.py:455-494`) runs `update_mobjects(dt)` first, so the updater
  runs on every idle frame, forever, while the scene is parked.
- The only pacing is `time.sleep(max(vt - rt, 0))` at `scene.py:494`,
  which sleeps only when the frame was *faster* than the fixed 1/30 s
  timestep. A slow frame is never compensated; virtual time still
  advances by exactly 1/30 s per frame.
- The per-frame stream then re-serializes the whole scene:
  `WebViewer.on_frame_rendered` (`maniml/web/viewer.py:319-373`) treats
  `any(m.has_updaters() for m in scene.mobjects)` as "animating" and
  sends geometry at up to 45 fps (`MIN_SEND_INTERVAL = 1/45`,
  `viewer.py:86`); `serialize_scene` (`maniml/web/geometry.py:323`) walks,
  packs, and blake2b-hashes every batch each time (already TODO.md "Now"
  item 2).

**Where the time goes.** `Axes.plot` (`maniml/mobject/coordinate_systems.py:223-240`)
builds a `ParametricCurve`; `ParametricCurve.init_points`
(`maniml/mobject/functions.py:38-54`) evaluates the function in a Python
list comprehension, one call per sample, then `add_points_as_corners` and
`make_smooth(approx=True)`. With `x_range=(0, 100, 0.1)` and
`num_sampled_graph_points_per_tick = 5` (`coordinate_systems.py:65`) the
bowed curve has 2001 points.

**Measurement.** Headless microbenchmark with the same `Axes`, functions,
and ranges, mean of 20 runs, idle machine:

| Operation | Time |
|---|---|
| `ax.plot(linear, x_range=(0, 100))` | 93 ms |
| `ax.plot(bowed, x_range=(0, 100, 0.1))`, 2001 points | 261 ms |
| one `always_redraw` update of the group | 359 ms |

A 3 s `sample` of the live scene process (100% CPU, scene parked at a
pausepoint) agrees: 87% of main-thread samples were inside one
constructor call chain, with `numpy` `array_concatenate` and Python-level
`sum` over generators as the hot leaves.

**Consequence.** Idle frame rate is under 3 fps at 100% CPU. Because the
timestep is fixed, a 1 s animation in this scene takes roughly 30 × 0.36 s
≈ 11 s of wall time. This alone accounts for "VERY slow". Every key press
and every reload also waits behind these frames.

**Suggested fixes, in order of payoff.**

1. Vectorize `ParametricCurve.init_points`: evaluate on a numpy array of
   `t` values (or call the function once with the whole array when it is
   vectorizable, falling back to a loop only on failure). CE does this in a
   few milliseconds for the same curve.
2. Make `always_redraw` cheap when nothing changed: skip the rebuild when
   no input the closure reads has moved (at minimum, let a scene opt in by
   passing the trackers it depends on), or memoize on the tracker values.
3. TODO.md item 2 (skip the per-frame walk of unchanged batches) is still
   worth doing but is second-order next to the 360 ms above.

## Finding 2: a concurrent render from another session (observed)

While the live scene was running, a second maniml process started by a
different Claude Code session was rendering the *same* episode from the same
directory:

```
python -m maniml 03_Code.py EpisodeB0 --render
ffmpeg -f rawvideo -s 2160x1080 -r 60 ... -vcodec libx264
```

Two CPU-pinned Python processes plus ffmpeg on 8 cores, load average 3.7.
Any session that renders or runs the test suite while the live viewer is
open will make the viewer stutter. Not an engine bug, but it explains part
of what Taylor saw, and it is worth a note in the project instructions for
agent sessions: do not render or run the suite while a live scene is up
unless asked.

## Finding 3: disconnect mechanism, event queue overflow during a replay (code reading, not reproduced)

The scene's WebSocket server (`maniml/web/server.py`) keeps inbound
browser events in a deque with `MAX_EVENT_QUEUE = 1024` (line 35). In
`_handle_client` (lines 173-179), when a message arrives and the deque is
already full it closes the socket with code 1013 "event queue full".

The chain that fills it:

- The deque is drained only by `WebServer.pop_events` (lines 218-224),
  called from `WebViewer.dispatch_events`, called from
  `on_frame_rendered` (`viewer.py:321`), called from
  `Scene.update_frame` (`scene.py:489`).
- `update_frame` returns before reaching that call when
  `self.skip_animations and not force_draw` (`scene.py:463`).
- A file edit triggers `_handle_file_change`
  (`maniml/scene/checkpoints.py:156-217`) and then `_replay_to_unit`
  (lines 219-243), whose docstring says units before the target are
  fast-forwarded with animations skipped. During that replay the drain does
  not run.
- The page sends one coalesced `pointer move` per animation frame
  (`viewer.html:1263-1272`), about 60/s while the mouse moves. So roughly
  17 s of mouse movement during a long replay fills the queue. Replays get
  long on real episodes: an edit above `construct()` triggers
  `_restart_from_source` (`checkpoints.py:268-302`), which reloads the
  module and fast-forwards every unit up to the current one.
- The deque is **not cleared** when a client disconnects
  (`_handle_client`'s `finally`, lines 188-191, only fixes the client
  count). On reconnect the page immediately sends `mode` and
  `geometry_request` (`viewer.html:727-728`), the server sees the deque
  still full, and closes again with 1013.
- The page retries at most `MAX_RECONNECTS = 3` times
  (`viewer.html:541`) with 700 ms × n backoff, about 4.2 s total, then
  shows the overlay "Can't reach the local engine" (lines 565-573) and
  stops. The scene process is still alive and still busy.

This matches "disconnects while a Claude session edits the file", is
worst on long episodes, and needs no crash. Not reproduced end to end; the
chain above is from reading the code.

**Suggested fixes.**

1. Clear the deque (or drop everything but the latest navigation intent)
   when a client disconnects, and again when a replay starts.
2. Drain, or at least discard pointer moves, inside the fast-forward path
   so a replay cannot fill the queue.
3. Do not close on overflow; drop the oldest non-navigation events instead.
4. Let the page keep retrying with a longer backoff while the process is
   alive, instead of giving up after three tries in four seconds.

**Related, lower confidence.**

- The agent log (`~/Library/Logs/maniml-agent.log`) has ten
  `ConnectionClosedError: received 1011 (internal error); then sent 1011`
  entries from the evening of 2026-09-04, all in the app's control-socket
  handler (`maniml/web/app.py:523`). "received" means the peer sent 1011
  first; browser JavaScript cannot send 1011, so the origin is unknown. The
  scene processes' own output goes to a pipe read by the app
  (`app.py:109-127`) and is not on disk, so there is no log of scene-side
  closes.
- `WebServer.broadcast` (`server.py:193-213`) creates one asyncio task per
  message with no producer-side backpressure. In websockets 17 `send()`
  writes the frame synchronously and then awaits `drain()`, so ordering is
  preserved, but the transport buffer grows without bound when the browser
  is slower than the scene; latency grows instead of frames being dropped.
  The relay (`app.py:459-505`) sets `max_queue=1` upstream, which pushes the
  backpressure to the scene but does not cap this buffer.
- Both servers use websockets' default keepalive (ping every 20 s, 20 s
  timeout); neither is configured explicitly.

## Finding 4: `Tex('Last Time...')` ghost after an edit during navigation (not identified)

Sequence as reported: an edit to the file and an arrow-key or timeline move
landed close together; a `Tex` removed by an earlier unit stayed on screen.

Relevant code:

- The watcher thread only raises a flag (`checkpoints.py:146-154`); the
  main loop handles it at the top of each interact pass
  (`scene.py:361-363`), so the edit is processed after whatever navigation
  was in flight.
- `_handle_file_change` truncates checkpoints to the last one before the
  edited unit, sets the frontier there, and restores state **only if**
  `current_animation_index != safe_idx` (`checkpoints.py:206-210`). When
  the indices already match, the live graph is used as-is and the replay
  runs against it.
- This is new ledger territory (commit `4aa37fe6`): frozen copies are
  shared across checkpoints keyed by `Mobject.revision`, the frontier
  skips the thaw, and `_live_matches_checkpoint` (`checkpoints.py:51`,
  `:628`; cleared in `scene.py:1037`) says whether the live scene equals
  the last save. The edit re-anchor path and the exec-error rollback are
  the two paths the ledger commit says were switched to thaw.

Nothing here was confirmed. The cheapest next step is the one TODO.md
already prescribes: run the episodes with `MANIML_VERIFY_LEDGER=1`, which
compares every ledger reuse against the live object and raises
`LedgerStale` naming the attribute a missed revision bump left stale. If
the ghost reproduces without a raise, the bug is in the re-anchor logic
(which checkpoint is "safe", or the frontier flag surviving the
truncation) rather than in the ledger.

Also worth knowing: the watcher (`maniml/scene/file_watcher.py:68-139`)
polls mtime once per second and diffs by line position, not by content
alignment. An editor that writes the file non-atomically can be read
mid-write; a truncated read parses as an error or as a shorter valid file,
and the following poll replays again from the truncation point. Two
replays per edit is harmless in itself but doubles the window for
Finding 3.

## Finding 5: simultaneous fade-ins appear at different times (not identified)

No mechanism confirmed. Two things to look at:

- With 360 ms frames (Finding 1) a `play` of several `FadeIn`s renders only
  two or three frames; anything that makes one batch land a frame later
  than another becomes visible as staggering.
- Geometry batches are delta-encoded per content hash. A batch the client
  does not hold triggers `onCacheMiss`, which sends `geometry_reset`
  (`viewer.html:738`) and waits for a resend; the cache is reset on every
  reconnect (`viewer.py:466-472`). If the WebGPU side draws a frame before
  every batch in it has been uploaded, or after a reset round trip, objects
  will pop in one at a time.

## Finding 6: `AddTextLetterByLetter` is unexported and not per-glyph (verified)

- `maniml/animation/creation.py:268`: `AddTextLetterByLetter = AddTextWordByWord`.
- `maniml/__init__.py:56` and `:273` export `AddTextWordByWord` only, so
  `from manim import *` raises `NameError` on `AddTextLetterByLetter`.
- `AddTextWordByWord` (`creation.py:220-243`) steps through
  `string_mobject.build_groups()` at `time_per_word = 0.2`; for a plain,
  un-isolated `Tex` that is very few groups, not one character at a time as
  in CE.
- The name is absent from `tests/ce_conformance/supported_names.txt`, so
  the conformance suite does not cover it.

Fix: export the name, and make it a real subclass that steps over the glyph
family with a per-character `int_func` and `time_per_char`. Episode
workaround in use: `ShowIncreasingSubsets(VGroup(*tex.family_members_with_points()),
run_time=time_per_char * n, rate_func=linear)`.

## Suggested order

1. Vectorize `ParametricCurve.init_points` (Finding 1). Largest payoff,
   smallest change, no protocol impact.
2. Event queue: clear on disconnect and on replay start, stop closing on
   overflow (Finding 3).
3. Dogfood with `MANIML_VERIFY_LEDGER=1` to split Finding 4 between the
   ledger and the re-anchor logic.
4. Export and reimplement `AddTextLetterByLetter` (Finding 6).
5. Then TODO.md item 2 (skip unchanged batches) and a bounded broadcast
   buffer.
