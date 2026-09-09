# Bounded vector-fill rendering

Preserve the scene's geometry, drawing order, and appearance while reducing
the screen area processed for each winding-fill batch. No scene API changes.

## Baseline

The B0 raster wordmark has 211 outlined squares and 135 drawing batches.
On the Apple M3 at 2160 x 1080, submission through rendering completion
measured 47.4 ms with touching squares versus 1.46 ms after separating them
into one batch. Forcing the separated picture back into 135 batches restored
47.4 ms with pixel-identical output. These are warmed native WebGPU mirror
measurements, including submission and a one-pixel readback; they exclude
Python animation, command encoding, and transport. Invalid native GPU
timestamps were discarded.

## Implementation sequence

1. Prototype a bounded composite with the original 135 batches; measure its
   effect and compare pixels with the existing full-frame renderer.
2. Calculate conservative screen rectangles for winding fills from their
   shader geometry and camera. Include fill-border and filtering margins;
   fall back to the full frame when a bound cannot be guaranteed. Send the
   optional rectangle as fresh frame metadata, including on cached batches.
3. Apply the rectangle in both browser and native WebGPU renderers. If the
   prototype shows full-size scratch clearing remains expensive, measure a
   regional clear before considering smaller scratch textures. Preserve the
   existing winding math and draw order.
4. Verify pixel equivalence for touching shapes, curves/holes, transparency,
   edge clipping, fill borders, camera motion, fixed-frame content, and cached
   geometry. Exercise the browser command path and geometry stream, then
   benchmark the original wordmark and a large-batch control.

Only the measured result will determine the final scope. The 32x one-batch
comparison is not a promise that clipping 135 batches produces the same gain.

## Implemented and measured

The intermediate composite-only prototype measured 47.4→28.0 ms; regional
clearing in a full-size target measured about 21.7 ms. The shipped path uses
power-of-two pooled scratch targets around each fill's conservative rectangle,
retains the 2x sample grid, and composites only that rectangle. Unsupported
bounds fall back to the original full-frame path; empty fills skip their fill
passes while ordinary strokes remain. Unused pooled textures are released
after submission (browser) or readback completion (native mirror).

The reusable benchmark measured 48.2→23.4 ms (2.06x), with pixel-identical B0
wordmark output and 135 batches in both variants. Single large-batch control
remained about 1.4–1.5 ms. Small targets avoid full-sized temporary allocations
for small scenes. Pass/command overhead remains: this is not the 32x result
from changing 135 batches to one.

Bounds are calculated together in NumPy rather than in 135 separate projection
calls: about 0.65 ms for the wordmark versus 5.48 ms for the first implementation.
