# ManimLive.app

Written 2026-09-28, revised 2026-09-29 when the shape was chosen. Taylor's
direction, quoted: "getting this more polished is the goal. right now it needs
the terminal and the app and it's a little clunky feeling"; and, choosing:
"the main goal is getting off the terminal usage. for some reason the fact that
it needs both the pwa and the terminal maintained separately is annoying and
feels janky. and then for it to be easily updatable and on a path for
consistency with knuth and plass so i don't need to understand many systems."
Status: step 1 built and merged (2026-09-29), then retired 2026-10-01 when
ManimLive moved onto the Claerbout shell (`docs/claerbout_experiment.md`,
`app/maniml.json`), which is the Electron direction below carried out. Of
the Next list, the one-line install and Windows remain, now the shell's work
shared with Knuth and Plass. The suite's direction, decided the same day, is
the last section: Electron for all three Claerbout apps, one Chromium shared
on disk. Knuth went first and
shipped on it 2026-09-29/30; what that taught is at the end of the last
section.

## The decision

**ManimLive.app is a launcher script, the shape of Edit <course>.app.** The
course editor app that started this is a 1.4 KB bash script as the bundle's
executable: it starts a local server and opens the browser, and the server
stops itself a few minutes after its last tab closes. ManimLive.app is the
same (`app/ManimLive`, installed by `app/build.sh`):

- Opening it starts `maniml app ~ --exit-when-idle` in the background when no
  engine answers on 8685, then opens the landing page. Opening it again while
  the engine runs just opens another window.
- The window belongs to the browser already on the Mac: an app window
  (`--app=`, no tabs or address bar) of the first Chromium browser installed
  (Brave, Chrome, Edge, Chromium, Vivaldi), else a Safari tab. So the page
  runs on V8 and the WebGPU it is developed and measured on, and nothing is
  bundled. The default browser does not matter: Taylor's is Zen (Firefox 156),
  which has WebGPU but no app-window mode and has never run the viewer.
- The engine stops three minutes after its last window closes (the course
  editor's number), and its scene processes with it: every open page holds a
  socket, the landing page its control socket and a viewer its relay, so
  counting them is the whole rule (`AppServer(idle_exit=)`).
- It runs the maniml that is installed: `app/build.sh` records the Python
  behind the `maniml` command, so for development the editable checkout's
  edits reach the app with no rebuild. A Finder launch gets a bare PATH, so
  the script adds the agent's tool folders (TeX, Homebrew) before Python
  starts, and `run_app` applies `search_path()` too.
- `.py` stays Knuth's: scenes are opened from the app's landing page (recents
  and Open…), never by double-click, so the launcher needs no file-open
  handling and none of the grant design below.

This replaces, for daily use, both the launchd agent and the Chrome PWA. While
the agent holds 8685 the app simply uses it; once the app has proved itself,
`maniml agent uninstall` and removing the PWA leave one system.

**The `--app` switch** is an old Chromium command-line switch, not a documented
API. What Google is retiring is Chrome Apps (the packaged-app platform, end of
life in stages through 2028), not the switch; if the switch ever went, the
launcher opens a tab instead, a one-line change.

## Next

(Written for the launcher. 2026-10-01: item 1 is moot, the shell's app has
an engine and a port of its own; item 2 is done the shell's way, with no
wheel — `.github/workflows/deploy.yml` builds the app on a GitHub Mac with
the Lyon helper in the bundle and publishes the zips, the install line and
`latest.json` beside the site, and the app updates itself from there; item
3 is Windows, shared with Knuth; item 4 stands.)

1. **Retire the agent and the PWA** once the app is the daily driver (Knuth's
   step 5 did the same): `maniml agent uninstall`, uninstall the PWA in Chrome,
   and drop the page's install offer.
2. **A one-line install for others**, the Knuth/Plass distribution standard:
   the deploy builds maniml's wheel on a GitHub Mac with the Lyon helper
   compiled (CI's release-candidate job already does), publishes it beside
   the site with the app zip, and `curl -fsSL https://maniml.tayweid.io/install
   | bash` sets up ManimLive's own Python with uv from that wheel (pinned from
   `uv.lock`) and puts the app in Applications; running it again updates. The
   launcher already looks for that Python
   (`~/Library/Application Support/ManimLive/engine/bin/python`) after the
   recorded one.
3. **Windows, when students need it**: the same launcher as a PowerShell
   script with Edge (always installed, Chromium, WebGPU on by default) in
   `--app` mode, plus a Windows wheel. The engine has Mac-only corners to fix
   first (the agent, tool discovery; Knuth's report found its `--parent`
   check uses `os.kill(pid, 0)`, which is not a liveness test on Windows).
4. **TeX for anyone else**: the course scenes lean on MathTex (B5_Animation.py
   alone has ~250 lines of it), and maniml runs `latex` and `dvisvgm`. The
   Typst/mitex backend in TODO.md removes that prerequisite; the `typst`
   wheel is self-contained. ffmpeg (Present plays the rendered mp4) comes from
   Homebrew or `imageio-ffmpeg` (a 21 MB arm64 wheel).

## Why not a WebKit window of its own

The first draft of this plan was Knuth's shell: Swift + WKWebView, with the
page served by the engine. It works, and it was measured before choosing.

**The engine, measured (2026-09-29).** The live viewer in a WKWebView
configured as Knuth's windows are, against Chrome 154 driven by Playwright,
with one instrumentation script injected in both: JavaScript around the
driver's `ManimlWGPU.render` per frame, `queue.submit` → `onSubmittedWorkDone`
per submit, the rAF cadence, the geometry queue's depth, and every error. Fresh
scene processes at `efcb262c` (retained frame on, format 8), the same plan in
both (RIGHT through the first five to eight pausepoints; on the 3D episodes a
60-move orbit and eight wheel ticks each way), ABBA order, Apple M3, macOS
26.6.2. The two were sent the same stream (EpisodeB2: all 410 and 423 messages
the same length, in order).

| Episode, stack | JS ms/frame, WebKit (med / p95 / max) | Chrome | GPU ms/submit, WebKit | Chrome | Late refreshes, WebKit / Chrome |
| --- | --- | --- | --- | --- | --- |
| EpisodeB2, Default | 3 / 11 / 27 | 1.1 / 3.5 / 6.4 | 6 / 11 / 20 | 6.5 / 13.4 / 27.9 | 6 / 0 |
| EpisodeB2, Phase B | 1 / 19 / 203 | 0.7 / 4.7 / 18.8 | 7 / 15 / 53 | 7.5 / 22.6 / 187 | 14 / 2 |
| EpisodeB3, Default | 2 / 11 / 12 | 0.8 / 3.1 / 4.4 | 6 / 9 / 22 | 7.7 / 11.4 / 26.8 | 0 / 0 |
| EpisodeB3, Phase B | 1 / 21 / 62 | 0.9 / 4.6 / 11.6 | 6 / 16 / 21 | 8.8 / 25.6 / 65.3 | 14 / 0 |
| B4, Default | 2 / 11 / 13 | 0.8 / 3.1 / 4.4 | 5 / 9 / 17 | 5.8 / 12.5 / 23.1 | 0 / 0 |
| B4, Phase B | 1 / 18 / 60 | 0.9 / 4.7 / 13.3 | 7 / 15 / 24 | 6.8 / 22.8 / 71.6 | 13 / 1 |

A late refresh is an interval over 1.5× the median rAF interval (16.7 ms).
Everything draws in both: every step settled at the same checkpoint, same
frame counts, no catch-up, no GPU validation error (the one device loss per
Phase B run is the renderer switch replacing the device, in both). The GPU is
at parity. JavaScriptCore runs the driver 2.4-2.9× slower than V8 over every
run: inside a refresh on the default stack, but Phase B's largest frames
(230-450 KB) take 20-40 ms in WebKit against 4-11 in Chrome, and the session's
first Phase B run had two frames of 111 and 203 ms (Chrome 9-12), consistent
with the driver building pipelines lazily and synchronously (seven
`create*Pipeline`, no `…Async`). Caveats: the screen was locked, so WebKit's
occlusion throttling was switched off in the harness and Chrome ran with
`--disable-backgrounding-occluded-windows` (cadence synthetic, per-frame costs
real); WebKit's `performance.now()` is quantized to 1 ms; one repetition. The
harness lived in the session's scratch space. WKWebView also reports
`document.fullscreenEnabled` false unless a shell turns element fullscreen on,
so the viewer hides its fullscreen button there.

So a WebKit shell would have been a second engine to trust on the Mac, with a
Phase B cost, to buy a window identity. Borrowing the browser's window buys
V8 and the development engine for nothing. What the WebKit route would still
want, if it ever comes back: pipelines created with the `…Async` calls and
warmed at init, and cheaper large frames, which help Chrome too.

**What a native shell needed that the launcher does not.** Opening a scene
runs it, so a shell that delivers Finder opens as `?open=<path>` must grant
paths over a channel no web page reaches (the engine's stdin; the unused
`AppServer.grant_file` exists for it) and give its engine no broad root. The
launcher opens no paths, so none of that is needed until the app handles
double-clicks.

## Claerbout: Electron for all three apps

Decided 2026-09-29. Taylor, after the shared-Chromium prototype worked: "that
opens up Electron as the path for all apps in Claerbout." The audiences set the
order: Knuth on Windows for next semester, as an optional alternative to
Google Colab for students; Plass opened to researchers soon; ManimLive for a
narrower audience that is active and avid.

**One shell template, three apps.** The shell is written once, as Electron
(JavaScript; as built, plus one small compiled launcher, below), and built three times: Knuth.app, Plass.app and
ManimLive.app, each with its own name, icon, Dock entry, menus, file types and
install line (Taylor wants separate icons; a single suite app hosting all three
kinds of window was ruled out for that). Each app keeps its engine, which
serves its page: Knuth's and ManimLive's Python engines, and a small one for
Plass (its page, files by path, the Open and Save dialogs: what its Swift shell
does today minus the window; Python via uv like the others). The pages talk to
the shell through one small protocol (dialogs, files by path, fullscreen,
keep-awake, "open this file" events) in place of today's three
(`window.webkit.messageHandlers.knuth`, Plass's `native-fs.ts`, ManimLive's
engine-side dialogs).

**Why Electron.** Chromium everywhere: it is Plass's reference engine (its CI
and port audit run it, no private WebKit flag, its file layer is written for
Chromium's API), ManimLive's (V8 and the WebGPU it is developed on) and
indifferent to Knuth; the same engine on Mac, Windows and Linux. Tauri 2 would
split the engines (WebKit on the Mac, WebKitGTK on Linux, where Plass loses
parity and ManimLive loses WebGPU); Tauri 3 with CEF is the same idea in alpha.
Electron is what VS Code, Obsidian and Slack ship. The development loop does
not slow: the shell restarts without a compile, and the pages load from their
engines or Plass's Vite dev server as they do now, with Chrome's DevTools.

**One Chromium on disk, by APFS clones.** Electron.app 44.4.5 (macOS arm64) is
288 MB unpacked, 286 MB of it `Electron Framework.framework`; the launcher, four
helper apps and three small update frameworks come to 1.3 MB. The prototype
(2026-09-29, scratch only) tried three ways to share the framework:

- *A load path* in the launcher and helpers. Electron's programs have no header
  pad, so a new path cannot be added, but replacing the existing one fits up to
  67 characters (`/Library/Application Support/Claerbout/Electron-44` is 50).
  Chromium then loads from the shared folder, and Electron traps at startup:
  it looks for the framework's data files at
  `<App>.app/Contents/Frameworks/Electron Framework.framework`, hard-coded.
- *A link* at that spot. The main process starts, but the sandboxed GPU and
  network helpers crash: the macOS sandbox lets them read inside the app
  bundle only, and it judges the real path behind a link. With `--no-sandbox`
  the viewer ran; with the sandbox, neither a link nor a load path can work.
- *An APFS clone* of the framework into each app (`cp -c`): 287 MB in 0.07 s,
  no change in free space, a completely standard Electron app (stock
  programs, stock load path, Chromium inside the bundle). With the sandbox on,
  ManimLive's viewer ran on Chrome 152 / V8 15.2 with WebGPU up and stepped a
  scene.

**Clone from a sibling app, not from a shared folder** (Taylor's refinement,
the same day). A clone is an independent copy, so no folder of its own is
needed: each app's download leaves Chromium out (1-2 MB), and its install line
looks for an installed Claerbout app on the same Electron version (the
framework's `Resources/Info.plist` records it: `CFBundleVersion` 44.4.5) and
clones that app's frameworks in; with none, it downloads Electron's release
for that version from GitHub (130 MB) and checks the published SHASUMS256.
Updates do the same. Every app is then complete on its own: deleting one never
breaks another, nothing is left behind, and an old version's space frees
itself when the last app on it updates, where a shared folder would need its
old versions collected. Rules: clone only an exact version match; an app on
another volume cannot clone, so it downloads; Electron's framework is only
ad-hoc signed (no identity to verify), so if a check is wanted, each app can
carry the expected hash of its framework and compare before cloning. Clones
share space only on one APFS volume, the internal disk of every current Mac,
and Finder and `du` still count each app in full. Windows keeps a copy per app
for now.

**Order.**

1. The shell template, with Knuth on it for next semester, Mac and Windows.
   DONE on the Mac 2026-09-29/30 (knuth `app/shell/`, design and record in
   knuth `docs/APP.md`, "Electron, one shell for Claerbout"); Knuth's Swift
   source stays until the Electron app has proved itself. Windows is on hold
   (Taylor, 2026-09-30); it needs the engine's Mac-only corners fixed (its
   parent-process check uses `os.kill(pid, 0)`, which is not a liveness test
   there), a PowerShell install line in the shape of uv's own, and the
   Windows leg back in CI.
2. Plass on the template when it opens to researchers (its ROADMAP.md has
   the Plass-specific notes).
3. ManimLive on the template when it is worth it; its launcher (above) serves
   until then.

What was ruled out, and why, for the record: a WebKit window per app (a second
engine to trust, Plass's private flag, Mac-only); Tauri 2 (split engines);
Tauri 3 with CEF (alpha; its shared-CEF mode is for development); the user's
installed browser for all three (the window and menus belong to the browser;
Brave switches off the file-picker API Plass's file layer uses); a
shared-framework load path or link (the sandbox, above); a shared runtime
folder in Application Support (cloning from an installed sibling shares the
same disk with nothing hidden to manage). GitHub Pages holds a
~150 MB zip beside a site (a ~1 GB artifact, no 100 MB per-file limit), so the
Knuth/Plass distribution standard carries Electron apps unchanged.

### What building Knuth on it taught (2026-09-29/30)

The details and the measurements are in knuth `docs/APP.md` ("What building
it found"); these are the ones every Claerbout app inherits.

- **Where the template lives.** In knuth for now: the generic shell is
  `app/shell/` (`main.js`, `preload.js`, `launcher.swift`, `complete.sh`),
  each app's particulars one JSON config (`app/knuth.json`: name, bundle
  id, env prefix, port, scheme, engine command, file types, icon). It
  moves to its own repository when a second app uses it. Packaged with
  `@electron/packager` by `app/package.mjs`.
- **The page protocol** is `window.claerbout.request({type, ...}) →
  Promise` and `window.claerbout.on(event, listener)`, exposed by the
  preload over one IPC channel that checks the sender's origin. Node's URL
  gives a custom scheme the origin `"null"`, so the bundled page is
  recognized by scheme and host.
- **Electron's framework must stay Electron's exact bytes**, or it cannot be
  cloned from a sibling or replaced by Electron's release. The packager
  breaks this by default: since Electron 41 it writes an asar's integrity
  digest into the framework binary and re-signs it. So: `asar: false`, and
  no fuses (also bits in that binary). Each app records the framework
  binary's SHA-256 and the Electron version in its Info.plist
  (`ClaerboutFrameworkSHA256`, `ClaerboutElectronVersion`); a sibling is
  cloned, or a download accepted, only on an exact hash match. Only
  `Electron Framework.framework` is left out and shared; the three small
  frameworks stay in each app.
- **Signing without a Developer ID.** The packager's renamed helper apps and
  Electron's Mantle, ReactiveObjC and Squirrel frameworks all need fresh
  ad-hoc signatures: the stock small frameworks fail `codesign --verify
  --deep --strict`, and a browser download's Gatekeeper checks deeply and
  calls the app "damaged", with no Open Anyway. Re-signed, it gets the
  ordinary "Not Opened" and Open Anyway, as the Swift apps do. Arm64 only;
  Electron's x64 release is unsigned and Intel Macs run it so.
- **The app completes itself, and every launch is one flow** (Taylor: "open,
  check for electron, if it's there, use it, if not, find it, then run").
  Every zip, the site's download button's too, is the app without the
  framework (2.8 MB for Knuth). The bundle's executable is a compiled
  launcher: framework present, it `execv`s Electron before touching AppKit;
  absent, it shows a progress window, runs `complete.sh` (the same script
  the install line runs: clone from a sibling, else download and check),
  then `execv`s Electron with the launch's documents as arguments. Opened
  from Downloads (App Translocation, read-only), it asks to be moved first.
  It has to be compiled: any AppKit process a launch starts (a script's
  `osascript` window, even windowless) takes the launch's "open document"
  event and loses it, and Apple's `osascript` cannot be copied into the
  bundle (it is killed on launch). Verified by hand through a real browser
  download (2026-09-30).
- **macOS 13** is Electron 44's minimum.
- **No service worker inside a shell**: it can only serve a stale page there,
  and under Playwright's debugger a registered one wedges navigation.
- **Chromium's storage** goes inside the app's own config folder
  (`app.setPath('userData', …)`), so a test config folder isolates the page
  too, and removing the folder resets everything.
- **Testing**: Playwright drives Electron (`_electron.launch`); knuth's
  `app/smoke.mjs` launches a built app on a document in a throwaway config
  folder and checks the result, and the deploy runs it on the installed app
  and on a download completing itself. A single-instance lock hands a
  second launch to a running one, so tests must be sure the last instance
  is gone.
- **Plass may not need an engine.** Knuth's shell already serves its page
  from a custom scheme and does the file operations itself in the main
  process (its in-window Python mode), which is most of what the "small
  engine for Plass" above was for. OPEN until Plass is ported.
