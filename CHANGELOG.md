# Changelog

Notable user-facing changes are recorded here. ManimLive is currently alpha;
interfaces may still change before the first public release.

## Unreleased

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

### Compatibility and reliability

- Made package imports, star imports, and CLI help safe without a desktop
  display while preserving the existing native Pyglet window backend.
- Decoupled shared scene and browser input handling from Pyglet imports, with
  regression checks that its key and mouse values remain native-compatible.

### Packaging and release engineering

- Replaced inherited ManimCE publishing workflows with project-specific CI,
  CodeQL, Pages, and manual release-candidate workflows.
- Added a non-executing weekly check for public-API drift on ManimCE `main`.
- Added validation of wheel metadata and bundled browser assets.
- Aligned declared and tested Python support with current ManimCE at Python
  3.11 through 3.14.
- Restored audio support on Python 3.13+ through `audioop-lts`.
