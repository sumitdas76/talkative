"""Draw the Store package's logo PNGs from the same code as the app icon
(assets/generate_icon.py), so they never drift from it.

usage: python store/make_assets.py <out_dir>
Writes Square44x44Logo, Square150x150Logo, Wide310x150Logo and StoreLogo
(the four the manifest names), each drawn at 4x and scaled down.
"""
import runpy
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
icon = runpy.run_path(str(ROOT / "assets" / "generate_icon.py"), run_name="lib")["build_icon"]()

SQUARES = {"Square44x44Logo.png": 44, "Square150x150Logo.png": 150, "StoreLogo.png": 50}


def square(size, inset=0.0):
    """The icon on a transparent square; `inset` leaves a margin (tiles)."""
    canvas = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    inner = round(size * 4 * (1 - 2 * inset))
    canvas.paste(icon.resize((inner, inner), Image.LANCZOS),
                 ((size * 4 - inner) // 2,) * 2, icon.resize((inner, inner), Image.LANCZOS))
    return canvas.resize((size, size), Image.LANCZOS)


def main(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for name, size in SQUARES.items():
        square(size, inset=0.12 if size == 150 else 0.0).save(out / name)
    wide = Image.new("RGBA", (310, 150), (0, 0, 0, 0))
    mark = square(150, inset=0.12)
    wide.paste(mark, (80, 0), mark)
    wide.save(out / "Wide310x150Logo.png")
    print(f"Wrote {len(SQUARES) + 1} logos to {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/msix/Assets")
