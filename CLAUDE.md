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
| `client/` | TypeScript, hyparquet, pmtiles | `@oceanmetrics/places` JS client: reads `layers.json`, index, parquet and PMTiles straight from storage |
| `web/` | Svelte 5 + Vite + MapLibre | the site (live at https://oceanmetrics.io/places/ via GitHub Pages); uses `../client` from its TS source |
| `worker/` | Cloudflare Worker | future R2 front for storage (keys, Range/CORS, metering); code and tests only, not deployed |

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
uv run build.py detect                                    # upstream change vs. published provenance.json
uv run build.py next-version --slug ...                   # published current_version, patch bumped
uv run scripts/build_index.py                             # index/places_index.parquet + crosswalk.parquet
uv run scripts/build_layers_json.py                       # the client manifest layers.json
uv run scripts/validate_contribution.py contrib/OM-<ulid> # check a community contribution
```

Tests in `tests/test_staged.py` and similar run only when `catalog/staging/<slug>/` exists; otherwise they skip.

JS (each of `client/`, `web/`, `worker/` is its own npm package; run `npm install` inside it first):

```sh
cd client && npm test && npm run typecheck
cd web && npm run dev      # http://localhost:5180; also: npm test, npm run check (svelte-check), npm run build
cd worker && npm test && npm run typecheck
```

If vitest cannot create its temp dir in a sandbox, set `TMPDIR` to a writable directory. The web app reads data from
`https://storage.oceanmetrics.io/gazetteer/` by default; override with `VITE_PLACES_BASE` at build time or `?base=` at
run time (e.g. serve `client/test/fixtures/` locally with CORS + Range).

## Build pipeline architecture

`gazetteer/cli.py` loads every `sources/<authority>/<layer>.yml` (`config.load_all`); the config's `slug`, not its
filename, names the collection. `pipeline.build_layer` then runs per slug:

1. **fetch** (`pipeline.fetch_source` dispatches on `sources[].kind`): `arcgis` and `shapefile_zip` in `fetch.py`,
   `wfs` in `fetch_wfs.py` (Marine Regions), `calcofi_positions` in `calcofi.py`. Each returns a `SourceResult`
   (features, fields, url, `data_last_edit`, checksum) and raw pages are cached under `cache/<slug>/`.
2. **normalise** (`table.build_rows` -> `to_table`): renders `name` / `source_id` templates (`fmt.render`), builds
   `place_id`s (`ids.py`: rule `lease` or a `template`, duplicate suffixing, pattern check), resolves `status` from
   the config plus an optional CSV overlay (`status.py`, e.g. `sources/boem/wind_lease_status.csv`), cleans geometry
   by type (`geom.py` polygons with antimeridian split, `lines.py`, `mixed.py`, `calcofi.clean_simple_geometry`).
   Every row gets the `COMMON` columns in `table.py`; native attributes follow.
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
must not be published yet (e.g. `mr_*` pending VLIZ's reply). `.github/workflows/sync.yml` is the weekly detect ->
rebuild -> publish job on the self-hosted `msens` runner; `pages.yml` deploys `web/` on pushes touching `web/` or
`client/`; `validate-contribution.yml` checks PRs adding `contrib/OM-<ulid>/` (see CONTRIBUTING.md).

`client/` has its own `CHANGELOG.md` and version in `client/package.json`; add an entry with any user-facing change.
The client's test fixtures (`client/test/fixtures/`, made by `make_fixtures.sh`) must mirror the schema that
`scripts/build_index.py` and `scripts/build_layers_json.py` publish; change them together.
