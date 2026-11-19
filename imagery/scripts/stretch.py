"""The Horus imagery stretch (burndown A3): one curve for every file.

Builds an 8-bit RGBA VRT over an ESA WorldCover S2 RGBNIR source (a single
GeoTIFF or a mosaic VRT). Bands 1-3 go through a lookup table that encodes the
curve below; band 4 is alpha from the source NoData mask.

  python3 stretch.py SRC OUT.vrt [--alpha-band N]

With --alpha-band, alpha is read from band N of SRC (values 0 or 255, as
written by fill_holes.py) instead of the NoData mask of band 1.

Run inside the GDAL container. Keep CURVE in sync with BURNDOWN-IMAGERY.md.
"""
import math
import sys
from xml.sax.saxutils import escape

from osgeo import gdal

gdal.UseExceptions()

# --- the curve (reflectance = raw / 10000) ---------------------------------
BLACK = 0.010    # reflectance mapped to output 1 (removes residual haze)
WHITE = 0.35     # reflectance where the gamma part would reach 255
GAMMA = 1.4      # out = x ** (1 / GAMMA)
KNEE = 0.80      # above this output fraction, roll off softly instead of clipping


def curve(r):
    """Reflectance -> output fraction 0..1."""
    x = max((r - BLACK) / (WHITE - BLACK), 0.0)
    y = x ** (1 / GAMMA)
    if y > KNEE:
        s = 1 - KNEE
        y = KNEE + s * (1 - math.exp(-(y - KNEE) / s))
    return min(max(y, 0.0), 1.0)


def dn(raw):
    """Raw UInt16 -> output byte. 0 stays 0 (NoData); valid pixels are 1..255."""
    if raw <= 0:
        return 0
    return 1 + round(254 * curve(raw / 10000.0))


def lut():
    """Piecewise-linear LUT, 'in:out,...'. Breakpoints are dense where the
    curve bends (low reflectance), sparse in the shoulder; max error < 1 DN."""
    pts = {0, 1}
    raw = 1.0
    while raw < 20000:
        pts.add(int(round(raw)))
        raw = raw * 1.04 + 4
    pts.update([20000, 30000, 65535])
    return ",".join(f"{p}:{dn(p)}" for p in sorted(pts))


# --- VRT -----------------------------------------------------------------

def build(src, out, alpha_band=None):
    ds = gdal.Open(src)
    x, y = ds.RasterXSize, ds.RasterYSize
    bx, by = ds.GetRasterBand(1).GetBlockSize()
    table = lut()
    src_xml = escape(src)
    bands = []
    for i, ci in enumerate(["Red", "Green", "Blue"], start=1):
        bands.append(f"""  <VRTRasterBand dataType="Byte" band="{i}">
    <ColorInterp>{ci}</ColorInterp>
    <ComplexSource>
      <SourceFilename relativeToVRT="0">{src_xml}</SourceFilename>
      <SourceBand>{i}</SourceBand>
      <SourceProperties RasterXSize="{x}" RasterYSize="{y}" DataType="UInt16" BlockXSize="{bx}" BlockYSize="{by}"/>
      <SrcRect xOff="0" yOff="0" xSize="{x}" ySize="{y}"/>
      <DstRect xOff="0" yOff="0" xSize="{x}" ySize="{y}"/>
      <LUT>{table}</LUT>
    </ComplexSource>
  </VRTRasterBand>""")
    bands.append(f"""  <VRTRasterBand dataType="Byte" band="4">
    <ColorInterp>Alpha</ColorInterp>
    <SimpleSource>
      <SourceFilename relativeToVRT="0">{src_xml}</SourceFilename>
      <SourceBand>{alpha_band or "mask,1"}</SourceBand>
      <SrcRect xOff="0" yOff="0" xSize="{x}" ySize="{y}"/>
      <DstRect xOff="0" yOff="0" xSize="{x}" ySize="{y}"/>
    </SimpleSource>
  </VRTRasterBand>""")
    gt = ", ".join(repr(v) for v in ds.GetGeoTransform())
    xml = (f'<VRTDataset rasterXSize="{x}" rasterYSize="{y}">\n'
           f"  <SRS>{escape(ds.GetProjection())}</SRS>\n"
           f"  <GeoTransform>{gt}</GeoTransform>\n"
           + "\n".join(bands) + "\n</VRTDataset>\n")
    with open(out, "w") as f:
        f.write(xml)


if __name__ == "__main__":
    args = sys.argv[1:]
    alpha = None
    if "--alpha-band" in args:
        i = args.index("--alpha-band")
        alpha = int(args[i + 1])
        del args[i:i + 2]
    if len(args) != 2:
        sys.exit(__doc__)
    build(args[0], args[1], alpha)
