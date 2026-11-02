# Ovo brand

## The idea

Two circles, one overlap: your two tools in one view. The name is the logo's shape, O·V·O.

## Name

**Ovo**, always written with a capital O and lowercase "vo". Say it "OH-voh".

Tagline: **Claude and Codex usage, at a glance.**

## Logo

Two overlapping circles on a dark rounded tile: orange on the left, blue on the right, a light lens where they meet.

- `assets/ovo.png` and `assets/ovo.ico` are the mark.
- Keep clear space around it of at least a quarter of its width.
- Don't recolour it, stretch it, or put it on a busy background.
- On a very light background, keep the dark tile; it is part of the mark.

`assets/claude.png` and `assets/codex.png` are the two services' logos. They belong to their owners and are used only to label each service inside the window. They are not part of Ovo's own brand.

## Colour

| | Hex | Used for |
|---|---|---|
| Orange | `#D97757` | Claude, and the left circle |
| Blue | `#7A95FF` | Codex, and the right circle |
| Light | `#ECEBE8` | The overlap, and text |
| Tile | `#252523` to `#1B1B1A` | Backgrounds |
| Amber | `#F0A03C` | Warning (70% used), the 80% alert |
| Red | `#E5484D` | Danger (90% used), the 90% alert |
| Green | `#3FB27F` | The reset alert |

The window's outline fades from orange to blue.

## Type

- Greeting and the wordmark: **Georgia**, a serif.
- Everything else: **Segoe UI**.

## Tone

Short, plain and friendly. No jargon, no exclamation marks, no hype.

## Rebuilding the pictures

```bash
python tools/make_assets.py   # the logo and icon files
python tools/make_media.py    # the README banner and screenshot, with sample numbers
```
