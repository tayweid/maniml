# The retained frame's golden pin

blake2b-128 digests of the bytes `maniml.web.geometry.serialize_scene`
produces, frame by frame through one persistent `GeometryCache` per case
and renderer, for `renderer="triangles"` (Phase A) and `"phase_b"`. They
were recorded from the serializer as it stood before Phase B4's first
increment (docs/phase_b4_plan.md, B4.0) and are the contract every
increment of the retained frame holds: with `MANIML_RETAINED_FRAME=0` the
bytes may not move, and with the retained frame on, the default since
B4.5, they are the flag-off bytes. The pin runs with the run's switch; CI
runs it with the default, with the switch at 0 and under
`MANIML_VERIFY_LEDGER=1` (`.github/workflows/ci.yml`), and so should a
local proof of a change to the serializer.
`tests/test_retained_frame.py` asserts them and describes each case. Every
case records the frame contract its bytes assume (the CE config's pixel
resolution and frame height) as part of its `input`; a case whose input
differs from the recording's is skipped with the reason, not failed.

- `renderer_fixtures.json` — every case of `tests/renderer_fixtures.py`:
  a cold frame, a still, a pan, a zoom out and the zoom back.
- `quality_fixtures.json` — every case of `tests/renderer_quality_fixtures.py`,
  the same frames. The TeX cases carry the fixture's source digest as their
  `input`: TeX glyphs are the installation's, so a machine whose TeX builds
  other paths skips them rather than failing them.
- `synthetic.json` — the cases that carry what the per-record loop must
  preserve, since they run everywhere (CI has no episodes):
  - `scripted_sequence`: one scene through still ×3, a mobject added, one
    removed and later added back, a child's z_index up and back, a shift,
    the stroke put behind the fill and in front again, a pan, a zoom out
    and back, a cache reset, a dot cloud emptied and refilled, a 6× zoom
    in that grows the border and net reservations and the zoom back that
    keeps them, and a play that moves only uniforms.
  - `scene_render_groups`: a real `Scene`, whose render groups are the
    batches `Scene.add` assembles: two families with one batch key split
    by a fixed-in-frame overlay (the fixed group draws last, the two
    rejoin and a child's z_index lifts it over the other family), two
    leaves whose equal uniforms are spelled `1.0` and `1`, the overlay
    unfixed and fixed again, a top-level z_index change and the re-add
    that applies it, and a play recorded as GPU programs.
  - `textures`: an image and a textured surface, still, moved, and after
    a cache reset (the texture bytes are sent again); the texture file's
    digest is part of the case's `input`.
  - `run_cap`: a row of bordered discs under a lowered run output cap, so
    their border and patch runs split, through the camera moves and a 3×
    zoom; the case fails if the lowered cap stops splitting them.
- `episodes.json` — the course episodes the plan's gates are measured on,
  each with the episode file's sha256 as its `input`: twelve pausepoints
  restored as a navigation restores them, the gate's checkpoint ticked
  once, ten frames spread over the play that arrives there and the landing
  after it. These cases skip where the econ-0100 checkout is absent.

Record with `python -m tests.test_retained_frame --record` (or
`MANIML_RECORD_GOLDENS=1` under any unittest invocation); only the cases
that ran are rewritten. A golden may move only for a reason the commit
that re-records it names.
