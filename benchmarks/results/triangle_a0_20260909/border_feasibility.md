# A0 fill-border feasibility — 2026-09-09

**Recommendation:** first test a uniform-paint, uniform-width border union using
the existing Lyon dependency. Tessellate the original nonzero fill; tessellate
its closed centerline stroke; orient every resulting triangle consistently;
submit those closed triangle contours to one final nonzero fill tessellation.
The result is one ordinary mesh covering the union, including holes and
concavities, with no double-painted overlap. This is a composition of existing
algorithms, not a new polygon-boolean implementation. It is an unimplemented
feasibility proposal; repeated triangulation and intersection costs need measurement.

If that becomes expensive or unreliable, the strongest ready-made outline
alternative is **skia-pathops**, which already exposes both stroke expansion
and boolean union in Python. Kurbo is useful but does not by itself remove the
union and general offset-correctness questions.

## The current contract is more than “draw a wider fill”

The border pass reuses the stroke shader with fill RGBA and `fill_border_width`
as its inputs. Width in source-plane units is
`0.01 * fill_border_width * mix(frame_scale, 1, scale_stroke_with_zoom)`.
The default is `flat_stroke=True`, `scale_stroke_with_zoom=True`, and
`joint_type="auto"`. TeX/StringMobject adds a default border width of 0.5.

Quadratics are sampled by the existing area/frame-scale heuristic, capped at
32 steps. Width and color interpolate between segment endpoints; the middle
handle's width does not set the interpolation. Flat strokes offset in the path
plane; non-flat strokes face the camera. The shader adds a 0.0001 normal offset.
Miter/bevel/auto/no-joint are distinct: auto uses a smooth transition based on
cosine thresholds -0.8 and -0.9, not a standard library miter-limit rule. Closed
paths avoid cap-policy questions, but joins still need explicit comparison.

The AA width is `max(anti_alias_width * pixel_size, 1e-8)`, with
`pixel_size = frame_width / output_width` (equal to the height ratio when the
camera/output aspect ratios match). The strip extends half an AA width
beyond the geometric stroke. Its fragment alpha uses a smoothstep of the
interpolated transverse distance. Border fragments multiply alpha by 0.95,
premultiply color, and combine with the existing fill attachment by componentwise
MAX. The attachment is then composited once with the existing 1.06 adjustment.

For uniform paint and ordinary single winding, this behaves approximately like
maximum fill/border coverage. Gradients and repeated winding have additional
semantics; geometric union does not reproduce those artifacts automatically.
For uniform paint, a second source-over border draw is incorrect at translucency:
it paints the overlap twice. Likewise, binary geometric union with ordinary
MSAA/SS is not identical to the current smooth AA band.

Local evidence: `maniml/web/static/wgsl/stroke.wgsl`,
`maniml/web/wgpu_renderer.py:142`, `maniml/rendering/shader_wrapper.py:389`,
`maniml/mobject/types/vectorized_mobject.py:89`,
`maniml/mobject/svg/string_mobject.py:95`, `maniml/camera/camera.py:158`.

## Reusable options

| Option | What it supplies | Material limitation |
|---|---|---|
| Existing Lyon 1.0.22 | Stroke triangles plus the already-used nonzero fill sweep; no new dependency | Stroke triangles overlap by design; resolve them before ordinary alpha rendering. Standard joins differ from Manim auto. An additional fill tessellation could be expensive. |
| skia-pathops 0.9.2 | `Path.stroke(width, cap, join, miter_limit)` and `pathops.op(fill, stroke, UNION)` | New binary dependency; stroke wrapper lacks a tolerance/resolution-scale argument; output may contain cubic/conic segments beyond the current quadratic-only ABI. Boolean failure must propagate. |
| Kurbo 0.13.1 | `stroke(path, style, opts, tolerance) -> BezPath`, explicitly tolerance-controlled | New Rust dependency; parallel-curve expansion has documented pathological limitations. Result needs union/topology handling and cubic conversion or a richer fill ABI. |

Lyon explicitly documents stroke self-overlap; its mesh is not directly safe
for translucent single-owner output. The final positive-winding triangle union
addresses that geometric overlap. **Do not concatenate the original path and
the stroke outline and assume nonzero means union:** opposite winding signs
can cancel. Converting the already-resolved fill and stroke triangles to one
consistent orientation avoids that error. [Lyon stroke contract](https://docs.rs/lyon_tessellation/latest/lyon_tessellation/struct.StrokeTessellator.html)

The installed Lyon source also exposes per-vertex variable width, plus Miter,
MiterClip, Round and Bevel joins. That availability does not establish parity
with Manim's variable-width interpolation or auto-join formula. There is no
stroke-to-outline/boolean module in the inspected `lyon_algorithms` API.
[Lyon algorithms](https://docs.rs/lyon_algorithms/latest/lyon_algorithms/)

Skia-pathops' implementation calls Skia's stroke-to-fill operation and exposes
explicit boolean union. It supports conic-to-quadratic conversion but leaves
cubics; the current helper must not silently reduce them. The stroke wrapper
does not expose Skia's `resScale` argument, so a projected tolerance needs a
validated coordinate-scaling strategy or binding extension. No robust error
bound should be inferred from a default method call.
[Pinned Python binding](https://raw.githubusercontent.com/fonttools/skia-pathops/v0.9.2/src/python/pathops/_pathops.pyx),
[Skia stroke-to-fill API](https://api.skia.org/SkPathUtils_8h.html),
[Skia boolean API](https://api.skia.org/SkPathOps_8h.html)

The 0.9.2 release has CPython 3.10+ ABI3 wheels including a 2.9 MB universal2
macOS wheel, plus Windows/Linux builds. This host's Python 3.13 can use that
ABI, subject to an actual import/runtime probe. `pathops`, `skia`, `shapely`,
and `pyclipper` are not installed in the tested main venv. Nothing was installed
or added to project dependencies during this investigation.
[Published package files](https://pypi.org/project/skia-pathops/)

Kurbo offers an explicit approximation tolerance and ordinary stroke styles.
Its documentation warns that its parallel-curve approach is not the rigorously
correct general parallel sweep around all pathological curves. Treat it as a
candidate requiring cusp/high-curvature tests, not a guarantee of arbitrary
offset correctness. [Kurbo stroke](https://docs.rs/kurbo/0.13.1/kurbo/fn.stroke.html)

## Smallest useful A0 experiment

1. Uniform RGBA, uniform positive border width, closed planar paths,
   `flat_stroke=True`, unlit paint. Begin with smooth circles/annuli and explicit
   bevel/miter cases; measure the default auto-join differences separately.
   Per-point widths, gradients, camera-facing strokes and clipping stay gated.
2. Build the fill/stroke union with Lyon and draw it once through the ordinary
   shared output pipeline. Validate translucent overlap, counter shrinkage,
   holes closing, concavities, reversed contours and source self-intersections.
   Each covered sample must have one owner; do not rely only on total area.
3. Use existing full-target SS2 and 4x MSAA controls first to measure how much
   border geometry alone restores. Record the remaining smooth-band difference.
   AA is applied to the final union, never separately blended fill and border.
4. If smooth-band parity remains necessary, a library-backed reference can form
   nested offset unions and Boolean differences into non-overlapping coverage
   bands. That can approximate the shader's smoothstep without overdraw, but
   band count, contour topology changes and CPU cost require evidence. It is
   a reference experiment, not a reason to add a bespoke offset/AA framework.
   No inspected Lyon API already supplies this exact AA mesh.
5. Split the output-pixel error budget among plane fitting, stroke/curve
   approximation, any conic/cubic conversion, and float32 rounding. Projection
   bounds must cover the expanded border/AA hull, not only original controls.
   Combining flat borders onto the fill's plane also removes the old 0.0001
   normal offset; measure/charge its projected displacement before claiming parity.
   When `scale_stroke_with_zoom=False`, camera scale changes the border geometry
   itself and must invalidate its mesh. Resolution changes alter the AA band;
   cache identity/quality checks must account for both cases.

No default renderer switch follows from this investigation. The key next result
is whether ordinary single-owner border geometry restores default TeX quality
at acceptable total preparation/drawing cost, while keeping the shared renderer
small. Native/browser parity and full GPU generation remain later gates.
