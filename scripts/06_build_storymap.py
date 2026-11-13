"""
06_build_storymap.py
Nooksack Fish Passage Barrier Prioritization: build the StoryMap draft in ArcGIS Online.

Creates a new StoryMap item (saved as a DRAFT, not published) with:
  cover -> why it matters -> web map -> which fixes matter most (sidecar,
  one slide per top-3 site, map zoomed to each) -> who owns the problem
  (table) -> caveats -> credits

It also gives the hosted layers and the web map's layers readable titles,
so the public doesn't see "barriers_ranked" and "habitat_flowlines".

After it runs, open the story in the StoryMaps builder, add a cover photo,
look it over, and click Publish there. The builder runs its issue checker and
offers to share the web map and layers along with the story.

Usage (Command Prompt, from the folder with the scripts):
  %USERPROFILE%\\fishenv\\Scripts\\python 06_build_storymap.py
"""
from getpass import getpass

import pandas as pd
from arcgis.gis import GIS
from arcgis.apps.storymap import (
    Map,
    Sidecar,
    StoryMap,
    Table,
    Text,
    TextStyles,
)
from arcgis.apps.storymap.story_content import Cover, SidecarSlide

PORTAL = "https://crasmussen.maps.arcgis.com"
USERNAME = "carver.rasmussen.gis"
WEBMAP_ID = "09184f91f5fc4b94913f286497cc1d49"
BARRIERS_ID = "ed4d302655044ce381d2253fd2b7f090"
HABITAT_ID = "a3ed6a6f14e04ff2bd01f2cc6781709b"
REPO_URL = "https://github.com/MegaDeadCowboy/Fish-Passage-Barrier-Prioritization"

STORY_TITLE = "Small Pipes, Big Rivers"
SUBTITLE = (
    "Which fish passage barriers in the Nooksack basin would open up the most "
    "salmon habitat if fixed, and who owns them?"
)
BYLINE = "Carver Rasmussen"
TAGS = ["fish passage", "salmon", "Nooksack River", "culverts", "Whatcom County", "StoryMap"]

# Readable titles for the public
LAYER_TITLES = {
    BARRIERS_ID: "Nooksack Fish Passage Barriers (Ranked)",
    HABITAT_ID: "Nooksack Salmon Streams",
}
WEBMAP_LAYER_TITLES = {  # operational layer title in the web map -> legend title
    "barriers_ranked": "Fish passage barriers (bigger = more habitat opened)",
    "habitat_flowlines": "Salmon, steelhead and bull trout streams",
}

H = lambda s: Text(s, TextStyles.HEADING)  # noqa: E731
P = lambda s: Text(s)  # noqa: E731

WHY = [
    "A salmon creek can be in great shape and still be useless to salmon if a pipe "
    "under a road blocks the way in. A culvert that's too small, too steep or perched "
    "above the water stops fish from reaching everything upstream.",
    "In the Nooksack, that matters. Spring Chinook, steelhead and bull trout here are "
    "all listed as threatened. Barriers can be fixed with a bridge or a bigger pipe, "
    "but there are hundreds of them. So which ones first?",
]
WHERE = [
    "WDFW tracks 2,276 stream crossings, dams and other structures in the Nooksack "
    "basin. Take out the ones that pass fish, the ones already fixed, the natural "
    "waterfalls and the ones nobody has rated, and 577 human-made barriers are left "
    "on salmon streams.",
    "The basin has about 1,260 km (780 mi) of mapped salmon habitat. About 430 km "
    "(270 mi) of it, roughly a third, sits above one of those barriers. Most of them "
    "are in the lowlands, where farms, towns and roads crowd the small creeks.",
]
MAP_CAPTION = (
    "Blue lines are salmon streams. Bigger orange dots open up more habitat. "
    "Click one for details."
)
FIXES = [
    "Each barrier gets a score: how much salmon habitat is upstream (up to the next "
    "barrier), counted double for Chinook, steelhead and bull trout, and scaled by "
    "how badly it blocks fish.",
    "The results are lopsided. The top 20 barriers block 37% of all the habitat, "
    "about 160 km. Meanwhile about a third of the 577 open up nothing, many of them "
    "on Lake Whatcom creeks above Whatcom Falls, where salmon can't go anyway.",
]
SLIDES = [  # (rank, heading, text)
    (1, "#1: Wiser Lake Creek (private)",
     "Not a road culvert at all. It's a flap floodgate where the creek drains toward "
     "the Nooksack. It keeps floodwater out, and fish too. Fixing it would reopen "
     "13.5 km (8.4 mi) of habitat for coho, chum, steelhead and bull trout."),
    (2, "#2: Tenmile Creek, off E Hemmi Road (private)",
     "A culvert under an access road with 15.6 km (9.7 mi) of habitat above it, the "
     "most in the top 10. Some fish get through today, which is why it's second."),
    (3, "#3: Unnamed creek at SR 9 (state)",
     "Fully blocked, with 11 km (6.8 mi) of habitat above it, including spring "
     "Chinook streams."),
]
AFTER_SLIDES = (
    "Further down the top 20, a lot of these are a footpath, a driveway or a farm "
    "lane. Small crossings, lots of habitat behind them."
)
OWNERS_TABLE = [
    ["Owner", "Barriers", "Habitat blocked"],
    ["Private", "271", "205 km (127 mi)"],
    ["County", "153", "98 km (61 mi)"],
    ["City", "89", "62 km (39 mi)"],
    ["State", "56", "56 km (35 mi)"],
    ["Tribal", "4", "9 km (6 mi)"],
]
OWNERS = (
    "Private landowners own nearly half the barriers (271) and about half the "
    "blocked habitat (205 km). That matters, because every fix starts with an "
    "owner. Cities and counties can work a culvert into a road budget. A landowner "
    "often needs a grant or a local salmon group to make it happen."
)
CAVEATS = [
    "WDFW's barrier data is for planning use only. The inventory has gaps: about 400 "
    "sites have no known status, and about 1 in 5 don't line up with the federal "
    "stream map. Habitat length isn't habitat quality, and repair cost isn't counted.",
    "The top 20 were checked against aerial imagery and WDFW's site reports. 18 were "
    "confirmed, 2 couldn't be confirmed from the air, and none were in the wrong "
    "place. WDFW ranks barriers its own way, from field measurements, and gets a "
    "different list. It's a different question, so it gets a different answer.",
    f'Methods, code and data dictionary: <a href="{REPO_URL}" rel="noopener noreferrer" '
    f'target="_blank">GitHub repository</a>.',
]
CREDITS = [
    ("Barrier locations, status, passability and ownership",
     "Washington Department of Fish and Wildlife, Fish Passage and Diversion "
     "Screening Inventory. For planning use only."),
    ("Salmon, steelhead and bull trout distribution",
     "WDFW and the Northwest Indian Fisheries Commission, SWIFD"),
    ("Streams and watersheds",
     "U.S. Geological Survey, NHDPlus High Resolution and Watershed Boundary Dataset"),
    ("Analysis, maps and text", "Carver Rasmussen"),
]

ZOOM_HALF_WIDTH_M = 1500  # slide maps show about 3 km across


def table_block(rows):
    cells = {str(i): {str(j): {"value": v} for j, v in enumerate(r)} for i, r in enumerate(rows)}
    return Table(df=pd.DataFrame.from_dict(cells, orient="index"))


def site_extents(gis):
    """Web Mercator extents around the top-ranked barriers, keyed by rank."""
    layer = gis.content.get(BARRIERS_ID).layers[0]
    ranks = ",".join(str(r) for r, _, _ in SLIDES)
    fs = layer.query(where=f"rank IN ({ranks})", out_fields="rank",
                     out_sr=3857, return_geometry=True)
    out = {}
    for f in fs.features:
        x, y = f.geometry["x"], f.geometry["y"]
        out[int(f.attributes["rank"])] = {
            "spatialReference": {"wkid": 102100, "latestWkid": 3857},
            "xmin": x - ZOOM_HALF_WIDTH_M, "ymin": y - ZOOM_HALF_WIDTH_M,
            "xmax": x + ZOOM_HALF_WIDTH_M, "ymax": y + ZOOM_HALF_WIDTH_M,
        }
    return out


def retitle(gis, webmap):
    for item_id, title in LAYER_TITLES.items():
        item = gis.content.get(item_id)
        if item.title != title:
            item.update(item_properties={"title": title})
            print(f"  layer item retitled: {title}")
    data = webmap.get_data()
    changed = False
    for lyr in data.get("operationalLayers", []):
        new = WEBMAP_LAYER_TITLES.get(lyr.get("title"))
        if new:
            lyr["title"] = new
            changed = True
    if changed:
        webmap.update(data=data)
        print("  web map layer titles updated")


def main():
    gis = GIS(PORTAL, USERNAME, getpass(f"Password for {USERNAME}: "))
    print(f"Signed in as {gis.users.me.username}")
    webmap = gis.content.get(WEBMAP_ID)

    print("Readable titles:")
    retitle(gis, webmap)
    extents = site_extents(gis)

    print("Building story...")
    story = StoryMap(gis=gis)
    cover = next(c for c in story.contents if isinstance(c, Cover))
    cover.title = STORY_TITLE
    cover.summary = SUBTITLE
    cover.byline = BYLINE

    story.add(H("Why it matters"))
    for p in WHY:
        story.add(P(p))

    story.add(H("Where the barriers are"))
    for p in WHERE:
        story.add(P(p))
    story.add(Map(item=webmap), caption=MAP_CAPTION,
              alt_text="Map of fish passage barriers and salmon streams in the Nooksack River basin")

    story.add(H("Which fixes matter most"))
    for p in FIXES:
        story.add(P(p))

    sidecar = Sidecar(style="docked-panel")
    sidecar.slides = [
        SidecarSlide(content=[Text(head, TextStyles.SUBHEADING), P(text)], media=Map(item=webmap))
        for _, head, text in SLIDES
    ]
    story.add(sidecar)
    for (rank, _, _), slide in zip(SLIDES, sidecar.slides):
        try:
            if rank in extents:
                slide.media.set_viewpoint(extent=extents[rank])
        except Exception as e:  # leave the default extent; fix by hand in the builder
            print(f"  could not zoom slide #{rank}: {e}")
    story.add(P(AFTER_SLIDES))

    story.add(H("Who owns the problem"))
    story.add(table_block(OWNERS_TABLE), caption="Barriers and blocked salmon habitat by owner")
    story.add(P(OWNERS))

    story.add(H("What this can't tell you"))
    for p in CAVEATS:
        story.add(P(p))

    for content, attribution in CREDITS:
        story.credits(content=content, attribution=attribution)

    item = story.save(title=STORY_TITLE, tags=TAGS, publish=False)
    print(f"\nSaved as an unpublished draft: {item.title}")
    print(f"Open in the builder: https://storymaps.arcgis.com/stories/{item.id}/edit")


if __name__ == "__main__":
    main()
