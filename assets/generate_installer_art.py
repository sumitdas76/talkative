"""Installer artwork (installer/art/*.png), drawn from assets/icon-256.png.

Inno Setup's modern wizard shows WizardImageFile on the welcome page
(164x314 at 100%) and WizardSmallImageFile on the other pages (55x55 at
100%). Each is written at several Windows scales; the installer lists
them all and Inno picks the closest, so the art is sharp at 125-250%.

The panel uses the icon's own blue (sampled from icon-256.png), so the
mark sits on it naturally. Re-run after changing the icon:

    .venv\\Scripts\\python assets\\generate_installer_art.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "installer" / "art"
ICON = Image.open(HERE / "icon-256.png").convert("RGBA")
FONTS = Path("C:/Windows/Fonts")

TOP = (89, 151, 205)      # icon's top edge
BOTTOM = (33, 68, 100)    # a step darker than the icon's bottom edge
WHITE = (255, 255, 255)
SOFT = (214, 230, 245)    # tagline: >= 4.5:1 on every part of the gradient

SCALES = (100, 125, 150, 175, 200, 250)


def font(name, size):
    for n in name:
        p = FONTS / n
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def gradient(w, h):
    im = Image.new("RGB", (w, h))
    px = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(h - 1, 1)
        px.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(TOP, BOTTOM)))
    return im


def welcome(scale):
    s = scale / 100
    w, h = round(164 * s), round(314 * s)
    im = gradient(w, h).convert("RGBA")

    # The app icon, with a soft shadow so it lifts off the same-hue panel.
    size = round(84 * s)
    icon = ICON.resize((size, size), Image.LANCZOS)
    x, y = (w - size) // 2, round(78 * s)
    shadow = Image.new("RGBA", im.size, (0, 0, 0, 0))
    mask = icon.split()[3].point(lambda a: a * 0.45)
    shadow.paste((10, 25, 40, 255), (x, y + round(6 * s)), mask)
    im = Image.alpha_composite(im, shadow.filter(ImageFilter.GaussianBlur(8 * s)))
    im.alpha_composite(icon, (x, y))

    d = ImageDraw.Draw(im)
    title = font(["seguisb.ttf", "segoeuib.ttf"], round(21 * s))
    d.text((w / 2, y + size + round(30 * s)), "Talkative", font=title, fill=WHITE, anchor="mm")
    tag = font(["segoeui.ttf"], round(11.5 * s))
    for i, line in enumerate(("Hold a key and speak.", "It types for you.")):
        d.text((w / 2, y + size + round((56 + 16 * i) * s)), line, font=tag, fill=SOFT,
               anchor="mm")

    # The listening line from the app (pill.py), as a quiet signature.
    cy, half = h - round(46 * s), round(38 * s)
    bars = (3, 6, 10, 7, 12, 8, 5, 9, 4)
    gap = (2 * half) / (len(bars) - 1)
    for i, b in enumerate(bars):
        bx = w / 2 - half + i * gap
        bh = b * s
        d.rounded_rectangle([bx - 1.5 * s, cy - bh, bx + 1.5 * s, cy + bh],
                            radius=1.5 * s, fill=(255, 255, 255, 150))
    return im.convert("RGB")


def small(scale):
    n = round(55 * scale / 100)
    # Transparent corners would show Inno's page color; the modern style's
    # header is the page background, so draw the icon on nothing and let
    # WizardSmallImageBackColor fill around it.
    return ICON.resize((n, n), Image.LANCZOS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for sc in SCALES:
        welcome(sc).save(OUT / f"welcome-{sc}.png", optimize=True)
        small(sc).save(OUT / f"small-{sc}.png", optimize=True)
    print("wrote", len(SCALES) * 2, "files to", OUT)


if __name__ == "__main__":
    main()
