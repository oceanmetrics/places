import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { unwrapAntimeridian, wkbToGeometry, layerSpec, registerPmtiles, createClient, isRaster, isDerived, viaLayer, derivedDisplay, displayFilter, tileBounds } from '../src/index'
import type { IndexPlace, Layer, MapLike } from '../src/index'
import { FIXTURES, serveFixtures } from './server'

const layers: Layer[] = JSON.parse(readFileSync(FIXTURES + 'index/layers.json', 'utf8')).layers
const by = (s: string) => layers.find((l) => l.slug === s)!

class FakeMap implements MapLike {
  sources = new Map<string, any>(); layers: any[] = []; before = new Map<string, string | undefined>()
  getSource = (id: string) => this.sources.get(id)
  getLayer = (id: string) => this.layers.find((l) => l.id === id)
  addSource = (id: string, s: any) => void this.sources.set(id, s)
  addLayer = (l: any, b?: string) => { this.layers.push({ ...l, paint: { ...l.paint } }); this.before.set(l.id, b) }
  removeLayer = (id: string) => { this.layers = this.layers.filter((l) => l.id !== id) }
  removeSource = (id: string) => void this.sources.delete(id)
  setPaintProperty = (id: string, k: string, v: unknown) => { this.getLayer(id).paint[k] = v }
}

describe('layerSpec', () => {
  it('polygons get a fill and a line layer on a pmtiles source with attribution', () => {
    const s = layerSpec(by('fx_leases'))
    expect(s.source).toEqual({ type: 'vector', url: 'pmtiles://https://storage.oceanmetrics.io/gazetteer/fx_leases/places.pmtiles',
      attribution: by('fx_leases').attribution_html })
    expect(s.layers.map((l) => [l.id, l.type, l['source-layer']])).toEqual([
      ['places:fx_leases:fill', 'fill', 'fx_leases'], ['places:fx_leases:line', 'line', 'fx_leases']])
    expect(s.layers[0].paint).toEqual({ 'fill-color': '#e08a1e', 'fill-opacity': 0.45 })
  })
  it('points get a circle layer and lines a line layer', () => {
    expect(layerSpec(by('fx_stations')).layers.map((l) => l.type)).toEqual(['circle'])
    expect(layerSpec(by('fx_lines')).layers.map((l) => l.type)).toEqual(['line'])
  })
  it('a raster (reference) layer is one raster layer on its publisher\'s tiles, with attribution', () => {
    const r = by('fx_ref')
    const s = layerSpec(r, { opacity: 0.5, colour: '#ff0000', width: 3 })
    expect(s.source).toEqual({ type: 'raster', tiles: r.raster!.tiles, tileSize: 256, minzoom: 0, maxzoom: 12,
      attribution: r.attribution_html, bounds: [-180, -80, 180, 80] })
    expect(s.layers).toEqual([{ id: 'places:fx_ref:raster', type: 'raster', source: 'places:fx_ref', paint: { 'raster-opacity': 0.5 } }])
    expect(isRaster(r)).toBe(true)
    expect(isRaster(by('fx_leases'))).toBe(false)
    expect(() => layerSpec({ ...r, raster: null })).toThrow(/no tiles/)
  })
  it('raster bounds come from the bbox (regression: VLIZ answers 400 TileOutOfRange outside a layer, 2026-10-20)', () => {
    expect(tileBounds([95, -11, 141, 6])).toEqual([95, -11, 141, 6])
    expect(tileBounds([170, -60, 190, 89])).toEqual([-180, -60, 180, 85.0511])   // across the antimeridian
    expect(tileBounds(null)).toBeUndefined()
  })
  it('colour, opacity and width override the default paint', () => {
    const [fill, line] = layerSpec(by('fx_leases'), { colour: '#ff0000', opacity: 0.3, width: 2 }).layers
    expect(fill.paint).toEqual({ 'fill-color': '#ff0000', 'fill-opacity': 0.3 })
    expect(line.paint).toEqual({ 'line-color': '#ff0000', 'line-width': 2, 'line-opacity': 0.3 })
  })
})

describe('addLayer / removeLayer', () => {
  const client = createClient({
    fetch: (async () => new Response(JSON.stringify({ layers }))) as typeof fetch,
  })
  it('adds the source and layers, restyles on a second call, removes cleanly', async () => {
    const map = new FakeMap()
    expect(await client.addLayer(map, 'fx_leases', { beforeId: 'labels' })).toEqual(['places:fx_leases:fill', 'places:fx_leases:line'])
    expect(map.sources.size).toBe(1)
    await client.addLayer(map, 'fx_leases', { colour: '#00ff00' })
    expect(map.layers.length).toBe(2)                       // not duplicated
    expect(map.getLayer('places:fx_leases:fill').paint['fill-color']).toBe('#00ff00')
    client.removeLayer(map, 'fx_leases')
    expect(map.layers.length).toBe(0)
    expect(map.sources.size).toBe(0)
    client.removeLayer(map, 'fx_leases')                    // absent: no throw
  })
  it('adds and removes a raster layer', async () => {
    const map = new FakeMap()
    expect(await client.addLayer(map, 'fx_ref')).toEqual(['places:fx_ref:raster'])
    expect(map.sources.get('places:fx_ref').type).toBe('raster')
    client.removeLayer(map, 'fx_ref')
    expect(map.layers.length + map.sources.size).toBe(0)
  })
  it('inserts below beforeId only when that layer exists', async () => {
    const map = new FakeMap()
    map.layers.push({ id: 'labels', paint: {} })
    await client.addLayer(map, 'fx_lines', { beforeId: 'labels' })
    expect(map.before.get('places:fx_lines:line')).toBe('labels')
    await client.addLayer(map, 'fx_stations', { beforeId: 'gone' })
    expect(map.before.get('places:fx_stations:circle')).toBeUndefined()
  })
  it('rejects an unknown slug', async () => {
    await expect(client.addLayer(new FakeMap(), 'nope')).rejects.toThrow(/unknown layer/)
  })
})

describe('registerPmtiles', () => {
  it('registers the pmtiles protocol once per maplibre module', () => {
    const calls: string[] = []
    const ml = { addProtocol: (n: string) => void calls.push(n) }
    class Protocol { tile = () => {} }
    registerPmtiles(ml, { Protocol }); registerPmtiles(ml, { Protocol })
    expect(calls).toEqual(['pmtiles'])
  })
})

describe('wkbToGeometry', () => {
  it('decodes little-endian polygons and big-endian points', () => {
    const poly = new Uint8Array([1, 3, 0, 0, 0, 1, 0, 0, 0, 4, 0, 0, 0,
      ...[0, 0, 1, 0, 1, 1, 0, 0].flatMap((x, i) => Array.from(new Uint8Array(new Float64Array([[0, 0, 1, 0, 1, 1, 0, 0][i]]).buffer)))])
    expect(wkbToGeometry(poly)).toEqual({ type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] })
    const be = new Uint8Array(21); const v = new DataView(be.buffer)
    v.setUint8(0, 0); v.setUint32(1, 1); v.setFloat64(5, 3.5); v.setFloat64(13, -2)
    expect(wkbToGeometry(be)).toEqual({ type: 'Point', coordinates: [3.5, -2] })
  })
})

describe('unwrapAntimeridian', () => {
  const sq = (x0: number, x1: number) => [[[x0, 0], [x1, 0], [x1, 1], [x0, 1], [x0, 0]]]
  it('shifts western parts of a split multipolygon by +360', () => {
    const g = { type: 'MultiPolygon' as const, coordinates: [sq(170, 180), sq(-180, -170), sq(-165, -164)] }
    expect(unwrapAntimeridian(g).coordinates).toEqual([sq(170, 180), sq(180, 190), sq(195, 196)])
  })
  it('leaves a geometry that does not cross untouched (same object)', () => {
    const g = { type: 'MultiPolygon' as const, coordinates: [sq(10, 20), sq(-20, -10)] }
    expect(unwrapAntimeridian(g)).toBe(g)
  })
  it('does not mutate its input', () => {
    const g = { type: 'MultiPolygon' as const, coordinates: [sq(170, 180), sq(-180, -170)] }
    const copy = JSON.stringify(g)
    unwrapAntimeridian(g)
    expect(JSON.stringify(g)).toBe(copy)
  })
})

// derived layers (kind "derived": fx_hs, drawn by the PMTiles of fx_leases) ----
describe('derived layers', () => {
  const hs = by('fx_hs')
  const row = (place_id: string, source_id: string | null, collection = 'fx_hs'): IndexPlace =>
    ({ place_id, name: `name of ${place_id}`, collection, source_id, url: null, bbox: [0, 0, 1, 1] }) as IndexPlace
  const rows = [row('FXH:B-2', 'FX:B-2'), row('FXH:A-1', 'FX:A-1'), row('FXH:NO', null), row('FX:A-1', 'FX:A-1', 'fx_leases')]
  let srv: Awaited<ReturnType<typeof serveFixtures>>
  beforeAll(async () => { srv = await serveFixtures() })
  afterAll(() => srv.close())

  it('the fixture row is derived: no tiles of its own, drawn via fx_leases', () => {
    expect(isDerived(hs)).toBe(true)
    expect(isDerived(by('fx_leases'))).toBe(false)
    expect(hs).toMatchObject({ kind: 'derived', pmtiles: null, source_layer: null, display: { via: 'fx_leases', id_from: 'place_id' } })
    expect(viaLayer(hs, layers)!.slug).toBe('fx_leases')
  })
  it('viaLayer is null when via is not in the manifest or has no tiles of its own (a missing or a raster via)', () => {
    expect(viaLayer(hs, layers.filter((l) => l.slug !== 'fx_leases'))).toBeNull()
    expect(viaLayer({ ...hs, display: { via: 'fx_ref', id_from: 'x' } }, layers)).toBeNull()     // raster
    expect(viaLayer({ ...hs, display: { via: 'fx_hs', id_from: 'x' } }, layers)).toBeNull()      // another derived layer
    expect(viaLayer({ ...hs, display: null }, layers)).toBeNull()
    expect(viaLayer(by('fx_leases'), layers)).toBeNull()                                           // not derived
  })
  it('derivedDisplay lists the pieces of the layer\'s own collection by source_id, sorted, leaving out rows with no source_id', () => {
    const d = derivedDisplay(hs, layers, rows)!
    expect(d.via.slug).toBe('fx_leases')
    expect(d.ids).toEqual(['FX:A-1', 'FX:B-2'])
    expect(d.pieces.map((p) => [p.place_id, p.source_id])).toEqual([['FXH:A-1', 'FX:A-1'], ['FXH:B-2', 'FX:B-2']])
    expect(derivedDisplay(hs, layers.filter((l) => l.slug !== 'fx_leases'), rows)).toBeNull()
    expect(derivedDisplay(by('fx_leases'), layers, rows)).toBeNull()
  })
  it('the filter keeps only the via features that are pieces', () => {
    expect(displayFilter(['FX:A-1', 'FX:B-2'])).toEqual(['in', ['get', 'place_id'], ['literal', ['FX:A-1', 'FX:B-2']]])
  })
  it('layerSpec draws the via PMTiles, filtered to the pieces, with the derived layer\'s own paint and attribution', () => {
    const d = derivedDisplay(hs, layers, rows)!
    const s = layerSpec(hs, { opacity: 0.3 }, d)
    expect(s.sourceId).toBe('places:fx_hs')
    expect(s.source).toEqual({ type: 'vector', url: 'pmtiles://https://storage.oceanmetrics.io/gazetteer/fx_leases/places.pmtiles', attribution: hs.attribution_html })
    expect(s.layers.map((l) => [l.id, l.type, l.source, l['source-layer'], l.filter])).toEqual([
      ['places:fx_hs:fill', 'fill', 'places:fx_hs', 'fx_leases', displayFilter(['FX:A-1', 'FX:B-2'])],
      ['places:fx_hs:line', 'line', 'places:fx_hs', 'fx_leases', displayFilter(['FX:A-1', 'FX:B-2'])]])
    expect(s.layers[0].paint).toEqual({ 'fill-color': '#2a7fb8', 'fill-opacity': 0.3 })     // not the via layer's orange
  })
  it('a vector layer has no filter (regression: the derived branch must not touch ordinary layers)', () => {
    expect(layerSpec(by('fx_leases')).layers.every((l) => !('filter' in l))).toBe(true)
  })
  it('layerSpec of a derived layer without its display source throws, and says what is missing', () => {
    expect(() => layerSpec(hs)).toThrow(/derived layer fx_hs needs its display source/)
  })
  it('client.displaySource reads the pieces from the published index; null for an ordinary layer or a missing via', async () => {
    const c = createClient({ base: srv.base })
    const d = (await c.displaySource('fx_hs'))!
    expect(d.ids).toEqual(['FX:A-1', 'FX:B-2'])
    expect(d.pieces.map((p) => p.name)).toEqual(['Piece one', 'Piece two'])
    expect(await c.displaySource('fx_leases')).toBeNull()
    expect(await c.displaySource('nope')).toBeNull()
    const noVia = createClient({ base: srv.base, fetch: (async (u: any, i: any) => String(u).endsWith('layers.json')
      ? new Response(JSON.stringify({ layers: layers.filter((l) => l.slug !== 'fx_leases') })) : fetch(u, i)) as typeof fetch })
    expect(await noVia.displaySource('fx_hs')).toBeNull()
  })
  it('client.addLayer adds the filtered via source, restyles on a second call, removes cleanly', async () => {
    const c = createClient({ base: srv.base })
    const map = new FakeMap()
    expect(await c.addLayer(map, 'fx_hs', { beforeId: 'labels' })).toEqual(['places:fx_hs:fill', 'places:fx_hs:line'])
    expect(map.sources.get('places:fx_hs').url).toContain('fx_leases/places.pmtiles')
    expect(map.getLayer('places:fx_hs:fill').filter).toEqual(displayFilter(['FX:A-1', 'FX:B-2']))
    await c.addLayer(map, 'fx_hs', { colour: '#00ff00' })
    expect(map.layers.length).toBe(2)
    expect(map.getLayer('places:fx_hs:fill').paint['fill-color']).toBe('#00ff00')
    c.removeLayer(map, 'fx_hs')
    expect(map.layers.length + map.sources.size).toBe(0)
  })
  it('client.addLayer rejects, without touching the map, when via is missing (the app lists the layer but does not draw it)', async () => {
    const noVia = createClient({ base: srv.base, fetch: (async (u: any, i: any) => String(u).endsWith('layers.json')
      ? new Response(JSON.stringify({ layers: layers.filter((l) => l.slug !== 'fx_leases') })) : fetch(u, i)) as typeof fetch })
    const map = new FakeMap()
    await expect(noVia.addLayer(map, 'fx_hs')).rejects.toThrow(/drawn by "fx_leases"/)
    expect(map.layers.length + map.sources.size).toBe(0)
  })
  it('getPlace of a derived place pinned to its layer is null: its geometry is not published (no parquet read)', async () => {
    const c = createClient({ base: srv.base })
    expect(await c.getPlace('FXH:A-1', { slug: 'fx_hs' })).toBeNull()
    expect(srv.requests.some((r) => r.includes('fx_hs/places.parquet'))).toBe(false)
  })
})
