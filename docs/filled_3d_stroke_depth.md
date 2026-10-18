# Filled 3D strokes hiding behind their own fill (2026-10-17)

Reproduced in the checkout with ordinary `ThreeDScene`, without course helpers:
small filled Squares with a contrasting stroke, spread across the XY plane,
viewed at phi=theta=gamma=0. `ThreeDScene.add` selects camera-facing strokes.
The stroke ribbon straddles the source plane; its back portion fails the depth
comparison against the square's fill. This looks like chipped or slanted pixel
corners, particularly away from the camera's center. Unfilled squares and the
same draws without depth testing have intact outlines.

The generated renderer now marks foreground strokes of filled, depth-tested
VMobjects with `stroke_on_fill`. The shared stroke shader intersects each
expanded vertex's sightline with the source plane and uses that plane's depth,
with the existing small camera offset. It preserves original clip XY and W,
so stroke width and antialiasing interpolation remain camera-facing. Empty
paths, painter draws, explicit backstrokes and flat strokes retain their
previous behavior. The flag occupies a formerly unused uniform padding slot;
native and browser uniform packers agree. Program and row-source draws carry
it as well as ordinary draws. No raster-font special case is needed.

Verification:

- Reproduction with the existing shader: 896 pixels differ materially from
  a depth-free reference at 0 degrees, 803 at 35 degrees (768x432, nine squares).
  The repair matches that reference exactly at both angles, on mesh and GPU
  patch fills.
- GPU regression covers the above comparison and a foreground occluder in
  both submission orders: depth testing remains active for the outlines.
- CPU regression checks applicability to filled/depth/foreground draws,
  without changing the source's non-flat stroke setting or fill uniforms.
- Actual course bumper rendered through plain ThreeDScene, including its
  color flicker and title movement, with no course adapter. Pixel outlines
  are intact; depth testing remains enabled and flat_stroke remains false.

Limit: this does not solve all stroke self-overlap at grazing angles. At
75 degrees the nine-square fixture still differs from the painter reference
at 264 pixels (451 before the repair), where narrow projected strokes overlap.
This is distinct from the fill cutting into the ribbon and should not be
presented as a general cure for all 3D stroke artifacts.

The desktop app uses its bundled engine. Updating the checkout alone does not
update that app; keep scene-side compatibility until a fixed app is installed.
