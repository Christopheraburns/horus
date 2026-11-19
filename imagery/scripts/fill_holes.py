"""Fill small NoData holes in one ESA WorldCover S2 source cell.

  python3 fill_holes.py SRC.tif OUT.tif [--max-hole PIXELS] [--search PIXELS]

The 2021 composite has NoData holes on land, mostly on very bright new-build
sand (presumably rejected as cloud). The 2020 composite has the same holes, so
they are filled by interpolation instead:

  1. valid = band 1 != 0
  2. sieve the valid mask: NoData regions smaller than --max-hole pixels
     (default 20000 = 2 km^2) are enclosed holes; open sea and the coastal
     NoData strip are far larger and stay NoData
  3. GDAL FillNodata (inverse-distance, up to --search pixels) on bands 1-3,
     kept only inside those holes

Writes a 4-band UInt16 GeoTIFF: 1-3 = R, G, B (raw reflectance x 10000),
4 = alpha (0 or 255). Valid pixels are copied unchanged. Use with
`stretch.py --alpha-band 4`.
"""
import argparse
import time

import numpy as np
from osgeo import gdal

gdal.UseExceptions()


def mem_like(ds, nbands, dtype):
    return gdal.GetDriverByName("MEM").Create(
        "", ds.RasterXSize, ds.RasterYSize, nbands, dtype)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--max-hole", type=int, default=20000)
    ap.add_argument("--search", type=int, default=100)
    a = ap.parse_args()
    t0 = time.time()

    src = gdal.Open(a.src)
    rgb = src.ReadAsArray(band_list=[1, 2, 3])          # 3 x H x W, UInt16
    valid = rgb[0] != 0

    # Sieve: small NoData polygons merge into their (valid) neighbour.
    m = mem_like(src, 2, gdal.GDT_Byte)
    m.GetRasterBand(1).WriteArray(valid.astype(np.uint8))
    gdal.SieveFilter(m.GetRasterBand(1), None, m.GetRasterBand(2), a.max_hole, 4)
    holes = (m.GetRasterBand(2).ReadAsArray() == 1) & ~valid
    n_holes = int(holes.sum())

    if n_holes:
        # Fill only the bounding box of the holes (plus the search margin).
        rows = np.flatnonzero(holes.any(axis=1))
        cols = np.flatnonzero(holes.any(axis=0))
        r0 = max(rows[0] - a.search, 0); r1 = min(rows[-1] + a.search + 1, holes.shape[0])
        c0 = max(cols[0] - a.search, 0); c1 = min(cols[-1] + a.search + 1, holes.shape[1])
        r0, r1, c0, c1 = int(r0), int(r1), int(c0), int(c1)
        h, w = r1 - r0, c1 - c0
        f = gdal.GetDriverByName("MEM").Create("", w, h, 4, gdal.GDT_UInt16)
        f.GetRasterBand(4).WriteArray(valid[r0:r1, c0:c1].astype(np.uint16))
        for i in range(3):
            b = f.GetRasterBand(i + 1)
            b.WriteArray(rgb[i, r0:r1, c0:c1])
            gdal.FillNodata(b, f.GetRasterBand(4), maxSearchDist=a.search,
                            smoothingIterations=0)
            filled = b.ReadAsArray()
            sub = rgb[i, r0:r1, c0:c1]
            hsub = holes[r0:r1, c0:c1]
            sub[hsub] = filled[hsub]
        # Anything the search radius could not reach stays NoData.
        holes &= rgb[0] != 0
    alpha = ((valid | holes) * 255).astype(np.uint16)

    drv = gdal.GetDriverByName("GTiff")
    out = drv.Create(a.out, src.RasterXSize, src.RasterYSize, 4, gdal.GDT_UInt16,
                     ["COMPRESS=DEFLATE", "PREDICTOR=2", "TILED=YES",
                      "BLOCKXSIZE=512", "BLOCKYSIZE=512", "BIGTIFF=IF_SAFER",
                      "NUM_THREADS=ALL_CPUS"])
    out.SetGeoTransform(src.GetGeoTransform())
    out.SetProjection(src.GetProjection())
    for i in range(3):
        out.GetRasterBand(i + 1).WriteArray(rgb[i])
    out.GetRasterBand(4).WriteArray(alpha)
    out.GetRasterBand(4).SetColorInterpretation(gdal.GCI_AlphaBand)
    out = None
    print(f"{a.src.rsplit('/', 1)[-1]}: filled {n_holes} px in holes "
          f"({100 * n_holes / valid.size:.3f} %), {time.time() - t0:.0f} s")


if __name__ == "__main__":
    main()
