# places: the oceanmetrics marine gazetteer

One [STAC](https://stacspec.org) catalog of place layers (sanctuaries, MPAs, EEZs, leases, planning areas, AOAs,
stations ...). Each layer is a collection with a **GeoParquet** file and a **PMTiles** archive, and every feature
carries its own **licence** and **attribution**. Places are identified by `place_id = <authority>:<source_id>`
(for example `BOEM:OCS-P 0561`), ids never change; geometry versions do.

- Catalog: https://storage.oceanmetrics.io/gazetteer/ (S3 bucket `oceanmetrics.io-public`, prefix `gazetteer/`)
- Each collection: `places.parquet` (GeoParquet 1.1, WKB, `bbox` struct, EPSG:4326, split at +/-180),
  `places.pmtiles` (layer name = collection slug, attribution in the metadata), `style.json`, `README.md`,
  `provenance.json`
- Rules for contributors and agents: [AGENTS.md](AGENTS.md)

Query a collection with DuckDB (bbox pushdown):

```sql
SELECT place_id, name, status
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/boem_wind_leases/places.parquet')
WHERE bbox.xmin < -117 AND bbox.xmax > -125;
```

## Layout

| path | what |
|---|---|
| `sources/<authority>/<layer>.yml` | one config per source layer: endpoint, paging, field map, `place_type`, licence, attribution, cadence, status overlay |
| `gazetteer/` | the Python package: fetch -> normalise -> validate -> GeoParquet -> PMTiles -> STAC (the plan's `build/` stage) |
| `build.py` | CLI entry point: `build`, `detect`, `next-version`, `check` |
| `R/` | R code that still works as is (`build_places.R`: sanctuaries + MarineRegions + ProtectedSeas) |
| `catalog/` | the Portolan STAC tree, built here and published to the bucket; builds stage in `catalog/staging/` |
| `web/` | the website, places.oceanmetrics.io (placeholder) |
| `client/` | the `@oceanmetrics/places` JS package (placeholder) |
| `tests/` | pytest, one fixture per source rule |
| `.github/workflows/sync.yml` | weekly change detection, rebuild and publish |

## Quickstart

Needs [uv](https://docs.astral.sh/uv/) and, for PMTiles, [tippecanoe](https://github.com/felt/tippecanoe) on PATH.

```sh
uv run --group dev pytest -q                 # unit tests (staged-artifact tests skip when nothing is built)
uv run build.py detect                       # which collections changed upstream vs. the published copy
uv run build.py build --slug boem_wind_leases --version 1.0.0
uv run build.py check                        # parquet + PMTiles checks; 'not built' for absent collections
```

## Licence

The code is MIT ([LICENSE](LICENSE)). The data is **not** covered by it: each collection is distributed under its
own licence, recorded in its STAC `license`, in every row's `license` and `attribution` columns and in the PMTiles
metadata. Credit the sources shown there when you use the data.

Status: the plan is in the private notes (`om/plans_todo/2026-10-08_places-gazetteer_plan.md`). This repo was split
out of `oceanmetrics/erddap-places` `catalog/`; until that move completes, `R/build_places.R` still runs from there.
