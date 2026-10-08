# RUNBOOK: mpa_inventory and gebco_undersea (staged 2026-10-08, not published)

Two Tier-1 collections, staged in `catalog/staging/mpa_inventory/` and `catalog/staging/gebco_undersea/` (git-ignored,
like every staging dir; this runbook is not in git either).

| Collection | place_id | place_type | geometry | features | parquet | pmtiles | licence |
|---|---|---|---|---|---|---|---|
| `mpa_inventory` | `MPAINV:<Site_ID>` (e.g. `MPAINV:CA123`) | `mpa` | MultiPolygon | 981 | 68.8 MB | 24.8 MB (z0-12) | CC-PDDC |
| `gebco_undersea` | `GEBCO:<FEATURE_ID>` | `undersea_feature` | MultiPolygon 1,652 / MultiLineString 1,128 / MultiPoint 2,632 | 5,412 | 1.2 MB | 6.1 MB (z0-8) | LicenseRef-IHO-IOC-GEBCO-Gazetteer (STAC `other`) |

## Sources

- `mpa_inventory`: https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/NOAA_MPA_Inventory_2023/FeatureServer/0,
  item `eb2b36aecb004f14ac29cf0260624291`, `dataLastEditDate` 2025-01-15T18:28:55Z. All 35 native fields are columns
  (`ProSeasID` and `WDPA_Cd` are the crosswalk keys). The item `licenseInfo` is a disclaimer only ("Data are not to be used for
  navigation ... not legal documents"); "public domain" comes from InPort 69506 (notes `mpa-sources.md`). Treated as CC-PDDC.
- `gebco_undersea`: https://services2.arcgis.com/C8EMgrsFcRFL6LrL/arcgis/rest/services/Undersea_Features/FeatureServer,
  layers 2 (Polygon_Features, 1,652), 1 (Line_Features, 1,128), 0 (Point_Features, 2,632); item `f09d579c68b84c5184fef1ac69ea7b24`
  (NCEI, "GEBCO Undersea Feature Names Gazetteer"); layers edited 2026-10-08.

## GEBCO licence (recorded verbatim)

Item `licenseInfo` (HTML stripped) and the GEBCO page https://www.gebco.net/data-products/undersea-feature-names ("Data set
acknowledgement") say the same: "Please include the following citation when data from the gazetteer are used or reproduced in
reports, presentations and other products: IHO-IOC GEBCO Gazetteer of Undersea Feature Names, www.gebco.net". Item
`accessInformation` / layer `copyrightText`: "IHO Data Centre for Digital Bathymetry (IHO DCDB); General Bathymetric Chart of the
Oceans (GEBCO); NOAA National Centers for Environmental Information (NCEI)". Neither page nor the GEBCO disclaimer page states a
non-commercial or no-redistribution term, so it is staged as Tier 1 (attribution required). It is NOT an explicit open licence;
if a written confirmation is wanted, ask the GEBCO SCUFN / IHO DCDB (the repo's Tier 2 rule does not require it here). The raw
licenseInfo HTML is kept in `provenance.json` (`source_license`).

## Decisions and assumptions

- **GEBCO id = `FEATURE_ID`** (the gazetteer's permanent feature number, identical across the three layers, no nulls, unique
  within each layer). `OBJECTID` is service-assigned and renumbered on republish. 101 FEATURE_IDs appear in more than one layer
  (a point plus an extent): the first configured source keeps the bare id (polygon, then line, then point), the others get
  `:line` / `:point` (`id_collisions: suffix_component`). `source_id` is always the bare FEATURE_ID.
- GEBCO `name` = `NAME` + `TYPE` ("Satsuma Seamount"); the native `NAME` stays as `NAME_src`. All geometries are normalised to
  Multi* and `geom_type` is per row; `component` (polygon/line/point) says which layer a row came from. The service already
  splits lines and polygons at +/-180; the builder still snaps and verifies.
- Tiles: one layer per slug holding all three kinds; the default style has one style layer per kind (filters on
  `geometry-type`). GEBCO uses a fixed `tile_maxzoom: 8` (-zg gave z5, too coarse; z10 was 22 MB).
- Both collections use `spatial_sort` (Z-order of bbox centres, globe-spanning features last) with small row groups so
  `rashid check` passes PTL-DAT-006.
- `mpa_inventory` place_type `mpa`, status `active`; `gebco_undersea` status `approved`. Cadence monthly (detect compares
  `dataLastEditDate` + counts).
- The duplicate `noaa_mpa_inventory` (`MPA:` ids, `protected_area`) from the MarineCadastre first-15 was retired 2026-10-08; this
  `mpa_inventory` (`MPAINV:`) is the only MPA Inventory collection, config `sources/noaa/mpa_inventory.yml`.

## Check and rebuild

    cd ~/Github/oceanmetrics/places
    uv run build.py build --slug mpa_inventory --slug gebco_undersea     # MPA fetch takes ~3.5 min (large geometries)
    uv run build.py check --slug mpa_inventory --slug gebco_undersea
    uv run --group dev pytest -q tests/test_mpa_gebco.py

Verified on a scratch catalog (`portolan init --license CC-PDDC`, `portolan add <slug>/ --force --force-thumbnails`):
`rashid check <catalog> --data-scope local` gives 0 errors, one PTL-DAT-005 warning for GEBCO (PMTiles bbox is Web-Mercator
clipped at 85.05 N, the data reaches 89.6 N) and PTL-PRO-002 infos.

## Publish (not done here)

    cd catalog
    cp -R staging/mpa_inventory/. mpa_inventory/ && portolan add mpa_inventory/ --force --force-thumbnails
    cp -R staging/gebco_undersea/. gebco_undersea/ && portolan add gebco_undersea/ --force --force-thumbnails
    cd .. && rashid check catalog --data-scope local
    aws s3 sync catalog/mpa_inventory/ s3://oceanmetrics.io-public/gazetteer/mpa_inventory/ --exclude '.portolan/*'
    aws s3 sync catalog/gebco_undersea/ s3://oceanmetrics.io-public/gazetteer/gebco_undersea/ --exclude '.portolan/*'
    aws s3 cp catalog/versions.json catalog/catalog.json s3://oceanmetrics.io-public/gazetteer/   # copy each file; never --delete

Both are version 1.0.0. `portolan init` needs `--license` (CC-PDDC) when a catalog is first created.

## Shared-pipeline changes (additive; defaults unchanged)

- `config.py`: place types `mpa`, `undersea_feature`.
- `table.py`: collection flag `mixed_geometry` (per-row `geom_type`, Multi* cleaning via new `gazetteer/mixed.py`),
  `id_collisions: suffix_component`, `spatial_sort`. `validate.py`: mixed type check, `geom_type` must match the geometry.
- `stac.py`: `Mixed` default style; `geoparquet:geometry_type` follows the file; `stac_license` (`other`) overrides the STAC
  `license` for a non-SPDX licence. `pipeline.py`: passes `row_group_size`, the Mixed style.
- New: `gazetteer/mixed.py`, `sources/gebco/undersea_features.yml`, `sources/noaa/mpa_inventory.yml`,
  `tests/test_mpa_gebco.py` (30 tests; staged-output tests skip when not built).
