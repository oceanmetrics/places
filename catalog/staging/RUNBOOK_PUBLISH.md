# RUNBOOK_PUBLISH: master publish plan for the places gazetteer (written 2026-10-08, NOTHING PUBLISHED YET)

Merges the per-agent runbooks: `RUNBOOK_mr.md`, `RUNBOOK_mc15.md`, `RUNBOOK_mpa_gebco.md`, `RUNBOOK_calcofi.md`, plus
the BOEM/NOAA-AOA six (already published at 1.0.0, commit 28eb877 in the erddap-places pipeline) and the proven
`~/Github/oceanmetrics/erddap-places/catalog/publish_places.sh`. Rules: `AGENTS.md` (licence tiers, `rashid check` gate,
never `--delete` outside the collection being published).

Collection set (30 configs in `sources/`): 6 BOEM/AOA (published), 2 CalCOFI, 7 `mr_*`, `mpa_inventory`, `gebco_undersea`,
13 MarineCadastre first-15 layers (the 14th, `noaa_mpa_inventory`, was RETIRED 2026-10-08 in favour of `mpa_inventory`,
`MPAINV:` ids).

## 0. Hold / flag table (decide BEFORE step 3)

| collection(s) | status | why | action |
|---|---|---|---|
| `mr_eez`, `mr_territorial_seas`, `mr_contiguous_zones`, `mr_high_seas`, `mr_ecs`, `mr_goas`, `mr_world_heritage_marine` | HOLD | CC-BY 4.0 is stated, but the disclaimer asks users not to make the products available for download elsewhere; the question to VLIZ (info@marineregions.org) about GeoParquet/PMTiles copies is unanswered (RUNBOOK_mr.md item 5) | publish nothing `mr_*` until VLIZ replies; the index/crosswalk build already tolerates their absence |
| `noaa_esa_critical_habitat` (NMFS) | HOLD | item `accessInformation` is EMPTY; attribution falls back to "NOAA Fisheries ..." (item owner), unverified; licenceInfo only says "not the official legal definitions" | confirm attribution wording with NMFS (or the item's InPort page) first; 129 MB parquet |
| `mpa_inventory` | FLAG | licence text is a disclaimer ("not for navigation", "not legal documents"), public-domain statement is on InPort item 69506 not on the layer item; boundaries come from state/other managers | OK to publish after one human read of the README "licence" block; keep the not-for-navigation line in the description |
| `noaa_hapc` | FLAG | item licenceInfo is a no-warranty disclaimer only, no explicit public-domain statement (federal work, 17 U.S.C. 105 assumed) | same: human confirms, then publish |
| `noaa_maritime_limits` | FLAG (verified) | item says "NOT FOR LEGAL USE ... not the official depiction"; the notice IS in the collection `description` (config, staged `collection.json`, and `tests/test_marinecadastre15.py::test_maritime_limits_description_carries_the_not_for_legal_use_notice`) | surface it in the UI next to the data; no fix needed |
| `fws_critical_habitat_final` | EXCLUDE from first publish (recommended) | 244.5 MB parquet / 75 MB PMTiles for 803 features of very detailed geometry, mostly terrestrial species; breaks the "range-read on a phone" budget. Do NOT simplify as part of publishing | either leave out of the first publish, or simplify the geometry in the source config (a separate, tested change, new minor version) then rebuild; same note for `fws_critical_habitat_proposed` (81 MB for 70 features) |
| everything else (`calcofi_*`, `gebco_undersea`, `noaa_sanctuaries`, `noaa_nerrs`, `noaa_marine_monuments`, `noaa_state_*`, `noaa_vessel_routing_measures`, `noaa_submarine_cables`, `usace_danger_zones`, `fws_critical_habitat_proposed`) | READY | Tier 1; licence reviewed in the per-agent runbooks | publish in step 3 |

`gebco_undersea`: one expected `rashid` warning PTL-DAT-005 (PMTiles bbox is Web-Mercator clipped at 85.05 N, data reaches 89.6 N); not a blocker.

## 1. Preconditions (laptop, no network writes)

    cd ~/Github/oceanmetrics/places
    git status                                  # clean
    uv run --group dev pytest -q                # green (staged-artifact tests run only where catalog/staging/<slug>/ exists)
    uv run build.py check                       # parquet + PMTiles checks per staged slug
    uv run scripts/build_index.py               # regenerate index/ (places_index, crosswalk) from staging + published
    uv run scripts/build_layers_json.py         # regenerate catalog/staging/layers.json (client manifest)
    aws sts get-caller-identity                 # right account; portolan 0.8.0, rashid on PATH

Edit each collection's README "Changes" before step 3 (portolan checksums the README).

## 2. Build the catalog tree (known portolan 0.8.0 quirks, guarded)

Work in a scratch copy of the published catalog, never edit the bucket tree by hand. Pull the current published tree first
(read-only): `aws s3 sync s3://oceanmetrics.io-public/gazetteer/ catalog/pub/ --exclude '*.parquet' --exclude '*.pmtiles'`
(metadata only: root `catalog.json`, `versions.json`, the existing collections' `collection.json`).

Quirks of `portolan add` 0.8.0 (see `erddap-places/catalog/publish_places.sh` and RUNBOOK_mr.md), and the guard for each:

1. `add` rewrites OTHER collections' `collection.json` and the root `catalog.json`: snapshot them before, restore after.
2. `add` auto-creates a patch version in the collection's `versions.json`, so a later `version bump` reports "no changes":
   snapshot the collection ledger and restore it, then `portolan version bump <slug> 1.0.0 -m "<note>" -y`.
3. `bump` leaves the root `versions.json` summary at the old version: rewrite that collection's entry (current_version,
   updated, asset_count, total_size_bytes) from the ledger (the python block in publish_places.sh).
4. `add` leaves stale `file:size` / `file:checksum` on some assets and re-extracts the PMTiles role as `data`: recompute size and
   `1220`+sha256 from the bytes for every asset, and set the PMTiles asset role back to `["visual"]`.
5. `portolan init` needs `--license CC-PDDC` the first time only; pass `--force --force-thumbnails` on `add` for a new collection.

One slug at a time (a helper modelled on publish_places.sh; `$slug` from the READY list in step 0):

    cd catalog/pub
    snap=$(mktemp -d)
    others=$(find . -name collection.json -not -path "./$slug/*" -not -path '*/items/*')
    for f in $others catalog.json; do mkdir -p "$snap/$(dirname $f)"; cp $f "$snap/$f"; done
    mkdir -p $slug && cp -R ../staging/$slug/. $slug/
    portolan add $slug/ --force --force-thumbnails
    for f in $others catalog.json; do cp "$snap/$f" $f; done            # quirk 1
    rm -f $slug/versions.json                                            # quirk 2: fresh ledger, then bump to 1.0.0
    portolan version bump $slug 1.0.0 -m "initial publish" -y
    # quirks 3 and 4: python blocks from erddap-places/catalog/publish_places.sh (root versions.json entry; asset sizes/checksums;
    # PMTiles role = visual)

## 3. Gate, then upload (only after the gate is green for every slug in the batch)

    cd ~/Github/oceanmetrics/places
    rashid check catalog/pub --data-scope local        # HARD STOP on any error; PTL-PRO-002 infos and the GEBCO PTL-DAT-005 warning are expected
    # per slug, never --delete:
    aws s3 sync catalog/pub/$slug/ s3://oceanmetrics.io-public/gazetteer/$slug/ --exclude '.portolan/*'
    # (or: portolan push s3://oceanmetrics.io-public/gazetteer --collection $slug --catalog catalog/pub)
    # root summary files LAST among the collection data, one file each:
    aws s3 cp catalog/pub/versions.json s3://oceanmetrics.io-public/gazetteer/versions.json --content-type application/json
    aws s3 cp catalog/pub/catalog.json  s3://oceanmetrics.io-public/gazetteer/catalog.json  --content-type application/json

Suggested order (small and safe first, so a problem shows up cheap): `calcofi_stations`, `calcofi_lines`,
`noaa_sanctuaries`, `noaa_nerrs`, `noaa_marine_monuments`, `noaa_state_lateral_boundaries`, `noaa_maritime_limits`,
`usace_danger_zones`, `noaa_submarine_cables`, `noaa_vessel_routing_measures`, `noaa_state_submerged_lands`, `gebco_undersea`,
`fws_critical_habitat_proposed`, then (after the flags in step 0 are cleared) `mpa_inventory`, `noaa_hapc`; later
`noaa_esa_critical_habitat`, `fws_critical_habitat_final` (simplified), and `mr_*` (after VLIZ).

## 4. index/ and layers.json LAST

The index and the client manifest describe what is published, so they go up after the collections they list:

    # index only what is published: a staging dir of symlinks to the published slugs (held slugs left out), plus the published
    # catalog read remotely (default). --no-local would ignore staging entirely; --staging points at the publish set.
    mkdir -p /tmp/pub_set && for s in <published slugs>; do ln -sfn "$PWD/catalog/staging/$s" /tmp/pub_set/$s; done
    uv run scripts/build_index.py  --staging /tmp/pub_set --out catalog/staging/index
    uv run scripts/build_layers_json.py --staging /tmp/pub_set --out catalog/staging/layers.json
    rashid check catalog/staging/index --data-scope local
    aws s3 sync catalog/staging/index/ s3://oceanmetrics.io-public/gazetteer/index/ --exclude '.portolan/*'     # no --delete
    aws s3 cp catalog/staging/layers.json s3://oceanmetrics.io-public/gazetteer/layers.json --content-type application/json

The held slugs (`mr_*`, `noaa_esa_critical_habitat`, excluded FWS) must not appear in the index or `layers.json` of this publish; the
symlink set above guarantees it for local staging (check the table printed by `build_index.py` for the expected slugs and totals).
After the held slugs are later published, rerun this step with them included.

## 5. After publishing

- Smoke test through the Worker: `https://storage.oceanmetrics.io/gazetteer/<slug>/collection.json`, a Range read of `places.parquet`, a PMTiles tile.
- Log the milestone (notes repo), tag the repo (`gazetteer-1.0.0`), delete `cache/` raw pages on the mini (FWS final alone is ~800 MB).
- Refresh later with `uv run build.py detect` (weekly `sync.yml`); each content change bumps the collection patch version.

## Follow-ups (not done)

- `gazetteer/lines.py` and `gazetteer/mixed.py` partially duplicate the geometry-cleaning / antimeridian logic for non-polygon types; fold into one module later.
- `scripts/build_index.py` still maps the legacy `MPA:` prefix to `mpainv_site_id` (harmless; remove with the test fixture that uses it).
- `build_index.py` warns that 4 place_ids occur in two collections: `BOEM:OCS-P 0562/0563/0564` (in both `boem_pacific_og_leases` and
  `boem_wind_leases`: a lease number reused across the Pacific O&G and wind layers) and `MRGID:8439` (`mr_eez` and the published `places`
  collection, expected: the same Marine Regions record). Decide whether the BOEM overlap needs a distinct prefix before the index is published.
- `scripts/build_layers_json.py` crashed on mixed-geometry collections (`gebco_undersea`, list-valued `geoparquet:geometry_type`); fixed in this
  reconciliation (row `geom_type` is `Mixed`, paint holds fill+line+circle) with a regression test.
