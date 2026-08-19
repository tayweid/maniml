# Working on ManimLive

ManimLive is alpha software with a single maintainer, developed in the
open. Issues and small fixes are welcome; large changes are worth an
issue first, because the architecture is opinionated and in motion
(`CLAUDE.md` explains it, and `TODO.md` says where it is going). Scene
files are trusted Python programs, but browser clients and requested
filesystem paths are not; changes must preserve the boundaries
documented in `SECURITY.md`.

## Development setup

Install [uv](https://docs.astral.sh/uv/) and create the locked
development environment:

```console
uv sync --locked
```

Install editable so the `maniml` command runs your working tree
(`pip install -e . --no-deps`), and see the install trap in `CLAUDE.md`
before debugging anything user-visible.

## Tests

The full display-independent suite:

```console
python -m unittest discover -s tests -t .
```

CI's job definitions in `.github/workflows/ci.yml` are the canonical
list of what runs where — when adding a test module, add it there. The
current developer preview targets macOS; CI runs on macOS 14, and the
windowed interactive suite (`MANIML_WINDOW_TESTS=1`) is run manually
before a release. Windows and Linux testing returns after the WebGPU
renderer transition and cross-platform packaging work.

## ManimCE compatibility

ManimLive targets current ManimCE behavior. The checked-in public API
reference is harvested from ManimCE source with Python's AST; upstream
code is not imported or executed:

```console
python -m tests.ce_conformance.extract_ce_names ../manimce --check
```

When upstream API drift is reviewed deliberately, regenerate
`tests/ce_conformance/ce_api_names.txt`. Update
`tests/ce_conformance/supported_names.txt` only when ManimLive's
supported surface intentionally changes. Compatibility fixes should
include a minimal scene or regression test.

## Changes

- Explain user-visible behavior and compatibility implications; commit
  messages here are prose that says why.
- Test the smallest relevant surface, including native and browser paths
  when both are affected.
- Add a changelog entry for user-visible changes.
- Do not commit generated media, environments, or secrets.
- Report vulnerabilities privately as described in `SECURITY.md`.
