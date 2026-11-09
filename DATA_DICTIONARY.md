# Data Dictionary

Fields in the two published layers. The same fields appear in `data/processed/` and in the hosted feature layers on ArcGIS Online.

| Layer | Geometry | Features | File | Hosted layer |
|---|---|---|---|---|
| `barriers_ranked` | Point | 577 | `barriers_ranked.gpkg`, `barriers_ranked.csv` (no geometry) | `barriers_ranked` |
| `habitat_flowlines` | Line | 20,925 | `habitat_flowlines.gpkg` | `habitat_flowlines` |

`results/qa_table.csv` holds every FPDSI site in the study area (2,276), with the FPDSI and QA fields below plus `role` and `excluded_reason` for each one. It has no gain or score fields.

## Conventions

- **Coordinate system.** The GeoPackages use NAD83 / UTM zone 10N (EPSG:26910). The hosted layers are stored in Web Mercator (EPSG:3857). All lengths and distances in the attributes are true meters or kilometers, measured in UTM.
- **Flags** (`qa_*`, `is_stop`, `side_channel_cut`, `esa_upstream`, `pct_estimated`) are 1 = yes, 0 = no. Some are stored as doubles in the hosted layer, but they still hold only 0 or 1.
- **Blanks.** FPDSI uses `-99.99` and `-999` as placeholder nulls. They're converted to blank wherever this project decodes a field. Fields copied straight from FPDSI are noted below and may still contain them.
- **Fixed by role.** Every feature in `barriers_ranked` is a ranked candidate, so a few fields hold a single value in that layer (`role` = candidate, `barrier_status` = Yes, `is_stop` = 1). They vary in `qa_table.csv`.
- **Source credit.** FPDSI and SWIFD: Washington Department of Fish and Wildlife (SWIFD with NWIFC). NHDPlus HR and WBD: USGS. FPDSI is for **planning use only**.

## barriers_ranked

One point per ranked barrier. It sits at its snapped position on the stream network, which may be up to 50 m from the original FPDSI location.

### From FPDSI (WDFW)

| Field | Type | Description |
|---|---|---|
| `fid` | OID | Feature ID assigned on publish. Not stable between publishes. |
| `SiteId` | String | WDFW site ID. Use this to join back to FPDSI or WDFW's site reports. |
| `SiteRecordID` | Double | WDFW internal record ID. |
| `StreamName` | String | Stream name as recorded by WDFW. May differ from the NHD name (see `snap_gnis_name`). "unnamed" is common. |
| `TributaryToName` | String | Stream this one flows into, per WDFW. |
| `RoadName` | String | Road or crossing name, per WDFW. Several are listed with `;` (e.g. "footpath; 120th St SE"). Often blank for dams. |
| `feature_type` | String | Decoded `FishPassageFeatureTypeCode`: Culvert, Non-Culvert Xing, Dam, Other. Natural barriers are never ranked. |
| `barrier_status` | String | Decoded `FishPassageBarrierStatusCode`. Always "Yes" in this layer. |
| `pct_passable_label` | String | WDFW passability rating as recorded: 0, 33, 67, or Unknown. |
| `owner_type` | String | Decoded `OwnerTypeCode`: Private, County, City, State, Tribal, Federal, Unknown, etc. Owner names aren't published. |
| `fish_use` | String | Decoded `FishUseCode`: Yes, No, Unknown. |
| `correction` | String | Decoded `BarrierCorrectionTypeCode`. Blank for every ranked barrier, since corrected sites are excluded. |
| `LinealGainMeasurement` | Double | WDFW's own potential habitat gain, **meters**, copied from FPDSI. Blank for about 45% of sites. It measures something different from `gain_km` (see the README). |
| `PriorityIndexTotalQuantity` | Double | WDFW's priority index, copied from FPDSI. Blank for about half of sites. |
| `PotentialSpecies` | String | Species WDFW lists as potentially present at the site, comma-separated. Includes resident trout. |
| `SurveyDate` | String | Date of the WDFW survey, MM/DD/YYYY. |
| `FormLinkURL` | String | Link to the WDFW site report (PDF). |

### Passability used for scoring

| Field | Type | Description |
|---|---|---|
| `pct_passable` | Double | Percent passable used in the score: 0, 33 or 67. |
| `pct_estimated` | Double (flag) | 1 if WDFW confirmed a barrier but gave no passability rating, so the score assumes 33%. 21 barriers. The pop-up shows these as "Not assessed (scored as 33%)". |

### Snapping

| Field | Type | Description |
|---|---|---|
| `snap_nhdplusid` | BigInteger | `nhdplusid` of the flowline the barrier was snapped to. Joins to `habitat_flowlines`. |
| `snap_dist_m` | Double | Distance moved from the FPDSI location to the flowline, meters (max 50). |
| `snap_method` | String | `name match`: the nearest flowline within 50 m whose NHD name matches `StreamName`. `nearest eligible`: no name match, so the nearest allowed flowline. Culverts, non-culvert crossings and "Other" can't snap to big rivers (NHD ArtificialPath, or stream order 6 or higher). |
| `snap_gnis_name` | String | NHD (GNIS) name of the snapped flowline. Blank if NHD has no name. |
| `nearest_any_dist_m` | Double | Distance to the nearest flowline of any kind, meters, before the eligibility rules. |
| `dist_from_upstream_end_m` | Double | Position of the snapped point along its flowline, meters from the flowline's upstream end. Used to split partial reaches in the gain trace. |
| `flowline_length_m` | Double | Length of the snapped flowline, meters. |

### Role and QA flags

QA flags are computed for every FPDSI site in `03_qa_and_snap.py`. In `barriers_ranked` most are 0 by definition, because sites that trip them are excluded. They're kept so the layer matches `qa_table.csv`.

| Field | Type | Description |
|---|---|---|
| `role` | String | `candidate` (ranked), `stop` (natural barrier or barrier on a non-fish stream; ends upstream traces but isn't ranked) or `excluded`. Always `candidate` here. |
| `excluded_reason` | String | Why a site was excluded: duplicate, corrected, not a barrier, barrier status unknown/blank, no feature type, culvert only near a large river, more than 50 m from a flowline. Blank here. |
| `is_stop` | SmallInteger (flag) | 1 if the site ends upstream traces (candidates and stops). |
| `qa_duplicate` | SmallInteger (flag) | Another FPDSI site lies within 1 m. |
| `qa_duplicate_dropped` | SmallInteger (flag) | Duplicate that was dropped; the most recently surveyed site is kept. |
| `qa_far_from_stream` | SmallInteger (flag) | No eligible flowline within 50 m. |
| `qa_corrected` | SmallInteger (flag) | WDFW records a correction (replaced, removed, fishway, etc.). |
| `qa_missing_pct` | Double (flag) | Confirmed barrier with no usable passability rating. Same set as `pct_estimated` among candidates. |
| `qa_pct_conflict` | Double (flag) | Recorded as a barrier but rated 100% passable. |
| `qa_unknown_status` | Double (flag) | Barrier status is Unknown, NA or blank (natural barriers aside). |
| `qa_no_owner` | SmallInteger (flag) | Owner type blank or Unknown. |
| `qa_only_big_river_nearby` | SmallInteger (flag) | A culvert or crossing whose only flowline within 50 m is a big river, so it can't be snapped. |
| `qa_name_mismatch` | SmallInteger (flag) | Has a stream name, but it snapped to a flowline with a different NHD name. Worth checking by hand (see "How the results were checked" in the README). |

### Habitat gain and score

| Field | Type | Description |
|---|---|---|
| `gain_km` | Double | **Salmon habitat opened**, km. Length of target-species habitat upstream of the barrier, stopping at the next barrier or natural barrier. Partial reaches are split at the snap point. |
| `weighted_gain_km` | Double | `gain_km` with each reach multiplied by its `hab_weight` (2 for Chinook, steelhead or bull trout; 1 for other salmon). |
| `species_upstream` | String | Target species found in the habitat counted in `gain_km`, `;`-separated, using SWIFD's species and run names (e.g. "Coho; Fall Chum; Winter Steelhead"). |
| `stream_km_upstream` | Double | All stream length upstream to the next stop, km, habitat or not. Used for the WDFW comparison. |
| `side_channel_cut` | SmallInteger (flag) | The upstream trace was stopped where a side channel (NHDPlus minor divergence) leaves the main channel. 61 barriers. |
| `esa_upstream` | SmallInteger (flag) | `species_upstream` includes an ESA-listed species (Chinook, steelhead or bull trout). |
| `score` | Double | Priority score = `weighted_gain_km` × (1 − `pct_passable` / 100). |
| `rank` | BigInteger | Rank by `score`, 1 = highest. |
| `subbasin` | String | HUC10 watershed name (USGS WBD) the barrier falls in. |

## habitat_flowlines

Every NHDPlus HR flowline in the Nooksack HUC8 (17110004), tagged with target species from SWIFD. The web map shows only reaches with `hab_weight > 0`.

### Added by this project

| Field | Type | Description |
|---|---|---|
| `species` | String | Target species mapped on this reach, `;`-separated SWIFD species and run names. Blank if none. A reach is tagged with a species when at least 2 of 3 points along it (at 25%, 50% and 75% of its length) lie within 25 m of that species' SWIFD line. Only Documented, Presumed, Gradient Accessible and Potential distribution types count. |
| `hab_weight` | BigInteger | 2 = Chinook, steelhead or bull trout (ESA-listed). 1 = coho, chum, pink or sockeye only. 0 = no target species. A reach with several species takes the highest weight. |
| `length_m` | Double | Flowline length, meters, measured in UTM 10N. Used for all gain sums. |

### From NHDPlus HR (USGS)

Carried through unchanged from `NHDFlowline` and `NHDPlusFlowlineVAA`. See the NHDPlus HR user guide for full definitions.

| Field | Type | Description |
|---|---|---|
| `fid` | OID | Feature ID assigned on publish. |
| `nhdplusid` | BigInteger | NHDPlus HR flowline ID. Primary key; joins to `barriers_ranked.snap_nhdplusid`. |
| `permanent_identifier` | String | NHD permanent ID. |
| `fdate` | Date | NHD feature date. |
| `resolution` | Integer | NHD resolution code (2 = high). |
| `gnis_id`, `gnis_name` | String | Geographic Names Information System ID and name. Blank for unnamed streams. |
| `lengthkm` | Double | NHD's own length, km. |
| `reachcode` | String | 14-digit NHD reach code. |
| `flowdir` | Integer | 1 = digitized in the direction of flow. |
| `wbarea_permanent_identifier` | String | Waterbody the line runs through (for artificial paths through lakes and wide rivers). |
| `ftype`, `fcode` | Integer | NHD feature type and code. Main types: 460 StreamRiver, 558 ArtificialPath (centerline through a lake or wide river), 336 CanalDitch, 334 Connector. |
| `mainpath`, `innetwork`, `visibilityfilter`, `enabled`, `vpuid` | various | NHD and NHDPlus housekeeping fields. Not used here. |
| `streamorde` | Double | Strahler stream order. Order 6 and up counts as a big river for snapping. |
| `hydroseq`, `dnhydroseq`, `uphydroseq` | Double | NHDPlus hydrologic sequence numbers for this flowline and its downstream and upstream mainstem neighbors. |
| `terminalpa` | Double | Hydroseq of the network's outlet. |
| `arbolatesu` | Double | Arbolate sum: total stream length upstream, km. Used to check that the network was built correctly. |
| `startflag` | Double | 1 = headwater flowline. |
| `divergence` | Double | 0 = no split, 1 = main path at a split, 2 = minor path (side channel). Upstream traces stop at 2. |
| `pathlength` | Double | Distance to the network outlet, km. |
| `shape_length` | Double | Length from the source GeoPackage, in its units. Ignore it; use `length_m`. |
| `Shape__Length` | Double | Length computed by ArcGIS Online in Web Mercator. Overstates true length (about 1.5× at this latitude). Use `length_m`. |
