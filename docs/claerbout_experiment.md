# ManimLive in the Claerbout shell: the experiment

Run 2026-09-30, on the branch `claude/kind-gates-be81d2` (off `main` at
835e2746). An experiment, not a port: the viewer page was run inside the
Claerbout shell (`~/Projects/claerbout`, Electron 44.5.0, Chrome
152.0.7977.130) from a config written for it, and the questions in the
app plan's "Claerbout: Electron for all three apps" (the `maniml-app`
worktree's `docs/app_plan.md`) were answered by doing. This section is
meant to be merged into that plan.

**Outcome in one line:** a scene renders in the shell's sandboxed window
on WebGPU, stepped by arrow keys, with uv's Python running the engine
that the shell installed on first launch, no Chromium flag set, and no
shell code changed. Two lines of maniml changed (below), and the engine
was started through a 30-line wrapper that does what `maniml app` does
not yet: take `--port` and `--parent`.

## What was run

Everything lived in a scratch folder (`$S` below), the shell's state in
`$S/state` (`MANIML_CONFIG_DIR`), the engine on port 8690 (`MANIML_PORT`;
the login agent holds 8685 and was left alone), the recents list at
`$S/state/recents.json` (`MANIML_RECENTS_PATH`, which is the one state
path the engine has). The only thing on the Mac the run touched is
`~/Library/Logs/ManimLive.log`, which the shell and today's launcher
share; uv was Homebrew's, already installed.

```
CLAERBOUT_APP=$S/maniml.json MANIML_CONFIG_DIR=$S/state MANIML_PORT=8690 \
MANIML_RECENTS_PATH=$S/state/recents.json \
SDKROOT=/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
electron --remote-debugging-port=9333 ~/Projects/claerbout
```

`SDKROOT` is explained under question 1; the debugging port let the
window be driven and screenshotted over the DevTools protocol without
touching the Mac's UI (`Runtime.evaluate`, `Input.dispatchKeyEvent`,
`Page.captureScreenshot`).

The config, `$S/maniml.json`:

```json
{
  "name": "ManimLive",
  "id": "io.tayweid.manimlive",
  "envPrefix": "MANIML",
  "package": "engine",
  "devPython": ".",
  "web": "web",
  "port": 8690,
  "pythons": ["uv"],
  "scheme": "manimlive",
  "setupPage": "setup.html",
  "defaultDocument": "scene.py",
  "engine": {
    "args": ["-m", "engine.serve", "--root", "<scratch>/scenes"],
    "marker": "serve.py",
    "probe": "manimlive",
    "python": "3.13",
    "requirements": ["<this worktree's path>"]
  },
  "window": { "width": 1280, "height": 820, "minWidth": 640, "minHeight": 400 },
  "documentTypes": [
    { "name": "Manim scene", "role": "Viewer", "rank": "Alternate",
      "contentTypes": ["public.python-script"], "extensions": ["py"] }
  ]
}
```

Two things in it are scaffolding for the experiment rather than the
shape of a port:

- `package: "engine"` names a scratch package holding one module,
  `serve.py`, which is what `maniml app --port N --parent PID` would be
  (question 1): it parses both flags, starts a thread that polls the
  parent pid every two seconds and sends itself SIGTERM when it is gone,
  then calls `run_app(root, open_browser=False, port=N,
  offer_agent=False, allow_outside_root=True)`. The shell's `PYTHONPATH`
  points at the scratch folder, so `maniml` itself was imported from the
  venv uv built, not from the bundle.
- `web: "web"` names a scratch folder holding Knuth's `setup.html`,
  `setup.js` and `setup.css` with the name changed. With `pythons:
  ["uv"]` there is no choice to make, but the setup page is still the
  progress screen of the first launch and the shell loads it from the
  page folder, so a ManimLive port needs one in `web/static/` (the shell
  serves the page folder under `manimlive://app/` only for that screen;
  the viewer comes from the engine).

The product change, in this worktree, two lines: `AppServer` in
`maniml/web/app.py` and `WebServer` in `maniml/web/server.py` add
`http://127.0.0.1:<port>` to their `allowed_origins` beside
`http://localhost:<port>`. The shell hard-codes the engine's origin as
`http://127.0.0.1:N` (its probe, the page URL it loads, and the origin its
permission handler trusts), and the engine's Origin check accepted only
the `localhost` spelling, so the first run served the landing page and
refused its control socket. Both spellings are the same loopback and the
check is exactly as strong with two entries as with one; a port would
keep this change (or the shell would learn a `host` key, which is the
worse end to bend). `tests/test_app.py`'s pin of the allowlist was
updated with it; the two other `test_app` failures in this worktree
(`test_open_scene_from_landing`, `test_missing_module_hint`) fail on the
unchanged code too, because the worktree carries no compiled Lyon helper
and its venv path is relative.

The scene was `dogfood/scene.py` (`Demo`: a `Write`, two `Create`s and
two `.animate` shifts), copied to `$S/scenes/`.

## 1. The engine

**Does ManimLive have a serve command that takes `--port` and `--parent`?
No.** `maniml app [dir]` in `maniml/__main__.py` reads its flags as a set
of strings starting with `-` and ignores what it does not know; there is
no `--port` for the app (the `--port=N` later in `main()` is the viewer's,
for `maniml script.py Scene`), and no `--parent`. Started as the shell
starts an engine, `python -m maniml app --port 8690 --parent 8286`, the
two flags vanish and `8690` becomes the positional root directory. The
engine then binds 8685 (or, with 8685 taken, an OS-assigned port, as
`bind_loopback` does) and the shell's probe of its own port never
answers. `run_app` already accepts `port=` and `offer_agent=False`, so the
command is a small addition: parse `--port N` and `--parent PID` in the
`app` branch, and add the parent watch (the wrapper's; Knuth's engine has
the same, with the same Windows caveat that `os.kill(pid, 0)` is not a
liveness test there). With `--exit-when-idle` the shell's engine would
also stop three minutes after its last window; the shell stops it at
quit and the parent watch covers a force-quit, so the idle timer is not
needed in the shell and was not used.

The shell also sets `MANIML_CONFIG_DIR` and `MANIML_UV` in the engine's
environment. maniml reads neither: its one piece of app state is the
recents list, at `~/.maniml_recents.json` or `MANIML_RECENTS_PATH`. A port
would have the engine keep that list (and nothing else) under
`MANIML_CONFIG_DIR` when it is set.

The engine's lifetime was checked both ways: the shell's page loaded and
connected after `engine.isUp` saw `manimlive` in the landing page (the
probe is matched lowercased against `<title>ManimLive</title>`), and a
`kill -9` of the Electron main process was followed within two seconds by
`engine: parent gone, exiting` and the port freed.

**What `requirements` has to be.** The choices the question names:

- *From PyPI:* not available. `https://pypi.org/pypi/maniml/json` answers
  404; nothing is published.
- *From a path or git:* this is what was run (`requirements` was this
  worktree's path, so uv built and installed maniml itself plus its 41
  dependencies into the shell's venv). It works only where cargo and a
  working Apple linker exist, and on this Mac the second was not a given:
  the Command Line Tools' current SDK (`MacOSX27.0.sdk`) has `.tbd`
  stubs naming an architecture (`arm64e.x1-macos`) that the `ld` cargo
  invokes rejects as "malformed file", so the helper's build failed
  inside `uv pip install` and inside a plain `cargo build`. It built in
  2.5 s with `SDKROOT` pointed at the `MacOSX26.5.sdk` beside it, which
  is how the run above proceeded. A user's machine has no cargo at all,
  so from-source is not a first-launch path for anyone but Taylor.
- *From the bundle (Knuth's model):* the right one. The `maniml` package
  is 2.4 MB of source plus the 0.5 MB Lyon helper
  (`maniml/web/maniml_lyon_fill.cpython-313-darwin.so`, a C-ABI
  library loaded through ctypes, so it is tied to the platform and not
  to the Python minor version beyond its file name). The bundle would
  carry the package with the helper prebuilt per platform under
  `Resources/python`, and `requirements` would be maniml's dependency
  list alone. Every one of those dependencies installed as a wheel: with
  an empty uv cache (`UV_CACHE_DIR` fresh) and an empty `CARGO_HOME`, the
  only source build in the log was `Building maniml` itself. So nothing
  in the dependency set needs a compiler; only maniml does, for the
  helper. (A wheel per platform on PyPI would do the same job as the
  bundle and would also fix the README's `--force-reinstall` trap; either
  is a build step this branch does not add.)

**How long, and how big.** Measured on this Mac (M-series, fast
network), uv 0.12.7, Python 3.13.15 already managed by uv:

| step | time | size |
| --- | --- | --- |
| `uv venv --python 3.13` (Python already present) | 0.04 s | (Python ~40 MB when not) |
| `uv pip install <worktree>`, warm uv cache, cargo warm | 4.0 s | |
| the same with empty uv and cargo caches | 6 s | 246 MB downloaded, 42 packages |
| the venv | | 243 MB |
| first engine start after the install, to the probe answering | 14.3 s | |
| later starts (`import maniml.web.cli`) | 1.5 s | |

The shell's 25-second deadline on the first start holds, but not by
much; the 14 s is the first read of freshly written packages (the same
venv imports in 14.4 s then 1.5 s with bytecode writing off both
times), not compilation, and the shell's progress line ("Starting
Python…") covers it. A clean machine with a slow connection adds the
downloads: uv 18 MB if none, Python 40 MB, and the 246 MB of wheels,
of which scipy is 73 MB installed, matplotlib 24, numpy 22, manimpango
18, PyObjC 26 (pulled in by `screeninfo` on macOS), PyOpenGL 16 and
Cython 12 (with `moderngl`, for the reference GL camera), fontTools 14,
Pillow 14, wgpu 8. The list has fat that a port could trim (the GL
reference camera's two packages and `screeninfo`'s PyObjC are 55 MB for
things the shell's window never uses), but that is a maniml decision,
not the shell's.

## 2. WebGPU

**Yes, with no flag.** The shell's window has `contextIsolation`,
`sandbox: true` and `nodeIntegration: false`, and was started with no
switch beyond the remote-debugging port. In the viewer, `navigator.gpu`
was present, `requestAdapter()` returned an adapter, the renderer
selector showed Default / Phase A / Phase B / Original 2D, the status
read Connected at 1 / 4, and two RIGHT keys (dispatched through the
DevTools protocol to the focused canvas) stepped it to 3 / 4 with the
title, the blue circle and the red square drawn on the stage; the
screenshot was taken by Chromium from the window's own compositor. It
rendered while `document.hidden` was true (the window was behind the
desktop app that ran the experiment), so the swap chain is not gated on
visibility. This matches the 2026-09-29 prototype's finding (the APFS
clone with the sandbox on, WebGPU up) and adds that it holds under the
shell's own window settings and permission handler. Nothing for the
config to set.

Two side notes from the same run: the landing page registered its
service worker against `http://127.0.0.1:8690/` inside the shell's
Chromium profile (harmless in the scratch state folder, but in a port
the install button and `sw.js` have no job in the shell, since the
window is the app), and the worker's `background-sync` check was
refused by the shell's permission handler and logged once, as designed.

## 3. The protocol

What ManimLive's page asks its engine for today, and what each would
need from the shell:

- **File open.** The landing page's Open button sends the engine
  `{"op": "choose"}`; the engine runs `choose_python_file` in
  `maniml/desktop.py` (an `osascript` dialog on the Mac, PowerShell on
  Windows, zenity or kdialog elsewhere) and grants the chosen file. In
  the shell this still works as it is, but the dialog belongs to the
  engine process, so it is not a sheet of the window. The shell's `open`
  request gives the window's own panel; the page would send that and
  then the engine's existing `{"op": "open", "path"}`. Two gaps: the
  shell's `open` panel has no file filter (Knuth opens anything), so a
  `filters` field on the request (`[{name, extensions}]`) is the one
  shell addition worth making; and the engine must accept the path,
  which is question 4's authorization point.
- **Fullscreen.** Nothing missing. The viewer's button calls
  `document.documentElement.requestFullscreen()`, the shell grants
  `fullscreen` to its own pages by default, `document.fullscreenEnabled`
  read true in the window, and the View menu has Electron's
  `togglefullscreen`. Not clicked in this run (a real gesture is
  required), and no refusal was logged.
- **Keep-awake while rendering.** ManimLive has none today (nothing in
  the page or the engine takes a wake lock; a render is a headless
  `--render` run). `navigator.wakeLock` exists in the window; a
  `request('screen')` failed with "the requesting page is not visible"
  both before and after `Page.bringToFront`, because the window was
  occluded for the whole run, so whether Chromium grants it in the shell
  is unverified (no `refused screen-wake-lock` line reached the log,
  which is what a refusal by the handler would write). If the web API is
  refused, the shell has `powerSaveBlocker` and a `keepAwake {on}`
  request would be a dozen lines; not needed until ManimLive has a
  reason to hold the screen.
- **"Open this scene file".** The shell already delivers it as
  `?open=<absolute path>` on the page URL (Finder, the command line, a
  second launch); question 4 covers what the page does with it. The
  shell's `openBy: "drop"` is for handle-based pages and is not wanted:
  the engine needs the path, and gets it.
- **Files by path** (`read`, `write`, `stat`, `rename`, `remove`): not
  needed; the engine does its own files, and the page never reads a
  file.

So, exactly: nothing the shell lacks blocks a port. One addition is
worth making (file filters on `open`), and one is conditional
(`keepAwake`, only if the Wake Lock API turns out refused and ManimLive
wants it).

## 4. Documents

A Finder double-click means a `.py` scene file: `documentTypes` names
`public.python-script`, role Viewer, rank Alternate, so ManimLive appears
in Open With and takes nothing from VS Code, the same rule Knuth chose.
There is no other document type: the exports (`media/<Scene>.mp4`, the
web and student bundles) are outputs, not documents to open.

The shell opens it as `http://127.0.0.1:N/?open=/abs/path/scene.py` in a
new window (or, before the engine is up, holds it in `pending` and opens
it on the first window). **Today `app.html` ignores the query** and shows
the landing page; the file is not opened. The page needs a few lines:
read `open` from `location.search`, call its own `openScene(path, null)`
(the function the recents rows already use), and it lands on
`viewer.html?scene=<id>` at the file's first scene, with the viewer's
picker for the others. Each window is its own scene process, so two
double-clicks are two viewers on one engine, which `AppServer` already
supports.

The authorization point: `open_payload` accepts a path outside the
engine's root only with `allow_outside_root` or when the path was
granted (`grant_file`, which exists for this and is unused). Today's
launcher runs `maniml app ~`, so anything under the home folder is
inside the root already and a Finder open from there just works; a file
on another volume would be refused with "path is outside the app
root". The app plan's note about granting paths over the engine's stdin
stands for that case; the experiment ran with `allow_outside_root=True`
in the wrapper, which is the wrong answer for a product.

## 5. Sizes and first launch

The download, before Electron's framework:

| part | size |
| --- | --- |
| the shell (launcher, helper apps, update frameworks) | ~1.3 MB, "3 MB" with the app's icon and plist |
| `maniml` package source (`Resources/python/maniml`) | 2.4 MB |
| the Lyon helper, prebuilt for the platform | 0.5 MB |
| the setup page | negligible |

About 4 to 5 MB. Electron's framework (287 MB) is cloned from an installed
sibling on the same Electron version or downloaded (130 MB zip), as the
plan says; nothing about ManimLive changes that.

The first launch installs, in order and only what is missing: uv (18 MB,
skipped when any uv is on the machine), a managed Python 3.13 (~40 MB),
and the dependency wheels (246 MB down, 243 MB on disk; 6 s here, minutes
on a slow connection), then starts the engine (14 s the first time).
LaTeX, dvisvgm and ffmpeg are not part of it; the engine's `search_path`
finds them where the user has them, as today.

## Shipped the same day

The four pieces above, on this branch, verified by running the shell on
`app/maniml.json` (the config, no scratch wrapper) and by building and
smoking the app:

- `maniml app` takes `--port N` and `--parent PID` (the `app` branch of
  `maniml/__main__.py` parses its arguments with argparse now; `cli.
  watch_parent` polls the pid and stops the server, `cli.parent_alive`
  with a Windows implementation that is a liveness test). A parent implies
  no browser tab and no agent offer.
- The engine accepts `http://127.0.0.1:<port>` as its own origin.
- `app.html` opens `?open=<path>` once its control socket is ready, and
  drops the query from the address. The viewer's `document.title` is the
  file name, so the window is titled like a document app's.
- `MANIML_CONFIG_DIR` is where the recents list lives when the shell sets
  it (`library.recents_path`).
- `app/maniml.json`, `web/static/setup.{html,js,css}` (Knuth's setup page
  with one option), `tests/test_shell_config.py` (the config's
  requirements are `pyproject.toml`'s dependencies; the marker, setup page
  and icon exist; the probe is in the landing page; documents are `.py`
  and never the default handler; the parent watch stops the engine; the
  recents path follows the config dir). The bundle carries the package
  with the prebuilt helper (2.9 MB in `Resources/python`), so the
  first-launch install is the dependency wheels alone, no cargo.
- The engine's root: `--allow-outside-root` in the config's args. A path
  that reaches the page in the shell is a user action (Finder, the Open
  panel, the command line), the page has no other way to name one, and
  the Origin check keeps other pages out. Without it, a Finder open from
  another volume is refused as "outside the app root" (seen in the run,
  with the scratch scene under `/private/tmp`).

Verified: the shell on the config, with a scene file on the command line,
refused it outside the root and, with a copy under home handed to the
running shell by a second launch, opened a viewer window titled
`scene.py` at 1 / 4, stepped it, and wrote the recents list into the
config folder; `package.mjs --install` built `ManimLive.app` (staged under
`app/build/`, now ignored) and `smoke.mjs uv` on that bundle passed: a
throwaway config, uv's Python, the dependencies installed, the document
opened, the viewer connected.

One shell change, made in the `claerbout` checkout and not committed
there: `package.mjs` required an `index.html` in the page folder, which
only an app that serves its page from the bundle has; it now requires it
only when `pythons` includes `browser`, and requires the setup page
instead. It is six lines, for Taylor to take into the shell.

Left for later: the Windows corners (the parent watch has a Windows
implementation, untested there); the dependency trim; whether `app/`'s
script launcher stays beside the config.

## Verdict

The port is a config file plus one small shell addition, but it needs
four small pieces of ManimLive-side work first, all of which the
experiment had to scaffold or patch around: `maniml app --port N
--parent PID` (parse the two flags in the `app` branch and watch the
parent, ~30 lines; the shell's `MANIML_CONFIG_DIR` should also become the
recents file's home); the engine accepting `http://127.0.0.1:<port>` as
its own origin (the two lines in this worktree); `app.html` acting on
`?open=<path>` (a few lines, plus the grant for paths outside the root);
and, the one with a build step, shipping the Lyon helper prebuilt, in
the bundle per platform or as wheels, because uv cannot build it on a
user's machine and could not on this one without an SDK override. On
the shell side nothing was needed to get a scene rendering; a `filters`
field for the `open` panel is worth adding, and a `keepAwake` message
only if the Wake Lock API is refused, which this run could not tell.
WebGPU needs no flag. Everything else, including the dependency set's
55 MB of packages the window never uses, is a ManimLive decision that
the port does not wait on.
