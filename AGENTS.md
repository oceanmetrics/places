# AGENTS.md: working rules for the places gazetteer

Rules for anyone (human or agent) changing this repo. Each rule is guarded by a test or a check where it can be.

## Licence tiers (decide before adding a source)

- **Tier 1: public domain or CC-BY.** Redistributed (GeoParquet + PMTiles) with attribution.
- **Tier 2: restricted or unclear terms.** Redistributed only after written confirmation from the licensor;
  keep the confirmation (email/link) in the source's `sources/<authority>/<layer>.yml` notes.
- **Tier 3: no redistribution right.** Crosswalk ids only (`index/crosswalk.parquet`); never geometry in the bucket.

## Data rules

- **No feature without licence and attribution.** `license` (SPDX) and `attribution` are required in every source
  config and are written to every row; `gazetteer/config.py` rejects a config without them.
- **Every PMTiles carries attribution metadata** (`name`, `description`, `attribution`), written by tippecanoe
  `--attribution`; `check_pmtiles` fails a file without it.
- **Antimeridian:** geometries are stored split at +/-180 (GeoParquet 1.1, EPSG:4326, WKB, `bbox` struct).
- **`place_id = <authority>:<source_id>`**; ids never change, geometry versions do. Duplicates within a layer are
  suffixed deterministically and reported.
- **One collection per source layer** (the unit of licence, cadence and style). Collection `version` is semver and
  is bumped on every rebuild that changes content.
- **Per-source provenance** in `provenance.json` and the STAC collection: `source_url`, `source_item_id`,
  `data_last_edit`, `retrieved`, `record_count`, `checksum`.

## Publishing

- `rashid check` must pass before every publish (the sync workflow runs it; run it locally before any manual push).
- Publish with `portolan add` then sync to `s3://oceanmetrics.io-public/gazetteer/` (served as
  https://storage.oceanmetrics.io/gazetteer/). Never `--delete` outside the collection being published.
- Built artifacts (`*.parquet`, `*.pmtiles`, `*.thumb.jpg`, `collection.json`) are git-ignored.

## Code conventions

- Python with uv; DuckDB SQL and tippecanoe for heavy lifting; R only where it already works (`R/`).
- 2-space indent, snake_case, lowercase comments, section headings suffixed by `----` in long files.
- Logic lives in tested functions in `gazetteer/`; `build.py` and the workflow only call them.
- **One pytest per source rule**, with a small synthetic fixture asserting the exact expected output. A bug fix adds
  a named regression assertion. `uv run --group dev pytest -q` must be green before committing; a red test is a
  hard stop. Tests needing staged artifacts or the network skip with a reason (`network`, `tippecanoe` markers).
