"""Windowed 3D regression: MSAA letterbox blit (ThreeDScene uses
samples=4) and depth-correct fills for multiple same-batch VMobjects.

Run directly:  python -m tests.interactive.three_d
"""
import os
import sys

import numpy as np

from tests.interactive.harness import WindowDriver, finish

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "three_d_scene.py")


def script(d: WindowDriver):
    d.pump(0.5)  # several frames through the MSAA blit path
    image = np.array(d.scene.get_image())
    reds = ((image[:, :, 0] > 150) & (image[:, :, 1] < 110)
            & (image[:, :, 2] < 110)).sum()
    blues = ((image[:, :, 2] > 150) & (image[:, :, 0] < 120)).sum()
    greens = ((image[:, :, 1] > 130) & (image[:, :, 0] < 120)).sum()
    d.check(f"blue square fill renders ({blues} px)", blues > 10000)
    d.check(f"red square fill renders in same batch ({reds} px)", reds > 10000)
    d.check(f"sphere renders ({greens} px)", greens > 1000)


def main() -> int:
    driver = WindowDriver(FIXTURE, "ThreeDFills")
    return finish(driver.run(script))


if __name__ == "__main__":
    sys.exit(main())
