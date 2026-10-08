import type { AddLayerOptions, Layer, MapLike } from './types'

export const sourceId = (slug: string) => `places:${slug}`
export const layerId = (slug: string, kind: 'fill' | 'line' | 'circle') => `places:${slug}:${kind}`

const kindsFor = (geomType: string): Array<'fill' | 'line' | 'circle'> => {
  const g = geomType.toLowerCase()
  return g.includes('point') ? ['circle'] : g.includes('line') ? ['line'] : ['fill', 'line']
}

/** the MapLibre source and layer specs for a layer: pure, so it can be inspected without a map. */
export function layerSpec(layer: Layer, opts: AddLayerOptions = {}) {
  const { colour, opacity, width } = opts
  const layers = kindsFor(layer.geom_type).map((kind) => {
    const paint: Record<string, unknown> = { ...(layer.paint?.[kind] ?? {}) }
    if (colour !== undefined) paint[`${kind}-color`] = colour
    if (opacity !== undefined) paint[`${kind}-opacity`] = opacity
    if (width !== undefined && kind !== 'fill') paint[kind === 'circle' ? 'circle-stroke-width' : 'line-width'] = width
    return { id: layerId(layer.slug, kind), type: kind, source: sourceId(layer.slug), 'source-layer': layer.source_layer, paint }
  })
  return {
    sourceId: sourceId(layer.slug),
    source  : { type: 'vector', url: `pmtiles://${layer.pmtiles}`, attribution: layer.attribution_html },
    layers,
  }
}

/** add (or restyle, when already present) a gazetteer layer on a MapLibre map. Returns the map layer ids. */
export function addLayerSpec(map: MapLike, layer: Layer, opts: AddLayerOptions = {}): string[] {
  const spec = layerSpec(layer, opts)
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
  for (const kind of ['fill', 'line', 'circle'] as const) if (map.getLayer(layerId(slug, kind))) map.removeLayer(layerId(slug, kind))
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
