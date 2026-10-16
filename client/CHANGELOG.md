# Changelog

## 0.1.4

- `search()` takes `collection` (a slug or a list): keep only places of those collections, e.g. to search within one
  layer. An empty list means no filter.

## Unreleased (data only, no client change)

- A layer whose places are cut at the antimeridian (e.g. `noaa_sanctuaries` with Papahanaumokuakea) gets a layers.json
  `bbox` that is unwrapped like the index bbox (`[177.8, -15.4, 295.5, 48.5]`: east beyond 180), instead of
  `[-180, ..., 180, ...]` round the globe. `fitBounds` takes it as is. The collection's STAC extent and its parquet
  `geo` bbox cross the antimeridian the RFC 7946 way (west > east, `[177.8, -15.4, -64.5, 48.5]`).

## 0.1.3

- `Layer` (a layers.json row) gains optional `status`, `status_history`, `status_label` (layer-level status, e.g. the
  BOEM wind planning areas: `rescinded`, 2025-07-30, with the BOEM notice), `created` (first published version's date),
  `source_date` (latest upstream data edit), `parquet` and `parquet_sha256` (pin `version` + `parquet_sha256`). All are
  null when unknown and absent in older manifests. New type `LayerStatus`.
- New `layerLabel(layer)`: `title (status_label)` when the layer has a status, else the title. Layer titles in the
  manifest are now plain (`BOEM offshore wind planning areas`, no "(rescinded 2025-07-30)" suffix).
- Collections' `places.parquet` gain `status_upstream` (the source's own status code, verbatim) and `status_history`
  (JSON event list); `getPlace` returns them as properties when present. No client change needed.
- docs: `base_direct` is the path-style bucket URL.

## 0.1.2

- `getPlace` features gain `collection` (a GeoJSON foreign member): the slug of the collection the place was read
  from. `place_id` is not unique across collections, and an id whose authority prefix matches no layer's `authority`
  (e.g. `NMS:PMNM` in the legacy `places` collection, whose manifest entry has no authority) otherwise has no way
  back to its layers.json entry for licence, attribution and citation.

## 0.1.1

- **fix: index centroids.** `search` read `centroid` but the published index has `centroid_lon` / `centroid_lat`, so every
  hit's `centroid` was `null`. It now reads the live columns (the old `centroid` list is still accepted). The test fixture
  index is regenerated with the live schema (and must mirror `scripts/build_index.py`).
- `search` hits gain `collection` (the slug holding the place: pick the PMTiles layer with it) and `geom_type`.
- `getPlace(id, { slug })` pins the collection (no authority walk, no manifest fetch); a pinned lookup is not remembered
  for unpinned ones. `place_id` is unique per collection, not globally: `search` keeps one hit per (collection, place_id),
  `creditsFor` accepts search hits and `{ collection, place_id }` and credits every collection for a bare duplicate id.
- `listLayers` falls back to `${base}layers.json` when `${base}index/layers.json` answers 404 or 403 (an explicit
  `layersUrl` is used as given).
- index centroids of places cut at the antimeridian are computed on the unwrapped parts (`centroid[0]` may exceed 180, e.g. NMS:PMNM ~188 instead of a mid-Pacific average), same convention as the bbox.
- `bboxIntersects` / `search({ bbox })` understand unwrapped index bboxes whose east edge exceeds 180 (places cut at the
  antimeridian are indexed as e.g. 177..199).
- docs: `layers.json` `base_direct` (apps MAY rewrite canonical `pmtiles` URLs onto the redirect-free bucket host).
- Collections are now written with small parquet row groups, so a `getPlace` by id is a real range read (a few hundred kB
  instead of up to 30 MB for `mpa_inventory`). Republished as collection version 1.0.1; no client change needed.

## 0.1.0

- Initial release: `listLayers`, `getLayer`, `addLayer` / `removeLayer`, `search`, `getPlace`, `creditsFor`, `unwrapAntimeridian`.
