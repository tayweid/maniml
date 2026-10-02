"""ManimLive's icon: Knuth's tile grid (Knuth's public/icons, sampled
2026-09-30: a #212121 rounded square, nine 92 px tiles on a 512 canvas,
8 px apart, corners 14 px, the frame's 90 px) with the red tiles at the
lower left, lower right and upper right (Taylor, 2026-09-30). Regenerates
maniml/web/static/icons/maniml-{512,192}.png; the shell builds the app
icon from the 512.

    python tools/make_icon.py
"""

from pathlib import Path

from PIL import Image, ImageDraw

BACKGROUND = (33, 33, 33)
RED = (203, 24, 29)
# Knuth's blues, row by row, with its one red replaced by the middle-right
# blue and ours placed where Taylor asked.
TILES = [
    [(104, 172, 213), (22, 99, 170), RED],
    [(45, 125, 187), (223, 236, 247), (45, 125, 187)],
    [RED, (143, 194, 222), RED],
]
SCALE = 4  # drawn large and resampled down, for clean edges


def draw(size: int) -> Image.Image:
    canvas = 512 * SCALE
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    s = SCALE
    pen.rounded_rectangle([47 * s, 47 * s, 465 * s - 1, 465 * s - 1], radius=90 * s, fill=BACKGROUND + (255,))
    for row, colors in enumerate(TILES):
        for col, color in enumerate(colors):
            x = (111 + 99 * col) * s
            y = (111 + 99 * row) * s
            pen.rounded_rectangle([x, y, x + 92 * s - 1, y + 92 * s - 1], radius=14 * s, fill=color + (255,))
    return image.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "maniml" / "web" / "static" / "icons"
    for size in (512, 192):
        draw(size).save(out / f"maniml-{size}.png", optimize=True)
        print("wrote", out / f"maniml-{size}.png")


if __name__ == "__main__":
    main()
