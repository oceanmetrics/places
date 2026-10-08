# client/

The `@oceanmetrics/places` JavaScript package for apps that use the gazetteer: `listLayers()`, `addLayer(map, slug, opts)`,
`removeLayer`, `search(q, {bbox, type, authority, limit})` over the index parquet, `getPlace(id, {unwrap})` and
`creditsFor(ids | slugs)` (the attribution line for what is on screen). It reads `layers.json` and the published
GeoParquet/PMTiles directly from the bucket. Not started.
