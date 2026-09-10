# A0 native GL references

These ten 960×540 images record native GL output for the real-TeX, zoom,
hairline/hole, perspective, and translucent-border quality fixtures. Each has
a production-style and an explicitly zero-fill-border variant. All use the
production 2D setting `samples=0`.

`manifest.json` records live source/style/order and uniform fingerprints,
camera/output settings, the GL device/version, and each image's SHA-256. The
source builders are in `tests/renderer_quality_fixtures.py`. Reference loading
rejects a changed image or source contract. The baseline includes historical
opacity/rendering quirks; it is not the sole definition of correct semantics.

Images retain raw RGBA attachment bytes. For opaque-background visual
comparisons, the A0 harness saves RGB crops so historical alpha defects cannot
change the preview's compositing. Do not compare differently converted PNGs.

Run `python -m benchmarks.renderer_quality --help` from the repository for the
capture/comparison command. Capturing missing references requires the explicit
`--capture-native` flag; changed existing references require a new directory.
