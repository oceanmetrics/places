# RUNBOOK: MarineCadastre first-15 layers, 14 collections (staged 2026-10-08, not published)

Digest: `~/Github/bbest/notes/om/plans_todo/2026-10-08_places-gazetteer_research/marinecadastre-boem.md` ("First-15 ingest list").
Configs: `sources/noaa/*.yml`, `sources/fws/*.yml`, `sources/usace/*.yml`. Tests: `tests/test_marinecadastre15.py`.
Built on the Mac mini (tmux `om`, windows `mc15` and `mc15b`, log `~/Github/oceanmetrics/places/logs/mc15.log`, copy in
`catalog/staging/mc15_build.log`), rsynced back to `catalog/staging/<slug>/`. Version 1.0.0 each.

## Scope against the digest list

| digest # | layer | outcome |
|---|---|---|
| 1 | National Marine Sanctuaries | `noaa_sanctuaries` |
| 2 | NOAA MPA Inventory | RETIRED here: built as `mpa_inventory` (`MPAINV:` ids, RUNBOOK_mpa_gebco.md); see the retirement note below |
| 3 | National Estuarine Research Reserves | `noaa_nerrs` |
| 4 | Marine National Monuments | `noaa_marine_monuments` |
| 5 | State waters | two collections: `noaa_state_lateral_boundaries` (lines) and `noaa_state_submerged_lands` (polygons) |
| 6 | US Maritime Limits | `noaa_maritime_limits` (lines; MapServer layers 1/2/3 as components) |
| 7 | OCS Planning Areas (+ 11th Program draft) | SKIPPED: already built (`boem_ocs_planning`, `boem_program_11_draft`) |
| 8 | Wind Lease Outlines | SKIPPED: already built (`boem_wind_leases`) |
| 9 | Wind Planning Area Outlines (rescinded) | SKIPPED: already built (`boem_wind_planning_rescinded`) |
| 10 | Aquaculture Opportunity Areas | SKIPPED: already built (`noaa_aoa_socal`) |
| 11 | EFH and HAPC | `noaa_hapc` only. **EFH is NOT staged: its item (`b2404d6c...`) has an empty `licenseInfo`.** |
| 12 | Critical habitat NMFS + FWS | `noaa_esa_critical_habitat` (polygon layer 1; the 59,888-feature line layer is skipped as the digest says), `fws_critical_habitat_final` (layer 0), `fws_critical_habitat_proposed` (layer 2) |
| 13 | Vessel Routing Measures | `noaa_vessel_routing_measures` |
| 14 | Submarine Cables | `noaa_submarine_cables` (the layer is polygons, not lines) |
| 15 | Danger Zones and Restricted Areas | `usace_danger_zones` |

## Collections

| slug | authority / id | place_type | n | parquet | pmtiles | build (mini) | licence review |
|---|---|---|---|---|---|---|---|
| `noaa_sanctuaries` | `ONMS:<site>[:<section>]` | protected_area | 47 | 5.5 MB | 3.1 MB | 14 s | clear |
| `noaa_nerrs` | `NERRS:<sitecode>` | protected_area | 30 | 1.9 MB | 0.5 MB | 2 s | clear |
| `noaa_marine_monuments` | `MC:monuments:<site>` | protected_area | 32 | 2.1 MB | 2.5 MB | 16 s | clear |
| `noaa_state_lateral_boundaries` | `MC:state_lateral:<fips-fips>` | jurisdiction (lines) | 19 | 30 kB | 17 kB | 1 s | clear |
| `noaa_state_submerged_lands` | `MC:submerged_lands:<objectid>` | jurisdiction | 483 | 53.3 MB | 12.4 MB | 58 s | clear |
| `noaa_maritime_limits` | `NOAA-OCS:<BOUND_ID>` | maritime_limit (lines) | 246 | 2.6 MB | 0.3 MB | 5 s | "NOT FOR LEGAL USE" |
| `noaa_hapc` | `NMFS:HAPC:<FID>` | habitat | 237 | 22.0 MB | 7.0 MB | 49 s | REVIEW: no-warranty text only |
| `noaa_esa_critical_habitat` | `NMFS:CH:<ID>[:part]` | habitat | 2114 | 123.1 MB | 46.2 MB | 479 s | REVIEW: attribution is a fallback |
| `fws_critical_habitat_final` | `FWS:CH:<entity_id>` | habitat | 803 | 244.5 MB | 74.9 MB | 568 s | disclaimer |
| `fws_critical_habitat_proposed` | `FWS:CHP:<entity_id>` | habitat | 70 | 71.0 MB | 18.5 MB | 443 s | disclaimer |
| `noaa_vessel_routing_measures` | `MC:vrm:<objectid>` | navigation_measure | 327 | 35.5 MB | 20.8 MB | 63 s | clear |
| `noaa_submarine_cables` | `MC:cables:<objectid>` | infrastructure | 2816 | 10.0 MB | 8.8 MB | 22 s | clear |
| `usace_danger_zones` | `USACE:<state>:<cfr-section>[:part]` | restricted_area | 422 | 1.4 MB | 1.0 MB | 5 s | clear |

Net build time 1,923 s (32 min). Wall time on the mini 3,590 s (60 min) because of two failures that were fixed and re-run:
the first FWS-final attempt hung on 200-feature pages (about 200 MB each), re-run with `page_size: 25`; the NMFS ID rendered
as a float (see 3). Nothing was dropped (no feature without geometry) in any layer; served counts equal staged counts.

## Authority prefixes (digest: per-agency where clear, else `MC:<layer>:`)

`ONMS` (NOAA Office of National Marine Sanctuaries), `MPA` (NOAA MPA Center), `NERRS`, `NMFS` (HAPC and ESA critical habitat),
`FWS`, `USACE`, `NOAA-OCS` (NOAA Office of Coast Survey; not `OCS`, which BOEM uses for its lease series). Where the item is a
NOAA Office for Coastal Management compilation of other agencies' data the prefix is `MC:<layer>:` (monuments, state lateral
boundaries, submerged lands, vessel routing measures, submarine cables). `place_id` pattern per authority is asserted in the tests.

## Licence and attribution (harvested from the AGOL items, 2026-10-08)

All collections: SPDX `CC-PDDC` (US federal government works, 17 U.S.C. 105; `license_url` points there). The verbatim item
`licenseInfo` and `accessInformation` are stored per source in `provenance.json` (`source_license`, `source_attribution`) and the
attribution line in every row is built from `accessInformation`. Items with the standard NOAA OCM text (17 U.S.C. 403 notice): sanctuaries,
NERRS, monuments, lateral boundaries, submerged lands, vessel routing, cables, danger zones. Others:

| slug | item `licenseInfo` | `accessInformation` | note |
|---|---|---|---|
| `noaa_maritime_limits` | "NOT FOR LEGAL USE ... internal purposes ... not the official depiction" | DOC / NOAA / NOS / Coast Survey | surface the warning in the UI; item last modified 2020, data v4.0 (2013) |
| `noaa_hapc` | no-warranty disclaimer only | long NOAA Fisheries / Councils list (shortened in the row, full in provenance) | no explicit PD statement; federal work; confirm |
| `noaa_esa_critical_habitat` | "not the official legal definitions" | EMPTY | attribution falls back to "NOAA Fisheries ..." (the item owner is a NOAA account): unverified, per the digest's fallback rule |
| `fws_critical_habitat_*` | "None." plus accuracy / no-warranty text | USFWS | many attributes read "Please check current species specific shapefile" |
| EFH (`noaa_efh`) | EMPTY | NOAA Fisheries Habitat Protection Division | NOT STAGED: no licence text. Ask NOAA Fisheries HPD, or use the FMC / PSMFC sources |

## Assumptions and decisions

1. **Disclaimer-only `licenseInfo` counts as usable** (the layer is a federal work and the text is the item's own use statement); an
   empty `licenseInfo` does not (EFH). Review the flagged rows above before publishing; AGENTS.md tiers: all are staged as Tier 1.
2. **Ids without a natural key use the source OBJECTID** (submerged lands, vessel routing, cables): hosted-layer OBJECTIDs are stable
   until the layer is republished from scratch. Names for those are generic ("State submerged lands 12"; cables fall back to
   "Submarine cable area (n)" because 2,484 of 2,816 have no `shortname`). NMFS critical habitat: `ID` is a float with noise
   (100062107.99999999) so the id uses `{ID|round}` and repeats (`ID` is not unique) get `:part` in OBJECTID order. FWS: `entity_id`, same dedupe.
   Danger zones: state + the slug of `boundaryidentifier` (some read "See RNC 11490 (Note B)"), repeats `:part`, `:part-2` in OBJECTID order.
3. **`status`**: literal per layer (sanctuaries/monuments/NERRS/HAPC `designated`, MPA `established`, boundaries/limits/routing/danger zones
   `in_force`, cables `charted` because the native status is empty for 2,411 of 2,816, FWS `final` / `proposed`); NMFS takes `CHSTATUS`
   (final 2021, proposed 73, designated 20). `status_date` is the layer `editingInfo.dataLastEditDate` where served (MPA, HAPC, NMFS, FWS)
   and empty for the NOAA OCM hosted layers, which serve none; maritime limits use `APPRV_DATE`. Change detection for the hosted layers
   therefore falls back to the payload checksum (supported by `detect`).
4. **Lines** (lateral boundaries, maritime limits) are `geometry_type: MultiLineString`, split at +/-180 by `gazetteer/lines.py`
   (Alaska and Marianas limits cross the dateline: staged bbox -180..180).
5. **Paging**: the NOAA/Esri servers time out on large polygon pages; `page_size` is 200 (25 for FWS), 0.5 s between pages (about 2 req/s or less).
   Raw pages are cached in `cache/` on the mini (FWS final alone is about 800 MB; delete after publishing).
6. **RETIRED 2026-10-08: `noaa_mpa_inventory`** (`MPA:` ids, same 981 MPA Center polygons) duplicated `mpa_inventory` (`MPAINV:` ids, the plan's
   prefix, kept). Its yml `sources/noaa/mpa_inventory.yml` now holds the `mpa_inventory` config, its `catalog/staging/noaa_mpa_inventory/` was deleted,
   and its tests removed (this collection set is now 13 layers).
7. **Heavy files**: `fws_critical_habitat_final` (245 MB parquet / 75 MB tiles) and `fws_critical_habitat_proposed` (71 MB for 70 features) carry
   very detailed geometry for species that are mostly terrestrial; consider simplification or leaving them out of the first publish.
8. The first-15 list's cables are called lines; the service serves polygons (cable areas).

## Publish (not done here)

```sh
cd ~/Github/oceanmetrics/places
uv run build.py check --sources sources --slug noaa_sanctuaries ...       # parquet + PMTiles checks per slug
cd catalog && portolan add <slug>/ && cd .. && rashid check catalog         # per slug, from catalog/staging into the tree
aws s3 sync catalog/<slug>/ s3://oceanmetrics.io-public/gazetteer/<slug>/   # only that collection; never --delete outside it
```

Rebuild one collection on the mini: `uv run build.py build --slug <slug>` (the 14 configs sit in `sources/`; the mini run used a copy
in `sources_mc15/` so other sessions' configs could not break it). Refresh: `uv run build.py detect`.

## Shared-pipeline changes made (all additive, defaults unchanged)

- `config.py`: place types `protected_area`, `jurisdiction`, `maritime_limit`, `habitat`, `restricted_area`, `navigation_measure`,
  `infrastructure`; `geometry_type` also accepts `MultiLineString`.
- `lines.py` (new): `clean_multiline_geometry`, antimeridian split for lines, `max_line_span`.
- `table.py`, `validate.py`, `stac.py`: dispatch and type id for `MultiLineString` (style is a line layer); the span check also looks at lines.
- `ids.py`: `place_id.dedupe: {order: FIELD}` (repeats get `:part`, `:part-2`; lowest FIELD keeps the bare id).
- `fmt.py`: template filters `default:<text>` and `round`.
- `status.py`: `status.value: field:NAME` (native attribute, lower-cased, `status.default` when empty).
