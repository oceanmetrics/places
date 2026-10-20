import { afterAll, beforeAll, describe, expect, it } from 'vitest'
import { statSync } from 'node:fs'
import { candidateGroups, createClient, creditLine, layerLabel } from '../src/index'
import { serveFixtures, FIXTURES } from './server'

let srv: Awaited<ReturnType<typeof serveFixtures>>
let c: ReturnType<typeof createClient>
beforeAll(async () => { srv = await serveFixtures(); c = createClient({ base: srv.base }) })
afterAll(() => srv.close())

describe('listLayers', () => {
  it('fetches layers.json from the configured base', async () => {
    const layers = await c.listLayers()
    expect(layers.map((l) => l.slug)).toEqual(['fx_leases', 'fx_aoa', 'fx_stations', 'fx_lines', 'fx_ref', 'fx_hs'])
    expect(layers[0]).toMatchObject({ source_layer: 'fx_leases', n: 6, license: 'CC-PDDC' })
    expect(layers[0].source_link).toEqual({ href: 'https://fixture.example/', title: 'Fixture Agency' })   // credit link
    expect(layers.find((l) => l.slug === 'fx_ref')!.raster!.feature_url).toBe('fx_ref/wfs/{source_id}.json')
  })
  it('carries the layer status, first-release date and the pinned parquet (null when the layer has none)', async () => {
    const [leases, aoa, stations] = await c.listLayers()
    expect(aoa).toMatchObject({ status: { value: 'identified', date: '2025-09-19' }, status_label: 'identified 2025-09-19',
      created: '2026-09-15', source_date: '2025-08-19', parquet: 'https://storage.oceanmetrics.io/gazetteer/fx_aoa/places.parquet' })
    expect(aoa.status_history?.map((e) => e.value)).toEqual(['identified'])
    expect(aoa.parquet_sha256).toMatch(/^[0-9a-f]{64}$/)
    expect(leases).toMatchObject({ status: null, status_label: null })
    expect(layerLabel(aoa)).toBe('Fixture AOAs (identified 2025-09-19)')
    expect(layerLabel(leases)).toBe('Fixture leases')
    // a row from an older manifest has none of the fields
    const { status, status_label, ...old } = stations
    expect(layerLabel(old)).toBe('Fixture stations')
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
      expect((await fb.listLayers()).length).toBe(6)
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
    expect((await bad.listLayers()).length).toBe(6)
  })
})

describe('search', () => {
  it('matches keywords, ranked after name matches (regression: "Belgium" missed the "Belgian" Marine Regions EEZ, 2026-10-20)', async () => {
    const hits = await c.search('fixtureland')
    expect(hits.map((h) => h.place_id)).toEqual(['FXR:1'])
    expect(hits[0].keywords).toBe('Fixtureland · FXL')
    expect((await c.search('fixture zone fxl')).map((h) => h.place_id)).toEqual(['FXR:1'])   // name words + a keyword
    // a keyword equal to the whole query ranks with name prefixes, ordered by area (the EEZ was cut off below 12 Navigator
    // "Belgium ..." prefix matches)
    expect((await c.search('fxl')).map((h) => h.place_id)).toEqual(['FXR:1'])
    expect((await c.search('fixtureland', { limit: 1 }))[0].place_id).toBe('FXR:1')
    const zone = await c.search('zone')
    expect(zone.map((h) => h.place_id)).toContain('FXR:2')                                    // name matches still all there
  })
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
      updated: '2026-10-01T12:00:00Z', group_id: null, source_id: 'A-1', url: 'https://fixture.example/leases/A-1', keywords: null,
    })
  })
  it('reads the centroid from the live centroid_lon / centroid_lat columns (regression: it was always null)', async () => {
    const hits = await c.search('', { limit: 100 })
    expect(hits.length).toBe(15)
    expect(hits.every((p) => p.centroid !== null && p.collection !== '' && p.geom_type !== null)).toBe(true)
    expect((await c.search('delta'))[0].centroid).toEqual([-117.5, 39.5])
  })
  it('an antimeridian place has an unwrapped bbox and centroid (east beyond 180)', async () => {
    const [pm] = await c.search('pacific meridian')
    expect(pm.bbox).toEqual([170, 20, 196, 22])
    expect(pm.centroid![0]).toBeGreaterThan(180)
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
  it('filters by collection, one slug or several', async () => {
    expect((await c.search('FX:C-3', { collection: 'fx_aoa' })).map((p) => [p.collection, p.name])).toEqual([['fx_aoa', 'Charlie lease (AOA copy)']])
    expect((await c.search('lease', { collection: ['fx_leases'] })).every((p) => p.collection === 'fx_leases')).toBe(true)
    expect((await c.search('', { collection: [], limit: 100 })).length).toBe(15)
    expect((await c.search('', { collection: 'no_such_slug' })).length).toBe(0)
  })
  it('lists every copy of a place without `group`', async () => {
    const hits = await c.search('zulu')
    expect(hits.map((p) => [p.collection, p.place_id, p.group_id])).toEqual([
      ['fx_aoa', 'AOA:Z9', 'fx_aoa/AOA:Z9'], ['fx_leases', 'FX:Z-9', 'fx_aoa/AOA:Z9']])
  })
  it('with `group`, shows the copy with the lower search_rank and lists the others in `also`', async () => {
    const [h, ...rest] = await c.search('zulu', { group: true })
    expect(rest).toEqual([])
    expect([h.collection, h.place_id, h.also?.map((p) => p.place_id)]).toEqual(['fx_leases', 'FX:Z-9', ['AOA:Z9']])
  })
  it('`prefer` overrides search_rank (an app that wants its own copy)', async () => {
    const [h] = await c.search('zulu', { group: true, prefer: ['fx_aoa'] })
    expect([h.place_id, h.also?.map((p) => p.place_id)]).toEqual(['AOA:Z9', ['FX:Z-9']])
  })
  it('grouping does not touch places without copies, nor the cached index rows', async () => {
    const all = await c.search('', { group: true, limit: 100 })
    expect(all.length).toBe(14)
    expect((await c.search('zulu')).every((p) => p.also === undefined)).toBe(true)
  })
  it('samePlace lists the other copies, [] for a place with none', async () => {
    expect((await c.samePlace('AOA:Z9')).map((p) => [p.collection, p.place_id])).toEqual([['fx_leases', 'FX:Z-9']])
    expect((await c.samePlace('FX:Z-9', { slug: 'fx_leases' })).map((p) => p.place_id)).toEqual(['AOA:Z9'])
    expect(await c.samePlace('FX:A-1')).toEqual([])
    expect(await c.samePlace('NOPE:1')).toEqual([])
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

describe('identify', () => {
  it('names the reference-layer place under a point from the publisher GetFeatureInfo (regression: Marine Regions EEZs were not clickable, 2026-10-20)', async () => {
    const fresh = createClient({ base: srv.base })
    const before = srv.requests.length
    const hits = await fresh.identify('fx_ref', [-36, -36, -34, -34])
    expect(hits.map((h) => [h.place_id, h.collection])).toEqual([['FXR:1', 'fx_ref']])
    expect(srv.requests.slice(before).map((r) => r.split(' ')[1])).toContain('fx_ref/info/-36,-36,-34,-34.json')
  })
  it('nothing there, or a layer without info_url, gives []', async () => {
    expect(await c.identify('fx_ref', [0, 0, 1, 1])).toEqual([])
    expect(await c.identify('fx_leases', [-36, -36, -34, -34])).toEqual([])
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
    expect(f.collection).toBe('fx_leases')
  })
  it('carries the collection it was read from (regression: NMS:PMNM in the legacy places collection had no way back to its layers.json credit)', async () => {
    const fresh = createClient({ base: srv.base })
    expect((await fresh.getPlace('FX:C-3', { slug: 'fx_aoa' }))!.collection).toBe('fx_aoa')
    expect((await fresh.getPlace('AOA:S2'))!.collection).toBe('fx_aoa')
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
    // no walk: only that parquet (and the manifest, which says whether the slug is a reference layer)
    expect(touched.every((p) => p === 'fx_aoa/places.parquet' || p === 'index/layers.json')).toBe(true)
    expect(touched).toContain('fx_aoa/places.parquet')
  })
  it('returns null for an unknown id', async () => {
    expect(await c.getPlace('FX:NOPE')).toBeNull()
  })
  it('a reference (raster) layer place comes from the publisher\'s feature_url, never from a parquet of ours', async () => {
    // marine regions: VLIZ serves one boundary per request (2026-10-16); we hold no public copy
    const fresh = createClient({ base: srv.base })
    const before = srv.requests.length
    const f = (await fresh.getPlace('FXR:1'))!
    const touched = srv.requests.slice(before).map((r) => r.split(' ')[1])
    expect(touched).toContain('fx_ref/wfs/1.json')
    expect(touched.some((p) => p.includes('fx_ref/places.parquet'))).toBe(false)
    expect(f.collection).toBe('fx_ref')
    expect(f.served_by).toBe(`${srv.base}fx_ref/wfs/1.json`)
    expect(f.geometry.type).toBe('MultiPolygon')                         // two publisher features, one place
    expect((f.geometry as any).coordinates.length).toBe(2)
    expect(f.bbox).toEqual([-40, -40, -28, -30])
    expect(f.properties).toMatchObject({ place_id: 'FXR:1', name: 'First fixture zone', source_id: '1', pol_type: '200NM',
      url: 'https://fixture.example/zones/1', license: 'CC-BY-4.0' })
    expect((await fresh.getPlace('FXR:1', { slug: 'fx_ref' }))!.id).toBe('FXR:1')
  })
  it('a reference place the publisher does not return is null; one not in the layer is null when pinned', async () => {
    expect(await c.getPlace('FXR:2')).toBeNull()                          // empty FeatureCollection
    expect(await c.getPlace('FX:A-1', { slug: 'fx_ref' })).toBeNull()
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

describe('candidateGroups', () => {
  // three row groups, as a spatially sorted layer writes them: every place_id range is wide, the bboxes are not
  const col = (path: string, min: unknown, max: unknown) => ({ meta_data: { path_in_schema: path.split('.'), statistics: { min_value: min, max_value: max } } })
  const rg = (n: number, bytes: number, ids: [string, string], b: [number, number, number, number]) => ({
    num_rows: n, total_byte_size: bytes,
    columns: [col('place_id', ...ids), col('bbox.xmin', b[0], b[2]), col('bbox.ymin', b[1], b[3]), col('bbox.xmax', b[0], b[2]), col('bbox.ymax', b[1], b[3])],
  })
  const md = { row_groups: [
    rg(10, 900, ['PSGID:A', 'PSGID:Z'], [0, 50, 10, 60]),        // europe
    rg(10, 100, ['PSGID:A', 'PSGID:Z'], [-130, 20, -110, 40]),   // california
    rg(5, 5000, ['PSGID:A', 'PSGID:Z'], [-180, -80, 180, 85]),   // globe-spanning places
  ] } as any
  it('keeps groups whose place_id range holds the id, smallest first (regression: Navigator place page read ~1 GB, 2026-10-20)', () => {
    expect(candidateGroups(md, 'PSGID:AIBEL1').map((g) => g.rowStart)).toEqual([10, 0, 20])
    expect(candidateGroups(md, 'OTHER:1')).toEqual([])
  })
  it('the index bbox leaves only groups that can contain the place', () => {
    expect(candidateGroups(md, 'PSGID:AIBEL1', [2.2, 51.1, 3.4, 51.9])).toEqual([
      { rowStart: 0, rowEnd: 10, bytes: 900 }, { rowStart: 20, rowEnd: 25, bytes: 5000 }])
  })
  it('an unwrapped (antimeridian) box is tested on latitude only', () => {
    expect(candidateGroups(md, 'PSGID:X', [170, 30, 190, 35]).map((g) => g.rowStart)).toEqual([10, 20])
  })
})
