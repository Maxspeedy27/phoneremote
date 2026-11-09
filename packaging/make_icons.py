"""Draw the Phone Remote icon at every size the phone page and installers need.

Run from the repository root:  python packaging/make_icons.py
Writes src/phoneremote/web/icon-{180,192,512}.png and icon.svg, plus
packaging/icons/phoneremote.{png,ico,icns} for the installers.
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "phoneremote" / "web"
OUT = ROOT / "packaging" / "icons"

BG, PHONE, MARK = (15, 17, 21), (79, 140, 255), (255, 255, 255)

# Geometry on a 512-unit canvas, shared by the PNG and SVG versions.
CORNER = 112
PHONE_BOX, PHONE_RADIUS = (156, 72, 356, 440), 44
SCREEN_BOX, SCREEN_RADIUS = (178, 112, 334, 372), 14
TRIANGLE = [(226, 182), (226, 302), (310, 242)]
BUTTON = (238, 396, 274, 410)


def draw(size):
    scale = 4  # draw large, then downsample for smooth edges
    s = 512 * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    k = lambda box: tuple(v * scale for v in box)
    d.rounded_rectangle((0, 0, s - 1, s - 1), CORNER * scale, fill=BG)
    d.rounded_rectangle(k(PHONE_BOX), PHONE_RADIUS * scale, fill=PHONE)
    d.rounded_rectangle(k(SCREEN_BOX), SCREEN_RADIUS * scale, fill=BG)
    d.polygon([(x * scale, y * scale) for x, y in TRIANGLE], fill=MARK)
    d.rounded_rectangle(k(BUTTON), 7 * scale, fill=BG)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def svg():
    pts = " ".join(f"{x},{y}" for x, y in TRIANGLE)
    rect = lambda box, r, fill: (f'<rect x="{box[0]}" y="{box[1]}" width="{box[2] - box[0]}" '
                                 f'height="{box[3] - box[1]}" rx="{r}" fill="{fill}"/>')
    hexc = lambda c: "#%02x%02x%02x" % c
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'{rect((0, 0, 512, 512), CORNER, hexc(BG))}{rect(PHONE_BOX, PHONE_RADIUS, hexc(PHONE))}'
            f'{rect(SCREEN_BOX, SCREEN_RADIUS, hexc(BG))}<polygon points="{pts}" fill="{hexc(MARK)}"/>'
            f'{rect(BUTTON, 7, hexc(BG))}</svg>\n')


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
    big.resize((512, 512), Image.Resampling.LANCZOS).save(OUT / "phoneremote.png", optimize=True)
    big.save(OUT / "phoneremote.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(OUT / "phoneremote.icns")
    print("icons written")


if __name__ == "__main__":
    main()
