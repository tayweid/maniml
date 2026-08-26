# Changelog

Notable user-facing changes are recorded here. ManimLive is currently alpha;
interfaces may still change before the first public release.

## Unreleased

### The viewer

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

- New `--export-present`: renders the scene and writes
  `media/<Scene>_present/`, a self-contained folder — a page that steps
  through the episode by pausepoint, both directions, plus the mp4 —
  for hosting on a course site so students can click through an episode
  with no engine anywhere. Opens from `file://` too. The viewer's own
  presentation cache (mp4 + pausepoints table) is unchanged.
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
