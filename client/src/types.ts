import type { Feature, Geometry } from 'geojson'

/** [west, south, east, north] in EPSG:4326. */
export type BBox = [number, number, number, number]

/** MapLibre paint properties per layer kind, as published in layers.json. */
export interface LayerPaint {
  fill?  : Record<string, unknown>
  line?  : Record<string, unknown>
  circle?: Record<string, unknown>
}

/** one row of layers.json (written by scripts/build_layers_json.py). */
export interface Layer {
  slug            : string
  title           : string
  collection      : string
  /** absolute URL of the collection's PMTiles archive. */
  pmtiles         : string
  /** the vector-tile layer name inside the archive (equals the slug). */
  source_layer    : string
  geom_type       : string
  /** number of features. */
  n               : number | null
  updated         : string | null
  version         : string | null
  paint           : LayerPaint
  authority       : string | null
  place_type      : string | null
  bbox            : BBox | null
  attribution     : string
  attribution_html: string
  license         : string | null
  license_url     : string | null
  citation        : string
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
}

export interface SearchOptions {
  /** keep places whose bbox intersects [west, south, east, north]; west > east means across the antimeridian. */
  bbox?     : BBox
  type?     : string | string[]
  authority?: string | string[]
  limit?    : number
}

/**
 * a GeoJSON Feature; `id` is the place_id, `properties` the collection's columns without geometry and bbox.
 * `collection` (a foreign member) is the slug of the collection the place was read from: place_id is not unique
 * across collections, so this is what links the feature back to its layers.json entry (licence, attribution, citation).
 */
export type PlaceFeature = Feature<Geometry, Record<string, unknown>> & { id: string; bbox?: BBox; collection: string }

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
