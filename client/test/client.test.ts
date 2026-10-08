import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { statSync } from 'node:fs'
import { createClient, creditLine } from '../src/index'
import { serveFixtures, FIXTURES } from './server'

let srv: Awaited<ReturnType<typeof serveFixtures>>
let c: ReturnType<typeof createClient>
beforeAll(async () => { srv = await serveFixtures(); c = createClient({ base: srv.base }) })
afterAll(() => srv.close())

describe('listLayers', () => {
  it('fetches layers.json from the configured base', async () => {
    const layers = await c.listLayers()
    expect(layers.map((l) => l.slug)).toEqual(['fx_leases', 'fx_aoa', 'fx_stations', 'fx_lines'])
    expect(layers[0]).toMatchObject({ source_layer: 'fx_leases', n: 6, license: 'CC-PDDC' })
  })
  it('getLayer rejects an unknown slug', async () => {
    await expect(c.getLayer('nope')).rejects.toThrow(/unknown layer "nope"/)
  })
  it('an unreachable manifest rejects and is not cached', async () => {
    const bad = createClient({ base: srv.base + 'missing/' })
    await expect(bad.listLayers()).rejects.toThrow(/layers\.json: 404/)
    bad.configure({ base: srv.base })
    expect((await bad.listLayers()).length).toBe(4)
  })
})

describe('search', () => {
  it('matches words in the name, case and accent insensitive', async () => {
    expect((await c.search('BRAVO')).map((p) => p.place_id)).toEqual(['FX:B-2'])
    expect((await c.search('lease alpha')).map((p) => p.place_id)).toEqual(['FX:A-1'])
  })
  it('returns the index columns in client shapes', async () => {
    const [p] = await c.search('alpha')
    expect(p).toEqual({
      place_id: 'FX:A-1', name: 'Alpha lease', authority: 'FX', place_type: 'lease', bbox: [-124, 33, -123, 34],
      centroid: [-123.5, 33.5], area_km2: expect.any(Number), license: 'CC-PDDC',
      attribution: 'Fixture Agency, via MarineCadastre. Processed by Ocean Metrics.', version: '1.0.3',
      updated: '2026-10-01T12:00:00.000Z',
    })
  })
  it('filters by type and authority', async () => {
    expect((await c.search('', { type: 'aoa' })).map((p) => p.place_id).sort()).toEqual(['AOA:N1', 'AOA:S2'])
    expect((await c.search('area', { authority: 'aoa' })).length).toBe(2)
    expect((await c.search('lease', { type: ['easement', 'aoa'] })).length).toBe(0)
    expect((await c.search('', { type: 'easement' })).map((p) => p.place_id)).toEqual(['FX:D-4'])
  })
  it('filters by bbox, including one that crosses the antimeridian', async () => {
    expect((await c.search('', { bbox: [-125, 32.5, -122.5, 34.5] })).map((p) => p.place_id)).toEqual(['FX:A-1'])
    const ids = (await c.search('', { bbox: [170, 15, -170, 25] })).map((p) => p.place_id)
    expect(ids).toEqual(['FX:PM'])
  })
  it('ranks exact name, then prefix, then substring; limit applies', async () => {
    expect((await c.search('lease', { limit: 3 })).length).toBe(3)
    const r = await c.search('delta easement')
    expect(r[0].place_id).toBe('FX:D-4')
    expect((await c.search('FX:Z-9'))[0].place_id).toBe('FX:Z-9')   // by place_id
  })
  it('reads the zstd index with range requests, once', async () => {
    const before = srv.requests.filter((r) => r.includes('places_index.parquet')).length
    await c.search('alpha'); await c.search('bravo')
    expect(srv.requests.filter((r) => r.includes('places_index.parquet')).length).toBe(before)   // cached
    expect(srv.requests.some((r) => r.startsWith('GET index/places_index.parquet bytes='))).toBe(true)
  })
})

describe('getPlace', () => {
  it('returns a GeoJSON Feature with the properties and decoded WKB geometry', async () => {
    const f = (await c.getPlace('FX:B-2'))!
    expect(f.id).toBe('FX:B-2')
    expect(f.bbox).toEqual([-122, 35, -121, 36])
    expect(f.geometry).toEqual({ type: 'Polygon', coordinates: [[[-122, 35], [-121, 35], [-121, 36], [-122, 36], [-122, 35]]] })
    expect(f.properties).toMatchObject({ place_id: 'FX:B-2', name: 'Bravo lease', status: 'cancelled', authority: 'FX' })
    expect(f.properties).not.toHaveProperty('geometry')
  })
  it('finds a place in a different authority via the layers manifest', async () => {
    expect((await c.getPlace('AOA:S2'))!.properties.name).toBe('Southern aquaculture area')
  })
  it('returns null for an unknown id', async () => {
    expect(await c.getPlace('FX:NOPE')).toBeNull()
  })
  it('uses a filtered range read: only the matching row group, not the whole file', async () => {
    const fresh = createClient({ base: srv.base })
    const path = 'fx_big/places.parquet'
    const before = srv.bytes.get(path) ?? 0
    const f = await fresh.getPlace('BIG:0300', { slug: 'fx_big' })
    expect(f!.properties.name).toBe('Big place 300')
    const sent = (srv.bytes.get(path) ?? 0) - before
    expect(sent).toBeGreaterThan(0)
    expect(sent).toBeLessThan(statSync(FIXTURES + path).size / 2)
  })
  it('keeps antimeridian parts split by default', async () => {
    const f = (await c.getPlace('FX:PM'))!
    expect(f.geometry.type).toBe('MultiPolygon')
    expect(f.bbox).toEqual([-180, 20, 180, 22])
  })
  it('unwrap: true gives contiguous longitudes beyond 180', async () => {
    const f = (await c.getPlace('FX:PM', { unwrap: true }))!
    const xs = (f.geometry as any).coordinates.flat(2).map((p: number[]) => p[0])
    expect(Math.min(...xs)).toBe(170)
    expect(Math.max(...xs)).toBe(196)          // the -164 part, +360
    expect(f.bbox).toEqual([170, 20, 196, 22])
  })
})

describe('creditsFor', () => {
  it('dedupes place ids that share an attribution', async () => {
    expect(await c.creditsFor(['FX:A-1', 'FX:B-2', 'FX:A-1'])).toBe('Fixture Agency, via MarineCadastre. Processed by Ocean Metrics.')
  })
  it('combines authorities and says "Processed by Ocean Metrics." once', async () => {
    expect(await c.creditsFor(['FX:A-1', 'AOA:N1'])).toBe('Fixture Agency, via MarineCadastre; NOAA AOA program. Processed by Ocean Metrics.')
  })
  it('takes slugs, and slugs + ids together', async () => {
    expect(await c.creditsFor('fx_aoa')).toBe('NOAA AOA program. Processed by Ocean Metrics.')
    expect(await c.creditsFor(['fx_leases', 'FX:A-1', 'fx_stations'])).toBe(
      'Fixture Agency, via MarineCadastre; CalCOFI. Processed by Ocean Metrics.')
  })
  it('html: true uses the layers\' linked attribution', async () => {
    expect(await c.creditsFor(['fx_leases'], { html: true })).toBe(
      '<a href="https://fixture.example/">Fixture Agency</a>, via MarineCadastre. Processed by Ocean Metrics.')
  })
  it('skips unknown refs', async () => {
    expect(await c.creditsFor(['nope', 'FX:NOPE'])).toBe('')
  })
})

describe('creditLine', () => {
  it('merges, dedupes and normalises whitespace', () => {
    expect(creditLine(['A  b. Processed by Ocean Metrics.', 'A b. Processed by Ocean Metrics.', 'C'])).toBe('A b; C. Processed by Ocean Metrics.')
    expect(creditLine([])).toBe('')
  })
})
