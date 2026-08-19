# Changelog

Notable user-facing changes are recorded here. ManimLive is currently alpha;
interfaces may still change before the first public release.

## Unreleased

### Delivery

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
