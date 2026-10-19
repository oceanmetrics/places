# AGENTS.md: working rules for the places gazetteer

Rules for anyone (human or agent) changing this repo. Each rule is guarded by a test or a check where it can be.

## Licence tiers (decide before adding a source)

- **Tier 1: public domain or CC-BY.** Redistributed (GeoParquet + PMTiles) with attribution.
- **Tier 2: restricted or unclear terms.** Redistributed only after written confirmation from the licensor;
  keep the confirmation (email/link) in the source's `sources/<authority>/<layer>.yml` notes.
- **Tier 3: no redistribution right.** Crosswalk ids only (`index/crosswalk.parquet`); never geometry in the bucket.
- **Reference collections: the publisher asks us not to republish (even under CC-BY).** A `reference:` block in the
  YAML: public metadata, index rows and a layers.json `kind: "raster"` row on the publisher's own tiles; one boundary
  at a time from its `feature_url`; the parquet/PMTiles stay on the build machine (`~/data/oceanmetrics/places-internal`)
  for derived products. `publish_collections.sh` refuses to upload their data files (e.g. `mr_*`, VLIZ 2026-10-16).
- **Link back to the source.** `source_page`/`source_home` and `source_title` give every layer a `source_link`; a
  `place_url` template gives every index row its own page at the source (`url`). Apps show both next to the credit.

## Data rules

- **No feature without licence and attribution.** `license` (SPDX) and `attribution` are required in every source
  config and are written to every row; `gazetteer/config.py` rejects a config without them.
- **Every PMTiles carries attribution metadata** (`name`, `description`, `attribution`), written by tippecanoe
  `--attribution`; `check_pmtiles` fails a file without it.
- **Antimeridian:** geometries are stored split at +/-180 (GeoParquet 1.1, EPSG:4326, WKB, `bbox` struct).
  Published bboxes follow RFC 7946: the parquet `geo` bbox and the STAC extent of a layer with places cut at +/-180
  cross it (west > east, e.g. `noaa_sanctuaries` `[177.8, -15.4, -70.0, 48.5]`), never `-180..180` round the globe
  (`gazetteer/bbox.py`, checked by `check_parquet`; `publish_collections.sh` re-joins the extent after `portolan add`).
  The per-row `bbox` struct stays plain min/max for `xmin <= x <= xmax` filters; the index bbox and layers.json
  `bbox` are unwrapped instead (east beyond 180) so `fitBounds` takes them as is.
- **`place_id = <authority>:<source_id>`**; ids never change, geometry versions do. Duplicates within a layer are
  suffixed deterministically and reported.
- **One collection per source layer** (the unit of licence, cadence and style). Collection `version` is semver and
  is bumped on every rebuild that changes content.
- **Per-source provenance** in `provenance.json` and the STAC collection: `source_url`, `source_item_id`,
  `data_last_edit`, `retrieved`, `record_count`, `checksum`.

- **H3 membership follows its parquet.** `<slug>/h3/` is built from the PUBLISHED `places.parquet`
  (`scripts/build_h3_membership.py`) and `layers.json` advertises `h3` only while `membership.json`'s `places_sha256`
  is the row's `parquet_sha256`. Republishing a polygon collection means rebuilding its membership (or accepting
  `h3: null` until it is). Shares are ≥ 0.01 of the cell or the cell holds ≥ 1% of the place (`MIN_SHARE`).

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
