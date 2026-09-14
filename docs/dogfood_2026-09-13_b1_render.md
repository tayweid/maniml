# B1 render observations — 2026-09-13

**Status: reported text defect not reproduced in the retained evidence.**
This records the animation editor's render concern, the subsequent evidence
check, and the limits of that check. No engine fix is established or applied.

## Report and correction

During work on ECON 0100's `EpisodeB1`, the animation editor reported
intermittently missing letters in the stationary “Consumer Surplus” title
while a price tracker moved. That earlier claim was too strong and is
withdrawn: the saved movie frame at 67.73 seconds contains the complete title.
It must not be used as evidence of missing glyphs or a geometry-cache defect.

The follow-up examined the title region in all **540 decoded movie frames
from 64 through just before 100 seconds**, covering the isolated-bar price
demonstrations. No missing-letter defect was found. A simple blue-pixel mask
in the title crop contained 8,301–8,341 pixels per frame; at most 42 of the
first frame's 8,339 blue pixels were absent in another frame. Visual inspection
of the frame with the largest discrepancy against the restored still also
showed the complete title. These small edge differences do not establish a
rendering defect; this is a bounded check, not a whole-episode parity test.

Restoring checkpoint **91** (B12c, price $2.40 above the first bar's $2.00
marginal benefit) and forcing a capture produced a complete title. Replacing
`scene.camera._geometry_cache` with `GeometryCache()` and capturing again
produced a byte-identical PNG. **The cache reset did not demonstrate a fix.**
This comparison used a fast-forwarded scene restored to the checkpoint, not
the original moving frame's live state.

At that price, the grey bar and absent expenditure/CS labels are intentional
scene behavior: the unit is not purchased. They are not missing-render issues.

## Build and retained evidence

| Item | Recorded value |
| --- | --- |
| ManimL revision | `50f6a38f76390a80557852dd7a5aea3118972f43` (`main`, clean before this documentation) |
| Verified import, from `/private/tmp` | `/Users/taylorjweidman/Projects/ManimLive/maniml/maniml/__init__.py` |
| Environment | macOS 26.6.2, arm64; Python 3.13.9; wgpu 0.32.0 |
| Renderer | Default native Phase A triangle/WebGPU movie output |
| Preview | 2160 × 1080, **15 fps override**, 153.2 seconds |
| Checkpoints | 212 including initial state; 61 authored pauses, plus the initial stop |
| Scene SHA-256 | `523333cf88eaf2aa7934b574d8d0de509bc04f9ab8446d50561f968a5a4d7588` |
| Metadata source BLAKE2b-128 | `5917b52cadcb94074938d5050a0bc81b` |
| Shared `style.py` SHA-256 | `aa952b95ccdd99b26aa99077635f06b7dbdb395e308ce973a211fdaca748cd72` |
| Movie SHA-256 | `bbc377915efefecb161ee4046900db5ec895c11a896628c98b4222a53a3408bb` |

Local course files, outside this repository:

- Scene: `/Users/taylorjweidman/Projects/econ-0100/Blocks/B1_Demand/03_Code.py`.
  B12 begins at line 391; `update_exchange` at 422; the $2.40 move at 478.
- Shared style: `/Users/taylorjweidman/Projects/econ-0100/Blocks/_Assets/style.py`.
- Movie and timing table: `Blocks/B1_Demand/media/EpisodeB1_tracker_review.mp4`
  and `EpisodeB1_tracker_review.pausepoints.json`, relative to `econ-0100`.
- Extracted frame: `Blocks/B1_Demand/media/tracker_review_frames/above_mb.png`
  at 67.73 seconds. Its title is complete.

Temporary diagnostics (may be removed): `/private/tmp/b1-cache-before.png`
and `/private/tmp/b1-cache-fresh.png` both have SHA-256
`9c59cfd4a7a05205f1c83a3646ca66bd7173a778af6e5f672e817f0d3cfe9581`.
Render logs are `/private/tmp/b1_tracker_preview.log` and
`/private/tmp/b1_cache_check.log`. Full movies/checkpoint image sets are not
copied into this repository.

## Reproduce the render conditions

This is a full course-scene render, **not a minimized failing reproduction**.
It requires the local course tree and its assets. Check the recorded source
hashes before comparing; the course scene remains under active editing.

```bash
cd /private/tmp
MPLCONFIGDIR=/private/tmp/b1-matplotlib /opt/miniconda3/bin/python - <<'PY'
import json
from pathlib import Path
from maniml.__main__ import load_scene_module
from maniml.web.present_bundle import build_meta

path = Path('/Users/taylorjweidman/Projects/econ-0100/Blocks/B1_Demand/03_Code.py')
output = Path('/private/tmp/b1-render-repro')
output.mkdir(parents=True, exist_ok=True)
module = load_scene_module(str(path))
scene = module.EpisodeB1(
    window=None,
    camera_config={'fps': 15},
    file_writer_config=dict(
        write_to_movie=True, output_directory=str(output),
        file_name='EpisodeB1_tracker_review'),
)
scene._scene_filepath = str(path)
scene._render_mode = True
scene.run()
(output / 'EpisodeB1_tracker_review.pausepoints.json').write_text(
    json.dumps(build_meta(scene), indent=2))
PY
```

The still-image diagnostic instead ran `_render_all()` inside `temp_skip()`,
with `_render_checkpoints=True` and movie writing disabled. It then called
`_restore_checkpoint_for_display(91)` and `update_frame(dt=0, force_draw=True)`
before each cache-comparison capture. Passing this fast-forwarded check does
not establish normal-speed playback or browser correctness.

## Remaining verification limits

- The current revision's complete **60 fps** course render was not validated.
  The earlier 60 fps attempt was interrupted to edit labels; its FFmpeg exit
  255 followed that interruption and is not a confirmed encoder failure.
- The sandbox initially exposed no suitable Metal adapter. Rendering worked
  with GPU access; that launch restriction is separate from visual fidelity.
- No browser, Original 2D, or NativeGL comparison was performed for this report.
- No matching raw camera frame before FFmpeg was compared with a genuinely
  malformed encoded frame. There is no basis yet to blame the serializer,
  tessellation, revision caching, checkpoint restoration, GPU, or encoder.

If missing glyphs are observed again, first retain the exact failing frame,
its neighbors, source hash, renderer, and checkpoint/time. Compare the raw
camera capture with the movie frame at that same live state before trying a
cache reset or reducing the scene. Keep the static title and price-tracker
updater in the reduced case. Do not change animation choreography to work
around a rendering defect that has not been demonstrated.
