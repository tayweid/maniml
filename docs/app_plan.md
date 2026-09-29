# ManimLive.app: the Mac app

Written 2026-09-28; the browser engine measured 2026-09-29. Taylor's
direction, quoted: "getting this more polished is the goal. right now it
needs the terminal and the app and it's a little clunky feeling." The shape
is the one Knuth and Plass already ship (`../knuth/docs/APP.md`,
`../knuth/app/`, `../plass/app/`): a native window around the page the
engine serves, a Python the app manages itself, built on a GitHub Mac by
every deploy and installed with one line. Status: plan. Nothing is built,
and every choice below is a proposal until Taylor makes it.

## What is clunky today

- **Three pieces to install and keep in step.** A pip install from git
  (which compiles the Lyon helper, so it needs Rust and the command-line
  tools), the launchd agent or a terminal running `maniml app`, and a
  Chrome PWA installed from `http://localhost:8685`
  (`~/Applications/Chrome Apps.localized/ManimLive.app`).
- **A scene cannot be double-clicked.** The PWA would receive a browser
  file handle, which has no path, and the watcher and a scene's
  `__file__`-relative imports need one (CLAUDE.md, "No `file_handlers`
  yet"). Opening goes through the page's Open button, which asks the engine
  to run an `osascript` dialog in another process.
- **Tools are found by PATH.** A Finder- or launchd-started engine gets
  `/usr/bin:/bin:/usr/sbin:/sbin`, so `agent.search_path()` exists to find
  `latex`, `dvisvgm` and `ffmpeg`.

None of this is about the browser engine. It is where the engine lives,
how files reach it, and how it is installed.

## The proposal

**ManimLive ships as `ManimLive.app`, on the Knuth pattern.** Swift +
AppKit + WKWebView in one file, built by `app/build.sh` with `swiftc` from
the command-line tools: no Xcode project, no Electron, no Tauri. The shell
owns exactly four things: a window per scene file, the native open dialog,
the engine's lifetime, and the first-launch setup. Everything else is the
page the engine already serves.

**The engine is the package in the bundle.** `Contents/Resources/python/
maniml` is this repository's `maniml/`, with the Lyon helper already built
beside `web/`. The engine runs it with `PYTHONPATH` on a Python uv
installed, so the app and its engine are always one version and a pip
install elsewhere on the Mac can never be what a window talks to. The
scene subprocesses inherit the environment (`SceneProcess` passes
`os.environ` through), so they run the same copy.

**One question at first launch, in the window.** Knuth asks "install
Python?" and offers Pyodide as the alternative. ManimLive has no
alternative to offer — manimpango, wgpu and the Lyon helper cannot run in
a page — so the setup screen explains uv in two sentences and installs:
uv (any uv already on the Mac, else Astral's release into
`~/.local/bin/uv`, as Knuth does), a uv-managed Python 3.13
(`UV_PYTHON_PREFERENCE=only-managed`), and the dependencies. Everything
the app installs lives in `~/Library/Application Support/ManimLive`;
deleting that folder returns it to its first launch.

**Distribution is Knuth's and Plass's.** A Mac job in the deploy builds the
app from the pushed commit and publishes `app/ManimLive.app.zip` beside the
preview site; `curl -fsSL https://maniml.tayweid.io/install | bash` unzips
it into Applications, and running it again updates. Ad-hoc signed and not
notarized, as the others are: the curl route is never quarantined, and a
Developer ID can slot into the job later.

**The browser engine is WebKit's.** Measured against Chrome on three course
episodes (below): the same frames drawn, GPU cost at parity, the driver's
JavaScript 2.4–2.9× slower, which costs little on the default stack and
shows on the heaviest frames, most of them Phase B's. WebGPU is on by default in WebKit
from the 26 releases (verified on 26.6.2), so the app requires macOS 26
(Knuth supports 12).

## What is different from Knuth

Knuth's shell carries over nearly line for line. Five things do not.

### 1. Opening a scene runs it

Knuth opens `http://127.0.0.1:<port>/?open=<path>`: harmless there, since
opening reads a document. Here the open op executes the scene, and any
website can navigate a browser tab to a loopback URL with any query
string; the Origin check does not help, because the page that then asks
is the real one. So the path must reach the engine by a channel no web
page can reach, and the engine must refuse an `?open=` it was not told
about.

The engine already has the primitive: `AppServer.grant_file()`
(`maniml/web/app.py`), documented as "a path handed over by Finder or a
native dialog", uncalled since the desktop bridge was deleted. The shell
starts the engine with a pipe on its stdin and writes one line per grant
(Finder open, Open With, the Open panel); the engine grants the file,
acknowledges on the pipe, and only then does the shell open the window at
`/?open=<path>`, which `app.html` learns to honor for granted paths only.
Root confinement stays as it is: the app's engine gets no broad root (not
`~`), or a `.py` a website dropped into Downloads would become openable.
Stdin gives the lifetime for free: when the shell dies — quit, crash or
`kill -9` — the pipe closes, and the engine stops its scene processes and
exits. That replaces Knuth's `--parent <pid>` polling.

### 2. The environment is twenty times Knuth's

Knuth installs one package (websockets) beside its bundled engine.
maniml's runtime dependencies come to about 230 MB installed (measured in
the development venv: scipy 81 MB, matplotlib 28, numpy 25, manimpango 18,
PyOpenGL 17, Pillow 14, fontTools 13, wgpu 8). So the dependency list is
pinned, not resolved at install: the build exports it from `uv.lock`
(`uv export --no-dev --no-emit-project --frozen`) into the bundle, the
setup runs `uv pip sync` against it, and the shell re-syncs whenever the
bundled file's hash differs from the one it last synced — which is what an
app update that changes a dependency looks like. First launch is a longer
progress bar than Knuth's, once.

**Scenes import more than maniml.** The course scenes import pandas (11
files) and seaborn (12), which are not maniml dependencies, and the app
never uses a Python already on the Mac. v1: when a scene fails on
`ModuleNotFoundError` (`missing_module_hint` already names the module),
the page offers "Install <module>", and the shell runs `uv pip install`
into the app's Python — Knuth's "Download with uv", app-wide rather than
per document. Per-scene PEP 723 headers (Knuth's `ENVIRONMENT.md`) are the
later, reproducible version; each scene is already its own process, so
each could have its own environment.

### 3. The Lyon helper is built by the deploy

Today's install compiles it, which is why the README asks for Rust. The
app job does what CI already does (macOS, rustup 1.97.0), for both
architectures, and `lipo`s one universal library into the bundled
package. It is a plain C ABI loaded with ctypes and found by glob
(`maniml/web/triangle_geometry.py`), so one file serves every Python
version. The app is then easier to install than the pip route is.

### 4. ffmpeg and LaTeX are programs, not packages

The engine's PATH is composed once, by the shell, from `search_path()`'s
list (TeX, Homebrew), with the app's own `bin/` first.

- **ffmpeg is on the classroom path**, not only the export one: Present
  plays the rendered mp4. `SceneFileWriter` runs whatever `ffmpeg` is on
  PATH. Use the Mac's own if there is one; otherwise the setup installs
  `imageio-ffmpeg` (0.6.0 ships a 21 MB arm64 wheel) into the app's
  Python and links its binary into the app's `bin/`. The writer does not
  change.
- **LaTeX has no clean answer yet.** The course scenes lean on it
  (`B5_Animation.py` alone has about 250 lines calling Tex/MathTex), and
  maniml runs `latex` and `dvisvgm`. On a Mac with MacTeX, which Taylor's
  has, the app works on day one; the setup screen should detect TeX and
  say plainly when it is missing, before the first equation fails. For
  anyone else the answer is TODO.md's Typst/mitex backend: the `typst`
  wheel is self-contained, so uv installs it like everything else. That
  item stops being "do whenever" the day the app is for someone other than
  Taylor.

### 5. Two maniml's on one Mac

The app runs its bundled release; `maniml` in a terminal runs this
checkout — CLAUDE.md's install trap in a new form. As in Knuth, the app's
engine keeps its own port (8686, next free if taken: between the
terminal's 8685 and the scene range from 8687) and never adopts an engine
it did not start, and the page says which engine it is talking to.
Development stays on the command line; `MANIML_APP_PACKAGE=<checkout>`
(read only from `open --env`, never from Finder) points a development
build of the shell at the working tree.

## What the shell does, exactly

1. On launch: setup if the engine is not installed or its dependency list
   changed; then start `python -m maniml app --shell` (new: implies
   `--no-browser`, never offers or hands off to the agent, reads grants
   from stdin and exits at its EOF) on 8686 as a child, and wait for it to
   answer.
2. Finder open, Open With, ⌘O: grant over the pipe, wait for the
   acknowledgement, open a window at `/?open=<path>`. `.py` is an
   alternate handler, never the default (Knuth's Info.plist: it appears in
   Open With; the user can promote it in Get Info). A Dock click with no
   window opens `/`, the recents page.
3. Bridge the page's Open button to an `NSOpenPanel` sheet (the same grant
   path); `desktop.py`'s osascript dialog stays for the terminal route.
4. Mirror the page title into the window title. WKWebView reports
   `document.fullscreenEnabled` false unless element fullscreen is turned
   on, so the viewer hides its fullscreen button there (visible in the
   measurement's snapshots). `F` should become native fullscreen through
   the bridge, which gives the projector its own Space.
5. Hold a display-sleep assertion while the page says it is presenting.
6. Menu: Open…, Show Log (`~/Library/Logs/ManimLive.log`, shared by shell
   and engine with `O_APPEND`, as Knuth's is), Open in Browser (the same
   page in the default browser: Chrome's WebGPU as a cross-check), Quit.
7. On quit: close the pipe; the engine takes its scene processes down.

## The engine, measured

Taylor asked whether it would be simpler with WebGPU on Chromium than on
WebKit. Measured 2026-09-29 before answering.

**Method.** One instrumentation script, injected at document start into the
real viewer in both engines: a WKWebView configured as Knuth's windows are,
and Google Chrome 154 driven by Playwright with a temporary profile. Per
frame it times the JavaScript around the driver's `ManimlWGPU.render`
(excluding time queued behind the previous frame: the boundary
`benchmarks/browser_frames.py` times in Node), and per submit
`queue.submit` → `onSubmittedWorkDone`; it records the rAF cadence, the
depth of the viewer's geometry queue (over 6 is the catch-up that collapses
states), console errors, GPU validation errors and device loss. Each run
is a fresh scene process at `efcb262c` (retained frame on, format 8
deltas), the same plan in both engines — RIGHT through the first five to
eight pausepoints, and on the 3D episodes a 60-move orbit and eight wheel
ticks in and out, sent through the page's own `send()` — in ABBA order per
scene. Apple M3, macOS 26.6.2. The two engines were sent the same stream
(EpisodeB2: all 410 and 423 messages the same length, in order), so each
row compares the same frames. "Default" is the viewer's default stack,
which is Phase A's since no flip passed; "Phase B" is the forced Phase B.

**Everything draws.** Every step of every run settled at the same
checkpoint in both engines (42/76, 31/58, 32/97), with the same frame
counts, no catch-up (the queue never passed 2) and no GPU validation
error; the one device loss per Phase B run is the renderer switch
replacing the device, identical in both. Snapshots of B4 at 32/97 on
Phase B after the orbit show the same scene (the orbit left the two
cameras a few degrees apart).

| Episode, stack | JS ms/frame, WebKit (med / p95 / max) | Chrome | GPU ms/submit, WebKit | Chrome | Late refreshes, WebKit / Chrome |
| --- | --- | --- | --- | --- | --- |
| EpisodeB2, Default | 3 / 11 / 27 | 1.1 / 3.5 / 6.4 | 6 / 11 / 20 | 6.5 / 13.4 / 27.9 | 6 / 0 |
| EpisodeB2, Phase B | 1 / 19 / 203 | 0.7 / 4.7 / 18.8 | 7 / 15 / 53 | 7.5 / 22.6 / 187 | 14 / 2 |
| EpisodeB3, Default | 2 / 11 / 12 | 0.8 / 3.1 / 4.4 | 6 / 9 / 22 | 7.7 / 11.4 / 26.8 | 0 / 0 |
| EpisodeB3, Phase B | 1 / 21 / 62 | 0.9 / 4.6 / 11.6 | 6 / 16 / 21 | 8.8 / 25.6 / 65.3 | 14 / 0 |
| B4, Default | 2 / 11 / 13 | 0.8 / 3.1 / 4.4 | 5 / 9 / 17 | 5.8 / 12.5 / 23.1 | 0 / 0 |
| B4, Phase B | 1 / 18 / 60 | 0.9 / 4.7 / 13.3 | 7 / 15 / 24 | 6.8 / 22.8 / 71.6 | 13 / 1 |

A late refresh is an interval over 1.5× the median rAF interval (16.7 ms).

**Reading.** The GPU is at parity, WebKit's tails shorter. The JavaScript
is where the engines differ: JavaScriptCore runs the driver 2.4–2.9×
slower than V8 over every run. On the default stack that stays inside a
16.7 ms refresh — 2–3 ms at the median and 11 at p95 — except on the
largest frames: EpisodeB2's three over 15 ms are its 2.3 MB payloads
(Chrome: 6 ms). Phase B is the visible cost: its frames with the largest
payloads (230–450 KB) take 20–40 ms in WebKit against 4–11 in Chrome —
the same frames are among Chrome's slowest, so the cost is the content's,
multiplied — which is 13–14 late refreshes a run against 0–2. And in the
session's first Phase B run two frames took 111 and 203 ms (Chrome: 9–12),
which later runs, in fresh processes, did not repeat: consistent with
shader compilation the system then cached, and with the driver building
pipelines lazily and synchronously (seven `create*Pipeline` calls, no
`…Async`); not yet attributed.

**Verdict.** WebKit runs the viewer as it is, correctly and on the GPU as
fast. Chromium would buy V8's speed on Phase B's heaviest frames, not
simplicity, at Electron's price. The Phase B tail is a driver item that
helps both engines — pipelines created with `createRenderPipelineAsync`/
`createComputePipelineAsync` and warmed at init, and a play's row frames
made cheaper to apply — and should land before Phase B is the app's
default.

**Caveats.** The screen was locked for the run, so WebKit's occlusion
throttling was switched off in the harness (private setters, as Plass
reaches `_setEnabled:forFeature:`; harness only) and Chrome ran with
`--disable-backgrounding-occluded-windows`: the refresh cadence is
therefore synthetic in both, while the per-frame JavaScript and GPU costs
are not. WebKit's `performance.now()` is quantized to 1 ms on this page
(Chrome's to 0.1 ms), so its small medians are coarse. One repetition in
ABBA order; the same pattern held in all three episodes. The harness
lived in the session's scratch space and is not in the repository.

## Deploy

`site.yml` today publishes `site/` on pushes that touch it. It grows an app
job on a Mac: check out, build the Lyon helper (both targets, `lipo`),
`app/build.sh` into `$RUNNER_TEMP`, `ditto` the zip, and hand it to the
deploy beside `site/`, which gains `site/install`. The triggers widen to
the package, `app/` and `uv.lock`. As in Knuth, a failed app build never
holds the site: the deploy republishes the zip already live. The site's
invariants hold — it still reaches no engine and has no manifest
(`tests/check_site.py` scans only `.html`, `.js` and `.json`, so
`site/install` passes as it is) — but its docstring's "nothing
installable" gains a sentence: the one installable thing is the Mac app,
and it is the local one.

## Risks and open questions

- **WebKit is a second WebGPU implementation.** Every frame dogfooded
  before this, and the browser gates in `phase_b1_plan.md`, ran on
  Chrome's. The measurement above is the evidence so far; "Open in
  Browser" is the escape hatch while trust builds. If WebKit fails on
  something real, the fallback is Electron: the rest of this plan (engine,
  grants, setup, deploy) is unchanged by it, at the cost of a ~100 MB
  download, a Node toolchain and shipping Chromium's security updates
  ourselves.
- **Phase B in WebKit**: the tail above, before Phase B is the default.
- **LaTeX** decides the audience (above).
- **The wire keeps moving.** The measurement ran on the retained frame and
  format 8; re-run it when the stream changes shape again.
- **Gatekeeper.** Unsigned, as Knuth and Plass are; the curl route avoids
  the prompt, and a downloaded zip needs Privacy & Security → Open Anyway
  once.

## Order

1. Engine: `maniml app --shell` (stdin grants and lifetime), `?open=` in
   `app.html` for granted paths, PATH composition shared with the agent,
   ffmpeg resolution, the install-a-module hook. Unit tests over the real
   socket, as the app's tests are now.
2. Shell: `app/Sources/main.swift` from Knuth's, minus its Pyodide mode
   and file operations; `Info.plist`; `app/build.sh` (+ the helper build);
   the setup page.
3. Deploy: the app job and `site/install`.
4. Retire the PWA surface (manifest, `sw.js`, the install offer) once the
   app is the daily driver, as Knuth's step 5 does; `maniml app` in a tab
   stays for Linux, Windows and the terminal-inclined, and the agent stays
   optional.
5. The Typst text backend, if the app is for anyone but Taylor.
