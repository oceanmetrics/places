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
  /** where layers.json lives; default `${base}index/layers.json`. */
  layersUrl?: string
  /** where the place index lives; default `${base}index/places_index.parquet`. */
  indexUrl? : string
  /** collection parquet for a slug; default `${base}${slug}/places.parquet`. */
  parquetUrl?: (slug: string) => string
  /** fetch implementation (default: global fetch). */
  fetch?    : typeof fetch
}

/** a row of places_index.parquet. */
export interface IndexPlace {
  place_id  : string
  name      : string
  authority : string
  place_type: string
  bbox      : BBox
  /** [lon, lat] */
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

/** a GeoJSON Feature; `id` is the place_id, `properties` the collection's columns without geometry and bbox. */
export type PlaceFeature = Feature<Geometry, Record<string, unknown>> & { id: string; bbox?: BBox }

export interface GetPlaceOptions {
  /** unwrap antimeridian-split parts into contiguous longitudes beyond 180 (see `unwrapAntimeridian`). */
  unwrap?: boolean
  /** collection slug when known, which skips the lookup of the collection. */
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
