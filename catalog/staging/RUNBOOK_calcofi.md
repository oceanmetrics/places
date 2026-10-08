# RUNBOOK: calcofi_stations and calcofi_lines (staged 2026-10-08, not published)

Two small gazetteer collections contributed by CalCOFI under its own licence (decision D13). Staged in
`catalog/staging/calcofi_stations/` and `catalog/staging/calcofi_lines/` (git-ignored; built on the laptop in seconds).

## What they are

| Collection | place_id | place_type | geometry | features |
|---|---|---|---|---|
| `calcofi_stations` | `CALCOFI:<line>_<station>`, e.g. `CALCOFI:093.3_030.0` | `station` | Point | 113 (75 `core_75`, 38 `extended`) |
| `calcofi_lines` | `CALCOFI:line-<line>`, e.g. `CALCOFI:line-093.3` | `transect` | LineString | 11 |

Station columns: `line_id`, `station_id` (zero-padded strings), `station_key` (`093.3 030.0`, the CalCOFI database
`site_key` form), `line`, `station` (numeric), `order_occ`, `depth_est_m`, `sta_type` (ROS | SCCOOS), `in_core_75`
(bool), `sampling_pattern` (`core_75` | `extended`). Line columns: `line_id`, `line`, `n_stations`, `n_core_75`,
`in_core_75`, `station_min`, `station_max`, `length_km`.

## Source (what was used, and why)

1. Local repos first: `~/Github/CalCOFI/calcofi4r/data-raw/station_positions.csv` (113 rows, `in_75` flag, fetched
   2026-10-02 from calcofi.org) and the `stations` table in calcofi4r (2,634 historically occupied stations). The explore
   repo has no station source of its own. ERDDAP was not needed.
2. The pipeline fetches CalCOFI's own published files, which calcofi4r copied, so the staged data traces to the publisher:
   - positions: https://calcofi.org/downloads/maps/CalCOFIStationOrder.csv (113 stations; `Last-Modified` 2022-02-06,
     ETag `"21b0-5d76164d7a3de"`, sha-256 of the two downloads in `provenance.json`); linked from
     https://calcofi.org/sampling-info/station-positions/ ("Download as CSV").
   - core-75 membership: https://calcofi.org/downloads/CalCOFI_75StandardStations.kml (`Last-Modified` 2022-02-06).
   - retrieved 2026-10-08. The HTML table on the page and the calcofi4r CSV agree with the downloaded CSV on all 113
     positions (checked 2026-10-08, tolerance 1e-5 degrees).
3. Positions are published values, not computed from the station algebra, so there is no algebra code; the known-coordinate
   fixtures assert published values (93.3/30.0 = 32.84637 N, 117.53122 W; 93.3/26.7 = 32.95637 N, 117.30538 W).

## Core 75 vs extended (how determined)

`in_core_75` = the station key (`LLL.L SSS.S`) is a placemark name in `CalCOFI_75StandardStations.kml`. 75 of the 113 match.
Cross-checks (tests `test_staged_core_75_*`): the page describes the 75 as lines 76.7 to 93.3 (66 stations) plus 9 SCCOOS
inshore stations, and in the table that is exactly every station with `line >= 76.7`; lines 60.0 to 73.3 are the extended
grid (38 stations). The calcofi4r `in_75` flag gives the same set. The KML lists one more key than the table,
`083.3 043.0`, which has no position in the table; it is ignored and reported in `provenance.json` `dropped`.
The 104-station winter/spring pattern is not separately flagged (the source lists no membership for it).

## Lines

Polyline through the listed stations of a line, in station-number order (nearshore to offshore); `length_km` is geodesic.
Eleven lines have two or more positions (60.0, 63.3, 66.7, 70.0, 73.3, 76.7, 80.0, 83.3, 86.7, 90.0, 93.3). Seven
single-station lines (81.7, 81.8, 85.4, 86.8, 88.5, 91.7, 93.4: the SCCOOS inshore stations and 81.8/46.9) cannot form a
linestring and are listed in `dropped`; their stations are in `calcofi_stations`. The line is not extended beyond the
listed stations (no extrapolation from the algebra).

## Licence

`CC-BY-4.0`. Stated by CalCOFI at https://calcofi.org/data/data-usage-policy/ (read 2026-10-08): CalCOFI data "are
licensed under the Creative Commons Attribution 4.0 International License"; users must state the data were obtained from
CalCOFI (calcofi.org). The policy covers CalCOFI data in general and does not mention the station-position tables
specifically; they are treated as covered. Attribution: "California Cooperative Oceanic Fisheries Investigations
(CalCOFI), calcofi.org. CC BY 4.0. Processed by Ocean Metrics." Tier 1.

## Rebuild and check

    cd ~/Github/oceanmetrics/places
    uv run build.py build --slug calcofi_stations --slug calcofi_lines
    uv run build.py check --slug calcofi_stations --slug calcofi_lines
    uv run --group dev pytest -q tests/test_calcofi.py          # add -m network for the live-table check

PMTiles: layer = slug, `--attribution`, fixed `-z10` (`tile_maxzoom: 10`; `-zg` guessed z0/z1, too coarse for sparse
points and lines). Default styles: `circle` layer for stations, `line` layer for lines (`styles/default.json`).

## Publish (not done here)

`rashid check`, then `portolan add` and sync to `s3://oceanmetrics.io-public/gazetteer/` for the two slugs only (see
AGENTS.md). Version 1.0.0 each. Refresh: the source files change rarely; `detect` compares the CSV HTTP validators.

## Shared-pipeline changes made (all additive, defaults unchanged)

- `config.py`: place types `station`, `transect`; source kind `calcofi_positions`; collection-level `geometry_type`
  (default `MultiPolygon`; also `Point`, `LineString`) validated.
- `pipeline.py`: dispatch for the new kind; passes `geometry_type`, `tile_maxzoom`, `column_docs` through.
- `table.py`: `bool` column type; non-polygon geometry cleaning (`calcofi.clean_simple_geometry`); `geom_type` and the
  GeoParquet `geometry_types` follow the collection; source-reported `dropped` notes join the build's dropped list.
- `validate.py`: expected geometry type per collection. `stac.py`: circle/line default styles, `geoparquet:geometry_type`,
  per-collection column descriptions (`column_docs`). `tiles.py`: optional fixed max zoom.
- `tests/test_config.py`: the six-collection check is now a subset check so other collections can be added.
- New: `gazetteer/calcofi.py`, `sources/calcofi/{stations,lines}.yml`, `tests/test_calcofi.py`.
