# Nooksack Fish Passage Barrier Prioritization

**Which fish passage barriers in the Nooksack basin would open up the most salmon habitat if they were fixed, and who owns them?**

This project ranks 577 human-made fish passage barriers in the Nooksack River basin (HUC8 17110004, Whatcom County, WA). The measure is the salmon, steelhead and bull trout habitat each one blocks. It combines WDFW's fish passage inventory, the WDFW/NWIFC statewide fish distribution and USGS NHDPlus High Resolution hydrography. The pipeline is a set of plain Python scripts, and every number below can be reproduced from the public downloads.

> **Status:** analysis complete (Nov 2026). AGOL web map and StoryMap in progress.

## Key findings

- **577 barriers block about 432 km of mapped anadromous and bull trout habitat**, roughly a third of the 1,260 km mapped in the basin.
- **Private owners hold almost half of it:** 205 km behind 271 private barriers. County is next (98 km, 153 barriers), then city (62 km, 89) and state (56 km, 56).
- **Most of the blocked habitat is in the lowlands.** The Nooksack River–Frontal Bellingham Bay sub-basin alone accounts for 291 km. The Whatcom Creek–Frontal Bellingham Bay sub-basin has 189 candidate barriers.
- **The top of the ranking is lowland tributaries:** Cougar Creek (120th St), Tenmile Creek (E Hemmi Rd), an unnamed stream at SR 9, Deer Creek (Northwest Dr), Bender Ditch, Schneider Creek and Pepin Creek (Main St).

Full outputs: [`results/gain_summary.txt`](results/gain_summary.txt), [`results/qa_summary.txt`](results/qa_summary.txt).

## Data

| Dataset | Source | Used for |
|---|---|---|
| Fish Passage & Diversion Screening Inventory (FPDSI), `WDFW_FishPassageSite` | [WDFW open data](https://data-wdfw.opendata.arcgis.com/datasets/fish-passage-barriers-inventory-zipped-file-geodatabase) | Barrier locations, status, percent passable, feature type, owner |
| Statewide Washington Integrated Fish Distribution (SWIFD) | [WA Geoportal](https://geo.wa.gov/datasets/wdfw::statewide-washington-integrated-fish-distribution/explore) (WDFW / NWIFC) | Which streams carry which species |
| NHDPlus High Resolution, HU4 1711 (vector GDB) | [USGS staged products](https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHDPlusHR/VPU/Current/GDB/NHDPLUS_H_1711_HU4_GDB.zip) | Stream network, flow routing, HUC8/HUC10 boundaries |

**FPDSI is for planning use only.** WDFW states the inventory is not comprehensive and makes no guarantee of accuracy or completeness. Rankings here are a screening tool, not a substitute for field assessment. Data credit: Washington Department of Fish and Wildlife, Northwest Indian Fisheries Commission, U.S. Geological Survey.

## Method

| Step | Script | What it does |
|---|---|---|
| 1 | [`01_build_network.py`](scripts/01_build_network.py) | Clips NHDPlus HR flowlines to the HUC8, joins value-added attributes, builds a directed stream graph from the `NHDPlusFlow` table |
| 0 | [`02_coverage_check.py`](scripts/02_coverage_check.py) | Go/no-go check: what's in FPDSI and SWIFD for the study area |
| 2–3 | [`03_qa_and_snap.py`](scripts/03_qa_and_snap.py) | Decodes FPDSI codes, raises QA flags, assigns roles, snaps sites to flowlines |
| 4–6 | [`04_habitat_gain.py`](scripts/04_habitat_gain.py) | Tags habitat from SWIFD, traces functional gain, scores, summarizes |

### Network
NHDPlus HR flowlines with the `NHDPlusFlow` from/to table become a directed graph, with edges pointing downstream. As a check, the traced length upstream of the basin outlet (6,474 km) matches USGS's own arbolate sum (6,483 km) within 0.1%.

### QA and roles
Every FPDSI site in the study area (2,276) gets flags for: duplicate location, missing passability, more than 50 m from a flowline, already corrected, unknown barrier status, missing owner, only a large river nearby, and stream-name mismatch. Then each site gets a role:

- **Candidate** (577): human-made, confirmed barrier, not corrected, snapped, fish use not "No". These get ranked.
- **Stop** (357): blocks upstream traces but isn't ranked. These are natural barriers and confirmed barriers on non-fish streams.
- **Excluded** (1,342), each with a reason: not a barrier (523), status unknown (389), no eligible flowline within 50 m (201), corrected (192), and others.

### Snapping
Sites snap to a flowline within 50 m, in this order of preference:
1. The nearest flowline whose GNIS name matches FPDSI's stream name (480 sites).
2. The nearest *eligible* flowline. Culverts can't snap to large rivers (NHD ArtificialPath centerlines, or stream order ≥ 6), because rivers get bridges, not culverts. Dams and natural barriers can snap anywhere.

### Habitat
A flowline carries a species if at least 2 of 3 points along it (at 25/50/75% of its length) lie within 25 m of that species' SWIFD line. Each reach takes the highest weight among its species:

| Weight | Species / runs |
|---|---|
| 2 (ESA-listed) | Spring and fall Chinook, winter and summer steelhead, Dolly Varden/bull trout |
| 1 | Coho, chum, pink, sockeye |
| excluded | Resident trout (coastal cutthroat, rainbow, kokanee) |

The distribution types counted are Documented, Presumed, Gradient Accessible and Potential. Counting only documented habitat would undercount exactly what this project measures: habitat above barriers, which often goes undocumented because fish can't reach it.

### Functional gain
For each candidate, the trace walks upstream and sums habitat until it reaches the next stop point (another barrier, natural or human-made). When a barrier sits partway along a flowline, the snap position splits the segment. Traces don't climb out of an NHDPlus minor divergence (a side channel) into the main river. Because each trace stops at the next barrier, gains don't double-count, and they sum cleanly by owner and sub-basin.

### Score

```
score = weighted_gain_km × (1 − percent_passable / 100)

weighted_gain_km = Σ (reach habitat length × reach species weight)
```

FPDSI rates passability in buckets (0 / 33 / 67 / 100%). The 21 confirmed barriers with no rating are scored at 33%, the most common rating among assessed barriers, and flagged `pct_estimated`.

## How the results were checked

Sanity-checking the top of the ranking turned up two bugs in earlier versions, both now fixed:

1. **Culverts snapping to the river.** Version 1 snapped each site to the nearest flowline. A culvert on Van Hook's Creek at North Fork Rd sat closer to the North Fork Nooksack than to its own creek. Its trace ran up the whole North Fork, and it ranked #1 with 83 km of habitat, including sockeye. That's implausible for a small-creek culvert. *Fix:* name-match snapping, and culverts excluded from large rivers.
2. **Side channels tracing into the mainstem.** Version 2 still ranked a culvert at Nielson Rd #1 with 39 km including sockeye. It sat on a side channel, and walking upstream from a side channel leads back into the main river. *Fix:* traces stop at NHDPlus minor divergences (`Divergence = 2`). 61 traces are now cut there.

**Comparison with WDFW's own estimate.** FPDSI includes WDFW's `LinealGainMeasurement` ("Potential Habitat Gain"). Its Spearman rank correlation with this project's habitat gain is **0.18** (n = 233). Against plain upstream stream length, with no habitat filter, it's 0.13. So SWIFD habitat tagging isn't what drives the disagreement; the two measure different things. WDFW's value is a field-assessed potential habitat length under its own prioritization protocol. This project's value is network-derived, stops at the next barrier, and counts only mapped anadromous and bull trout habitat. Treat the two as complementary, not as one validating the other.

## Limitations

- **Inventory gaps.** 389 sites in the study area have unknown or blank barrier status, and private land is under-surveyed.
- **Dataset mismatch.** About 19% of FPDSI sites have no eligible NHDPlus HR flowline within 50 m. Most likely they're on ditches and small tributaries NHDPlus HR doesn't map, or have location errors. 201 of them would otherwise have been candidates or stops.
- **Coarse passability.** FPDSI uses 0/33/67/100% buckets and doesn't distinguish species or life stage.
- **No cost or habitat quality.** Upstream length is the only habitat measure, and repair cost isn't modeled.
- **Species lumping.** SWIFD combines Dolly Varden and bull trout into one category.
- **Not cumulative.** The score doesn't account for barriers *downstream*. Fixing a barrier above an impassable one yields little until the lower one is fixed.

## Running it

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

Put the three downloads (`NHDPLUS_H_1711_HU4_GDB.zip`, `WdfwFishPassage.zip`, `SWIFD.zip`) in one working folder and run from there. Outputs go to `data/processed/`.

```bash
python scripts/01_build_network.py NHDPLUS_H_1711_HU4_GDB.zip
python scripts/02_coverage_check.py
python scripts/03_qa_and_snap.py
python scripts/04_habitat_gain.py
```

Each script takes `--help` for paths and options, such as `--huc8` to change the study area.

| Output | Contents |
|---|---|
| `flowlines.gpkg`, `flow_edges.csv` | Study-area stream network |
| `barriers_qa.gpkg`, `qa_table.csv` | Every FPDSI site with decoded fields, QA flags, role and snap info |
| `habitat_flowlines.gpkg` | Flowlines with species and weight |
| `barriers_ranked.gpkg`, `barriers_ranked.csv` | Ranked candidates with gain, score, species, owner and sub-basin |
| `*_summary.txt`, `coverage_report.txt` | Run summaries (copies in [`results/`](results/)) |

## Tools

Python (geopandas, pyogrio, shapely, networkx, pandas), ArcGIS Online, ArcGIS API for Python.
