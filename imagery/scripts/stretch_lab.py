"""A3 colour-tuning lab: statistics and side-by-side stretch comparisons.

Runs inside the GDAL container (numpy and PIL are included):

  docker run --rm -v $PWD:/work -w /work ghcr.io/osgeo/gdal:ubuntu-full-3.9.3 \
      python3 stretch_lab.py stats N25E055 N24E121 ...
  ... python3 stretch_lab.py sheet OUT.png TILE [W N E S]

Reads source tiles in place over /vsicurl/ unless a local copy exists in
./src/. Curves map reflectance (raw / 10000) to 0..1; output is 1..255 so
valid pixels never collide with NoData 0.
"""
import os
import sys

import numpy as np
from osgeo import gdal
from PIL import Image, ImageDraw

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
gdal.SetConfigOption("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif")

URL = "https://esa-worldcover-s2.s3.eu-central-1.amazonaws.com/rgbnir/2021"


def src_path(tile):
    name = f"ESA_WorldCover_10m_2021_v200_{tile}_S2RGBNIR.tif"
    local = os.path.join("src", name)
    return local if os.path.exists(local) else f"/vsicurl/{URL}/{tile[:3]}/{name}"


# --- candidate curves: reflectance -> 0..1 -------------------------------

def gamma_curve(white, gamma):
    def f(r):
        return np.clip(r / white, 0, 1) ** (1 / gamma)
    f.label = f"lin 0-{white:g} g{gamma:g}"
    return f


def knee_curve(white, gamma, knee=0.8, black=0.0, sat=1.0):
    """Black-point offset, gamma up to `knee` of output, then an exponential
    shoulder that approaches 1 instead of clipping, so bright roofs and sand
    keep detail. `sat` scales chroma around per-pixel luminance afterwards."""
    def f(r):
        y = np.clip((r - black) / (white - black), 0, None) ** (1 / gamma)
        s = 1 - knee
        hi = knee + s * (1 - np.exp(-(y - knee) / s))
        y = np.clip(np.where(y > knee, hi, y), 0, 1)
        if sat != 1.0:
            lum = (y * [0.2126, 0.7152, 0.0722]).sum(axis=-1, keepdims=True)
            y = np.clip(lum + sat * (y - lum), 0, 1)
        return y
    f.label = (f"knee {black:g}-{white:g} g{gamma:g}"
               + (f" sat{sat:g}" if sat != 1.0 else ""))
    return f


CANDIDATES = [
    knee_curve(0.35, 1.4, black=0.01),      # chosen in A3; see stretch.py

    knee_curve(0.40, 1.5, black=0.01),
    knee_curve(0.35, 1.5, black=0.012, sat=1.2),
    knee_curve(0.40, 1.6, black=0.015, sat=1.3),
]


# --- reading ---------------------------------------------------------------

def read(tile, win=None, size=480):
    """Return (rgb float reflectance HxWx3, valid mask HxW)."""
    path = src_path(tile)
    opts = dict(bandList=[1, 2, 3], format="MEM", outputType=gdal.GDT_UInt16)
    if win:
        w, n, e, s = win
        opts.update(projWin=[w, n, e, s])       # full resolution
    else:
        path = gdal.Open(path, gdal.GA_ReadOnly)
        opts.update(width=size, height=size)    # GDAL picks an overview
    ds = gdal.Translate("", path, **opts)
    a = ds.ReadAsArray().astype(np.float32)     # 3xHxW
    valid = np.all(a > 0, axis=0)
    return np.moveaxis(a, 0, -1) / 10000.0, valid


def render(rgb, valid, curve):
    out = (1 + 254 * curve(rgb)).round().astype(np.uint8)
    out[~valid] = (255, 0, 255)   # magenta = NoData, so holes are obvious
    return Image.fromarray(out, "RGB")


# --- commands ----------------------------------------------------------------

def cmd_stats(tiles):
    pcts = [1, 5, 50, 95, 98, 99, 99.5, 99.9]
    print("percentiles of reflectance x10000, valid pixels, 1500px overview")
    print(f"{'tile':8} {'band':5} " + " ".join(f"p{p:<5g}" for p in pcts) + "  valid%")
    for t in tiles:
        rgb, valid = read(t, size=1500)
        for i, b in enumerate("RGB"):
            v = rgb[..., i][valid] * 10000
            q = np.percentile(v, pcts)
            print(f"{t:8} {b:5} " + " ".join(f"{x:<6.0f}" for x in q)
                  + f"  {100 * valid.mean():.0f}")


def cmd_sheet(out, tile, win=None):
    rgb, valid = read(tile, win)
    tiles = [render(rgb, valid, c) for c in CANDIDATES]
    w, h = tiles[0].size
    scale = min(1.0, 480 / max(w, h))
    w, h = int(w * scale), int(h * scale)
    sheet = Image.new("RGB", (w * len(tiles), h + 22), "white")
    d = ImageDraw.Draw(sheet)
    for i, (im, c) in enumerate(zip(tiles, CANDIDATES)):
        sheet.paste(im.resize((w, h), Image.BILINEAR), (i * w, 22))
        d.text((i * w + 6, 5), f"{chr(65 + i)}: {c.label}", fill="black")
    sheet.save(out)
    print(out, sheet.size)


if __name__ == "__main__":
    cmd, *args = sys.argv[1:]
    if cmd == "stats":
        cmd_stats(args)
    elif cmd == "sheet":
        out, tile, *win = args
        cmd_sheet(out, tile, [float(x) for x in win] if win else None)
    else:
        sys.exit(__doc__)
