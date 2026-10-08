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
  it('falls back to the root layers.json when index/layers.json is 404 or 403', async () => {
    for (const status of [404, 403]) {
      const seen: string[] = []
      const f = ((url: any, init?: any) => {
        seen.push(String(url))
        return String(url).endsWith('index/layers.json') ? Promise.resolve(new Response(null, { status })) : fetch(url, init)
      }) as typeof fetch
      const fb = createClient({ base: srv.base, fetch: f })
      expect((await fb.listLayers()).length).toBe(4)
      expect(seen).toEqual([srv.base + 'index/layers.json', srv.base + 'layers.json'])
    }
  })
  it('an explicit layersUrl is used as is, with no fallback', async () => {
    const seen: string[] = []
    const f = ((url: any, init?: any) => { seen.push(String(url)); return fetch(url, init) }) as typeof fetch
    const ex = createClient({ base: srv.base, layersUrl: srv.base + 'index/nope.json', fetch: f })
    await expect(ex.listLayers()).rejects.toThrow(/layers\.json: 404/)
    expect(seen).toEqual([srv.base + 'index/nope.json'])
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
      place_id: 'FX:A-1', name: 'Alpha lease', authority: 'FX', place_type: 'lease', geom_type: 'Polygon',
      collection: 'fx_leases', bbox: [-124, 33, -123, 34],
      centroid: [-123.5, 33.5], area_km2: expect.any(Number), license: 'CC-PDDC',
      attribution: 'Fixture Agency, via MarineCadastre. Processed by Ocean Metrics.', version: '1.0.3',
      updated: '2026-10-01T12:00:00Z',
    })
  })
  it('reads the centroid from the live centroid_lon / centroid_lat columns (regression: it was always null)', async () => {
    const hits = await c.search('', { limit: 100 })
    expect(hits.length).toBe(9)
    expect(hits.every((p) => p.centroid !== null && p.collection !== '' && p.geom_type !== null)).toBe(true)
    expect((await c.search('delta'))[0].centroid).toEqual([-117.5, 39.5])
  })
  it('a place_id in two collections is two hits, told apart by collection', async () => {
    const hits = await c.search('FX:C-3')
    expect(hits.map((p) => [p.collection, p.name]).sort()).toEqual([['fx_aoa', 'Charlie lease (AOA copy)'], ['fx_leases', 'Charlie lease']])
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
  it('an unwrapped index bbox (east beyond 180) matches a query on either side of the antimeridian', async () => {
    expect((await c.search('', { bbox: [-180, 15, -170, 25] })).map((p) => p.place_id)).toEqual(['FX:PM'])   // west side
    expect((await c.search('', { bbox: [175, 15, 179, 25] })).map((p) => p.place_id)).toEqual(['FX:PM'])    // east side
    expect((await c.search('', { bbox: [-160, 15, -150, 25] })).map((p) => p.place_id)).toEqual([])         // east edge 196 is -164
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
  it('slug pins the collection when a place_id is in two (regression: unpinned guessing returned only the first)', async () => {
    const fresh = createClient({ base: srv.base })
    expect((await fresh.getPlace('FX:C-3', { slug: 'fx_aoa' }))!.properties.name).toBe('Charlie lease (AOA copy)')
    expect((await fresh.getPlace('FX:C-3', { slug: 'fx_leases' }))!.properties.name).toBe('Charlie lease')
    // a pinned lookup does not teach the unpinned one: FX ids still start with the FX collection
    expect((await fresh.getPlace('FX:C-3'))!.properties.name).toBe('Charlie lease')
  })
  it('a pinned lookup reads only that collection, and null when it is not there', async () => {
    const fresh = createClient({ base: srv.base })
    const before = srv.requests.length
    expect(await fresh.getPlace('FX:A-1', { slug: 'fx_aoa' })).toBeNull()
    const touched = srv.requests.slice(before).map((r) => r.split(' ')[1])
    expect(touched.every((p) => p === 'fx_aoa/places.parquet')).toBe(true)      // no manifest fetch, no walk
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
  it('a place_id in two collections credits both, unless pinned by collection (keyed on collection + place_id)', async () => {
    expect(await c.creditsFor('FX:C-3')).toBe('NOAA AOA program; Fixture Agency, via MarineCadastre. Processed by Ocean Metrics.')
    expect(await c.creditsFor({ collection: 'fx_aoa', place_id: 'FX:C-3' })).toBe('NOAA AOA program. Processed by Ocean Metrics.')
    const [hit] = (await c.search('FX:C-3')).filter((p) => p.collection === 'fx_leases')
    expect(await c.creditsFor(hit)).toBe('Fixture Agency, via MarineCadastre. Processed by Ocean Metrics.')
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
