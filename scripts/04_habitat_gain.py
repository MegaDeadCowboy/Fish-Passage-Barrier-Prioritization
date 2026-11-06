"""
04_habitat_gain.py
Nooksack Fish Passage Barrier Prioritization, steps 4-6: habitat, gain, score.

  A. Tag fish-bearing flowlines from SWIFD (spatial match: a flowline carries a
     species if >= 2 of 3 points along it (25/50/75%) lie within 25 m of that
     species' SWIFD line). Each flowline gets a weight = max species weight.
  B. Functional gain for each candidate barrier: habitat length upstream,
     stopping at the next stop point (any candidate, natural barrier, or other
     confirmed barrier). Partial segments are handled with the snap position.
  C. Score = weighted gain (km) x (1 - percent passable / 100)
     where weighted gain = sum(reach habitat length x reach species weight).
  D. Summaries: top 20, blocked habitat by owner, by sub-basin (HUC10),
     comparison with WDFW's own LinealGainMeasurement.

Decisions (see project brief):
  weight 2: Chinook, steelhead, Dolly Varden/Bull Trout (ESA-listed)
  weight 1: coho, chum, pink, sockeye
  excluded: resident trout (cutthroat, rainbow, kokanee) and everything else
  distribution types counted: Documented, Presumed, Gradient Accessible,
  Potential (incl. Artificial-Documented)

Usage (same folder as before):
  python 04_habitat_gain.py
Outputs in data/processed:
  habitat_flowlines.gpkg  flowlines with species + weight (for the web map)
  barriers_ranked.gpkg    candidates with gain, score, rank (snapped points)
  barriers_ranked.csv
  gain_summary.txt
"""

import argparse
import re
import sys
import warnings
import zipfile
from collections import defaultdict, deque
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from shapely.strtree import STRtree

warnings.filterwarnings("ignore", message=".*Measured \\(M\\) geometry.*")
UTM10N = 26910
MATCH_DIST_M = 25.0
SAMPLE_FRACS = (0.25, 0.5, 0.75)
MIN_HITS = 2

WEIGHT_RULES = [  # (regex on SPECIESRUN, weight); first match wins
    (r"chinook|steelhead|bull trout", 2),
    (r"coho|chum|pink|sockeye", 1),
]
DIST_KEEP = r"documented|presumed|gradient|potential"


def find_in(path: Path, pattern: str) -> Path:
    folder = path
    if path.suffix.lower() == ".zip":
        folder = path.with_suffix("")
        if not folder.exists():
            with zipfile.ZipFile(path) as z:
                z.extractall(folder)
    hit = next(folder.glob(pattern), None) if folder.is_dir() else None
    if hit is None and path.match(pattern.split("/")[-1]):
        hit = path
    if hit is None:
        sys.exit(f"Nothing matching {pattern} in {path}")
    return hit


def col(df, *patterns):
    for p in patterns:
        for c in df.columns:
            if re.search(p, c.lower()):
                return c
    return None


def species_weight(name: str) -> int:
    n = (name or "").lower()
    for pat, w in WEIGHT_RULES:
        if re.search(pat, n):
            return w
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--swifd", type=Path, default=Path("SWIFD.zip"))
    ap.add_argument("--nhd", type=Path, default=Path("NHDPLUS_H_1711_HU4_GDB"))
    ap.add_argument("--proc", type=Path, default=Path("data/processed"))
    args = ap.parse_args()
    P = args.proc

    fl = gpd.read_file(P / "flowlines.gpkg", layer="flowlines")
    fl["nhdplusid"] = fl["nhdplusid"].astype("int64")
    fl = fl.reset_index(drop=True)
    edges = pd.read_csv(P / "flow_edges.csv").astype("int64")
    sites = gpd.read_file(P / "barriers_qa.gpkg", layer="sites_snapped")
    print(f"Loaded {len(fl):,} flowlines, {len(sites):,} snapped sites", flush=True)

    # ============ A. Tag habitat on flowlines from SWIFD ============
    shp = find_in(args.swifd, "**/*.shp")
    crs = pyogrio.read_info(shp)["crs"]
    x0, y0, x1, y1 = fl.total_bounds
    env = gpd.GeoSeries([shapely.box(x0 - 500, y0 - 500, x1 + 500, y1 + 500)], crs=UTM10N)
    bbox = tuple(env.to_crs(crs).total_bounds)
    print("Reading SWIFD for the study area ...", flush=True)
    sw = pyogrio.read_dataframe(shp, bbox=bbox).to_crs(UTM10N)
    sp_col = col(sw, r"^speciesrun", r"species")
    dt_col = col(sw, r"^disttype", r"dist")
    sw["species"] = sw[sp_col].astype(str).str.strip()
    sw["weight"] = sw["species"].map(species_weight)
    keep_dt = sw[dt_col].astype(str).str.lower().str.contains(DIST_KEEP, regex=True)
    sw = sw[(sw["weight"] > 0) & keep_dt & sw.geometry.notna()].reset_index(drop=True)
    print(f"SWIFD segments used (target species, kept distribution types): {len(sw):,}",
          flush=True)
    print("Matching SWIFD to flowlines ...", flush=True)

    tree = STRtree(sw.geometry.values)
    hits = []
    geoms = fl.geometry.values
    for f in SAMPLE_FRACS:
        pts = shapely.line_interpolate_point(
            shapely.line_merge(geoms), f, normalized=True)
        pi, si = tree.query(pts, predicate="dwithin", distance=MATCH_DIST_M)
        hits.append(pd.DataFrame({"fl_idx": pi, "species": sw["species"].values[si],
                                  "frac": f}))
    hits = pd.concat(hits).drop_duplicates()
    present = (hits.groupby(["fl_idx", "species"])["frac"].nunique()
               .reset_index(name="n"))
    present = present[present["n"] >= MIN_HITS]
    present["w"] = present["species"].map(species_weight)

    fl["species"] = ""
    fl["hab_weight"] = 0
    if len(present):
        by_fl = present.groupby("fl_idx").agg(
            species=("species", lambda s: "; ".join(sorted(set(s)))),
            hab_weight=("w", "max"))
        fl.loc[by_fl.index, "species"] = by_fl["species"]
        fl.loc[by_fl.index, "hab_weight"] = by_fl["hab_weight"]
    hab = fl["hab_weight"] > 0
    hab_km = fl.loc[hab, "length_m"].sum() / 1000
    print(f"Flowlines tagged as habitat: {hab.sum():,} ({hab_km:,.0f} km)", flush=True)

    # ============ B. Functional gain ============
    ids = fl["nhdplusid"].values
    length = dict(zip(ids, fl["length_m"].values))
    weight = dict(zip(ids, fl["hab_weight"].values))
    spp = dict(zip(ids, fl["species"].values))
    # Minor branch of a divergence (side channel): its upstream end is the main
    # channel, so traces must not climb out of it into the mainstem.
    div = dict(zip(ids, pd.to_numeric(fl.get("divergence", 0), errors="coerce")
                   .fillna(0).astype(int).values)) if "divergence" in fl else {}
    upstream_of = defaultdict(list)  # node -> nodes that flow into it
    for a, b in edges.itertuples(index=False, name=None):
        upstream_of[b].append(a)

    sites["snap_nhdplusid"] = sites["snap_nhdplusid"].astype("int64")
    stops = sites[sites["is_stop"].astype(bool)]
    stops_on = defaultdict(list)  # flowline -> sorted distances from upstream end
    for f, d in zip(stops["snap_nhdplusid"], stops["dist_from_upstream_end_m"]):
        stops_on[f].append(float(d))
    for f in stops_on:
        stops_on[f].sort()

    def add(acc, f, meters):
        if meters <= 0:
            return
        acc["all_m"] += meters  # every stream, habitat or not (diagnostic)
        w = weight.get(f, 0)
        if w > 0:
            acc["gain_m"] += meters
            acc["wgain_m"] += meters * w
            if spp.get(f):
                acc["spp"].update(spp[f].split("; "))

    def functional_gain(f, d):
        acc = {"gain_m": 0.0, "wgain_m": 0.0, "all_m": 0.0, "spp": set(),
               "div_cut": False}
        above = [x for x in stops_on.get(f, []) if x < d - 0.5]
        if above:  # another stop further up the same flowline
            add(acc, f, d - max(above))
            return acc
        add(acc, f, d)
        if div.get(f) == 2:
            acc["div_cut"] = True
            return acc
        seen, q = {f}, deque(upstream_of.get(f, []))
        while q:
            u = q.popleft()
            if u in seen:
                continue
            seen.add(u)
            if stops_on.get(u):  # stop on this reach: count the part below it
                add(acc, u, length[u] - max(stops_on[u]))
                continue
            add(acc, u, length[u])
            if div.get(u) == 2:  # side channel: stop where it leaves the river
                acc["div_cut"] = True
                continue
            q.extend(upstream_of.get(u, []))
        return acc

    cand = sites[sites["role"] == "candidate"].copy()
    print(f"Tracing functional gain for {len(cand):,} candidates ...", flush=True)
    res = []
    for i, (f, d) in enumerate(zip(cand["snap_nhdplusid"],
                                   cand["dist_from_upstream_end_m"]), 1):
        res.append(functional_gain(f, float(d)))
        if i % 100 == 0:
            print(f"  {i:,} / {len(cand):,}", flush=True)
    print("Scoring and writing outputs ...", flush=True)
    cand["gain_km"] = [r["gain_m"] / 1000 for r in res]
    cand["weighted_gain_km"] = [r["wgain_m"] / 1000 for r in res]
    cand["species_upstream"] = ["; ".join(sorted(r["spp"])) for r in res]
    cand["stream_km_upstream"] = [round(r["all_m"] / 1000, 3) for r in res]
    cand["side_channel_cut"] = [r["div_cut"] for r in res]
    cand["esa_upstream"] = cand["species_upstream"].str.contains(
        r"Chinook|Steelhead|Bull Trout", case=False, regex=True)

    # ============ C. Score ============
    p = pd.to_numeric(cand["pct_passable"], errors="coerce").fillna(33)
    cand["score"] = (cand["weighted_gain_km"] * (1 - p / 100)).round(3)
    cand = cand.sort_values("score", ascending=False)
    cand["rank"] = np.arange(1, len(cand) + 1)
    for c in ("gain_km", "weighted_gain_km"):
        cand[c] = cand[c].round(3)

    # Sub-basin (HUC10) names from the NHDPlus WBD
    nhd_gdb = find_in(args.nhd, "**/*.gdb")
    try:
        h10 = pyogrio.read_dataframe(nhd_gdb, layer="WBDHU10").to_crs(UTM10N)
        n10 = col(h10, r"^name$")
        h10 = h10[[n10, "geometry"]].rename(columns={n10: "subbasin"})
        cand = gpd.sjoin(cand, h10, how="left", predicate="within").drop(
            columns="index_right")
        cand = cand[~cand.index.duplicated(keep="first")]
    except Exception as e:  # noqa: BLE001
        print(f"(No HUC10 sub-basins: {e})")
        cand["subbasin"] = ""

    # ============ Outputs ============
    fl.to_file(P / "habitat_flowlines.gpkg", layer="habitat_flowlines", driver="GPKG")
    cand.to_file(P / "barriers_ranked.gpkg", layer="barriers_ranked", driver="GPKG")
    cand.drop(columns="geometry").to_csv(P / "barriers_ranked.csv", index=False)

    # ============ D. Summary ============
    L = [f"Habitat flowlines: {hab.sum():,} ({hab_km:,.0f} km); "
         f"ESA-weighted (w=2): {fl.loc[fl.hab_weight == 2, 'length_m'].sum() / 1000:,.0f} km",
         f"Candidates scored: {len(cand):,}; with zero habitat gain: "
         f"{(cand['gain_km'] == 0).sum():,}",
         f"Total functional gain, all candidates: {cand['gain_km'].sum():,.1f} km "
         f"(no double counting: traces stop at the next barrier)",
         f"Traces cut at a side-channel split: {int(cand['side_channel_cut'].sum()):,}",
         "",
         "TOP 20",
         f"{'rk':>3} {'score':>7} {'gain_km':>8} {'pct':>4} {'type':<9} {'owner':<9} "
         f"{'stream':<22} {'road':<18} species"]
    for _, r in cand.head(20).iterrows():
        L.append(f"{r['rank']:>3} {r['score']:>7.2f} {r['gain_km']:>8.2f} "
                 f"{str(r.get('pct_passable_label', '')):>4} "
                 f"{str(r.get('feature_type', ''))[:9]:<9} "
                 f"{str(r.get('owner_type', ''))[:9]:<9} "
                 f"{str(r.get('StreamName', ''))[:22]:<22} "
                 f"{str(r.get('RoadName', ''))[:18]:<18} {r['species_upstream']}")

    L += ["", "BLOCKED HABITAT BY OWNER (sum of functional gain, km)"]
    own = cand.groupby("owner_type").agg(barriers=("rank", "size"),
                                         gain_km=("gain_km", "sum"),
                                         score=("score", "sum"))
    own = own.sort_values("gain_km", ascending=False)
    for k, r in own.iterrows():
        L.append(f"  {k:<20} {int(r['barriers']):>5,} barriers  {r['gain_km']:>8.1f} km  "
                 f"score {r['score']:>8.1f}")

    L += ["", "BLOCKED HABITAT BY SUB-BASIN (HUC10)"]
    sb = cand.groupby("subbasin", dropna=False).agg(
        barriers=("rank", "size"), gain_km=("gain_km", "sum")).sort_values(
        "gain_km", ascending=False)
    for k, r in sb.iterrows():
        L.append(f"  {str(k):<35} {int(r['barriers']):>5,} barriers  {r['gain_km']:>8.1f} km")

    if "LinealGainMeasurement" in cand:
        w = pd.to_numeric(cand["LinealGainMeasurement"], errors="coerce")
        ok = w.notna() & (w > 0) & (cand["gain_km"] > 0)
        L += ["", "COMPARISON WITH WDFW 'Potential Habitat Gain' (LinealGainMeasurement)"]
        if ok.sum() >= 5:
            b = w[ok]
            rho = np.corrcoef(cand.loc[ok, "gain_km"].rank(), b.rank())[0, 1]
            ok2 = w.notna() & (w > 0) & (cand["stream_km_upstream"] > 0)
            rho2 = np.corrcoef(cand.loc[ok2, "stream_km_upstream"].rank(),
                               w[ok2].rank())[0, 1]
            ok3 = w.notna() & (w > 0)
            zero = (cand.loc[ok3, "gain_km"] == 0).sum()
            ratio = (b / (cand.loc[ok, "gain_km"] * 1000)).median()
            ratio2 = (w[ok2] / (cand.loc[ok2, "stream_km_upstream"] * 1000)).median()
            L.append(f"  barriers with both values: {ok.sum():,}")
            L.append(f"  Spearman, SWIFD habitat gain vs WDFW:       {rho:.2f}")
            L.append(f"  Spearman, all-stream length upstream vs WDFW: {rho2:.2f} "
                     f"(n={ok2.sum():,})")
            L.append(f"  median WDFW / our habitat gain (m): {ratio:.2f};  "
                     f"WDFW / all-stream length (m): {ratio2:.2f}")
            L.append(f"  WDFW says >0 but our habitat gain is 0: {zero:,} barriers")
        else:
            L.append(f"  too few barriers with both values ({ok.sum()})")

    text = "\n".join(L)
    (P / "gain_summary.txt").write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"\nWrote habitat_flowlines.gpkg, barriers_ranked.gpkg/.csv, "
          f"gain_summary.txt to {P.resolve()}")


if __name__ == "__main__":
    main()
