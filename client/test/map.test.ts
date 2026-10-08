import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { unwrapAntimeridian, wkbToGeometry, layerSpec, registerPmtiles, createClient } from '../src/index'
import type { Layer, MapLike } from '../src/index'
import { FIXTURES } from './server'

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
