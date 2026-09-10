# Lyon fill helper

This Phase A helper generates CPU fill meshes. The production
serializer integration is in progress. It uses Lyon's fill tessellator and,
for uniform fill borders, its stroke tessellator followed by a fill union.
Existing direct strokes remain separate.

The C ABI has no Python binding code and uses Python's standard `ctypes` module
plus the project's existing NumPy dependency. It is loaded from a platform
binary built by setuptools-rust. Git, editable and
source-distribution installs require Rust/Cargo and the platform linker at
build time. A prebuilt compatible wheel includes the helper and its license
notices. No build occurs at import or render time. A WASM binding is separate work.
No helper binary, Cargo cache, or target directory belongs in the repository.

From the repository root, build with an existing Rust toolchain:

```sh
CARGO_HOME=/private/tmp/maniml-triangle-cargo \
CARGO_TARGET_DIR=/private/tmp/maniml-triangle-target \
cargo build --release --locked --manifest-path tools/lyon_fill/Cargo.toml
```

The macOS output is
`/private/tmp/maniml-triangle-target/release/libmaniml_lyon_fill.dylib`.
Linux uses `libmaniml_lyon_fill.so`; Windows uses `maniml_lyon_fill.dll`.
Only the macOS arm64 build has been exercised for A0. Set `CARGO_HOME` and
`CARGO_TARGET_DIR` to suitable scratch directories on other systems.

```python
import numpy as np
from maniml.web.triangle_geometry import LyonFillTessellator

tessellator = LyonFillTessellator("/path/to/libmaniml_lyon_fill.dylib")
# Manim's anchor, handle, anchor representation, in a chosen 2D space.
path = np.array([[0, 0], [1, 2], [2, 0]], dtype=np.float32)
mesh = tessellator.tessellate([path], tolerance=0.01)
# mesh.positions: (N, 2) float32; mesh.indices: flat uint32 triples.
# mesh.attributes: (N, K) float32; mesh.status: "success" or "empty".
```

The loader uses an explicit constructor path, then `MANIML_LYON_LIBRARY`,
then a packaged `maniml_lyon_fill*.so`, `.pyd`, or `.dylib` beside the Python
adapter, in that order. Python/ABI extension suffixes are accepted. Multiple
packaged candidates fail explicitly rather than picking an arbitrary binary.
Nothing builds or downloads automatically at Python import time. The helper
exports `ml_lyon_abi_version` (currently 1), `ml_lyon_tessellate`, the additive
`ml_lyon_tessellate_border`, and `ml_lyon_free`. Existing ABI1 helpers still
support plain fills; a border request detects a missing new symbol explicitly.
Rust owns temporary output; the adapter copies complete arrays
and always frees the native allocation before returning.

Run the isolated checks using the existing project Python environment:

```sh
MANIML_LYON_LIBRARY=/private/tmp/maniml-triangle-target/release/libmaniml_lyon_fill.dylib \
MPLCONFIGDIR=/private/tmp/maniml-triangle-mpl \
python -m unittest tests.test_triangle_geometry
```

The native cases use the packaged helper or environment override and skip
only when neither exists. A present but
broken/wrong-ABI library fails the tests rather than hiding an installation
error. The checks cover holes, concavity, self-intersections, repeated and
reversed contours, attribute insertion, varying curve tolerance, disappearing
paths, mutable/read-only/strided input arrays, and failure/recovery limits.

## Contract and limits

- `nonzero` is explicit and is the default. `evenodd` is separately opt-in.
- Contours are filled with implicit closure. Empty contours and isolated
  anchors have no covered region. Public source arrays are never modified.
- The caller chooses tessellation coordinates and tolerance. `0.25` denotes
  0.25 pixels only when coordinates are in pixels. Camera/perspective accuracy,
  local-plane extraction, reconstructed normals, and clipping remain caller
  responsibilities. Do not project every 3D path into world xy.
- Optional source attributes have one row per source point. Lyon uses endpoint
  attributes and interpolates inserted vertices; the handle rows are not a
  separate paint definition. At intersections it averages contributions from
  the incident sources. Passing z/RGBA is possible, but neither this policy nor
  triangle interpolation proves parity with existing interior gradients.
- Returned meshes cover the classified fill without repeated interior alpha
  from overlapping helper triangles. Uniform geometric fill borders are
  supported as described below. Smooth antialiasing coverage still requires
  independent rendered-image validation.
- The native ABI caps source points at 65,536, attribute width at 32, vertices
  at 1,048,576, and indices at 6,291,456. Python's per-call defaults are lower:
  262,144 vertices and 1,572,864 indices. These are output **count** limits, not
  a promise that allocations exactly equal the packed output size.
- Before invoking Lyon, a conservative quadratic subdivision estimate is
  limited to 262,144 segments. The estimate uses the uniform chord-error bound
  `length(P0 - 2*P1 + P2)/(4*n*n)` in float64. Lyon still performs the actual
  adaptive flattening. This gates excessive curve work, not intersections.
- Output overflow, invalid/nonfinite data, tessellation errors, and caught
  Rust panics never publish partial geometry. The Python adapter raises an
  explicit exception. A later valid call has independent state. This does
  not make a process-wide allocator failure recoverable: Lyon's internal
  sweep/intersection storage is **not** under a hard total-memory/time budget.
  That remains a production-readiness gate for adversarial/large inputs.
- A new tessellation is performed per call. There is no identity cache that
  could return stale connectivity after a public point-array edit.

## Uniform fill-border union

```python
mesh = tessellator.tessellate(
    contours, attributes=uniform_rgba_arrays,
    tolerance=0.001, border_width=0.005, border_join="bevel",
)
```

`border_width` is the **full** stroke width in the caller's tessellation space,
not Manim style units or pixels. The caller applies Manim's width conversion,
camera scaling and local-plane projection. Zero leaves the original fill route
unchanged. Positive widths require uniform endpoint attributes across all
contours; source handle attributes remain unused. The geometric style options
are `bevel`, `miter` with `border_miter_limit >= 1` (default 4), and `round`.
Lyon's closed-path strokes have no end caps, including an input contour's
implicit closing segment.

The helper resolves the original fill with its requested nonzero/evenodd
rule, appends a stroke mesh, then expresses **all** resulting triangles as
consistently oriented closed contours. One final nonzero fill tessellation
resolves their union. This handles reversed/repeated/crossing contours,
concavities, holes shrinking or closing, and intersections between borders.
Lyon stroke strips overlap internally by design; rendering those strips
directly with ordinary alpha blending would be incorrect for translucent
paint. The returned union has single coverage and must be painted once.

This route deliberately does **not** claim exact legacy border appearance.
Manim's angle-dependent `auto` joins differ from Lyon's standard joins. Its
current border also has a smooth AA coverage band, a 0.95 border-alpha factor,
a 0.0001 normal displacement and a later 1.06 composite adjustment; none is
encoded by this binary union. In particular, full-target MSAA/supersampling
is not the same as the old smooth band. The scene integration must choose and
validate an explicit mapping; `border_join="auto"` is rejected here.

`tolerance` controls Lyon's centerline flattening and round-join approximation.
It is not a proved global Hausdorff error bound on arbitrary stroked cusps or
miter corners. A caller's projected error budget must also account for input
float32 rounding, the expanded border hull, plane fitting and the actual
stroke-style approximation. Border width changes (including camera-dependent
width) invalidate geometry. Changes in AA/resolution need their own treatment.

Source/output count limits apply to the combined intermediate fill/stroke
mesh and the final union individually. Before building the union path, its
straight-edge count is limited to 262,144 (three per intermediate triangle).
This prevents unlimited union input construction but does not impose a hard
bound on Lyon's internal intersection sweep memory or time. Errors publish
no partial mesh. The extra tessellation's CPU and memory cost must be measured
on the actual glyph corpus; it is not assumed cheap because it reuses Lyon.

The CPU tests compare single coverage against an independent polygon winding
and distance-to-segment oracle, including crossing/opposite contours. They
also check exact bevel/miter square areas, round-join convergence, hole closure,
uniform translucent attributes, read-only sources, limits and call recovery.

## Versions and licensing

`Cargo.lock` pins the experiment's dependency graph. The tested build used
Rust/cargo 1.97.0 on macOS arm64, with `lyon_tessellation` 1.0.22 and
`lyon_path`/`lyon_geom` 1.0.19. These crates declare `MIT OR Apache-2.0`.
The MIT option is recorded in `THIRD_PARTY_LICENSES.txt`; no upstream source
has been copied into the implementation. Lyon's package source revision is
`b456b143215a1942a617c4672776b68b9a30feee`.

Other locked dependencies are `arrayvec` 0.7.8, `autocfg` 1.5.1,
`euclid` 0.22.14, `float_next_after` 1.0.0, `libm` 0.2.16, and
`num-traits` 0.2.19. Their crate license declarations permit MIT; corresponding
notices are included with the experiment. Keep them with any distributed
binary. `RUST_STANDARD_LIBRARY_LICENSES.html` carries the Rust 1.97.0
toolchain's standard-library notices, copied without modification from
`share/doc/rust/COPYRIGHT-library.html`. Refresh it when changing the release
toolchain; both notice files are included in distribution license metadata.

`pyproject.toml` pins setuptools-rust 1.13.0 and builds this crate with
`binding="NoBinding"` and Cargo `--locked`. `MANIFEST.in` includes the Rust
manifest, lockfile, source and license notice so the wheel can be built from
the source distribution alone. Both macOS CI jobs install the tested Rust
1.97.0 toolchain before the Python build; the package job runs the CPU mesh
tests and validates the wheel contents. Local wheel execution has been checked
only on macOS arm64/Python 3.13. CI is configured for Python 3.11 and 3.14;
those remote runs, Intel macOS, Windows, Linux and WASM are not locally proven.
The wheel checker also supports `--load-native`: it extracts just the adapter
and helper into a temporary directory, clears the environment override, and
runs fill/border smoke tests in an isolated Python process. This verifies the
packaged loader and actual binary without reinstalling the development environment.

Primary references:
[Lyon fill API](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.FillTessellator.html),
[fill options](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.FillOptions.html),
[stroke overlap contract](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.StrokeTessellator.html),
[stroke options](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.StrokeOptions.html),
[pinned Lyon license](https://github.com/nical/lyon/blob/b456b143215a1942a617c4672776b68b9a30feee/LICENSE-MIT).
