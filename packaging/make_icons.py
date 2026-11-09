"""Draw the Kumpas icon at every size the phone page and installers need.

Run from the repository root:  python packaging/make_icons.py
Writes src/kumpas/web/icon-{180,192,512}.png and icon.svg, plus
packaging/icons/kumpas.{png,ico,icns} for the installers.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "kumpas" / "web"
OUT = ROOT / "packaging" / "icons"

BG, PHONE, MARK = (15, 17, 21), (79, 140, 255), (255, 255, 255)

# The K monogram on a 512-unit canvas, shared by the PNG and SVG versions:
# the K's stem is a phone, its arms a sweeping hand gesture ("kumpas").
CORNER = 112
STEM_BOX, STEM_RADIUS = (128, 104, 232, 408), 34
BUTTON_BOX, BUTTON_RADIUS = (164, 370, 196, 382), 6
ARMS = [(384, 120), (272, 256), (384, 392)]
ARM_WIDTH = 58


def draw(size):
    scale = 4  # draw large, then downsample for smooth edges
    s = 512 * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = lambda box: tuple(v * scale for v in box)
    d.rounded_rectangle((0, 0, s - 1, s - 1), CORNER * scale, fill=BG)
    d.rounded_rectangle(k(STEM_BOX), STEM_RADIUS * scale, fill=PHONE)
    d.rounded_rectangle(k(BUTTON_BOX), BUTTON_RADIUS * scale, fill=BG)
    pts = [(x * scale, y * scale) for x, y in ARMS]
    w = ARM_WIDTH * scale
    d.line(pts, fill=MARK, width=w, joint="curve")
    for x, y in pts:  # round caps and corner
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=MARK)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def svg():
    rect = lambda box, r, fill: (f'<rect x="{box[0]}" y="{box[1]}" width="{box[2] - box[0]}" '
                                 f'height="{box[3] - box[1]}" rx="{r}" fill="{fill}"/>')
    hexc = lambda c: "#%02x%02x%02x" % c
    path = "M" + "L".join(f"{x} {y}" for x, y in ARMS)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'{rect((0, 0, 512, 512), CORNER, hexc(BG))}{rect(STEM_BOX, STEM_RADIUS, hexc(PHONE))}'
            f'{rect(BUTTON_BOX, BUTTON_RADIUS, hexc(BG))}'
            f'<path d="{path}" fill="none" stroke="{hexc(MARK)}" stroke-width="{ARM_WIDTH}" '
            f'stroke-linecap="round" stroke-linejoin="round"/></svg>\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    big = draw(1024)
    for size in (180, 192, 512):
        # Home-screen icons are shown on an opaque tile; iOS ignores transparency.
        flat = Image.new("RGB", (size, size), BG)
        icon = big.resize((size, size), Image.Resampling.LANCZOS)
        flat.paste(icon, mask=icon)
        flat.save(WEB / f"icon-{size}.png", optimize=True)
    (WEB / "icon.svg").write_text(svg(), encoding="utf-8")
    big.resize((512, 512), Image.Resampling.LANCZOS).save(OUT / "kumpas.png", optimize=True)
    big.save(OUT / "kumpas.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "kumpas.icns")
    print("icons written")


if __name__ == "__main__":
    main()
