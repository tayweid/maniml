# Contributing to ManimLive

ManimLive is preparing for its first public release. Keep changes focused,
backward-compatible where practical, and covered by tests. Scene files are
trusted Python programs, but browser clients and requested filesystem paths are
not trusted; changes must preserve the boundaries documented in `SECURITY.md`.

## Development setup

Install [uv](https://docs.astral.sh/uv/) and create the locked development
environment:

```console
uv sync --locked
```

Run display-independent checks with:

```console
uv run --locked python -m unittest \
  tests.test_ce_extractor \
  tests.test_web_security \
  tests.test_safe_text_cache \
  tests.test_headless_import \
  tests.test_app_protocol \
  tests.test_export_publication \
  tests.test_external_processes \
  tests.test_remote_assets \
  tests.test_scene_lifecycle
```

The OpenGL and interactive suites require a working display. CI runs the
headless subset under Xvfb; before a release, the windowed interactive suite is
also run on macOS.

## ManimCE compatibility

ManimLive targets current ManimCE behavior. The checked-in public API reference
is harvested from ManimCE source with Python's AST; upstream code is not
imported or executed:

```console
python -m tests.ce_conformance.extract_ce_names ../manimce --check
```

When upstream API drift is reviewed deliberately, regenerate
`tests/ce_conformance/ce_api_names.txt`. Update
`tests/ce_conformance/supported_names.txt` only when ManimLive's supported
surface intentionally changes. Compatibility fixes should include a minimal
scene or regression test.

## Pull requests

- Explain user-visible behavior and compatibility implications.
- Test the smallest relevant surface, including native and browser paths when
  both are affected.
- Add a changelog entry for user-visible changes.
- Do not commit generated media, environments, credentials, or capability
  tokens.
- Report vulnerabilities privately as described in `SECURITY.md`.
