import type { Feature, Geometry } from 'geojson'

/** [west, south, east, north] in EPSG:4326. */
export type BBox = [number, number, number, number]

/** MapLibre paint properties per layer kind, as published in layers.json. */
export interface LayerPaint {
  fill?  : Record<string, unknown>
  line?  : Record<string, unknown>
  circle?: Record<string, unknown>
  raster?: Record<string, unknown>
}

/** a reference layer's tile source (layers.json `raster`): drawn from its publisher's own tile service. */
export interface RasterSource {
  /** XYZ tile URL templates ({z}/{x}/{y}). */
  tiles    : string[]
  tile_size: number
  minzoom  : number
  maxzoom  : number
  /** the layer's page at its publisher (e.g. marineregions.org): where its data live. */
  link     : string | null
  /** one place's boundary as GeoJSON from the publisher, `{source_id}` from the index row (a relative URL resolves
   *  against `base`); `getPlace` uses it. null: no per-place geometry (e.g. a single global polygon). */
  feature_url?: string | null
  /** identify on click: the publisher's WMS GetFeatureInfo (JSON, no geometry) for `{bbox}` = west,south,east,north
   *  around the point, the point at the centre pixel; `identify` uses it. null: not identifiable. */
  info_url?: string | null
  /** the response property naming the place: matched to the index row's source_id, else its name. */
  info_id?: string | null
}

/** a link back to the source gazetteer or publisher of a layer (layers.json `source_link`). */
export interface SourceLink {
  href : string
  title: string
}

/** a dated status event of a whole layer (layers.json `status` and the items of `status_history`). */
export interface LayerStatus {
  value : string
  /** ISO date, or a partial one (YYYY, YYYY-MM). */
  date  : string
  /** URL that documents the status. */
  source: string
  note? : string | null
}

/** one row of layers.json (written by scripts/build_layers_json.py). */
export interface Layer {
  slug            : string
  title           : string
  collection      : string
  /** 'vector': our PMTiles; 'raster': a reference layer drawn from its publisher's tiles (`raster`), with no PMTiles or
   *  parquet here. absent in manifests before client 0.3.0 (= 'vector'). */
  kind?           : 'vector' | 'raster'
  /** the tile source of a raster layer; null for vector layers. */
  raster?         : RasterSource | null
  /** absolute URL of the collection's PMTiles archive; null for a raster layer. */
  pmtiles         : string | null
  /** the vector-tile layer name inside the archive (equals the slug); null for a raster layer. */
  source_layer    : string | null
  geom_type       : string
  /** number of features. */
  n               : number | null
  updated         : string | null
  version         : string | null
  paint           : LayerPaint
  authority       : string | null
  place_type      : string | null
  /** the collection extent; unwrapped (east may exceed 180) for a layer with places cut at the antimeridian, like the index bbox. */
  bbox            : BBox | null
  attribution     : string
  attribution_html: string
  license         : string | null
  license_url     : string | null
  citation        : string
  // added in client 0.1.3 (manifest rows from before lack them; null when unknown) ----
  /** the layer-level status, e.g. { value: 'rescinded', date: '2025-07-30', source, note }; null when the layer has none. */
  status?         : LayerStatus | null
  /** the layer's status events, ascending by date. */
  status_history? : LayerStatus[] | null
  /** 'rescinded 2025-07-30' (value with '_' as space, then the date): show it as `${title} (${status_label})`, see `layerLabel`. */
  status_label?   : string | null
  /** which copy of a place to show when it is in several layers (lower first): 0 the agency's own layer, 1 layers that
   * re-use other agencies' boundaries (MPA Inventory, HAPCs), 2 legacy copies. absent in older manifests (= 0). */
  search_rank?    : number | null
  /** ISO date of the collection's first published version. */
  created?        : string | null
  /** latest upstream data edit date across the collection's sources (ISO date). */
  source_date?    : string | null
  /** absolute URL of the collection's places.parquet. */
  parquet?        : string | null
  /** sha256 (hex) of places.parquet at `version`: pin `version` + `parquet_sha256`. */
  parquet_sha256? : string | null
  /** the source gazetteer or publisher page to credit and link back to (client 0.4.0; null when unknown). */
  source_link?    : SourceLink | null
  /** URL of `<slug>/h3/membership.json`: the place x H3 membership (res 1-7, the share of each cell inside each
   *  place), set only while it was built from this `parquet_sha256`; null for points, lines and stale builds. */
  h3?             : string | null
}

export interface ClientConfig {
  /** root of the published gazetteer (trailing slash optional). */
  base?     : string
  /** where layers.json lives; default `${base}index/layers.json`, falling back to `${base}layers.json` on a 404/403. */
  layersUrl?: string
  /** where the place index lives; default `${base}index/places_index.parquet`. */
  indexUrl? : string
  /** collection parquet for a slug; default `${base}${slug}/places.parquet`. */
  parquetUrl?: (slug: string) => string
  /** fetch implementation (default: global fetch). */
  fetch?    : typeof fetch
}

/** a row of places_index.parquet. place_id is unique within a collection, not across collections. */
export interface IndexPlace {
  place_id  : string
  name      : string
  authority : string
  place_type: string
  /** Point, LineString, Polygon, MultiPolygon, ... (null if the index row has none). */
  geom_type : string | null
  /** slug of the collection holding the place: its PMTiles/GeoParquet live at `${base}${collection}/`. */
  collection: string
  /** [west, south, east, north]; a place cut at the antimeridian is unwrapped, so east may exceed 180 (177..199). */
  bbox      : BBox
  /** [lon, lat]; for a place cut at the antimeridian lon is the centroid of the unwrapped parts and may exceed 180 (e.g. 188), like the bbox. */
  centroid  : [number, number] | null
  area_km2  : number | null
  license   : string | null
  attribution: string | null
  version   : string | null
  updated   : string | null
  /** rows that are the same place in different collections share it (null: no other copy). see `search({ group })`. */
  group_id  : string | null
  /** the place's id at its source (MRGID, Navigator ps_id, ...); null in indexes before client 0.4.0. */
  source_id?: string | null
  /** the place's own page at its source (its Marine Regions page, a Navigator site's managing-authority page); link
   *  back to it. null when the source has none. */
  url?      : string | null
  /** extra words the search matches (a Marine Regions EEZ's territory "Belgium", while its name says "Belgian"; a
   *  Navigator site's country); null when none, absent in indexes before client 0.5.0. */
  keywords? : string | null
  /** with `search({ group: true })`: the other copies of this place, in preference order. */
  also?     : IndexPlace[]
}

export interface SearchOptions {
  /** keep places whose bbox intersects [west, south, east, north]; west > east means across the antimeridian. */
  bbox?     : BBox
  type?     : string | string[]
  authority?: string | string[]
  /** keep places of these collection slugs (an index row's `collection`, a layers.json `collection`). */
  collection?: string | string[]
  limit?    : number
  /** one hit per place: copies sharing a `group_id` collapse into the preferred one, the rest go to its `also`. */
  group?    : boolean
  /** collection slugs to prefer when grouping, first wins; then layers.json `search_rank`, then the search order. */
  prefer?   : string[]
}

/**
 * a GeoJSON Feature; `id` is the place_id, `properties` the collection's columns without geometry and bbox.
 * `collection` (a foreign member) is the slug of the collection the place was read from: place_id is not unique
 * across collections, so this is what links the feature back to its layers.json entry (licence, attribution, citation).
 */
export type PlaceFeature = Feature<Geometry, Record<string, unknown>> & {
  id: string; bbox?: BBox; collection: string
  /** set when the geometry came from the publisher's own service (a reference layer's `feature_url`): its URL. */
  served_by?: string
}

export interface GetPlaceOptions {
  /** unwrap antimeridian-split parts into contiguous longitudes beyond 180 (see `unwrapAntimeridian`). */
  unwrap?: boolean
  /** collection slug (an index hit's `collection`): reads only that collection, no authority-guess walk. A place_id can occur in several collections. */
  slug?  : string
}

export interface MapLike {
  getSource(id: string): unknown
  getLayer(id: string): unknown
  addSource(id: string, spec: any): unknown
  addLayer(spec: any, beforeId?: string): unknown
  removeLayer(id: string): unknown
  removeSource(id: string): unknown
  setPaintProperty(layerId: string, name: string, value: unknown): unknown
}

export interface AddLayerOptions {
  /** one colour for fill, line and circle. */
  colour?  : string
  /** 0..1, applied to fill, line and circle. */
  opacity? : number
  /** line width in px (circle outline width for point layers). */
  width?   : number
  /** insert below this existing map layer id. */
  beforeId?: string
}

/** what `creditsFor` accepts: a place id, a layer slug, a search hit, or a pinned `{ collection, place_id }`. */
export type CreditRef = string | { place_id: string; collection?: string }
