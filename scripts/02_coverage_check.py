"""
02_coverage_check.py
Nooksack Fish Passage Barrier Prioritization, Step 0: coverage check.

Answers the go/no-go question before Weekend 1:
  - What's inside the FPDSI and SWIFD downloads (layers, fields, counts)
  - How many barrier sites fall in the study area, by status / % passable /
    owner / feature type
  - How far barriers sit from the NHDPlus HR flowlines (the 50 m QA rule)
  - How well SWIFD matches the flowlines (ReachCode join rate) and which
    species are present

Run from the folder holding the zips and 01_build_network.py's outputs:
  python 02_coverage_check.py
  python 02_coverage_check.py --fpdsi WdfwFishPassage.zip --swifd SWIFD.zip \
      --nhd NHDPLUS_H_1711_HU4_GDB --huc8 17110004

Writes data/processed/coverage_report.txt (upload that file back to Claude).
"""

import argparse
import re
import sys
import warnings
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio

warnings.filterwarnings("ignore", message=".*Measured \\(M\\) geometry.*")
UTM10N = 26910
NULL_CODES = [-99.99, -999, -99, -9999]  # FPDSI placeholder nulls

REPORT = []


def out(line=""):
    print(line)
    REPORT.append(str(line))


def section(title):
    out()
    out("=" * 70)
    out(title)
    out("=" * 70)


# ---------------------------------------------------------------- helpers
def unpack(path: Path) -> Path:
    """Unzip next to the zip (once) and return the folder."""
    if path.is_dir():
        return path
    dest = path.with_suffix("")
    if not dest.exists():
        print(f"Unzipping {path.name} ...")
        with zipfile.ZipFile(path) as z:
            z.extractall(dest)
    return dest


def datasets_in(folder: Path):
    """Yield (source, layer) for every vector layer in gdbs/gpkgs/shps."""
    found = []
    for src in sorted(list(folder.glob("**/*.gdb")) + list(folder.glob("**/*.gpkg"))):
        for name, geom in pyogrio.list_layers(src):
            found.append((src, name, geom))
    for shp in sorted(folder.glob("**/*.shp")):
        found.append((shp, None, "shapefile"))
    return found


def describe(folder: Path):
    layers = datasets_in(folder)
    if not layers:
        out(f"  !! no .gdb/.gpkg/.shp found under {folder}")
    for src, name, geom in layers:
        try:
            info = pyogrio.read_info(src, layer=name)
            out(f"  {src.name} :: {name or src.stem}  [{info['geometry_type']}, "
                f"{info['features']:,} features]")
            out(f"     fields: {', '.join(info['fields'])}")
        except Exception as e:  # noqa: BLE001
            out(f"  {src.name} :: {name}  (could not read: {e})")
    return layers


def pick_layer(layers, want_geom, prefer=()):
    """Choose the largest layer of the wanted geometry; prefer name hints."""
    best, best_n = None, -1
    for src, name, _ in layers:
        try:
            info = pyogrio.read_info(src, layer=name)
        except Exception:  # noqa: BLE001
            continue
        g = (info["geometry_type"] or "").lower()
        if want_geom not in g:
            continue
        n = info["features"]
        label = (name or src.stem).lower()
        if any(p in label for p in prefer):
            n += 10**9  # name hint wins
        if n > best_n:
            best, best_n = (src, name), n
    return best


def find_col(df, *patterns, exclude=()):
    """First column whose lowercased name matches any regex pattern."""
    for p in patterns:
        for c in df.columns:
            lc = c.lower()
            if re.search(p, lc) and not any(re.search(x, lc) for x in exclude):
                return c
    return None


def counts(df, col, label, top=25):
    if col is None:
        out(f"\n{label}: (no matching field found)")
        return
    vc = df[col].astype("string").fillna("<null>").value_counts()
    out(f"\n{label}  [field: {col}]")
    for k, v in vc.head(top).items():
        out(f"  {v:>7,}  {k}")
    if len(vc) > top:
        out(f"  ... {len(vc) - top} more values")


def study_area(nhd: Path, huc8s):
    gdb = next(nhd.glob("**/*.gdb"), None) if nhd.is_dir() and nhd.suffix != ".gdb" else nhd
    if gdb is None:
        sys.exit(f"No NHDPlus .gdb under {nhd}")
    wbd = pyogrio.read_dataframe(gdb, layer="WBDHU8")
    hcol = find_col(wbd, r"^huc8$")
    poly = wbd[wbd[hcol].isin(huc8s)]
    if poly.empty:
        sys.exit(f"HUC8 {huc8s} not found in WBDHU8")
    return poly.dissolve().to_crs(UTM10N)


def read_clipped(src, layer, area_utm):
    """Read only features within the study-area bbox, then clip precisely."""
    info = pyogrio.read_info(src, layer=layer)
    crs = info["crs"]
    bbox = tuple(area_utm.to_crs(crs).total_bounds) if crs else None
    gdf = pyogrio.read_dataframe(src, layer=layer, bbox=bbox)
    if gdf.crs is None:
        gdf = gdf.set_crs(crs or 4326)
    gdf = gdf.to_crs(UTM10N)
    return gdf[gdf.intersects(area_utm.geometry.iloc[0])]


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fpdsi", type=Path, default=Path("WdfwFishPassage.zip"))
    ap.add_argument("--swifd", type=Path, default=Path("SWIFD.zip"))
    ap.add_argument("--nhd", type=Path, default=Path("NHDPLUS_H_1711_HU4_GDB"))
    ap.add_argument("--flowlines", type=Path,
                    default=Path("data/processed/flowlines.gpkg"))
    ap.add_argument("--huc8", nargs="+", default=["17110004"])
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    area = study_area(args.nhd, args.huc8)
    out(f"Study area: HUC8 {', '.join(args.huc8)}  "
        f"({area.geometry.area.iloc[0] / 1e6:,.0f} km²)")

    fl = gpd.read_file(args.flowlines, layer="flowlines")
    out(f"Flowlines loaded: {len(fl):,}")

    # ============================== FPDSI ==============================
    section("FPDSI: contents")
    fp_dir = unpack(args.fpdsi)
    fp_layers = describe(fp_dir)
    pick = pick_layer(fp_layers, "point", prefer=("site", "barrier", "passage"))
    if not pick:
        sys.exit("No point layer found in FPDSI download")
    src, layer = pick
    out(f"\nUsing barrier layer: {src.name} :: {layer or src.stem}")

    bar = read_clipped(src, layer, area)
    section(f"FPDSI: {len(bar):,} sites in study area")

    status = find_col(bar, r"barrier.*status.*(desc|name|text)", r"barrier.*status",
                      r"passage.*status", r"^status")
    pct = find_col(bar, r"percent.*pass.*(desc|name|text)", r"percent.*pass",
                   r"pct.*pass", r"passab")
    owner = find_col(bar, r"owner.*type.*(desc|name|text)", r"owner.*type",
                     r"owner")
    ftype = find_col(bar, r"feature.*type.*(desc|name|text)", r"feature.*type",
                     r"site.*type", r"structure.*type")
    fishuse = find_col(bar, r"fish.*use.*(desc|name|text)", r"fish.*use")
    sid = find_col(bar, r"^site.?id$", r"siteid", r"site.*id")

    counts(bar, status, "Barrier status")
    counts(bar, pct, "Percent passable")
    counts(bar, ftype, "Feature type")
    counts(bar, owner, "Owner type")
    counts(bar, fishuse, "Fish use")

    if pct is not None:
        num = pd.to_numeric(bar[pct], errors="coerce")
        null_like = num.isin(NULL_CODES).sum()
        out(f"\nPercent passable: {num.notna().sum():,} numeric, "
            f"{null_like:,} are placeholder nulls (-99.99/-999), "
            f"{num.isna().sum():,} non-numeric or empty")

    if sid is not None:
        dups = bar[sid].duplicated(keep=False).sum()
        out(f"\nDuplicate {sid} values: {dups:,} rows")
    xy_dups = bar.geometry.apply(lambda g: (round(g.x, 1), round(g.y, 1))
                                 if g is not None and not g.is_empty else None)
    out(f"Sites sharing identical coordinates (0.1 m): "
        f"{xy_dups.duplicated(keep=False).sum():,} rows")

    # Distance to nearest flowline (the 50 m QA rule)
    pts = bar[bar.geometry.notna() & ~bar.geometry.is_empty].copy()
    near = gpd.sjoin_nearest(pts[["geometry"]], fl[["geometry"]],
                             how="left", distance_col="dist_m")
    d = near.groupby(level=0)["dist_m"].min()
    out("\nDistance from barrier to nearest NHDPlus HR flowline:")
    for lo, hi in [(0, 10), (10, 25), (25, 50), (50, 100), (100, 250), (250, 1e12)]:
        n = ((d >= lo) & (d < hi)).sum()
        label = f"{lo:g}-{hi:g} m" if hi < 1e12 else f">= {lo:g} m"
        out(f"  {n:>7,}  {label}")
    out(f"  median {d.median():.1f} m, 90th pct {d.quantile(0.9):.1f} m")

    # ============================== SWIFD ==============================
    section("SWIFD: contents")
    sw_dir = unpack(args.swifd)
    sw_layers = describe(sw_dir)
    pick = pick_layer(sw_layers, "line", prefer=("swifd", "fish", "dist"))
    if not pick:
        out("No line layer found in SWIFD download")
    else:
        src, layer = pick
        out(f"\nUsing fish distribution layer: {src.name} :: {layer or src.stem}")
        sw = read_clipped(src, layer, area)
        section(f"SWIFD: {len(sw):,} segments in study area")

        species = find_col(sw, r"species.*(name|desc)", r"spp.*(name|desc)",
                           r"common.*name", r"species", r"spp")
        run = find_col(sw, r"run.*(desc|name)", r"run", exclude=(r"^runtime",))
        dist = find_col(sw, r"dist.*type.*desc", r"dist.*type", r"^dt$")
        use = find_col(sw, r"use.*type.*desc", r"use.*type", r"lifehist.*desc")
        counts(sw, species, "Species")
        counts(sw, run, "Run")
        counts(sw, dist, "Distribution type")
        counts(sw, use, "Use type / life history")

        rc = find_col(sw, r"reach.?code", r"reachcd")
        if rc is not None:
            sw_rc = set(sw[rc].dropna().astype(str).str.strip())
            fl_rc = set(fl["reachcode"].dropna().astype(str).str.strip())
            hit = sw_rc & fl_rc
            out(f"\nReachCode join [field: {rc}]: {len(hit):,} of {len(sw_rc):,} "
                f"SWIFD reach codes ({len(hit) / max(len(sw_rc), 1):.1%}) "
                f"found in NHDPlus HR flowlines")
            fl_hit = fl["reachcode"].astype(str).isin(sw_rc)
            out(f"Flowlines tagged fish-bearing via ReachCode: {fl_hit.sum():,} "
                f"({fl.loc[fl_hit, 'length_m'].sum() / 1000:,.0f} km of "
                f"{fl['length_m'].sum() / 1000:,.0f} km)")
        else:
            out("\nNo ReachCode field in SWIFD; habitat tagging will need a "
                "spatial overlay instead of a join.")
        swlen = sw.geometry.length.sum() / 1000
        out(f"SWIFD line length in study area (all species, overlapping): "
            f"{swlen:,.0f} km")

    rpt = args.out / "coverage_report.txt"
    rpt.write_text("\n".join(REPORT) + "\n", encoding="utf-8")
    print(f"\nReport written to {rpt.resolve()}")


if __name__ == "__main__":
    main()
