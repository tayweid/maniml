# Isolated Lyon fill prototype

This optional Phase A0 helper generates CPU fill meshes. The production
serializer does not import it. It uses Lyon's fill tessellator, not its stroke
tessellator: existing direct strokes remain separate.

The C ABI avoids a Python-version-specific extension and requires only Python's
standard `ctypes` module plus the project's existing NumPy dependency. This is
an experiment build route, not completed production packaging. Shipping it
would need platform binaries/wheels or a Rust build integration, license
notices, and CI for the supported platforms. A WASM binding is separate work.
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

`MANIML_LYON_LIBRARY` can select the library instead of a constructor argument.
Nothing builds or downloads automatically at Python import time. The helper
exports `ml_lyon_abi_version` (currently 1), `ml_lyon_tessellate`, and
`ml_lyon_free`. Rust owns temporary output; the adapter copies complete arrays
and always frees the native allocation before returning.

Run the isolated checks using the existing project Python environment:

```sh
MANIML_LYON_LIBRARY=/private/tmp/maniml-triangle-target/release/libmaniml_lyon_fill.dylib \
MPLCONFIGDIR=/private/tmp/maniml-triangle-mpl \
python -m unittest tests.test_triangle_geometry
```

The native cases skip when the environment variable is absent. A present but
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
  from overlapping helper triangles. Antialiasing and fill-border coverage
  are not implemented here and require independent rendered-image validation.
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
binary. Production packaging must also carry the Rust toolchain/runtime
notices applicable to its actual build.

Primary references:
[Lyon fill API](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.FillTessellator.html),
[fill options](https://docs.rs/lyon_tessellation/1.0.22/lyon_tessellation/struct.FillOptions.html),
[pinned Lyon license](https://github.com/nical/lyon/blob/b456b143215a1942a617c4672776b68b9a30feee/LICENSE-MIT).
