"""D1: write MANIFEST.md for every horus-imagery-*.mbtiles in a directory.

  python3 manifest.py OUTDIR

Reads each file's MBTiles metadata and tile counts, and its NAME.sources.txt
(written by region.sh / global.sh), and runs SQLite's quick_check. Exits
non-zero if a file fails the check or misses required metadata. SHA256SUMS is
written afterwards by delivery.sh (it must cover this manifest too).
"""
import datetime
import glob
import os
import re
import sqlite3
import sys

REQUIRED = ["name", "format", "minzoom", "maxzoom", "bounds", "attribution"]


def human(n):
    """Decimal units (1 GB = 10^9 bytes), as storage and transfer tools quote."""
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1000 or unit == "GB":
            return f"{n:.2f} {unit}" if unit == "GB" else (
                f"{n:.0f} {unit}" if unit != "B" else f"{n} B")
        n /= 1000


def main(outdir):
    files = sorted(glob.glob(os.path.join(outdir, "horus-imagery-*.mbtiles")))
    # the global base first, then regions alphabetically
    files.sort(key=lambda f: (not f.endswith("-global.mbtiles"), f))
    rows, details, problems, total = [], [], [], 0
    for path in files:
        base = os.path.basename(path)
        stem = base[: -len(".mbtiles")]
        size = os.path.getsize(path)
        total += size
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        meta = dict(db.execute("SELECT name, value FROM metadata"))
        counts = db.execute(
            "SELECT zoom_level, COUNT(*) FROM tiles GROUP BY zoom_level "
            "ORDER BY zoom_level").fetchall()
        check = db.execute("PRAGMA quick_check").fetchone()[0]
        db.close()
        missing = [k for k in REQUIRED if not meta.get(k)]
        if missing:
            problems.append(f"{base}: missing metadata {missing}")
        if check != "ok":
            problems.append(f"{base}: quick_check {check}")
        print(f"{base}: {human(size)}, z{meta.get('minzoom')}-{meta.get('maxzoom')}, "
              f"quick_check {check}", file=sys.stderr)

        src_path = os.path.join(outdir, f"{stem}.sources.txt")
        header, cells = "", []
        if os.path.exists(src_path):
            lines = open(src_path).read().splitlines()
            header = lines[0].lstrip("# ") if lines and lines[0].startswith("#") else ""
            cells = [l for l in lines if l and not l.startswith("#")]
        else:
            problems.append(f"{base}: no {stem}.sources.txt")
        box = re.search(r"box (W=\S+ S=\S+ E=\S+ N=\S+)", header)
        level = re.search(r"overview level (\d)", header)
        built = re.search(r"built (\S+)", header)

        w, s, e, n = (float(v) for v in meta["bounds"].split(","))
        bounds = f"{w:.4f}, {s:.4f}, {e:.4f}, {n:.4f}"
        ntiles = sum(c for _, c in counts)
        rows.append(f"| `{base}` | {human(size)} | {meta['minzoom']}–{meta['maxzoom']} "
                    f"| {bounds} | {ntiles:,} | {len(cells):,} |")

        d = [f"### `{base}`", ""]
        d.append(f"- Name: `{meta['name']}`; format `{meta['format']}`; "
                 f"zooms {meta['minzoom']}–{meta['maxzoom']}; {size:,} bytes")
        d.append(f"- Bounds (W, S, E, N; degrees): {bounds}")
        if box:
            d.append(f"- Requested box: {box[1]}")
        if built:
            d.append(f"- Built: {built[1]}")
        d.append("- Tiles per zoom: " + ", ".join(f"z{z} {c:,}" for z, c in counts))
        if level:
            px = {2: 1500, 3: 750}.get(int(level[1]), "?")
            d.append(f"- Source: {len(cells):,} ESA WorldCover 2021 S2 RGBNIR cells, "
                     f"read from their built-in overview level {level[1]} "
                     f"({px} px per 1° cell); full list in `{stem}.sources.txt`")
        else:
            names = [re.search(r"_([NS]\d\d[EW]\d\d\d)_", c)[1] for c in cells]
            d.append(f"- Source: {len(cells)} ESA WorldCover 2021 S2 RGBNIR cells at "
                     f"full resolution (10 m): {', '.join(names)}. "
                     f"Full object paths in `{stem}.sources.txt`")
        details.append("\n".join(d))

    out = [
        "# Horus offline imagery: manifest",
        "",
        f"Generated {datetime.datetime.now(datetime.timezone.utc):%Y-%m-%d %H:%M} UTC "
        f"by `imagery/scripts/manifest.py`. {len(files)} files, {human(total)} in total.",
        "",
        "Raster MBTiles, WebP tiles (quality 85), 256 × 256, XYZ Web Mercator. "
        "Ocean and other NoData areas are transparent. Every file uses the same "
        "colour stretch (see `BURNDOWN-IMAGERY.md`, A3), so the global base and "
        "the regions match where they meet.",
        "",
        "Source: ESA WorldCover 2021 Sentinel-2 composites, "
        "`s3://esa-worldcover-s2/rgbnir/2021/` (CC BY 4.0). "
        "Attribution, which must be shown on the map and is set in every file:",
        "",
        "> ESA WorldCover project 2021 / Contains modified Copernicus Sentinel "
        "data (2021) processed by ESA WorldCover consortium",
        "",
        "Verify the files with `sha256sum -c SHA256SUMS` in this directory.",
        "",
        "## Files",
        "",
        "| File | Size | Zooms | Bounds (W, S, E, N) | Tiles | Source cells |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
        "## Details",
        "",
        "\n\n".join(details),
        "",
    ]
    with open(os.path.join(outdir, "MANIFEST.md"), "w") as f:
        f.write("\n".join(out))
    if problems:
        sys.exit("PROBLEMS:\n  " + "\n  ".join(problems))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
