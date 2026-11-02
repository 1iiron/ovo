"""Builds the icon files in assets/: the Ovo mark (ovo.png/.ico) and .ico versions of the two provider
logos (claude.png, codex.png). Needs Pillow: python tools/make_assets.py"""
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

ASSETS = Path(__file__).parent.parent / 'assets'
ICON_SIZES = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
ORANGE, BLUE = (217, 119, 87), (122, 149, 255)  # Claude's orange, Codex's blue: the two brand colors
LIGHT = (236, 235, 232)  # where they overlap
TILE_TOP, TILE_BOTTOM = (37, 37, 35), (27, 27, 26)  # the widget's own dark background


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def ovo_mark():
    """Two overlapping circles, orange and blue, on the dark rounded tile; the overlap is light."""
    s = 2048  # drawn big, shrunk at the end for smooth edges
    tile = Image.new('RGBA', (s, s))
    d = ImageDraw.Draw(tile)
    for y in range(s):
        d.line([(0, y), (s, y)], fill=lerp(TILE_TOP, TILE_BOTTOM, y / s) + (255,))
    corners = Image.new('L', (s, s), 0)
    ImageDraw.Draw(corners).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=255)
    tile.putalpha(corners)

    def disc(cx):
        m = Image.new('L', (s, s), 0)
        r = s * 0.225
        ImageDraw.Draw(m).ellipse([cx - r, s / 2 - r, cx + r, s / 2 + r], fill=255)
        return m

    left, right = disc(s * 0.38), disc(s * 0.62)
    for mask, color in ((left, ORANGE), (right, BLUE), (ImageChops.multiply(left, right), LIGHT)):
        tile.paste(Image.new('RGBA', (s, s), color + (255,)), (0, 0), mask)
    return tile.resize((512, 512), Image.LANCZOS)


def save_ico(img, path):
    img.resize((256, 256), Image.LANCZOS).save(path, sizes=ICON_SIZES)


if __name__ == '__main__':
    mark = ovo_mark()
    mark.save(ASSETS / 'ovo.png')
    save_ico(mark, ASSETS / 'ovo.ico')
    for name in ('claude', 'codex'):
        save_ico(Image.open(ASSETS / f'{name}.png').convert('RGBA'), ASSETS / f'{name}.ico')
    print('wrote', ', '.join(sorted(p.name for p in ASSETS.iterdir())))
