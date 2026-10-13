"""Generate WiadSpot logo assets from static/images/logo.png.

Run from the repo root:  python3 scripts/make_logo_assets.py
Outputs go to static/images/logo/. Re-run after replacing the source logo.
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "static" / "images" / "logo.png"
OUT = ROOT / "static" / "images" / "logo"
NAVY = (0, 47, 79)
NAVY_DARK = (0, 37, 63)
TEAL = (9, 182, 194)
WIDTHS = (128, 256, 384, 512)


def trim(img):
    return img.crop(img.getchannel("A").getbbox())


def light_version(img):
    """Recolour the navy lettering to white; teal stays as is."""
    out = img.copy()
    px = out.load()
    for x in range(out.width):
        for y in range(out.height):
            r, g, b, a = px[x, y]
            if a and g < 120:  # navy pixels
                px[x, y] = (255, 255, 255, a)
    return out


def resized(img, width):
    return img.resize((width, round(img.height * width / img.width)), Image.LANCZOS)


def padded_square(logo, size, fill, radius_ratio=0.22, scale=0.62):
    tile = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(tile).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * radius_ratio), fill=fill
    )
    mark = resized(logo, int(size * scale))
    tile.alpha_composite(mark, ((size - mark.width) // 2, (size - mark.height) // 2))
    return tile


def og_image(logo_light):
    w, h = 1200, 630
    img = Image.new("RGB", (w, h), NAVY_DARK)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = tuple(int(NAVY_DARK[i] + (NAVY[i] + 20 - NAVY_DARK[i]) * t) for i in range(3))
    mark = resized(logo_light, 300)
    canvas = img.convert("RGBA")
    canvas.alpha_composite(mark, (90, (h - mark.height) // 2))
    d = ImageDraw.Draw(canvas)
    d.rectangle((440, 200, 446, 430), fill=TEAL)
    try:
        from PIL import ImageFont
        big = ImageFont.load_default(size=58)
        small = ImageFont.load_default(size=30)
    except Exception:
        big = small = None
    d.text((490, 215), "Make every", font=big, fill=(255, 255, 255))
    d.text((490, 285), "connection count.", font=big, fill=TEAL)
    d.text((490, 375), "Poster ads where people connect to Wi-Fi.", font=small, fill=(207, 227, 236))
    return canvas.convert("RGB")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    logo = trim(Image.open(SRC).convert("RGBA"))
    light = light_version(logo)
    for w in WIDTHS:
        resized(logo, w).save(OUT / f"wiadspot-logo-{w}.png", optimize=True)
        resized(light, w).save(OUT / f"wiadspot-logo-light-{w}.png", optimize=True)
    # App icons: logo on a rounded navy tile.
    for size, name in ((32, "favicon-32.png"), (48, "favicon-48.png"), (180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        padded_square(light, size, NAVY + (255,), scale=0.7 if size < 64 else 0.62).save(OUT / name, optimize=True)
    ico = padded_square(light, 64, NAVY + (255,), scale=0.7)
    ico.save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    og_image(light).save(OUT / "og-image.png", optimize=True)
    for p in sorted(OUT.iterdir()):
        print(p.name, Image.open(p).size)


if __name__ == "__main__":
    main()
