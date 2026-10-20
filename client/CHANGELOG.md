# Changelog

## 0.5.0

- `identify(slug, bbox)` names the places of a raster (reference) layer under a point. It asks the publisher's WMS
  GetFeatureInfo (`raster.info_url`, JSON, no geometry) for `bbox` around the point, then maps the response's
  `raster.info_id` to index rows (source_id, else name, else the layer's only row). Marine Regions places, drawn from
  VLIZ's PNG tiles, were not clickable before. New `RasterSource.info_url` and `info_id`.
- `search` also matches `IndexPlace.keywords` (new index column, null when none): extra words such as a Marine Regions
  EEZ's territory ("Belgium", while its name says "Belgian ...") or a Navigator site's country and state. A
  keyword-only match ranks after every name match.
- `getPlace` reads fewer row groups. It now picks them from the place_id statistics itself, smallest first. When more
  than 4 could hold the id (a spatially sorted layer), it also prunes by the place's bbox from the index. New helper
  `candidateGroups(metadata, id, bbox?)`. The 30,111-site Navigator layer made the place page fetch about 1 GB.
- Data: `protectedseas_navigator` is split into six layers by Navigator category: `protectedseas_mpa`,
  `protectedseas_fisheries`, `protectedseas_jurisdiction`, `protectedseas_vessel`, `protectedseas_human_use` and
  `protectedseas_other`.

## 0.4.0

- Link back to the source of every place and layer, for credit:
  - `IndexPlace.url` is the place's own page at its source. Examples: its Marine Regions gazetteer page, or the
    managing authority's page for a ProtectedSeas Navigator site.
  - `IndexPlace.source_id` is the place's id at its source (MRGID, Navigator `ps_id`).
  - `Layer.source_link` (`{ href, title }`, new type `SourceLink`) is the source gazetteer or publisher to credit,
    e.g. Marine Regions (VLIZ) or ProtectedSeas Navigator.
  - All three are null when unknown.
- `getPlace` on a raster (reference) layer fetches that one boundary from the publisher's `raster.feature_url`, filled
  with the index row's `source_id`. There is no parquet of ours for such a layer.
  - The feature's properties are the publisher's attributes plus the index row.
  - `served_by` is the URL it came from.
  - A publisher response split into several polygons becomes one MultiPolygon (new helper `mergeGeometries`).
  - A relative `feature_url` resolves against `base`.
- A `getPlace` pinned to a `slug` now also reads the manifest (cached) to tell whether the slug is a reference layer.
- Data: the Marine Regions layers become reference layers (VLIZ asked us not to republish their products). The new
  `protectedseas_navigator` layer is ordinary vector data (CC BY 4.0).

## 0.3.0

- Raster (reference) layers: a layers.json row with `kind: "raster"` is drawn from its publisher's own tile service
  (`raster` = `{ tiles, tile_size, minzoom, maxzoom, link }`, XYZ templates), with no PMTiles or parquet here. This is
  how Marine Regions layers will appear once VLIZ confirms the traffic is fine: they asked us not to republish their
  products. `addLayer` / `layerSpec` make one MapLibre `raster` layer (`places:<slug>:raster`, `opacity` sets
  `raster-opacity`; `colour` and `width` do not apply); `removeLayer` removes it.
- Breaking for TypeScript: `Layer.pmtiles` and `Layer.source_layer` are `string | null` (null for raster layers).
  New `Layer.kind` (absent in older manifests = `'vector'`), `Layer.raster`, `LayerPaint.raster`, type `RasterSource`.
- New `isRaster(layer)`, `DRAW_KINDS` and type `DrawKind` (`'fill' | 'line' | 'circle' | 'raster'`), for apps that
  reorder or query the map layers `addLayer` made.
- `getPlace` without `slug` skips raster layers (they have no parquet to read).

## 0.2.0

- Same place, several layers: index rows carry `group_id` (the same place in different collections, e.g. Florida
  Keys NMS in `noaa_sanctuaries`, `mpa_inventory`, `noaa_hapc` and erddap-places' `places`, or listed twice in one).
  `IndexPlace.group_id` is null for a place with no other copy.
- `search(q, { group: true })` returns one hit per place: the copy with the lowest layers.json `search_rank` (0 the
  agency's own layer, 1 layers re-using other agencies' boundaries, 2 legacy copies), the others in `also`.
  `prefer: [slug, ...]` overrides the order (erddap-places can prefer its own `places` copy).
- New `samePlace(placeId, { slug, prefer })`: the other copies of a place, in preference order.
- New `groupHits(hits, rank)` (pure) for apps that group their own lists.
- `Layer.search_rank` (absent in older manifests = 0).
- Data: `area_km2` is now filled for every polygon (geodesic, WGS84) where the source has none; it was null for all
  but erddap-places' `places`, so the larger-area tiebreak always ranked that copy first.

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
