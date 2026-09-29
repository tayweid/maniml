# ManimLive.app

Written 2026-09-28, revised 2026-09-29 when the shape was chosen. Taylor's
direction, quoted: "getting this more polished is the goal. right now it needs
the terminal and the app and it's a little clunky feeling"; and, choosing:
"the main goal is getting off the terminal usage. for some reason the fact that
it needs both the pwa and the terminal maintained separately is annoying and
feels janky. and then for it to be easily updatable and on a path for
consistency with knuth and plass so i don't need to understand many systems."
Status: step 1 built on the `app-plan` branch; steps 2-4 not started.

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

## The suite, later

Taylor would like Plass, Knuth and ManimLive on one cross-platform platform,
"but it has to make sense." What was learned on 2026-09-29, for when Windows
matters:

- **What each app needs.** Plass was built and tested on Chromium (its CI and
  port audit run Chromium; its file layer is written for Chromium's file API);
  on the Mac it matches through a private WebKit flag
  (`SubpixelInlineLayoutEnabled`) whose failure would be silent. Knuth does not
  care about the engine. ManimLive needs WebGPU and gains from V8.
- **Tauri 2** (stable) uses the system webview: WKWebView (JavaScriptCore;
  WebGPU on macOS 26+ only), WebView2 on Windows (Chromium, V8, WebGPU on), and
  WebKitGTK on Linux (no WebGPU; Plass's parity there "would say nothing"). A
  page on `http://127.0.0.1` can call the shell with an explicit `remote`
  capability (Tauri ≥ 2.11.1). Knuth v1's Tauri pain came from Tauri serving
  the whole UI and doing all file I/O in Rust; a thin shell over an engine
  mostly avoids it.
- **Tauri 3** (alpha since 2026-09-13) picks the runtime per app,
  system webview or CEF (Chromium 152), behind one API. CEF adds ~150-170 MB
  per app; the bundler's shared-CEF option is for development, not users.
  Early: no Windows sandbox under CEF, intermittent child-process
  disconnects on macOS.
- **Electron 44** is Chromium 152, a 124-130 MB zip per app per OS, a new
  major every eight weeks with three supported, and no shared runtime.
- **The installed browser** (this launcher) costs nothing and gives each app
  the Chromium it was built on, at the price of the window belonging to the
  browser. Frameworks built on the idea (Lorca, Carlo, Eel) are archived.
- **Distribution holds either way**: GitHub Pages deploys through Actions take
  a ~1 GB artifact with no 100 MB per-file limit, so even a ~150 MB zip can sit
  beside the site under the Knuth/Plass standard.

A plausible path, not a decision: the launcher shape for ManimLive now; Tauri
3 with CEF for the apps that need Chromium and the system webview for Knuth
once it is stable; one page-to-shell protocol across the three pages (dialogs,
files by path, grants, fullscreen, keep-awake, opened-file events) so that a
shell change rewrites only the host side.
