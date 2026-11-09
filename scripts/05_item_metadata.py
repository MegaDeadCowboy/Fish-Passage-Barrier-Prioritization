"""
05_item_metadata.py
Nooksack Fish Passage Barrier Prioritization, step 7: ArcGIS Online item metadata.

Sets the summary, description (lineage, QA, scoring), tags, credits and
terms of use on:
  - hosted feature layer  barriers_ranked
  - hosted feature layer  habitat_flowlines
  - their source GeoPackage items (short version)
  - web map  "Nooksack Fish Passage Barriers"

Safe by default: without --apply it only prints what it would change.
Before applying, it saves the current metadata of every item to
data/processed/item_metadata_backup.json so nothing is lost.

Usage (Command Prompt, from the folder with the scripts):
  %USERPROFILE%\\fishenv\\Scripts\\python 05_item_metadata.py            (dry run)
  %USERPROFILE%\\fishenv\\Scripts\\python 05_item_metadata.py --apply    (write)
You'll be prompted for the ArcGIS Online password.
"""
import argparse
import json
from datetime import date
from getpass import getpass
from pathlib import Path

from arcgis.gis import GIS

PORTAL = "https://crasmussen.maps.arcgis.com"
USERNAME = "carver.rasmussen.gis"
WEBMAP_ID = "09184f91f5fc4b94913f286497cc1d49"
REPO_URL = "https://github.com/MegaDeadCowboy/Fish-Passage-Barrier-Prioritization"
BACKUP = Path("data/processed/item_metadata_backup.json")

# ---------------------------------------------------------------- shared text
CREDITS = (
    "Barrier data: Washington Department of Fish and Wildlife (WDFW), Fish Passage "
    "and Diversion Screening Inventory (FPDSI). Fish distribution: WDFW and the "
    "Northwest Indian Fisheries Commission (NWIFC), Statewide Washington Integrated "
    "Fish Distribution (SWIFD). Hydrography: U.S. Geological Survey (USGS), NHDPlus "
    "High Resolution and Watershed Boundary Dataset. Analysis: Carver Rasmussen."
)

LICENSE = (
    "<p><b>For planning use only.</b> Barrier locations, status and passability "
    "come from WDFW's Fish Passage and Diversion Screening Inventory, which WDFW "
    "provides for planning purposes only. Field conditions may have changed since a "
    "site was assessed, and the inventory is incomplete, especially on private land. "
    "Do not use these data for regulatory, engineering or legal decisions. Confirm "
    "any individual site with WDFW and the barrier owner.</p>"
    "<p>Rankings are a screening-level estimate of upstream habitat gain, not a "
    "funding or design recommendation. Source data credit: WDFW, NWIFC, USGS.</p>"
)

TAGS_COMMON = [
    "fish passage", "barriers", "culverts", "salmon", "steelhead", "bull trout",
    "habitat connectivity", "restoration prioritization", "Nooksack River",
    "Whatcom County", "Washington", "WDFW", "FPDSI", "SWIFD", "NHDPlus HR",
]

METHOD_HTML = f"""
<h3>Lineage</h3>
<ul>
<li><b>Stream network:</b> USGS NHDPlus High Resolution, HU4 1711, clipped to the
Nooksack HUC8 (17110004): 20,925 flowlines, 7,307 km. A directed network was
built from the NHDPlusFlow table in Python (networkx). Upstream length at the
main outlet matches the USGS arbolate sum within 0.1%.</li>
<li><b>Barriers:</b> WDFW FPDSI, 2,276 sites in the study area.</li>
<li><b>Fish distribution:</b> WDFW/NWIFC SWIFD, 5,290 segments in the study area.
Counted species: Chinook, coho, chum, pink, sockeye, steelhead and bull
trout/Dolly Varden. Counted distribution types: Documented, Presumed, Gradient
Accessible and Potential. Resident trout are excluded.</li>
</ul>
<h3>QA/QC</h3>
<p>Every FPDSI site was flagged for duplicates, missing passability, distance from
a mapped stream, corrected status, unknown status, missing owner and stream-name
mismatch. Of 2,276 sites, 577 are ranked candidates, 357 are stop points only
(natural barriers and barriers on non-fish streams) and 1,342 are excluded (not a
barrier, unknown status, already corrected, or more than 50 m from a mapped
stream). Sites were snapped to the network within 50 m, preferring a stream with
a matching name. Road crossings were not allowed to snap to large rivers. The 20
top-ranked sites were checked against aerial imagery (18 confirmed, 2 could not
be confirmed from imagery, none wrong).</p>
<h3>Scoring</h3>
<p>Habitat gain is the length of mapped salmon, steelhead and bull trout habitat
upstream of a barrier, stopping at the next barrier or natural barrier. Reaches
with an ESA-listed species (Chinook, steelhead, bull trout) count double.</p>
<p><code>score = weighted gain (km) &times; (1 &minus; percent passable / 100)</code></p>
<p>21 confirmed barriers with no passability rating are scored as 33% passable and
labeled "Not assessed (scored as 33%)".</p>
<h3>Code and full documentation</h3>
<p><a href="{REPO_URL}">{REPO_URL}</a></p>
<p>Metadata updated {date.today():%B %d, %Y}.</p>
"""

# ---------------------------------------------------------------- per item
ITEMS = {
    "barriers_ranked": {
        "type": "Feature Service",
        "snippet": (
            "577 fish passage barriers in the Nooksack River basin, WA, ranked by how "
            "much salmon, steelhead and bull trout habitat fixing each would open up."
        ),
        "intro": (
            "<p>Fish passage barriers (mostly road culverts) in the Nooksack River "
            "basin, ranked by the salmon habitat each would open up if fixed. Each "
            "point has a priority score and rank, habitat opened upstream (km), the "
            "species using that habitat, barrier type, owner type, passability, "
            "sub-basin (HUC10) and a link to WDFW's site report.</p>"
            "<p>Points sit at their snapped position on the NHDPlus HR network, which "
            "may be up to 50 m from the original FPDSI location.</p>"
        ),
        "tags": ["priority ranking", "barrier ranking"],
    },
    "habitat_flowlines": {
        "type": "Feature Service",
        "snippet": (
            "NHDPlus HR streams in the Nooksack River basin, WA, tagged with the salmon, "
            "steelhead and bull trout species mapped in SWIFD."
        ),
        "intro": (
            "<p>Stream reaches in the Nooksack River basin used to measure habitat "
            "gain. Each reach is tagged with the target species SWIFD maps on it and "
            "a weight: 2 for ESA-listed species (Chinook, steelhead, bull trout), 1 "
            "for other salmon, 0 for no target species. A reach is tagged when at "
            "least 2 of 3 points along it lie within 25 m of the SWIFD line.</p>"
        ),
        "tags": ["fish distribution", "stream network"],
    },
    "webmap": {
        "type": "Web Map",
        "snippet": (
            "Which fish passage barriers in the Nooksack basin would open up the most "
            "salmon habitat if fixed, and who owns them."
        ),
        "intro": (
            "<p>Map of fish passage barriers in the Nooksack River basin, sized by "
            "priority score, over the salmon and steelhead habitat they block. Click "
            "a barrier for its rank, habitat opened, species, owner and WDFW site "
            "report.</p>"
        ),
        "tags": ["web map"],
    },
}

GPKG_SNIPPET = "Source GeoPackage for the hosted layer {name}. See the hosted layer for full metadata."


def props_for(key, cfg):
    return {
        "snippet": cfg["snippet"],
        "description": cfg["intro"] + METHOD_HTML,
        "tags": ",".join(TAGS_COMMON + cfg["tags"]),
        "accessInformation": CREDITS,
        "licenseInfo": LICENSE,
    }


def find_item(gis, title, item_type):
    hits = gis.content.search(
        query=f'title:"{title}" AND owner:{USERNAME}', max_items=50
    )
    hits = [h for h in hits if h.title == title and h.type == item_type]
    if len(hits) != 1:
        found = [(h.title, h.type, h.id) for h in hits]
        raise SystemExit(f"Expected one {item_type} titled '{title}', found {found}")
    return hits[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="write the changes")
    args = ap.parse_args()

    gis = GIS(PORTAL, USERNAME, getpass(f"Password for {USERNAME}: "))
    print(f"Signed in as {gis.users.me.username}\n")

    targets = []  # (item, properties)
    for key, cfg in ITEMS.items():
        if key == "webmap":
            item = gis.content.get(WEBMAP_ID)
            if item is None:
                raise SystemExit(f"Web map {WEBMAP_ID} not found")
        else:
            item = find_item(gis, key, cfg["type"])
        targets.append((item, props_for(key, cfg)))

        if key != "webmap":
            try:
                gpkg = find_item(gis, key, "GeoPackage")
            except SystemExit as e:
                print(f"  (skipping GeoPackage for {key}: {e})")
            else:
                targets.append((gpkg, {
                    "snippet": GPKG_SNIPPET.format(name=key),
                    "tags": ",".join(TAGS_COMMON + ["source data"]),
                    "accessInformation": CREDITS,
                    "licenseInfo": LICENSE,
                }))

    for item, props in targets:
        print(f"{item.type:16} {item.title}  ({item.id})")
        print(f"  summary: {props['snippet']}")
        print(f"  tags:    {props['tags']}")
        if "description" in props:
            print(f"  description: {len(props['description'])} characters of HTML")
        print()

    if not args.apply:
        print("Dry run only. Rerun with --apply to write these changes.")
        return

    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    backup = {
        item.id: {
            "title": item.title,
            "type": item.type,
            "snippet": item.snippet,
            "description": item.description,
            "tags": item.tags,
            "accessInformation": item.accessInformation,
            "licenseInfo": item.licenseInfo,
        }
        for item, _ in targets
    }
    BACKUP.write_text(json.dumps(backup, indent=2), encoding="utf-8")
    print(f"Backed up current metadata to {BACKUP}")

    for item, props in targets:
        ok = item.update(item_properties=props)
        print(f"{'updated' if ok else 'FAILED '}  {item.title} ({item.type})")


if __name__ == "__main__":
    main()
