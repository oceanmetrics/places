# @oceanmetrics/places

JavaScript client for the Ocean Metrics places gazetteer (https://storage.oceanmetrics.io/gazetteer/). It reads the
published `layers.json`, GeoParquet and PMTiles straight from object storage: no server, no API key.

- Dependencies: `hyparquet` and `hyparquet-compressors` (parquet range reads). `pmtiles` is an optional peer, needed
  only to draw layers on a map. MapLibre GL is not a dependency: functions take your `map`.
- ESM and TypeScript. Version 0.1.1 (see CHANGELOG.md), MIT, not published to npm yet (install from the repo: `client/`).
- Every function is available on the default client (`import { search } from '@oceanmetrics/places'`) and on
  `createClient(config)` for more than one base URL.

```ts
import { configure, listLayers, addLayer, removeLayer, search, getPlace, creditsFor } from '@oceanmetrics/places'

configure({ base: 'https://storage.oceanmetrics.io/gazetteer/' })   // the default; override for staging or tests
```

`configure({ base, layersUrl, indexUrl, parquetUrl, fetch })`: `layersUrl` defaults to `${base}index/layers.json`
and, when that answers 404 or 403, falls back to `${base}layers.json` (both locations are published; an explicit
`layersUrl` is used as given, with no fallback), `indexUrl` to `${base}index/places_index.parquet`, `parquetUrl(slug)` to `${base}${slug}/places.parquet`.
Calling `configure` clears the caches.

## listLayers(opts?) and getLayer(slug)

The manifest written by `scripts/build_layers_json.py`: one row per map layer (`slug`, `title`, `collection`,
`pmtiles`, `source_layer`, `geom_type`, `n`, `updated`, `version`, `paint`, `authority`, `place_type`, `bbox`,
`attribution`, `attribution_html`, `license`, `license_url`, `citation`). Cached; `{ refresh: true }` re-fetches.

URLs: each `pmtiles` is canonical, on the storage host (`https://storage.oceanmetrics.io/gazetteer/...`), which answers
every request with one 302 to the bucket. The manifest's top-level `base_direct`
(`https://oceanmetrics.io-public.s3.amazonaws.com/gazetteer/`) is the same key space on the bucket host, without the
redirect. Apps MAY rewrite a `pmtiles` URL onto `base_direct` (replace the manifest's `base` prefix) until a
redirect-free host replaces the redirect; nothing else needs to change. `listLayers()` returns the layer rows only; read
`base_direct` from the JSON if you need it.

```ts
const layers = await listLayers()
const wind = layers.find((l) => l.slug === 'boem_wind_leases')   // wind.n, wind.license, wind.citation ...
```

## addLayer(map, slug, opts?) / removeLayer(map, slug)

Adds a PMTiles vector source and one MapLibre layer per kind: polygons get `fill` + `line`, lines `line`, points
`circle`. Ids are `places:<slug>` (source) and `places:<slug>:fill|line|circle`. The source carries the layer's
`attribution_html`, so the map's attribution control credits it. Calling `addLayer` again for a slug that is on the map
restyles it. `removeLayer` removes the layers and the source (and ignores a layer that is not there).

| option | effect |
|---|---|
| `colour` | `fill-color`, `line-color`, `circle-color` |
| `opacity` | `fill-opacity`, `line-opacity`, `circle-opacity` |
| `width` | `line-width` (for points: `circle-stroke-width`) |
| `beforeId` | insert below this map layer, if it exists |

Register the `pmtiles://` protocol once per page:

```ts
import maplibregl from 'maplibre-gl'
import * as pmtiles from 'pmtiles'
import { registerPmtiles, addLayer, removeLayer } from '@oceanmetrics/places'

registerPmtiles(maplibregl, pmtiles)
map.on('load', async () => {
  await addLayer(map, 'boem_wind_leases', { colour: '#1b7f9e', opacity: 0.5, beforeId: 'place-labels' })
  // ...later
  removeLayer(map, 'boem_wind_leases')
})
```

`layerSpec(layer, opts)` returns the source and layer specs without touching a map.

## search(q, opts?)

Searches `places_index.parquet` (no geometry; one row per place across all layers). The index is read once with
range requests (footer first) and kept in memory; searching is then local. Every word of `q` must occur in the name
or place id (case and accent insensitive). Ranking: exact name or id, name prefix, word prefix, substring; ties by
larger `area_km2`. Options: `bbox: [west, south, east, north]` (west > east crosses the antimeridian), `type`,
`authority` (string or array), `limit` (default 20). An empty `q` lists by filter.

```ts
const hits = await search('humboldt', { type: 'lease', authority: 'BOEM', bbox: [-125, 38, -123, 42], limit: 10 })
// [{ place_id, name, authority, place_type, geom_type, collection, bbox, centroid: [lon, lat], area_km2, license,
//    attribution, version, updated }]
```

Index columns the client reads (the live schema, written by `scripts/build_index.py`): `place_id, name, authority,
place_type, geom_type, collection, bbox` (struct xmin/ymin/xmax/ymax), `centroid_lon, centroid_lat` (doubles; a
pre-0.1.1 `centroid` list is still understood), `area_km2, license, attribution, version, updated`. `collection` is the
slug whose PMTiles layer and GeoParquet hold the place (`${base}${collection}/`), `geom_type` its geometry kind.

- **bbox convention for places cut at the antimeridian:** the index bbox is *unwrapped*: parts west of the antimeridian are
  shifted +360, so `xmax` may exceed 180 (e.g. `[177, 10, 199, 14]`). `fitBounds` takes it as is. The `centroid` of such a place is computed on the unwrapped parts too, so `centroid[0]` may exceed 180 (NMS:PMNM is about 188); wrap it with `((x + 540) % 360) - 180` where a map needs [-180, 180]. The `bbox` option of
  `search` also matches such places from either side of the antimeridian.
- **`place_id` is unique within a collection, not across collections** (`BOEM:OCS-P 0562/0563/0564` are in both
  `boem_pacific_og_leases` and `boem_wind_leases`). `search` returns one hit per (collection, place_id); tell them apart
  by `collection`, and pass it on to `getPlace(id, { slug })` and `creditsFor`.

## getPlace(id, opts?)

One place as a GeoJSON Feature (`id` = place_id, `properties` = the collection's columns except geometry and bbox,
`bbox` = `[w, s, e, n]`). The collection is found through `layers.json` (layers of the id's authority first) and read
with a filtered range read: the footer is read once, then only the row groups whose `place_id` min/max admit the id
(the collections are written with small row groups, so that is a few hundred kB, not the file). `null` if no collection has the id.

`{ slug }` pins the collection and skips the authority-guess walk and the manifest fetch: use it with a search hit's
`collection`. It matters because a place_id can be in more than one collection; an unpinned `getPlace` returns the
first collection that has it (the id's authority first, then manifest order), a pinned one exactly the one you named.
`slug` is also the fast path when you already know where the place lives.

```ts
const [hit] = await search('OCS-P 0562', { type: 'lease' })
const f = await getPlace(hit.place_id, { slug: hit.collection, unwrap: true })
```

`unwrap: true` unwraps antimeridian-split geometries. The gazetteer stores places cut at +/-180. When a MultiPolygon has
a part touching +180 and a part touching -180, every part west of the antimeridian is shifted by +360, so longitudes run
contiguously beyond 180 (a place cut at 170..180 and -180..-164 becomes 170..196). The parts remain separate polygons
that share the x = 180 edge; they are not dissolved. Geometries that do not cross are returned untouched. `bbox` is
recomputed from the unwrapped coordinates. `unwrapAntimeridian(geometry)` and `wrapLongitude(x)` are exported.

```ts
const pm = await getPlace('NMS:PMNM', { unwrap: true })   // pm.geometry spans lon 160 .. 200
```

## creditsFor(ids | slugs, opts?)

The credit line for what is on screen. Strings with a `:` are place ids (attribution from the index), others are
layer slugs (from `layers.json`); mix freely. A bare id found in several collections credits all of them; pass a search
hit or `{ collection, place_id }` to credit one (the index is keyed on collection + place_id). Duplicates collapse and "Processed by Ocean Metrics." is said once.
`{ html: true }` returns the layers' linked `attribution_html` (index text is escaped). Unknown refs are skipped.

```ts
await creditsFor(['boem_wind_leases', 'AOA:N1'])
// 'Bureau of Ocean Energy Management (BOEM), ...; NOAA AOA program. Processed by Ocean Metrics.'
```

## R and Python: one-page SQL recipe

The same files are plain GeoParquet 1.1 (WKB geometry, EPSG:4326, `bbox` struct column), so any DuckDB reads them
directly. Filtering on the `bbox` struct lets DuckDB skip row groups, so only the matching rows cross the network.

```sql
INSTALL httpfs; LOAD httpfs;
SELECT place_id, name, status, ST_AsText(ST_GeomFromWKB(geometry)) AS wkt   -- needs `INSTALL spatial; LOAD spatial;`
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/boem_wind_leases/places.parquet')
WHERE bbox.xmin <= -117 AND bbox.xmax >= -125     -- bbox pushdown: west, east
  AND bbox.ymin <=   42 AND bbox.ymax >=   32     --                south, north
  AND status = 'active';
```

Python:

```python
import duckdb, geopandas as gpd, shapely
con = duckdb.connect(); con.sql("INSTALL httpfs; LOAD httpfs")
df = con.sql("""
  SELECT place_id, name, status, geometry
  FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/boem_wind_leases/places.parquet')
  WHERE bbox.xmin <= -117 AND bbox.xmax >= -125 AND bbox.ymin <= 42 AND bbox.ymax >= 32""").df()
gdf = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=shapely.from_wkb(df["geometry"].map(bytes)), crs=4326)
```

R:

```r
library(DBI); library(duckdb); library(sf)
con <- dbConnect(duckdb()); dbExecute(con, "INSTALL httpfs; LOAD httpfs")
d <- dbGetQuery(con, "
  SELECT place_id, name, status, geometry
  FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/boem_wind_leases/places.parquet')
  WHERE bbox.xmin <= -117 AND bbox.xmax >= -125 AND bbox.ymin <= 42 AND bbox.ymax >= 32")
x <- st_sf(d[c("place_id", "name", "status")], geometry = st_as_sfc(structure(d$geometry, class = "WKB")), crs = 4326)
```

Search the whole gazetteer without geometry: `SELECT * FROM read_parquet('.../index/places_index.parquet') WHERE name ILIKE '%canyon%'`.
Geometry is split at +/-180: for a place that crosses the antimeridian, query both sides or use `getPlace(id, { unwrap: true })`.

## Develop

```sh
npm install
npm test          # vitest, offline: serves test/fixtures over a local HTTP server with Range support
npm run build     # tsc to dist/
bash test/fixtures/make_fixtures.sh   # regenerate fixtures (duckdb CLI with spatial, and uv)
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md).
