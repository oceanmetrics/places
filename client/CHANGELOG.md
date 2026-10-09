# Changelog

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
