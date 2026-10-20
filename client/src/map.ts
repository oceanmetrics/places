import type { AddLayerOptions, DerivedPiece, DisplaySource, IndexPlace, Layer, MapLike } from './types'

export type DrawKind = 'fill' | 'line' | 'circle' | 'raster'
export const DRAW_KINDS: DrawKind[] = ['fill', 'line', 'circle', 'raster']
export const sourceId = (slug: string) => `places:${slug}`
export const layerId = (slug: string, kind: DrawKind) => `places:${slug}:${kind}`

/** a reference layer drawn from its publisher's tiles (no PMTiles, no parquet, no features to pick). */
export const isRaster = (layer: Pick<Layer, 'kind'>) => layer.kind === 'raster'

/** a layer computed from a reference collection and drawn by another layer's PMTiles (layers.json `kind: "derived"`). */
export const isDerived = (layer: Pick<Layer, 'kind'>) => layer.kind === 'derived'

/**
 * the layer that draws a derived layer (`display.via`), or null when the layer is not derived, `via` is not in the
 * manifest, or `via` has no PMTiles of its own to draw from (a raster or another derived layer). pure and synchronous,
 * so an app can tell a layer is not drawable before it asks the map for anything.
 */
export function viaLayer(layer: Pick<Layer, 'kind' | 'display'>, layers: Layer[]): Layer | null {
  if (!isDerived(layer) || !layer.display?.via) return null
  const via = layers.find((l) => l.slug === layer.display!.via)
  return via && via.kind !== 'raster' && via.kind !== 'derived' && via.pmtiles && via.source_layer ? via : null
}

/**
 * what a derived layer needs to be drawn: the layer `via` and the places of the derived layer (the index rows of its
 * collection) with their `source_id`, the value of the `via` feature's place_id they are shown in. an index row without
 * a source_id cannot be matched to a feature and is left out. null when `viaLayer` is null.
 */
export function derivedDisplay(layer: Layer, layers: Layer[], rows: IndexPlace[]): DisplaySource | null {
  const via = viaLayer(layer, layers)
  if (!via) return null
  const pieces: DerivedPiece[] = []
  for (const r of rows) {
    if (r.collection !== layer.collection || !r.source_id) continue
    pieces.push({ place_id: r.place_id, source_id: r.source_id, name: r.name, url: r.url ?? null, bbox: r.bbox ?? null })
  }
  pieces.sort((a, b) => a.place_id.localeCompare(b.place_id))
  return { layer, via, idFrom: layer.display!.id_from, pieces, ids: [...new Set(pieces.map((p) => p.source_id))] }
}

/** the MapLibre filter that keeps only the `via` features that are pieces of the derived layer. */
export const displayFilter = (ids: string[]) => ['in', ['get', 'place_id'], ['literal', ids]]

const kindsFor = (geomType: string): Array<'fill' | 'line' | 'circle'> => {
  const g = geomType.toLowerCase()
  return g.includes('point') ? ['circle'] : g.includes('line') ? ['line'] : ['fill', 'line']
}

/**
 * a raster source's `bounds` from the layer bbox, so MapLibre asks for no tile outside it: VLIZ GeoWebCache answers
 * HTTP 400 TileOutOfRange there (e.g. Marine Regions archipelagic waters at z4, 2026-10-20), not a blank tile. an
 * unwrapped bbox (east beyond 180, across the antimeridian) keeps every longitude; latitudes clamp to Web Mercator.
 */
export function tileBounds(bbox: number[] | null | undefined): [number, number, number, number] | undefined {
  if (!bbox || bbox.length !== 4 || !bbox.every(Number.isFinite)) return undefined
  const M = 85.0511
  const [w, s, e, n] = bbox
  const across = e > 180 || w < -180 || w > e
  return [across ? -180 : w, Math.max(s, -M), across ? 180 : e, Math.min(n, M)]
}

/** the MapLibre source and layer specs for a layer: pure, so it can be inspected without a map. */
export function layerSpec(layer: Layer, opts: AddLayerOptions = {}, display?: DisplaySource | null) {
  const { colour, opacity, width } = opts
  if (isRaster(layer)) {
    const r = layer.raster
    if (!r?.tiles?.length) throw new Error(`places: raster layer ${layer.slug} has no tiles`)
    const paint: Record<string, unknown> = { ...(layer.paint?.raster ?? {}) }
    if (opacity !== undefined) paint['raster-opacity'] = opacity
    return {
      sourceId: sourceId(layer.slug),
      source  : { type: 'raster', tiles: r.tiles, tileSize: r.tile_size, minzoom: r.minzoom, maxzoom: r.maxzoom, attribution: layer.attribution_html,
                  ...(tileBounds(layer.bbox) ? { bounds: tileBounds(layer.bbox) } : {}) },
      layers  : [{ id: layerId(layer.slug, 'raster'), type: 'raster' as DrawKind, source: sourceId(layer.slug), paint } as Record<string, any>],
    }
  }
  if (isDerived(layer) && !display) throw new Error(`places: derived layer ${layer.slug} needs its display source (layer "${layer.display?.via}" and its places): see derivedDisplay`)
  const tiles = display ? display.via : layer
  const layers = kindsFor(layer.geom_type).map((kind) => {
    const paint: Record<string, unknown> = { ...(layer.paint?.[kind] ?? {}) }
    if (colour !== undefined) paint[`${kind}-color`] = colour
    if (opacity !== undefined) paint[`${kind}-opacity`] = opacity
    if (width !== undefined && kind !== 'fill') paint[kind === 'circle' ? 'circle-stroke-width' : 'line-width'] = width
    return { id: layerId(layer.slug, kind), type: kind, source: sourceId(layer.slug), 'source-layer': tiles.source_layer, paint,
      ...(display ? { filter: displayFilter(display.ids) } : {}) } as Record<string, any>
  })
  return {
    sourceId: sourceId(layer.slug),
    source  : { type: 'vector', url: `pmtiles://${tiles.pmtiles}`, attribution: layer.attribution_html } as Record<string, any>,
    layers,
  }
}

/** add (or restyle, when already present) a gazetteer layer on a MapLibre map. Returns the map layer ids. */
export function addLayerSpec(map: MapLike, layer: Layer, opts: AddLayerOptions = {}, display?: DisplaySource | null): string[] {
  const spec = layerSpec(layer, opts, display)
  if (!map.getSource(spec.sourceId)) map.addSource(spec.sourceId, spec.source)
  for (const l of spec.layers) {
    if (map.getLayer(l.id)) {
      for (const [k, v] of Object.entries(l.paint)) map.setPaintProperty(l.id, k, v)
    } else {
      map.addLayer(l, opts.beforeId && map.getLayer(opts.beforeId) ? opts.beforeId : undefined)
    }
  }
  return spec.layers.map((l) => l.id)
}

/** remove a layer added by `addLayer` (its map layers, then its source). A layer that is not on the map is ignored. */
export function removeLayerSpec(map: MapLike, slug: string): void {
  for (const kind of DRAW_KINDS) if (map.getLayer(layerId(slug, kind))) map.removeLayer(layerId(slug, kind))
  if (map.getSource(sourceId(slug))) map.removeSource(sourceId(slug))
}

const registered = new WeakSet<object>()

/**
 * register the `pmtiles://` protocol with MapLibre once. Pass the maplibre-gl module and the pmtiles module:
 *
 *   import maplibregl from 'maplibre-gl'; import * as pmtiles from 'pmtiles'
 *   registerPmtiles(maplibregl, pmtiles)
 */
export function registerPmtiles(
  maplibre: { addProtocol(name: string, fn: any): void },
  pm: { Protocol: new () => { tile: any } },
): void {
  if (registered.has(maplibre)) return
  maplibre.addProtocol('pmtiles', new pm.Protocol().tile)
  registered.add(maplibre)
}
