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
| `mr_eez`, `mr_territorial_seas`, `mr_contiguous_zones`, `mr_high_seas`, `mr_ecs`, `mr_goas`, `mr_world_heritage_marine` | PUBLISHED REFERENCE 1.0.0 (metadata only, 2026-10-19) | VLIZ (Bart Vanhoorne, 2026-10-16) asked us not to republish the products as-is, then agreed ("All fine", 22:49) to map display from their GeoWebCache tiles, single-feature WFS on demand, a public index and public derived tables | `publish_collections.sh` publishes collection.json / README / AGENTS / provenance / style and a ledger (`gazetteer/ledger.py`), never `places.parquet` / `places.pmtiles` (refused before upload); the data go to `~/data/oceanmetrics/places-internal/<slug>/` on the publishing machine, which `build_index.py` reads. Publish them FROM THE MAC MINI (or rsync that folder to it): the weekly sync's index refresh runs there. 2026-10-19: first published from the laptop, internal store rsynced to the mini |
| `fao_major_areas` | BUILT TO STAGING 2026-10-20, NOT PUBLISHED | Tier 1: CC BY 4.0 + FAO Statistical Database Terms of Use, from the FAO GeoNetwork record (edition 2026.1.0); the CWP codelist page says CC BY-NC-SA 4.0 but holds no geometry (both in the YAML notes). 19 MAJOR areas of `fifao:FAO_AREAS_ERASE`, 14.7 MB parquet / 4.2 MB PMTiles | publish with `publish_collections.sh fao_major_areas` after Ben's OK; the mandatory FAO citation is the attribution line |
| `fao_high_seas` | BUILT ON THE MINI 2026-10-20, INTERNAL ONLY | derived: `mr_high_seas` (VLIZ reference) x `fao_major_areas`; `display: {via: fao_major_areas, id_from: fao_id}`, so `gazetteer:reference` is true and `publish_collections.sh` keeps its parquet in `places-internal/` and refuses to upload it | publish AFTER `fao_major_areas` (its `via`), from the mini (the parquet it needs is in the internal store); the index (`build_index.py --internal`) lists its pieces; web / client do not draw `kind: "derived"` rows yet |
| `protectedseas_navigator` | RETIRED 2026-10-20, files DELETED 2026-10-22 (was PUBLISHED 1.0.0 2026-10-19; unlinked from catalog.json and versions.json, then its 9 objects, 2.1 GB, removed from the bucket on Ben's OK) | CC BY 4.0 (export readme); ProtectedSeas (Alex Driedger, 2026-10-16) welcomed it and sent the Direct Data Export for API users; the Terms of Use carry an indemnity for our distribution (Ben accepts by publishing). Built from the export in `cache/protectedseas_navigator/export/` (raw archive in Ben's Drive, see the YAML) | first published by hand from the laptop 2026-10-19 (30,111 sites; 982 MB parquet, 1.1 GB PMTiles; the export is not on the runner; the weekly detect reports it unchanged there); quarterly refresh by a new export or, later, the Navigator API sync |
| `protectedseas_mpa`, `protectedseas_fisheries`, `protectedseas_jurisdiction`, `protectedseas_vessel`, `protectedseas_human_use`, `protectedseas_other` | PUBLISHED 1.0.0 (2026-10-20, from the laptop) | as `protectedseas_navigator` (one config per group of Navigator `category_name` values, shared keys in `sources/protectedseas/_navigator_base.yml`) | the split of `protectedseas_navigator`: one 30,111-site layer crashed the place page (spatial order, ~1 GB per lookup) and over-filled low-zoom tiles (300k vertices per tile). Id-sorted, `--low-detail=10` on the large-area groups. Published together 2026-10-20 (Ben's OK), then `protectedseas_navigator` was retired (runbook section 6); 13,061 / 6,163 / 545 / 1,313 / 3,130 / 5,899 sites |
| `mr_internal_waters`, `mr_archipelagic_waters`, `mr_eez_iho` | PUBLISHED REFERENCE 1.0.0 (metadata only, 2026-10-20) | VLIZ CC BY 4.0, as the other `mr_*`; IHO Sea Areas v3 is CC BY-NC-SA and is NOT a collection (display through VLIZ's WMS only) | internal store rsynced to the mini 2026-10-20 |
| the seven earlier `mr_*` | PUBLISHED REFERENCE 1.0.1 (metadata only, 2026-10-20) | as above | `restac --version 1.0.1`: `info_url` / `info_id` (click-to-identify) and search keywords; no data refetched |
| `noaa_efh`, `epa_ocean_disposal_sites`, `uscg_anchorages`, `boem_ocs_withdrawals`, `noaa_coral_protection_areas`, `noaa_narw_sma`, `noaa_cetacean_bia`, `boem_marine_minerals_leases`, `noaa_pilot_boarding_areas`, `noaa_lightering_zones`, `navy_operating_areas`, `navy_special_use_airspace` | PUBLISHED 1.0.0 (2026-10-20, Tier 1) | CC-PDDC (US government work; EFH item has no licenceInfo, NOAA work; BIA "public use, citation required", citation in attribution) | MarineCadastre scan `om/plans_todo/2026-10-20_marinecadastre-scan.md`; ids where no id field exists: EFH object id (as `noaa_hapc`), pilot boarding / lightering name slugs, SUA type+name (246 `:part-N`) |
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
`noaa_esa_critical_habitat`, `fws_critical_habitat_final` (simplified); `mr_*` (reference, metadata only) and `protectedseas_navigator` went up 2026-10-19.

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

The held slugs (`noaa_esa_critical_habitat`, excluded FWS) must not appear in the index or `layers.json` of this publish; the
symlink set above guarantees it for local staging (check the table printed by `build_index.py` for the expected slugs and totals).
After the held slugs are later published, rerun this step with them included.

## 5. After publishing

- Smoke test through the Worker: `https://storage.oceanmetrics.io/gazetteer/<slug>/collection.json`, a Range read of `places.parquet`, a PMTiles tile.
- Log the milestone (notes repo), tag the repo (`gazetteer-1.0.0`), delete `cache/` raw pages on the mini (FWS final alone is ~800 MB).
- Refresh later with `uv run build.py detect` (weekly `sync.yml`); each content change bumps the collection patch version.

## 6. Retiring a published collection

When a collection is replaced (e.g. `protectedseas_navigator` by its six category groups, 2026-10-20), take it out of
the catalog, not the bucket:

```sh
aws s3 sync s3://oceanmetrics.io-public/gazetteer/ catalog/pub/ --exclude '*.parquet' --exclude '*.pmtiles' --exclude '*.tif' --exclude '*.nc'
uv run python -m gazetteer.retire catalog/pub <slug>          # drops its child link (catalog.json) and versions.json entry
rashid check catalog/pub --data-scope local --all             # the gate: no new error at the root (compare with a run before)
aws s3 cp catalog/pub/catalog.json s3://oceanmetrics.io-public/gazetteer/catalog.json
aws s3 cp catalog/pub/versions.json s3://oceanmetrics.io-public/gazetteer/versions.json
```

Then remove its YAML and run a sync with `refresh=true`, so the index and `layers.json` drop it. The `<slug>/` files
stay, so old links keep working; delete them later only on purpose (and say so in the log).

To delete them (e.g. `protectedseas_navigator`, 2026-10-22): first check that nothing points at the slug any more
(root `catalog.json`, `versions.json`, `layers.json`, `index/places_index.parquet`, `gazetteer/dedup.py`), then
`aws s3 rm --recursive s3://oceanmetrics.io-public/gazetteer/<slug>/` and remove the local `catalog/pub/<slug>/` and
`catalog/staging/<slug>/` copies.

## Follow-ups (not done)

- `gazetteer/lines.py` and `gazetteer/mixed.py` partially duplicate the geometry-cleaning / antimeridian logic for non-polygon types; fold into one module later.
- `scripts/build_index.py` still maps the legacy `MPA:` prefix to `mpainv_site_id` (harmless; remove with the test fixture that uses it).
- `build_index.py` warns that 4 place_ids occur in two collections: `BOEM:OCS-P 0562/0563/0564` (in both `boem_pacific_og_leases` and
  `boem_wind_leases`: a lease number reused across the Pacific O&G and wind layers) and `MRGID:8439` (`mr_eez` and the published `places`
  collection, expected: the same Marine Regions record). Decide whether the BOEM overlap needs a distinct prefix before the index is published.
- `scripts/build_layers_json.py` crashed on mixed-geometry collections (`gebco_undersea`, list-valued `geoparquet:geometry_type`); fixed in this
  reconciliation (row `geom_type` is `Mixed`, paint holds fill+line+circle) with a regression test.

## Republish (a new version of published collections)

Rebuild the slugs at the new version (`uv run build.py build --slug <slug> --version 1.0.1`), pull the published metadata tree into
`catalog/pub/` (step 2), then `scripts/publish_collections.sh --republish [--version 1.0.1] [--note "..."] <slug> ...`. It keeps the
pulled `catalog/pub/<slug>/` and its ledger, copies the staged assets over it, restores the pulled ledger after `portolan add` (which
would otherwise auto-create a patch version) and runs `portolan version bump`, so the ledger ends at the new version exactly once.
Refuses when the pulled ledger already has that version. Then rebuild index/ and layers.json (step 4; the manifest is published at
`index/layers.json`, the client falls back to the root `layers.json`) and upload as in step 3.

## Unlisted copies (Marine Regions GeoParquet + PMTiles, since 2026-10-22)

The reference collections (`mr_*`, and `fao_high_seas` derived from `mr_high_seas`) are never uploaded by
`publish_collections.sh`. Their full-resolution `places.parquet` and `places.pmtiles` go to the second R2 bucket
`oceanmetrics-io-unlisted` instead, same key layout (`gazetteer/<slug>/places.parquet`, `places.pmtiles`, `provenance.json`,
`README.md`), plus `gazetteer/index/unlisted.json` (slug, version, credit, the two hrefs relative to that file, rows). The
contract is Ben's email to VLIZ of 2026-10-22 (notes `om/om_2026-10.md`, "VLIZ email sent"): one copy per release, unlisted,
not offered for download, credit and DOI on every map, the public layers stay on VLIZ's raster tiles. Nothing in the public
catalog, `layers.json` or the index links to them; the Worker serves them at `/unlisted/gazetteer/<slug>/...` with a key only
(`worker/README.md`). `fao_high_seas` has no PMTiles by design.

Per release, on the build machine (the files never enter the repo):

```sh
ST=/Volumes/msens_big/_big/oceanmetrics/unlisted_stage    # README.md + provenance.json + index/unlisted.json, outside the repo
R=~/.config/oceanmetrics/rclone-r2.sh
# provenance.json: the published one (its sha256 is the internal collection.json's `provenance` asset checksum)
for s in $(ls ~/data/oceanmetrics/places-internal); do $R copyto r2:oceanmetrics-io-public/gazetteer/$s/provenance.json $ST/gazetteer/$s/provenance.json; done
python3 -I $ST/stage_unlisted.py $ST                       # READMEs + index/unlisted.json; asserts DuckDB rows == provenance record_count
$R copy $ST/gazetteer r2:oceanmetrics-io-unlisted/gazetteer --s3-no-check-bucket
$R copy ~/data/oceanmetrics/places-internal r2:oceanmetrics-io-unlisted/gazetteer --s3-no-check-bucket \
  --include '*/places.parquet' --header-upload 'Content-Type: application/vnd.apache.parquet'
$R copy ~/data/oceanmetrics/places-internal r2:oceanmetrics-io-unlisted/gazetteer --s3-no-check-bucket --include '*/places.pmtiles'
$R check ~/data/oceanmetrics/places-internal r2:oceanmetrics-io-unlisted/gazetteer --one-way --include '*/places.parquet' --include '*/places.pmtiles'
```

rclone sets `.json` and `.md` content types from the extension but not `.parquet`, hence the `--header-upload`. Check:
`curl -sI '<worker>/unlisted/gazetteer/mr_eez/places.parquet?key=<id>' -H 'Range: bytes=0-1023'` is 206 and the same without
the key is 403 `key_required`. Any change VLIZ asks for (credit wording, maximum zoom) is applied at the next upload.
