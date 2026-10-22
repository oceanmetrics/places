# places: the oceanmetrics marine gazetteer

One [STAC](https://stacspec.org) catalog of place layers (sanctuaries, MPAs, EEZs, leases, planning areas, AOAs,
stations ...). Each layer is a collection with a **GeoParquet** file and a **PMTiles** archive, and every feature
carries its own **licence** and **attribution**. Places are identified by `place_id = <authority>:<source_id>`
(for example `BOEM:OCS-P 0561`), ids never change; geometry versions do.

- Catalog: https://storage.oceanmetrics.io/gazetteer/ (S3 bucket `oceanmetrics.io-public`, prefix `gazetteer/`)
- Each collection: `places.parquet` (GeoParquet 1.1, WKB, `bbox` struct, EPSG:4326, split at +/-180; the file
  bbox and STAC extent cross +/-180 with west > east, per RFC 7946, when a place is cut there),
  `places.pmtiles` (layer name = collection slug, attribution in the metadata), `style.json`, `README.md`,
  `provenance.json`
- Rules for contributors and agents: [AGENTS.md](AGENTS.md)

Query a collection with DuckDB (bbox pushdown):

```sql
SELECT place_id, name, status
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/boem_wind_leases/places.parquet')
WHERE bbox.xmin < -117 AND bbox.xmax > -125;
```

## H3 membership (place × hexagon)

Every polygon collection also publishes which [H3](https://h3geo.org) cells of res 1–7 each place covers, and the
share of each cell's area inside the place, so an app can filter or summarise hexagon data by place with a join on
`h3` and no geometry (obis-hex's place filter; the obisindicators per-place layer):

| file under `<slug>/` | what |
|---|---|
| `h3/membership.json` | res list, `parent_res` (`{"6": 2, "7": 3}`), every file with rows and bytes, `min_share`, and what it was built from (`places_sha256`, `collection_version`) |
| `h3/res=<1..5>/membership.parquet` | `place_id VARCHAR, h3 VARCHAR (hex), share FLOAT`, sorted by place_id, h3 |
| `h3/res=<6\|7>/p=<parent>/membership.parquet` | the same, split by the res-2 / res-3 parent (the obis-h3 release splits res 6/7 by the same parents) |
| `h3/parents.parquet` | `place_id, res, parent`: which split files hold each place |

`share` is the fraction of the cell's area inside the place, from the intersection in the cylindrical equal-area plane
`(lon, sin lat)`; a cell is kept when share ≥ 0.01 or when it holds ≥ 1% of the place's own area (so a place smaller than
1% of a coarse cell keeps the cells it touches). Σ share × cell area equals the place's area to within the dropped slivers
(< 1%). Built by `gazetteer/membership.py` (refining down the hierarchy, testing only cells near an edge) from the
PUBLISHED `places.parquet`:

```sh
uv run scripts/build_h3_membership.py [--slug noaa_sanctuaries ...] --layers-out catalog/h3/layers.json [--upload]
```

`layers.json` advertises a row's `h3` (the URL of its `membership.json`) only while `places_sha256` equals the row's
`parquet_sha256`: a collection republished without rebuilding its membership drops back to `h3: null`, never to stale cells.
The membership is a derived sidecar, not a STAC asset, so building it changes no collection version.
`--missing` builds every polygon vector layer whose membership is absent from the bucket or stale (the sync passes it every
week); the contract is that each such layer has an `h3` URL.

### Access

`layers.json` rows end with `h3` and `access`. `access` is `public` or `unlisted`, from the optional `access:` key of the
layer's `sources/<authority>/<layer>.yml` (default `public`) through the collection's `gazetteer:access`. An unlisted layer
stays in `layers.json` so a link to it works, but it is not in the place index (no search) and
`@oceanmetrics/places` `layers()` omits it unless called with `{ includeUnlisted: true }`.

```sql
-- the res-5 cells of Monterey Bay NMS, with the share of each inside
SELECT h3, share
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/noaa_sanctuaries/h3/res=5/membership.parquet')
WHERE place_id = 'NMS:MBNMS';
```

## Layout

| path | what |
|---|---|
| `sources/<authority>/<layer>.yml` | one config per source layer: endpoint, paging, field map, `place_type`, licence, attribution, cadence, status (event log, upstream code, layer status) |
| `gazetteer/` | the Python package: fetch -> normalise -> validate -> GeoParquet -> PMTiles -> STAC (the plan's `build/` stage) |
| `build.py` | CLI entry point: `build`, `restac`, `repack`, `detect`, `next-version`, `check` |
| `R/` | R code that still works as is (`build_places.R`: sanctuaries + MarineRegions + ProtectedSeas) |
| `catalog/` | the Portolan STAC tree, built here and published to the bucket; builds stage in `catalog/staging/`; H3 membership builds in `catalog/h3/` |
| `web/` | the website, places.oceanmetrics.io (placeholder) |
| `@oceanmetrics/places` (JS client) | not in this repo: lives in https://github.com/oceanmetrics/platform `packages/places` since 2026-10-22; `web/` links it locally until the npm publish on Day 5 (2026-10-26) |
| `tests/` | pytest, one fixture per source rule |
| `.github/workflows/sync.yml` | weekly change detection, rebuild and publish |

## Quickstart

Needs [uv](https://docs.astral.sh/uv/) and, for PMTiles, [tippecanoe](https://github.com/felt/tippecanoe) on PATH.

```sh
uv run --group dev pytest -q                 # unit tests (staged-artifact tests skip when nothing is built)
uv run build.py detect                       # which collections changed upstream vs. the published copy
uv run build.py build --slug boem_wind_leases --version 1.0.0
uv run build.py check                        # parquet + PMTiles checks; 'not built' for absent collections
uv run build.py repack --slug mr_eez          # rewrite the staged parquet + PMTiles with the current writer (small row groups) and tile_args; no fetch
```

## Licence

The code is MIT ([LICENSE](LICENSE)). The data is **not** covered by it: each collection is distributed under its
own licence, recorded in its STAC `license`, in every row's `license` and `attribution` columns and in the PMTiles
metadata. Credit the sources shown there when you use the data.

Status: the plan is in the private notes (`om/plans_todo/2026-10-08_places-gazetteer_plan.md`). This repo was split
out of `oceanmetrics/erddap-places` `catalog/`; until that move completes, `R/build_places.R` still runs from there.
