# Phase B2 plan: surfaces as control nets

Written 2026-09-11 at the start of B2, from `phase_b_plan.md` after the B1
prototype (`phase_b1_plan.md`). Status: proposed; the net mathematics and
the Surface changes are the first step, the GPU evaluation the second.
Taylor's direction: "ok lets move on to B2". Phase A stays the default
renderer throughout (`DECISIONS.md`, 2026-09-11).

## What a surface is today, and what it becomes

Today `Surface` samples `uv_func` on a `resolution` grid at construction
and keeps the samples as its points, `nu × nv` of them, each with a nudged
normal point; a fixed triangle list over the grid is built once and drawn
as it is, so a zoomed sphere shows its facets and a `Transform` between two
surfaces of different resolutions resizes the point arrays by index, which
scrambles a grid. Everything around the class reshapes the point array by
`resolution`: `uv_to_point`, `SurfaceMesh`, the partial reveal used by
creation animations, `TexturedSurface`'s image coordinates, back-to-front
face sorting.

After B2 a surface's points are a **biquadratic Bézier net**: an odd-sized
grid of control points, `(2·pu + 1) × (2·pv + 1)` for `pu × pv` patches,
each patch the `3 × 3` block that shares its edge rows with its
neighbours, exactly as a path's curves share their anchors. The surface is
the net evaluated in two parameters with the quadratic Bernstein basis the
paths already use. That is the whole of the decision in `phase_b_plan.md`:
one representation, evaluated at screen density, nothing kept that
depends on zoom.

- **Construction.** `Surface(uv_func, resolution)` keeps its signature.
  `resolution` names the net's density: it is rounded up to odd (a `(2, 2)`
  square becomes a `3 × 3` net, one patch, still exact for a plane), the
  function is sampled once at the net's parameter positions, and the net
  is solved so that every patch passes through every sample (the
  interpolating net: anchors are the samples, the handle points follow
  from the midpoint samples, row by row and then column by column). An
  existing `ParametricSurface(func, resolution=(101, 101))` therefore
  still passes through the same 10,201 points; between them it is now
  smooth rather than flat.
- **The built-ins keep their resolutions.** A `Sphere` at its default
  `(101, 51)` is the interpolating net of those samples, `50 × 25` patches
  through the same 5,151 points as today; `Square3D` at `(2, 2)` becomes one
  `3 × 3` patch. Sampling at the existing resolution is more accurate than
  a hand-built sixteen-curve net (the sixteen-curve sphere is off by
  hundredths of a percent, as the Phase B decision accepted; the sampled
  net is off by a float32 ulp at the samples) and, evaluated at two steps
  per patch, it is *exactly* today's grid, so the reference renderers'
  pixels do not move. The sixteen-curve nets remain available as a memory
  refinement (`tests/test_bezier_net.py` builds one and measures it); they
  are not the default.
- **What reads points.** `uv_to_point` evaluates the net at `(u, v)`
  (better than today's bilinear lookup). `SurfaceMesh` draws evaluated
  parameter lines, not control rows. The partial reveal collapses control
  rows, which collapses the surface smoothly. `TexturedSurface` carries
  image coordinates and opacity per control point and evaluates them with
  the same weights, so the texture follows the parametrization exactly.
  `Transform` aligns nets by exact subdivision (de Casteljau splits of
  whole patch rows and columns until the patch counts agree, as
  `insert_n_curves` does for paths), then blends control points.
  `VMobject3D`, whose points are an explicit triangulated polygon and not
  a grid, keeps its own mesh: a surface without a net draws as it does now.
- **The reference renderers keep working.** Phase A, native GL and
  Original 2D draw a surface from `get_shader_data()`. With points as a
  net, that call evaluates the net on the CPU at a fixed density (the
  net's own patch count times a small step count) and hands back the grid
  and its triangle list as before. This is not a second representation; it
  is the one representation evaluated on the other processor, the way
  Lyon draws the one path representation today. Evaluated at two steps per
  patch, the grid's anchors and midpoints are the construction's samples,
  so the grid is today's grid to a float32 ulp; it is cached per source
  revision, since the renderers ask for it every frame.

## The GPU evaluation

A compute stage per patch, the same shape as the border stage: a record
per patch, a capacity from screen density with headroom, an index pattern
the drivers build, output in the 40-byte surface layout (36 bytes for a
textured surface).

- **Records.** The net travels once per source revision as a hashed blob:
  control points with their per-point channels (RGBA, or image coordinates
  and opacity), plus per object the net's dimensions and a density. The
  patch kernel indexes the net by patch, so shared control points are not
  duplicated.
- **Density and steps.** A quadratic's deviation from its chord is a
  quarter of its second difference `|p0 − 2p1 + p2|`, and after `s`
  subdivisions a quarter of that over `s²`. The CPU keeps, per object per
  revision, the largest second difference over every row and column of
  every patch, in world units; the kernel turns it into steps per patch
  edge at the current zoom with the quarter-pixel target the fills use,
  and the CPU reserves capacity from the same number with the border
  stage's 2× headroom, growing only when a zoom outgrows it. One step
  count per object, so adjacent patches meet without cracks; a sphere
  patch at the normal view needs about four steps, so `128` patches at
  `25` vertices are 128 KB against today's 1.2 MB grid, and the reservation
  cap of 32 steps bounds a deep zoom at 5.6 MB.
- **Normals** come from the patch derivatives in the kernel; where they
  vanish (a sphere's poles) the built-in's own rule applies, as it does
  today for `Sphere`.
- **Wire.** Format 7 already; a `net` descriptor on the surface batch
  beside the `border` descriptor, `net_data` spans beside `border_data`.
  The browser mirror follows the native one once the native pixels are
  right, as in B1.
- **Switch.** The net representation itself is not switchable; it is the
  data model. The GPU evaluation lands behind `MANIML_SURFACE=nets` with
  the CPU evaluation as the default until the native and browser pixels
  agree, the same pattern as `MANIML_FILL`.

## Sequence

1. **The net mathematics**, `maniml/utils/bezier_net.py`: the interpolating
   solve, evaluation on a step grid with derivatives, exact subdivision,
   net alignment, the per-object density. Unit-tested against exact
   surfaces: a plane is exact, the sixteen-curve sphere is within
   hundredths of a percent of the true radius everywhere, subdivision
   changes no evaluated point, the interpolating net passes through its
   samples.
2. **Surface as a net**, the CPU evaluation in `get_shader_data`, and every
   dependent listed above. The existing suite is the regression: the
   generated-scene, native-camera, port and conformance tests all draw
   surfaces. Point counts change for even resolutions and for the
   built-ins; the conformance baseline lists what moved.
3. **The GPU stage** in the native mirror behind the switch, then pixels
   against the CPU evaluation at several zooms, then the browser mirror
   and `test_wgpu_port` parity.
4. **Measurement**: a zoomed sphere at 1×, 4× and 16× with no facets;
   memory per surface against today's grids; the preparation cost of a
   frame of surfaces, which should fall since no grid is copied per frame.

## Acceptance (from `phase_b_plan.md`)

A zoomed sphere shows no facets at any zoom; `test_wgpu_port` pixel parity
between mirrors; the conformance baseline unchanged or its changes listed;
memory per surface reported against today's grids.

## What to watch

- **Point semantics.** Scene code that reads a surface's `get_points()`
  expecting samples now gets the net. The read tables of 2026-09-11 found
  no such reads in the course; the conformance suite will show any other.
- **Poles and seams.** The sixteen-curve sphere's pole rows are degenerate
  patches (all control points at the pole); the kernel's derivative normal
  is zero there and the radial rule takes over. The seam where `u` wraps
  is a shared control column, so it is closed by construction.
- **The other session.** B2 edits `maniml/mobject/types/surface.py` and
  `three_dimensions.py`; the engine branch in `maniml-engine` touches
  scene and mobject files. Its current branch carries nothing on these
  two files; integrate B2 through `main` before either side reaches them
  again.
