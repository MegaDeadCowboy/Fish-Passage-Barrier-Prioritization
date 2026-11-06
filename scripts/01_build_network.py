"""
01_build_network.py
Nooksack Fish Passage Barrier Prioritization, step 3a: build the stream network.

Reads the NHDPlus HR HU4 1711 file geodatabase, keeps flowlines in the study
area HUC8(s), joins the value-added attributes (VAA), and builds a directed
stream graph from the NHDPlusFlow table (edges point downstream).

Outputs (in --out, default ./data/processed):
  flowlines.gpkg     layer "flowlines": study-area flowlines + VAA, EPSG:26910 (UTM 10N, meters)
  flow_edges.csv     from_id,to_id  (downstream-pointing edges inside the study area)
  network_summary.txt  sanity-check numbers for the README

Usage:
  python 01_build_network.py path/to/NHDPLUS_H_1711_HU4_..._GDB.zip
  python 01_build_network.py path/to/NHDPLUS_H_1711_HU4_GDB.gdb --huc8 17110004
  python 01_build_network.py <gdb> --huc8 17110004 17110002   # several HUC8s

Deps: geopandas, pyogrio, networkx, pandas
"""

import argparse
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import networkx as nx
import pandas as pd
import pyogrio

UTM10N = 26910
COASTLINE_FTYPE = 566  # NHD coastline, not a stream


def find_gdb(path: Path) -> Path:
    """Accept a .zip or a .gdb; unzip next to the zip if needed."""
    if path.suffix.lower() == ".gdb" and path.is_dir():
        return path
    if path.suffix.lower() == ".zip":
        dest = path.with_suffix("")
        if not any(dest.glob("**/*.gdb")):
            print(f"Unzipping {path.name} ...")
            with zipfile.ZipFile(path) as z:
                z.extractall(dest)
        gdbs = list(dest.glob("**/*.gdb"))
        if not gdbs:
            sys.exit(f"No .gdb found inside {path}")
        return gdbs[0]
    sys.exit(f"Expected a .zip or .gdb, got {path}")


def lower_cols(df):
    """NHDPlus HR field-name casing varies between releases; normalize it."""
    return df.rename(columns={c: c.lower() for c in df.columns if c != "geometry"})


def to_int_id(s: pd.Series) -> pd.Series:
    # NHDPlusIDs are stored as doubles in the GDB; make them exact int64 keys
    return pd.to_numeric(s, errors="coerce").round().astype("Int64")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path, help="NHDPlus HR 1711 .zip or .gdb")
    ap.add_argument("--huc8", nargs="+", default=["17110004"],
                    help="HUC8 code(s) to keep (default: 17110004, Nooksack)")
    ap.add_argument("--out", type=Path, default=Path("data/processed"))
    args = ap.parse_args()

    gdb = find_gdb(args.src)
    args.out.mkdir(parents=True, exist_ok=True)
    print(f"GDB: {gdb}")

    layers = {name for name, _ in pyogrio.list_layers(gdb)}
    for need in ("NHDFlowline", "NHDPlusFlowlineVAA", "NHDPlusFlow"):
        if need not in layers:
            sys.exit(f"Missing layer {need}. Layers present: {sorted(layers)}")

    # ---- Flowlines, filtered by ReachCode prefix (first 8 digits = HUC8) ----
    where = " OR ".join(f"ReachCode LIKE '{h}%'" for h in args.huc8)
    fl = lower_cols(pyogrio.read_dataframe(gdb, layer="NHDFlowline", where=where))
    fl["nhdplusid"] = to_int_id(fl["nhdplusid"])
    fl = fl[fl["ftype"] != COASTLINE_FTYPE]
    print(f"Flowlines in HUC8 {args.huc8}: {len(fl):,}")

    # ---- VAA join ----
    vaa = lower_cols(pyogrio.read_dataframe(gdb, layer="NHDPlusFlowlineVAA",
                                            read_geometry=False))
    vaa["nhdplusid"] = to_int_id(vaa["nhdplusid"])
    keep = [c for c in ("nhdplusid", "streamorde", "hydroseq", "dnhydroseq",
                        "uphydroseq", "terminalpa", "arbolatesu", "startflag",
                        "divergence", "pathlength") if c in vaa.columns]
    fl = fl.merge(vaa[keep], on="nhdplusid", how="left")
    no_vaa = fl["hydroseq"].isna().sum()
    fl = fl[fl["hydroseq"].notna()]  # no VAA = not part of the routed network

    # ---- Geometry: drop Z/M, project to meters, recompute length ----
    fl = fl.set_geometry(gpd.GeoSeries(fl.geometry).force_2d()).to_crs(UTM10N)
    fl["length_m"] = fl.geometry.length

    # ---- Flow table -> edges inside the study area ----
    flow = lower_cols(pyogrio.read_dataframe(gdb, layer="NHDPlusFlow",
                                             read_geometry=False))
    flow["from_id"] = to_int_id(flow["fromnhdpid"])
    flow["to_id"] = to_int_id(flow["tonhdpid"])
    ids = set(fl["nhdplusid"].dropna().astype("int64"))
    edges = flow[flow["from_id"].isin(ids) & flow["to_id"].isin(ids)]
    edges = edges[["from_id", "to_id"]].drop_duplicates().astype("int64")

    # ---- Graph + sanity checks ----
    G = nx.DiGraph()
    G.add_nodes_from(ids)
    G.add_edges_from(edges.itertuples(index=False, name=None))

    comps = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
    outlets = [n for n in G.nodes if G.out_degree(n) == 0]
    is_dag = nx.is_directed_acyclic_graph(G)
    lengths = fl.set_index(fl["nhdplusid"].astype("int64"))["length_m"]

    # Main stem outlet = flowline with the largest arbolate sum
    outlet_row = fl.loc[fl["arbolatesu"].idxmax()]
    outlet = int(outlet_row["nhdplusid"])
    upstream = nx.ancestors(G, outlet) | {outlet}
    up_km = lengths.reindex(list(upstream)).sum() / 1000
    total_km = fl["length_m"].sum() / 1000

    summary = [
        f"Source GDB: {gdb.name}",
        f"HUC8(s): {', '.join(args.huc8)}",
        f"Flowlines kept: {len(fl):,}  (dropped {no_vaa:,} with no VAA)",
        f"Total stream length: {total_km:,.1f} km",
        f"Edges: {G.number_of_edges():,}",
        f"Weakly connected components: {len(comps):,} "
        f"(largest = {len(comps[0]):,} flowlines, "
        f"{len(comps[0]) / G.number_of_nodes():.1%})",
        f"Outlets (no downstream edge): {len(outlets):,}",
        f"Graph is acyclic: {is_dag}",
        f"Main outlet: NHDPlusID {outlet} "
        f"({outlet_row.get('gnis_name') or 'unnamed'}, "
        f"arbolate sum {outlet_row['arbolatesu']:,.1f} km)",
        f"Length upstream of main outlet: {up_km:,.1f} km "
        f"({up_km / total_km:.1%} of total)",
    ]
    if not is_dag:
        summary.append("NOTE: cycles present (braids/diversions). "
                       "Upstream traces still work via nx.ancestors.")

    # ---- Write outputs ----
    fl.to_file(args.out / "flowlines.gpkg", layer="flowlines", driver="GPKG")
    edges.to_csv(args.out / "flow_edges.csv", index=False)
    (args.out / "network_summary.txt").write_text("\n".join(summary) + "\n")

    print("\n".join(summary))
    print(f"\nWrote outputs to {args.out.resolve()}")


if __name__ == "__main__":
    main()
