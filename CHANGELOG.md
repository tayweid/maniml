# Changelog

Notable user-facing changes are recorded here. ManimLive is currently alpha;
interfaces may still change before the first public release.

## Unreleased

### Desktop workflow

- Added a macOS desktop-launcher preview: one-time `maniml install-desktop`
  setup registers Finder **Open With**, preserves the selected Python
  environment, and starts hosted scenes without a terminal.
- Replaced the landing page's typed absolute-path field with an authenticated
  native file picker that grants only the selected file outside the app root.
- Switched locally launched hosted sessions to `maniml.tayweid.io` and added
  dynamic control ports for concurrent desktop-open sessions.

### Security

- Added independent process-local capabilities and browser Origin checks for
  the app control channel and every scene viewer.
- Confined `maniml app DIR` scene execution to `DIR` by default, including
  protection against symlink escapes.
- Added bounded, strict JSON parsing for localhost control protocols.
- Replaced the generated-SVG pickle cache with a bounded, atomic text cache.
- Made the app accept viewer capabilities only from the child process's exact
  launch-handshake line, preventing terminal log wrapping from truncating the
  token.
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

- Replaced inherited ManimCE publishing workflows with project-specific CI,
  CodeQL, Pages, and manual release-candidate workflows.
- Added a non-executing weekly check for public-API drift on ManimCE `main`.
- Added validation of wheel metadata and bundled browser assets.
- Aligned declared and tested Python support with current ManimCE at Python
  3.11 through 3.14.
- Restored audio support on Python 3.13+ through `audioop-lts`.
