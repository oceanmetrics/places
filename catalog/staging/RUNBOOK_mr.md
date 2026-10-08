# RUNBOOK: Marine Regions CC-BY products, `mr_*` (staged 2026-10-08, not published)

Seven gazetteer collections from Marine Regions (VLIZ, Flanders Marine Institute), all CC BY 4.0 (stated at
https://www.marineregions.org/disclaimer.php: products "licensed under CC-BY since Maritime Boundaries version 11 (2019)").
Staged in `catalog/staging/mr_*/` (git-ignored; EEZ and the other heavy layers were built on the Mac mini and rsynced back).
Research digest: `~/Github/bbest/notes/om/plans_todo/2026-10-08_places-gazetteer_research/marineregions.md`.

NOT ingested (licence unconfirmed, Tier gate; VLIZ email pending): IHO Sea Areas v3, LME, MEOW, Longhurst, Contourite.

## Products, versions, DOIs, sizes

| slug | WFS layer (geo.vliz.be, workspace MarineRegions) | place_type | product, version (released) | DOI | features | parquet | pmtiles | build (mini) |
|---|---|---|---|---|---|---|---|---|
| `mr_eez` | `eez` | `eez` | Exclusive Economic Zones (200NM), v12 (2023-10-25) | 10.14284/632 | 285 | 143.6 MB | 49.1 MB | 263 s |
| `mr_territorial_seas` | `eez_12nm` | `territorial_sea` | Territorial Seas (12NM), v4 (2023-10-25) | 10.14284/633 | 230 | 63.6 MB | 15.0 MB | 92 s |
| `mr_contiguous_zones` | `eez_24nm` | `contiguous_zone` | Contiguous Zones (24NM), v4 (2023-10-25) | 10.14284/630 | 220 | 57.1 MB | 8.1 MB | 57 s |
| `mr_high_seas` | `high_seas` | `high_seas` | High Seas, v2 (2024-10-10) | 10.14284/696 | 1 | 7.5 MB | 1.2 MB | 8 s |
| `mr_ecs` | `ecs` | `ecs` | Extended Continental Shelves, v2 (2024-10-10) | 10.14284/697 | 147 | 5.0 MB | 0.5 MB | 21 s |
| `mr_goas` | `goas` | `ocean_sea` | Global Oceans and Seas, v1 (2021-12-14) | 10.14284/542 | 10 | 111.1 MB | 40.7 MB | 351 s |
| `mr_world_heritage_marine` | `worldheritagemarineprogramme` | `world_heritage` | UNESCO World Heritage Marine Sites, v02 (as of 2023-01-01) | 10.14284/592 | 60 | 3.8 MB | 2.2 MB | 7 s |

DOIs and release dates are from https://www.marineregions.org/sources.php and downloads.php (read 2026-10-08), versions
from the WFS GetCapabilities titles. The v4 territorial/contiguous DOIs (633, 630) differ from the stale v3 DOIs in
`mregions2::mrp_list` (387, 384): the digest warned about that. Database citation (every attribution):
"Flanders Marine Institute (2026): MarineRegions.org. Available online at www.marineregions.org. Consulted on 2026-10-08."

## Access path

WFS 2.0 `https://geo.vliz.be/geoserver/MarineRegions/wfs`, `outputFormat=application/json`, `srsName=EPSG:4326`
(GeoServer returns lon/lat), paged `startIndex`/`count` (10 features per page for eez/ecs/high_seas/goas, 25 for the 12/24
NM and heritage layers) with `sortBy` (`mrgid`; `name` for goas; `refid` for heritage), serial, 1 s between pages, identified
User-Agent (`oceanmetrics-gazetteer/1.0 ... contact: bdbest@gmail.com`). The paged count must equal `resultType=hits`
or the build fails. The GPKG downloads sit behind a request form (name/purpose), so they were not used.
New module `gazetteer/fetch_wfs.py` (source kind `wfs`); configs `sources/marineregions/*.yml`.

## Columns

Common gazetteer columns plus: `mrgid` (int), `mrgid_uri` (`http://marineregions.org/mrgid/{id}`), `mr_product`,
`mr_product_version`, `mr_product_doi`, `mr_license` (`CC-BY-4.0`), `mr_modified`, `mr_part`, then every native WFS field
unchanged (a native `name` becomes `name_src`). `place_id = MRGID:<mrgid>` (`authority` MRGID); `license` CC-BY-4.0; `attribution`
= product DOI citation + database citation; every collection `description` carries the "no legal value / not for legal,
economic or navigational use" disclaimer (also in the PMTiles `-N` description; `--attribution` set; layer = slug).

## Assumptions and decisions (read before publishing)

1. **GOaS has no MRGID in the WFS layer.** Each of its 10 features is keyed to the gazetteer record of the same name and extent:
   6 match the record's bbox exactly (Arctic 1906, Southern 1907, North Pacific 1908, South Pacific 1910, North Atlantic 1912,
   Mediterranean 4278), 4 match within 0.02 degrees on one edge (Indian 1904, South Atlantic 1914, Baltic 2401, South China 4331).
   These are IHO Sea Area / SeaVoX General Sea Area records, used here only as identifiers (a crosswalk key), not for their
   geometry. The map is in `sources/marineregions/goas.yml`; confirm with VLIZ if they publish GOaS-specific MRGIDs.
2. **`mr_modified` is the product version's release date**, not the gazetteer `dc:modified` (the WFS serves no per-feature edit date and the
   digest found `dc:modified` unreliable for product swaps). `data_last_edit` / `source_date` / `status_date` use the same date.
   `status` is `current` for every row (the products carry no lifecycle field).
3. **Duplicate MRGIDs** are suffixed deterministically (first in source order keeps the bare id; others `:buffer`, `:buffer-2` or
   `:part`): only the heritage layer has any (10 rows, e.g. `MRGID:26839:part`, `MRGID:26839:buffer`; `mr_part` holds the suffix). Its
   `mrgid` column is cast from string to int.
4. **Antimeridian.** The WFS delivers geometries in -180..180 with polygons already cut at the meridian for most of the EEZ (Fiji `MRGID:8325`
   comes out as halves with bbox -180..180 meeting on it); `clean_geometry` unwraps and splits any ring that still jumps. The High Seas and
   Arctic Ocean polygons cap the pole with an edge along y=90 from -180 to 180: this is a real edge of the planar polygon, not a dateline jump, and
   used to trip the "ring encircles a pole" guard. Fixed in `geom.py` (`_unwrap_ring`, `max_edge_span` ignore edges lying on y=+/-90), with a
   named regression test. Tiles clip at Web Mercator's ~85 N, so the Arctic caps render as expected.
5. **Redistribution.** The disclaimer asks users "not to make our products available for download elsewhere and to always refer to
   marineregions.org". CC BY 4.0 permits redistribution, and the digest's open question to VLIZ (info@marineregions.org) about GeoParquet/PMTiles copies
   is still open; the README of each collection links the upstream product and DOI. Consider telling VLIZ (they also ask to be told of uses).
6. No overlap/clipping between layers (EEZ, 12 NM, 24 NM, ECS and High Seas are published as the products define them; `mrgid_eez` links 12/24 NM rows to their EEZ).
7. Version 1.0.0 each; cadence `monthly`. Change detection compares the WFS layer title (product version) and feature count
   (`http.etag` slot of the provenance record), not the data; a same-version silent correction would be missed (weekly `detect`
   would need a full re-fetch and checksum compare to catch it).

## Rebuild and check

    # laptop (small layers) or the mini (EEZ, 12/24 NM, GOaS: see below)
    cd ~/Github/oceanmetrics/places
    uv run build.py build --slug mr_high_seas --slug mr_ecs --slug mr_world_heritage_marine
    uv run build.py check --slug mr_eez --slug mr_territorial_seas --slug mr_contiguous_zones --slug mr_ecs \
        --slug mr_high_seas --slug mr_goas --slug mr_world_heritage_marine
    uv run --group dev pytest -q tests/test_mr.py     # staged-artifact tests take ~10 min (loading every geometry); the rest <1 s

On the mini (what was run; tmux session `om`, window `mrprod`, log `logs/mrprod.log`, marker `logs/mrprod.done`):

    rsync -aR gazetteer sources/marineregions build.py pyproject.toml uv.lock catalog/staging/run_mr.sh macmini:~/Github/oceanmetrics/places/
    ssh macmini 'cd ~/Github/oceanmetrics/places && mkdir -p sources_mr/marineregions && cp sources/marineregions/*.yml sources_mr/marineregions/ &&
      tmux new-window -d -t om -n mrprod "SOURCES=sources_mr catalog/staging/run_mr.sh mr_eez mr_territorial_seas mr_contiguous_zones mr_ecs mr_high_seas mr_world_heritage_marine mr_goas"'
    rsync -a macmini:~/Github/oceanmetrics/places/catalog/staging/mr_eez catalog/staging/      # and the other six

(`sources_mr` is a private copy so the build does not load other agents' configs on the shared mini checkout.)

## Publish (not done here)

`rashid check`, then `portolan add` for the seven slugs and sync to `s3://oceanmetrics.io-public/gazetteer/` for these slugs only (AGENTS.md;
never `--delete` outside them). Publish from the laptop or the mini after the VLIZ question in 5 is settled if you want to be conservative.

## Shared-pipeline changes made (all additive)

- `gazetteer/config.py`: place types `eez territorial_sea contiguous_zone high_seas ecs ocean_sea world_heritage`; source kind `wfs`.
- `gazetteer/pipeline.py`: `fetch_source` dispatches `wfs` to `fetch_wfs.fetch_wfs`; `detect` probes `wfs` sources (`probe_wfs`).
- `gazetteer/geom.py`: pole-cap edges (both ends at y=+/-90) are no longer read as dateline jumps (`_unwrap_ring`) or counted by `max_edge_span`.
- New: `gazetteer/fetch_wfs.py`, `sources/marineregions/*.yml` (7), `tests/test_mr.py`, `catalog/staging/run_mr.sh`, this runbook (force-added: `catalog/staging/` is git-ignored).
