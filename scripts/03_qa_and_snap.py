"""
03_qa_and_snap.py
Nooksack Fish Passage Barrier Prioritization, steps 2-3: QA/QC and snapping.

For every FPDSI site in the study area:
  1. Decode WDFW's integer codes into readable fields
  2. Raise QA flags (duplicates, missing passability, >50 m from a flowline,
     corrected, unknown status, status/passability conflicts)
  3. Snap to the nearest NHDPlus HR flowline and record where on the line it
     sits (meters from the upstream end; NHD lines are digitized downstream)
  4. Assign a role:
       candidate : human-made, confirmed barrier, not corrected, snapped,
                   fish use not "No"  -> gets ranked in step 4
       stop      : blocks upstream traces but isn't ranked (natural barriers,
                   confirmed barriers on non-fish-bearing streams)
       excluded  : everything else, with a reason

Usage (from the folder holding the downloads and data/processed):
  python 03_qa_and_snap.py
  python 03_qa_and_snap.py --fpdsi WdfwFishPassage.zip --nhd NHDPLUS_H_1711_HU4_GDB

Outputs in data/processed:
  barriers_qa.gpkg   layers "sites" (original points) and "sites_snapped"
  qa_table.csv       one row per site, all flags and decoded fields
  qa_summary.txt     counts for the README
"""

import argparse
import sys
import warnings
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import re
from shapely.geometry import LineString, MultiLineString
from shapely.ops import linemerge

warnings.filterwarnings("ignore", message=".*Measured \\(M\\) geometry.*")

UTM10N = 26910
SNAP_MAX_M = 50.0
DUP_TOL_M = 1.0
UNKNOWN_PCT_FILL = 33
ARTIFICIAL_PATH = 558   # NHD FType: centerline through river/lake polygons
BIG_RIVER_ORDER = 6     # culverts can't snap to streams this big  # decision: unassessed confirmed barriers scored at 33%

# ---- WDFW_FishPassageSite domains (from WDFW's hosted layer) ----
STATUS = {0: "NA", 10: "Yes", 20: "No", 99: "Unknown"}
PCT_LABEL = {0: "N/A", 10: "0", 20: "33", 30: "67", 40: "100", 99: "Unknown"}
PCT_VALUE = {10: 0, 20: 33, 30: 67, 40: 100}
FTYPE = {1: "Culvert", 2: "Non-Culvert Xing", 3: "Dam", 4: "Other", 5: "Natural"}
OWNER = {1: "City", 2: "County", 3: "Federal", 4: "Private", 5: "State",
         6: "Tribal", 7: "Other", 8: "Port", 9: "Drainage District",
         10: "Diking District", 11: "Irrigation District", 12: "Unknown"}
FISHUSE = {0: "Missing", 10: "Yes", 20: "No", 99: "Unknown"}
CORRECTION = {1: "Culvert removed, crossing abandoned", 2: "Culvert replaced with bridge",
              3: "Culvert replaced with culvert", 4: "Culvert retrofitted with fishway",
              5: "Dam removal", 6: "Dam retrofitted with fishway",
              7: "Fishway rebuild", 8: "Other", 9: "Tidegate removed"}
HUMAN_MADE = {1, 2, 3, 4}
NATURAL = 5


def find_gdb(path: Path) -> Path:
    if path.suffix.lower() == ".gdb" and path.is_dir():
        return path
    folder = path
    if path.suffix.lower() == ".zip":
        folder = path.with_suffix("")
        if not folder.exists():
            with zipfile.ZipFile(path) as z:
                z.extractall(folder)
    gdb = next(folder.glob("**/*.gdb"), None)
    if gdb is None:
        sys.exit(f"No .gdb found in {path}")
    return gdb


def code(series):
    return pd.to_numeric(series, errors="coerce").round().astype("Int64")


def decode(series, table, missing="<blank>"):
    return series.map(lambda v: missing if pd.isna(v) else table.get(int(v), f"code {v}"))


GENERIC = {"creek", "cr", "crk", "river", "r", "riv", "slough", "sl", "fork", "fk",
           "ditch", "trib", "tributary", "to", "of", "the", "n", "s", "e", "w",
           "north", "south", "east", "west", "middle", "nf", "sf", "mf",
           "unnamed", "lake", "pond", "branch", "br", "drain", "lt", "rt", "nan"}


def name_tokens(name):
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return set()
    t = re.sub(r"'s\b", "", str(name).lower())
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    toks = {w.rstrip("s") for w in t.split() if w not in GENERIC and len(w) > 1}
    return {w for w in toks if w}


def names_match(fpdsi_name, gnis_name):
    a, b = name_tokens(fpdsi_name), name_tokens(gnis_name)
    return bool(a) and bool(b) and bool(a & b)


def as_line(geom):
    """Flowlines come in as MultiLineStrings; merge to one line for project()."""
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        return LineString([c for part in geom.geoms for c in part.coords])
    return geom


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fpdsi", type=Path, default=Path("WdfwFishPassage.zip"))
    ap.add_argument("--layer", default="WDFW_FishPassageSite")
    ap.add_argument("--nhd", type=Path, default=Path("NHDPLUS_H_1711_HU4_GDB"))
    ap.add_argument("--huc8", nargs="+", default=["17110004"])
    ap.add_argument("--flowlines", type=Path,
                    default=Path("data/processed/flowlines.gpkg"))
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    # ---- Study area + flowlines ----
    nhd_gdb = find_gdb(args.nhd)
    wbd = pyogrio.read_dataframe(nhd_gdb, layer="WBDHU8")
    wbd.columns = [c.lower() if c != "geometry" else c for c in wbd.columns]
    area = wbd[wbd["huc8"].isin(args.huc8)].dissolve().to_crs(UTM10N)
    area_geom = area.geometry.iloc[0]
    fl = gpd.read_file(args.flowlines, layer="flowlines")
    fl["nhdplusid"] = fl["nhdplusid"].astype("int64")

    # ---- FPDSI sites in study area ----
    fp_gdb = find_gdb(args.fpdsi)
    crs = pyogrio.read_info(fp_gdb, layer=args.layer)["crs"]
    bbox = tuple(area.to_crs(crs).total_bounds)
    s = pyogrio.read_dataframe(fp_gdb, layer=args.layer, bbox=bbox).to_crs(UTM10N)
    s = s[s.intersects(area_geom)].reset_index(drop=True)
    n_all = len(s)

    # ---- Decode ----
    s["status_cd"] = code(s["FishPassageBarrierStatusCode"])
    s["pct_cd"] = code(s["PercentFishPassableCode"])
    s["ftype_cd"] = code(s["FishPassageFeatureTypeCode"])
    s["owner_cd"] = code(s["OwnerTypeCode"])
    s["fishuse_cd"] = code(s["FishUseCode"])
    s["corr_cd"] = code(s["BarrierCorrectionTypeCode"])

    s["barrier_status"] = decode(s["status_cd"], STATUS)
    s["pct_passable_label"] = decode(s["pct_cd"], PCT_LABEL)
    s["feature_type"] = decode(s["ftype_cd"], FTYPE)
    s["owner_type"] = decode(s["owner_cd"], OWNER)
    s["fish_use"] = decode(s["fishuse_cd"], FISHUSE)
    s["correction"] = s["corr_cd"].map(
        lambda v: "" if pd.isna(v) or v == 0 else CORRECTION.get(int(v), f"code {v}"))

    # ---- QA flags ----
    is_barrier = s["status_cd"] == 10
    s["qa_unknown_status"] = ~s["status_cd"].isin([10, 20]) & (s["ftype_cd"] != NATURAL)
    s["qa_corrected"] = s["correction"] != ""
    s["qa_missing_pct"] = is_barrier & ~s["pct_cd"].isin(PCT_VALUE.keys())
    s["qa_pct_conflict"] = is_barrier & (s["pct_cd"] == 40)  # "barrier" but 100% passable
    s["qa_no_owner"] = s["owner_cd"].isna() | (s["owner_cd"] == 12)

    # Duplicates: same location within 1 m. Keep the most recently surveyed.
    s["_gx"] = (s.geometry.x / DUP_TOL_M).round()
    s["_gy"] = (s.geometry.y / DUP_TOL_M).round()
    s["_date"] = pd.to_datetime(s.get("SurveyDate"), errors="coerce")
    order = s.sort_values(["_gx", "_gy", "_date"], na_position="first")
    keep_idx = order.drop_duplicates(["_gx", "_gy"], keep="last").index
    grp = s.groupby(["_gx", "_gy"])["_gx"].transform("size")
    s["qa_duplicate"] = grp > 1
    s["qa_duplicate_dropped"] = s["qa_duplicate"] & ~s.index.isin(keep_idx)

    # ---- Snap to a flowline (constrained) ----
    # Candidates: every flowline within 50 m. Pick, in order:
    #   1. nearest flowline whose GNIS name matches the FPDSI stream name
    #   2. nearest *eligible* flowline. Culverts / non-culvert crossings / other
    #      can't sit on big rivers: exclude ArtificialPath (FType 558, river and
    #      lake centerlines) and stream order >= BIG_RIVER_ORDER.
    nearest = gpd.sjoin_nearest(s[["geometry"]], fl[["nhdplusid", "geometry"]],
                                how="left", distance_col="d")
    nearest = nearest[~nearest.index.duplicated(keep="first")]
    s["nearest_any_dist_m"] = nearest["d"].round(1)

    si, fi = fl.sindex.query(s.geometry.values, predicate="dwithin",
                             distance=SNAP_MAX_M)
    pairs = pd.DataFrame({"site": s.index.values[si], "fl": fi})
    pairs["dist"] = s.geometry.values[si].distance(fl.geometry.values[fi])
    pairs["ftype_fl"] = fl["ftype"].values[fi]
    pairs["order"] = pd.to_numeric(fl["streamorde"], errors="coerce").values[fi]
    pairs["gnis"] = fl["gnis_name"].values[fi] if "gnis_name" in fl else None
    small_only = s["ftype_cd"].isin([1, 2, 4]).values
    pairs["needs_small"] = small_only[pd.Index(s.index).get_indexer(pairs["site"])]
    big = (pairs["ftype_fl"] == ARTIFICIAL_PATH) | (pairs["order"] >= BIG_RIVER_ORDER)
    pairs["eligible"] = ~(pairs["needs_small"] & big)
    site_names = s["StreamName"] if "StreamName" in s else pd.Series("", index=s.index)
    pairs["name_match"] = [
        names_match(site_names.get(a), g) for a, g in zip(pairs["site"], pairs["gnis"])]

    ok = pairs[pairs["eligible"]].sort_values(
        ["site", "name_match", "dist"], ascending=[True, False, True])
    best = ok.drop_duplicates("site").set_index("site")
    s["snap_nhdplusid"] = pd.Series(
        fl["nhdplusid"].values[best["fl"].values], index=best.index).astype("Int64")
    s["snap_dist_m"] = best["dist"].round(1)
    s["snap_gnis_name"] = best["gnis"]
    s["snap_method"] = ""
    s.loc[best.index, "snap_method"] = np.where(best["name_match"], "name match",
                                                "nearest eligible")

    any_within = s.index.isin(pairs["site"])
    only_big = any_within & ~s.index.isin(best.index)
    s["qa_far_from_stream"] = ~s.index.isin(best.index)
    s["qa_only_big_river_nearby"] = only_big
    named = site_names.fillna("").astype(str).str.strip().str.lower().map(
        lambda n: n not in ("", "unnamed", "nan", "none"))
    s["qa_name_mismatch"] = (s.index.isin(best.index) & named
                             & (s["snap_method"] != "name match")
                             & s["snap_gnis_name"].notna())
    snapped = s.index.isin(best.index)
    snapped = pd.Series(snapped, index=s.index)

    lines = fl.set_index("nhdplusid").geometry.map(as_line)
    s["dist_from_upstream_end_m"] = pd.NA
    s["flowline_length_m"] = pd.NA
    snap_geoms = {}
    for i in s.index[snapped]:
        line = lines[int(s.at[i, "snap_nhdplusid"])]
        d = line.project(s.geometry[i])
        s.at[i, "dist_from_upstream_end_m"] = round(d, 1)
        s.at[i, "flowline_length_m"] = round(line.length, 1)
        snap_geoms[i] = line.interpolate(d)

    # ---- Effective passability for scoring ----
    s["pct_passable"] = s["pct_cd"].map(
        lambda v: PCT_VALUE.get(int(v)) if pd.notna(v) else None).astype("Float64")
    s["pct_estimated"] = is_barrier & s["pct_passable"].isna()
    s.loc[s["pct_estimated"], "pct_passable"] = UNKNOWN_PCT_FILL

    # ---- Roles ----
    human = s["ftype_cd"].isin(HUMAN_MADE)
    natural = s["ftype_cd"] == NATURAL
    usable = snapped & ~s["qa_duplicate_dropped"]
    open_barrier = human & is_barrier & ~s["qa_corrected"] & usable

    s["role"] = "excluded"
    s["excluded_reason"] = ""
    cand = open_barrier & (s["fishuse_cd"] != 20)
    stop_only = (open_barrier & (s["fishuse_cd"] == 20)) | (
        natural & (s["status_cd"] != 20) & usable)
    s.loc[cand, "role"] = "candidate"
    s.loc[stop_only, "role"] = "stop"

    reasons = [  # first matching reason wins: data status first, then location
        (s["qa_duplicate_dropped"], "duplicate"),
        (s["qa_corrected"], "corrected"),
        (natural & (s["status_cd"] == 20), "natural, not a barrier"),
        (s["status_cd"] == 20, "not a barrier"),
        (s["qa_unknown_status"], "barrier status unknown/blank"),
        (s["ftype_cd"].isna(), "no feature type"),
        (s["qa_only_big_river_nearby"], "culvert only near a large river"),
        (s["qa_far_from_stream"], "more than 50 m from a flowline"),
    ]
    ex = s["role"] == "excluded"
    for mask, why in reasons:
        hit = ex & mask & (s["excluded_reason"] == "")
        s.loc[hit, "excluded_reason"] = why
    s.loc[ex & (s["excluded_reason"] == ""), "excluded_reason"] = "other"
    s["is_stop"] = s["role"].isin(["candidate", "stop"])

    # ---- Outputs ----
    keep_cols = ["SiteId", "SiteRecordID", "StreamName", "TributaryToName", "RoadName",
                 "feature_type", "barrier_status", "pct_passable_label", "pct_passable",
                 "pct_estimated", "owner_type", "fish_use", "correction",
                 "LinealGainMeasurement", "PriorityIndexTotalQuantity",
                 "PotentialSpecies", "SurveyDate", "FormLinkURL",
                 "snap_nhdplusid", "snap_dist_m", "snap_method", "snap_gnis_name",
                 "nearest_any_dist_m", "dist_from_upstream_end_m",
                 "flowline_length_m", "role", "excluded_reason", "is_stop",
                 "qa_duplicate", "qa_duplicate_dropped", "qa_far_from_stream",
                 "qa_corrected", "qa_missing_pct", "qa_pct_conflict",
                 "qa_unknown_status", "qa_no_owner", "qa_only_big_river_nearby",
                 "qa_name_mismatch"]
    keep_cols = [c for c in keep_cols if c in s.columns]
    out = s[keep_cols + ["geometry"]].copy()
    for c in ("LinealGainMeasurement", "PriorityIndexTotalQuantity"):
        if c in out:  # FPDSI placeholder nulls
            v = pd.to_numeric(out[c], errors="coerce")
            out[c] = v.where(~v.isin([-99.99, -999, -99, -9999]))
    for c in ("dist_from_upstream_end_m", "flowline_length_m"):
        out[c] = pd.to_numeric(out[c], errors="coerce")
    if "SurveyDate" in out:
        out["SurveyDate"] = out["SurveyDate"].astype("string")

    gpkg = args.out / "barriers_qa.gpkg"
    out.to_file(gpkg, layer="sites", driver="GPKG")
    sn = out.loc[list(snap_geoms)].copy()
    sn = sn.set_geometry(gpd.GeoSeries(snap_geoms, crs=UTM10N).reindex(sn.index))
    sn.to_file(gpkg, layer="sites_snapped", driver="GPKG")
    out.drop(columns="geometry").to_csv(args.out / "qa_table.csv", index=False)

    # ---- Summary ----
    L = [f"FPDSI sites in study area (HUC8 {', '.join(args.huc8)}): {n_all:,}", "",
         "QA flags (a site can have several):"]
    for c in ["qa_duplicate", "qa_duplicate_dropped", "qa_far_from_stream",
              "qa_corrected", "qa_missing_pct", "qa_pct_conflict",
              "qa_unknown_status", "qa_no_owner", "qa_only_big_river_nearby",
              "qa_name_mismatch"]:
        L.append(f"  {int(s[c].sum()):>6,}  {c}")
    L += ["", "Roles:"]
    for k, v in s["role"].value_counts().items():
        L.append(f"  {v:>6,}  {k}")
    L += ["", "Excluded, by reason:"]
    for k, v in s.loc[s["role"] == "excluded", "excluded_reason"].value_counts().items():
        L.append(f"  {v:>6,}  {k}")
    c = s[s["role"] == "candidate"]
    L += ["", f"Candidates: {len(c):,}",
          f"  passability estimated at {UNKNOWN_PCT_FILL}%: {int(c['pct_estimated'].sum()):,}",
          "  by passability:"]
    for k, v in c["pct_passable_label"].value_counts().items():
        L.append(f"    {v:>6,}  {k}")
    L.append("  by feature type:")
    for k, v in c["feature_type"].value_counts().items():
        L.append(f"    {v:>6,}  {k}")
    L.append("  by owner:")
    for k, v in c["owner_type"].value_counts().items():
        L.append(f"    {v:>6,}  {k}")
    L += ["", "Snap method (snapped sites):"]
    for k, v in s.loc[snapped, "snap_method"].value_counts().items():
        L.append(f"  {v:>6,}  {k}")
    L += ["", f"Stop points total (candidates + stops): {int(s['is_stop'].sum()):,}",
          f"Snapped sites: median {s.loc[snapped, 'snap_dist_m'].median():.1f} m "
          f"from a flowline"]
    text = "\n".join(L)
    (args.out / "qa_summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nWrote {gpkg.name}, qa_table.csv, qa_summary.txt to {args.out.resolve()}")


if __name__ == "__main__":
    main()
