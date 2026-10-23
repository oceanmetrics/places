# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

The working rules (licence tiers, data rules, publishing gate, code conventions, one pytest per source rule) are in
AGENTS.md and apply here in full:

@AGENTS.md

## What this repo is

The Ocean Metrics marine gazetteer: one STAC catalog of place layers (sanctuaries, MPAs, EEZs, leases, AOAs,
stations ...) published to `s3://oceanmetrics.io-public/gazetteer/` (https://storage.oceanmetrics.io/gazetteer/).
Each collection = `places.parquet` (GeoParquet 1.1) + `places.pmtiles` + `collection.json`, `provenance.json`,
`README.md`, `AGENTS.md`, `styles/default.json`. Four independent parts live side by side:

| part | stack | role |
|---|---|---|
| `build.py` + `gazetteer/` + `sources/` | Python (uv), tippecanoe | build pipeline: YAML config -> staged collection |
| `scripts/` | Python, bash | catalog-wide artifacts (index, `layers.json`, browse pages), contribution validation, publish |
| `web/` | Svelte 5 + Vite + MapLibre | the site (live at https://oceanmetrics.io/places/ via GitHub Pages); uses the `@oceanmetrics/places` client from npm (see below) |
| `worker/` | Cloudflare Worker | the R2 front for storage (keys, Range/CORS, metering); deployed to the workers.dev preview https://om-gazetteer.ben-f07.workers.dev since 2026-10-22, the production route waits on the DNS cutover |

`R/build_places.R` is a copy that still runs from `oceanmetrics/erddap-places`; edits here are not picked up yet.

## Commands

Python (needs `uv`; PMTiles builds need `tippecanoe` on PATH):

```sh
uv run --group dev pytest -q                              # all tests
uv run --group dev pytest -q tests/test_ids.py            # one file
uv run --group dev pytest -q tests/test_ids.py -k lease   # one test by name
uv run --group dev pytest -q -m "not network"             # skip live-service tests (markers: network, tippecanoe)
uv run build.py build --slug boem_wind_leases [--version 1.0.1]   # -> catalog/staging/<slug>/
uv run build.py check [--slug ...]                        # parquet + PMTiles checks on staged builds
uv run build.py repack --slug ...                        # rewrite staged parquet + PMTiles with the current writer and tile_args, no fetch
uv run build.py detect                                    # upstream change vs. published provenance.json
uv run build.py next-version --slug ...                   # published current_version, patch bumped
uv run scripts/build_index.py                             # index/places_index.parquet + crosswalk.parquet
uv run scripts/build_layers_json.py                       # the client manifest layers.json
uv run scripts/validate_contribution.py contrib/OM-<ulid> # check a community contribution
```

Tests in `tests/test_staged.py` and similar run only when `catalog/staging/<slug>/` exists; otherwise they skip.

JS (`web/` and `worker/` are each their own npm package; run `npm install` inside it first). The `@oceanmetrics/places` client
(reads `layers.json`, index, parquet and PMTiles straight from storage) lives in https://github.com/oceanmetrics/platform
`packages/places` since 2026-10-22 and is on npm: `web/` depends on
`@oceanmetrics/places` from the registry and consumes the client's built `dist/` like any other consumer. A client change is
made in oceanmetrics/platform `packages/places` and released there (version, `CHANGELOG.md`, npm publish); then bump the range
in `web/package.json` here. `@oceanmetrics/catalog` 0.3.0 holds the indicator cards (`@oceanmetrics/catalog/indicators`, shared
with the indicators viewer; `web/src/lib/indicators.ts` only wires it) and brings the JSON schemas that
`tests/test_layers_schema.py` validates against. Until 0.3.0 is on npm it is a `file:../../platform/packages/catalog` link to a
sibling checkout of oceanmetrics/platform (run `npm run build` there first; `pages.yml` checks out both); then it becomes
`^0.3.0` and the sibling checkout goes again (TODO in `web/src/lib/indicators.ts`).

```sh
# the client is tested in its own repo (oceanmetrics/platform: npm test && npm run typecheck)
cd web && npm run dev      # http://localhost:5180; also: npm test, npm run check (svelte-check), npm run build
cd worker && npm test && npm run typecheck
```

If vitest cannot create its temp dir in a sandbox, set `TMPDIR` to a writable directory. The web app reads data from
`https://storage.oceanmetrics.io/gazetteer/` by default; override with `VITE_PLACES_BASE` at build time or `?base=` at
run time (e.g. serve the client repo's `packages/places/test/fixtures/` locally with CORS + Range).

## Build pipeline architecture

`gazetteer/cli.py` loads every `sources/<authority>/<layer>.yml` (`config.load_all`); the config's `slug`, not its
filename, names the collection. `pipeline.build_layer` then runs per slug:

1. **fetch** (`pipeline.fetch_source` dispatches on `sources[].kind`): `arcgis` and `shapefile_zip` in `fetch.py`,
   `wfs` in `fetch_wfs.py` (Marine Regions, and any GeoServer WFS without an `mr` block: FAO's `fao_major_areas` takes
   `cql_filter`, `sort_by` and `released`), `calcofi_positions` in `calcofi.py`, `derive` in `derive.py` (a collection
   computed from other collections' built parquet, read from `PLACES_INTERNAL` then `PLACES_STAGING`; `op: intersect` of two
   inputs, slivers under `min_area_km2` dropped and listed; `fao_high_seas`, see AGENTS.md `display`). Each returns a
   `SourceResult` (features, fields, url, `data_last_edit`, checksum) and raw pages are cached under `cache/<slug>/`.
2. **normalise** (`table.build_rows` -> `to_table`): renders `name` / `source_id` templates (`fmt.render`), builds
   `place_id`s (`ids.py`: rule `lease` or a `template`, duplicate suffixing, pattern check), resolves `status` from
   the config plus an optional dated event log (`status.py`, e.g. `sources/boem/wind_lease_status_events.csv`: the
   latest event is the current status, all events go to `status_history`; `status.upstream` copies the source's own
   status code into `status_upstream`), cleans geometry
   by type (`geom.py` polygons with antimeridian split, `lines.py`, `mixed.py`, `calcofi.clean_simple_geometry`).
   Every row gets the `COMMON` columns in `table.py`; native attributes follow. A source's `exclude` drops features by
   native value at fetch (e.g. RENACV leases in `boem_pacific_og_leases`); `expected_count` counts after it.
   A layer-level status (`layer_status` / `layer_status_history` in the YAML) goes to collection.json
   (`gazetteer:status`) and layers.json (`status`, `status_history`, `status_label`); titles stay plain.
3. **write**: `table.write_geoparquet` (WKB, `bbox` struct, provenance in metadata), `tiles.build_pmtiles`
   (tippecanoe with `--attribution`), then `stac.py` writes the style, README, per-collection AGENTS.md and
   `collection.json`; `provenance_record` writes `provenance.json`.
4. **validate**: `validate.check_parquet` + `check_pmtiles`; any problem raises and the build fails.

Adding a source = a new YAML (required keys in `config.REQUIRED`; `place_type` and `kind` must be in the sets in
`config.py`, extend them there if needed) plus a pytest with a synthetic `SourceResult` fixture (see
`tests/conftest.py` `lease_cfg` / `lease_result`).

Change detection (`pipeline.detect`) compares each source's change token with the published `provenance.json`: ArcGIS
`data_last_edit` + record count, else a payload checksum; zips use HTTP validators; WFS uses layer title + count.

## Publishing

Staged builds in `catalog/staging/<slug>/` are integrated into `catalog/pub/` (a pulled copy of the published metadata
tree, git-ignored) and uploaded by `scripts/publish_collections.sh [--republish --version V] <slug>`, which guards known
`portolan add` 0.8.0 quirks (it rewrites other collections' JSON, auto-bumps ledgers, leaves stale checksums) and runs
the `rashid check` gate. Read `catalog/staging/RUNBOOK_PUBLISH.md` first: it has the hold/flag table of collections that
must not be published yet (e.g. `noaa_esa_critical_habitat`) and the reference collections (`mr_*`, metadata only). `.github/workflows/sync.yml` is the weekly detect ->
rebuild -> publish (through `publish_collections.sh --republish`) -> H3 / index / layers.json job on the self-hosted
`macmini` runner (Mondays 07:43 UTC; this repo is the only publisher of the place collections since 2026-10-16, when the
BOEM / NOAA AOA ones moved here from erddap-places); it reads the published catalog from the S3 origin, not the CDN; `pages.yml` deploys `web/` on pushes touching `web/` (npm ci, check, test, build); `validate-contribution.yml` checks PRs adding `contrib/OM-<ulid>/` (see CONTRIBUTING.md).

The client's own `CHANGELOG.md` and version are in oceanmetrics/platform `packages/places` (moved there 2026-10-22, on npm);
add an entry there with any user-facing change. The client's test fixtures (oceanmetrics/platform
`packages/places/test/fixtures/`, made by `make_fixtures.sh`) must mirror the schema that
`scripts/build_index.py` and `scripts/build_layers_json.py` publish; change them together (two repos, two commits).
