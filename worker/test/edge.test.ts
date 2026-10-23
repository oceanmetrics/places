// the edge cache for immutable keys: the rule, hit/miss, range slicing, If-Range/ETag, CORS, the cap, the key gates ----
import { beforeAll, describe, expect, it } from 'vitest'
import { env } from 'cloudflare:test'
import { handle } from '../src/index'
import { isImmutable } from '../src/paths'
import { conditionalStatus, ifRangeAllows } from '../src/range'
import { EDGE_CACHE_MAX_BYTES, IMMUTABLE_CACHE_CONTROL, SIZE_HEADER, edgeCacheKey } from '../src/edge'
import { GOOD_KEY, ORIGIN, UNLISTED_PARQUET, get, now, rig, seed } from './helpers'

const OBIS = 'obis-h3/v20261012/species_flat/res=3/p=81283ffffffffff.parquet'
const BODY = new Uint8Array(300_000).map((_, i) => (i * 17 + 9) % 247)
const COG_AT_CAP   = 'marine-atlas/cog_3857/00000000000000aa_3857.tif'
const COG_OVER_CAP = 'marine-atlas/cog_3857/00000000000000bb_3857.tif'
const SIZE = BODY.length

beforeAll(async () => {
  await seed()
  await env.BUCKET.put(OBIS, BODY, { httpMetadata: { contentType: 'application/vnd.apache.parquet' } })
  await env.BUCKET.put(COG_AT_CAP, new Uint8Array(EDGE_CACHE_MAX_BYTES).fill(1))
  await env.BUCKET.put(COG_OVER_CAP, new Uint8Array(EDGE_CACHE_MAX_BYTES + 1).fill(2))
  await env.BUCKET.put('basemap/gebco/far.pmtiles', BODY)
})

// a fresh cache, a ctx whose waitUntil promises can be awaited, and an R2 bucket that counts reads
let n = 0
async function edgeRig(over: Parameters<typeof rig>[0] = {}) {
  const r = rig(over)
  const calls = { get: [] as string[], head: [] as string[] }
  const real = r.env.BUCKET
  r.env.BUCKET = {
    get:  (k: string, o?: R2GetOptions) => { calls.get.push(k); return real.get(k, o) },
    head: (k: string) => { calls.head.push(k); return real.head(k) },
  } as unknown as R2Bucket
  const cache = await caches.open(`edge-test-${n++}`)
  const pending: Promise<unknown>[] = []
  const ctx = { waitUntil: (p: Promise<unknown>) => { pending.push(p) } }
  const run = async (req: Request) => handle(req, r.env, now, { ctx, cache })
  const settle = async () => { while (pending.length) await pending.shift() }
  return { ...r, calls, cache, run, settle }
}
const bytes = async (res: Response) => new Uint8Array(await res.arrayBuffer())

describe('isImmutable(): the rule', () => {
  const yes = [
    OBIS,
    'obis-h3/v20260728/all/res=1/data_0.parquet',
    'obis-h3/v20261012/files.parquet',
    'obis-h3/v20261012/taxon/rank=phylum/taxon=Apicomplexa%20incertae%20sedis/res=1/data_0.parquet',
    'marine-atlas/cog_3857/000108e0a038c385_3857.tif',
    'marine-atlas/v7/cog_3857/000108e0a038c385_3857.tif',
    'marine-atlas/cog/global05/000108e0a038c385.tif',
    'marine-atlas/native/rng_iucn/0007c35e939c220a.pmtiles',
    'atlas/aquamaps_native/registry/v2/registry.parquet',
    'basemap/gebco/v20261101/core.pmtiles',
  ]
  const no = [
    'obis-h3/latest.json', 'obis-h3/collection.json', 'obis-h3/v20261012/collection.json', 'obis-h3/v20261012/release.json',
    'obis-h3/v20261012/items/all.json', 'obis-h3/v20261012/README.md', 'obis-h3/vnext/a.parquet', 'obis-h3/v20261012x/a.parquet',
    'obis-h3/_history/2026-10-23/v20261012/files.parquet', 'obis-h3/v20261012/_history/files.parquet',
    'basemap/gebco/core.pmtiles', 'basemap/gebco/far.pmtiles', 'basemap/osm/land.pmtiles',
    'gazetteer/mpa/places.parquet', 'gazetteer/mpa/places.pmtiles', 'gazetteer/layers.json', 'gazetteer/catalog.json',
    'gazetteer/index/crosswalk.parquet',
    'indicators/indicators.json', 'indicators/changes/latest.json', 'indicators/feeds/all.xml', 'indicators/coverage.parquet',
    'indicators/values/indicator=sst/coll=mpa/data.parquet',
    'atlas/catalog.json', 'atlas/aquamaps_eov/collection.json', 'atlas/aquamaps_eov/score_risk_3857.tif',
    'atlas/aquamaps_native/registry.parquet', 'atlas/v2/registry.parquet', 'atlas/aquamaps_native/registry/v2/README.md',
    'marine-atlas/assets.parquet', 'marine-atlas/tables/cog_3857.parquet', 'marine-atlas/v9/manifest.json',
    'marine-atlas/v3/cell.tif', 'marine-atlas/latest.txt', 'marine-atlas/versions.json',
    'marine-atlas/cog_3857/000108E0A038C385_3857.tif', 'marine-atlas/cog_3857/000108e0a038c385_3857.json',
    'atlas-restricted/coll/v1/data.parquet', 'issues/apps-8/v1/a.parquet', 'index.html', 'nc.parquet', '',
  ]
  for (const k of yes) it(`${k} -> immutable`, () => expect(isImmutable(k)).toBe(true))
  for (const k of no) it(`${k || '(empty)'} -> mutable`, () => expect(isImmutable(k)).toBe(false))
  it('the unlisted bucket is never immutable, whatever the key', () => {
    expect(isImmutable(OBIS, 'unlisted')).toBe(false)
    expect(isImmutable('gazetteer/mr_eez/places.parquet', 'unlisted')).toBe(false)
  })
  it('the cap is 8 MiB and the header a year, immutable', () => {
    expect(EDGE_CACHE_MAX_BYTES).toBe(8 * 1024 * 1024)
    expect(IMMUTABLE_CACHE_CONTROL).toBe('public, max-age=31536000, immutable')
  })
  it('the cache key is the public URL without the query', () => {
    expect(edgeCacheKey(OBIS).url).toBe(`https://storage.oceanmetrics.io/${OBIS}`)
    expect(edgeCacheKey('obis-h3/v1/taxon=A%20b/x?.parquet').url).toBe('https://storage.oceanmetrics.io/obis-h3/v1/taxon=A%2520b/x%3F.parquet')
  })
})

describe('If-Range and date preconditions (pure)', () => {
  const etag = '"abc"', lm = 'Fri, 23 Oct 2026 18:25:04 GMT'
  const H = (o: Record<string, string>) => new Headers(o)
  it('If-Range: absent, a strong match and the exact date honour the Range; others do not', () => {
    expect(ifRangeAllows(H({}), etag, lm)).toBe(true)
    expect(ifRangeAllows(H({ 'if-range': '"abc"' }), etag, lm)).toBe(true)
    expect(ifRangeAllows(H({ 'if-range': '"xyz"' }), etag, lm)).toBe(false)
    expect(ifRangeAllows(H({ 'if-range': 'W/"abc"' }), etag, lm)).toBe(false)
    expect(ifRangeAllows(H({ 'if-range': lm }), etag, lm)).toBe(true)
    expect(ifRangeAllows(H({ 'if-range': 'Fri, 23 Oct 2026 18:25:05 GMT' }), etag, lm)).toBe(false)
    expect(ifRangeAllows(H({ 'if-range': 'garbage' }), etag, lm)).toBe(false)
  })
  it('conditionalStatus: tags first, then If-Unmodified-Since (412) and If-Modified-Since (304)', () => {
    expect(conditionalStatus(H({ 'if-none-match': '"abc"' }), etag, lm)).toBe(304)
    expect(conditionalStatus(H({ 'if-match': '"xyz"' }), etag, lm)).toBe(412)
    expect(conditionalStatus(H({ 'if-modified-since': lm }), etag, lm)).toBe(304)
    expect(conditionalStatus(H({ 'if-modified-since': 'Thu, 22 Oct 2026 00:00:00 GMT' }), etag, lm)).toBe(null)
    expect(conditionalStatus(H({ 'if-none-match': '"xyz"', 'if-modified-since': lm }), etag, lm)).toBe(null)
    expect(conditionalStatus(H({ 'if-unmodified-since': 'Thu, 22 Oct 2026 00:00:00 GMT' }), etag, lm)).toBe(412)
    expect(conditionalStatus(H({ 'if-unmodified-since': lm }), etag, lm)).toBe(null)
    expect(conditionalStatus(H({}), etag, lm)).toBe(null)
  })
})

describe('edge cache: miss then hit', () => {
  it('a suffix range misses (from R2, the copy stored after the response), then hits with no R2 read', async () => {
    const e = await edgeRig()
    const req = () => get(`/${OBIS}`, { headers: { range: 'bytes=-262144', 'cf-connecting-ip': '203.0.113.7' } })
    const miss = await e.run(req())
    expect(miss.status).toBe(206)
    expect(miss.headers.get('x-om-cache')).toBe('miss')
    expect(miss.headers.get('cache-control')).toBe(IMMUTABLE_CACHE_CONTROL)
    expect(miss.headers.get('content-range')).toBe(`bytes ${SIZE - 262144}-${SIZE - 1}/${SIZE}`)
    expect(await bytes(miss)).toEqual(BODY.slice(SIZE - 262144))
    await e.settle()
    expect(e.calls.get).toEqual([OBIS, OBIS])   // the range, then the whole object for the copy
    const stored = await e.cache.match(edgeCacheKey(OBIS))
    expect(stored?.headers.get(SIZE_HEADER)).toBe(String(SIZE))
    expect(stored?.headers.get('content-range')).toBeNull()
    await stored?.arrayBuffer()

    const hit = await e.run(req())
    expect(hit.status).toBe(206)
    expect(hit.headers.get('x-om-cache')).toBe('hit')
    expect(hit.headers.get('cache-control')).toBe(IMMUTABLE_CACHE_CONTROL)
    expect(hit.headers.get('content-range')).toBe(`bytes ${SIZE - 262144}-${SIZE - 1}/${SIZE}`)
    expect(hit.headers.get('content-length')).toBe('262144')
    expect(hit.headers.get('content-type')).toBe('application/vnd.apache.parquet')
    expect(hit.headers.get('accept-ranges')).toBe('bytes')
    expect(hit.headers.get('etag')).toBe(miss.headers.get('etag'))
    expect(hit.headers.get('last-modified')).toBe(miss.headers.get('last-modified'))
    expect(hit.headers.get(SIZE_HEADER)).toBeNull()
    expect(await bytes(hit)).toEqual(BODY.slice(SIZE - 262144))
    expect(e.calls.get).toEqual([OBIS, OBIS])   // no R2 read on the hit
    // metering unchanged: one row per request, the hit counts its bytes, the anonymous limiter saw both
    expect(e.points).toHaveLength(2)
    expect(e.points[1].blobs.slice(2, 5)).toEqual(['parquet', '', 'anonymous'])
    expect(e.points[1].doubles).toEqual([262144, 206])
    expect(e.limited.anon).toEqual(['203.0.113.7', '203.0.113.7'])
  })

  it('an un-ranged miss streams to the client and the cache at once (one R2 read), then hits', async () => {
    const e = await edgeRig()
    const miss = await e.run(get(`/${OBIS}`))
    expect(miss.status).toBe(200)
    expect(await bytes(miss)).toEqual(BODY)
    await e.settle()
    expect(e.calls.get).toEqual([OBIS])
    const hit = await e.run(get(`/${OBIS}`))
    expect(hit.status).toBe(200)
    expect(hit.headers.get('x-om-cache')).toBe('hit')
    expect(hit.headers.get('content-length')).toBe(String(SIZE))
    expect(await bytes(hit)).toEqual(BODY)
    expect(e.calls.get).toEqual([OBIS])
  })

  it('HEAD misses from R2 and stores the copy; HEAD + Range: bytes=0- then answers 206 from the copy', async () => {
    const e = await edgeRig()
    const h1 = await e.run(get(`/${OBIS}`, { method: 'HEAD' }))
    expect(h1.status).toBe(200)
    expect(h1.headers.get('x-om-cache')).toBe('miss')
    await e.settle()
    const h2 = await e.run(get(`/${OBIS}`, { method: 'HEAD', headers: { range: 'bytes=0-' } }))
    expect(h2.status).toBe(206)
    expect(h2.headers.get('x-om-cache')).toBe('hit')
    expect(h2.headers.get('content-range')).toBe(`bytes 0-${SIZE - 1}/${SIZE}`)
    expect(h2.headers.get('content-length')).toBe(String(SIZE))
    expect(h2.body).toBeNull()
  })

  it('a failing cache lookup falls back to R2', async () => {
    const e = await edgeRig()
    const broken = { match: async () => { throw new Error('down') }, put: async () => {}, delete: async () => false } as unknown as Cache
    const res = await handle(get(`/${OBIS}`, { headers: { range: 'bytes=0-9' } }), e.env, now,
      { ctx: { waitUntil: () => {} }, cache: broken })
    expect(res.status).toBe(206)
    expect(await bytes(res)).toEqual(BODY.slice(0, 10))
  })
})

describe('edge cache: ranges sliced from the copy', () => {
  const cases: [string, number, number][] = [
    ['bytes=0-0', 0, 0], ['bytes=0-99', 0, 99], ['bytes=299900-299999', 299900, 299999], ['bytes=299990-', 299990, 299999],
    ['bytes=299990-400000', 299990, 299999], ['bytes=-262144', SIZE - 262144, SIZE - 1], ['bytes=-1', SIZE - 1, SIZE - 1],
    ['bytes=-400000', 0, SIZE - 1], ['bytes=150000-150001', 150000, 150001],
  ]
  it('both ends, the middle, open-ended and suffix ranges equal the R2 answer byte for byte; 416 past the end', async () => {
    const e = await edgeRig()
    await (await e.run(get(`/${OBIS}`))).arrayBuffer()
    await e.settle()
    const before = e.calls.get.length
    for (const [range, start, end] of cases) {
      const res = await e.run(get(`/${OBIS}`, { headers: { range } }))
      expect(res.status, range).toBe(206)
      expect(res.headers.get('x-om-cache'), range).toBe('hit')
      expect(res.headers.get('content-range'), range).toBe(`bytes ${start}-${end}/${SIZE}`)
      expect(res.headers.get('content-length'), range).toBe(String(end - start + 1))
      expect(await bytes(res), range).toEqual(BODY.slice(start, end + 1))
      // the same request straight from R2 (no edge) gives the same bytes and range
      const direct = await handle(get(`/${OBIS}`, { headers: { range } }), rig().env, now)
      expect(direct.headers.get('content-range'), range).toBe(res.headers.get('content-range'))
      expect(await bytes(direct), range).toEqual(BODY.slice(start, end + 1))
    }
    const past = await e.run(get(`/${OBIS}`, { headers: { range: `bytes=${SIZE}-` } }))
    expect(past.status).toBe(416)
    expect(past.headers.get('content-range')).toBe(`bytes */${SIZE}`)
    expect(past.headers.get('access-control-allow-origin')).toBe('*')
    expect(e.calls.get.length).toBe(before)
  })
})

describe('edge cache: validators', () => {
  it('If-Range with the ETag or Last-Modified slices; another ETag, a weak one or another date gives the whole 200', async () => {
    const e = await edgeRig()
    const first = await e.run(get(`/${OBIS}`, { headers: { range: 'bytes=0-9' } }))
    const etag = first.headers.get('etag')!, lm = first.headers.get('last-modified')!
    await first.arrayBuffer()
    for (const phase of ['miss', 'hit']) {
      if (phase === 'hit') await e.settle()
      const ok = await e.run(get(`/${OBIS}`, { headers: { range: 'bytes=0-9', 'if-range': etag } }))
      expect(ok.status, phase).toBe(206)
      expect(await bytes(ok)).toEqual(BODY.slice(0, 10))
      const okDate = await e.run(get(`/${OBIS}`, { headers: { range: 'bytes=0-9', 'if-range': lm } }))
      expect(okDate.status, phase).toBe(206)
      await okDate.arrayBuffer()
      for (const v of ['"0000"', `W/${etag}`, 'Thu, 01 Jan 2026 00:00:00 GMT']) {
        const full = await e.run(get(`/${OBIS}`, { headers: { range: 'bytes=0-9', 'if-range': v } }))
        expect(full.status, `${phase} ${v}`).toBe(200)
        expect(full.headers.get('content-range')).toBeNull()
        expect(await bytes(full)).toEqual(BODY)
      }
    }
  })

  it('on a hit, If-None-Match is 304 and If-Match a mismatch 412, both with the ETag and no body', async () => {
    const e = await edgeRig()
    const first = await e.run(get(`/${OBIS}`))
    const etag = first.headers.get('etag')!
    await first.arrayBuffer()
    await e.settle()
    const nm = await e.run(get(`/${OBIS}`, { headers: { 'if-none-match': etag, range: 'bytes=0-9' } }))
    expect(nm.status).toBe(304)
    expect(nm.headers.get('etag')).toBe(etag)
    expect(nm.headers.get('x-om-cache')).toBe('hit')
    expect(nm.body).toBeNull()
    const im = await e.run(get(`/${OBIS}`, { headers: { 'if-match': '"nope"' } }))
    expect(im.status).toBe(412)
    const match = await e.run(get(`/${OBIS}`, { headers: { 'if-match': etag, range: 'bytes=5-9' } }))
    expect(match.status).toBe(206)
    expect(await bytes(match)).toEqual(BODY.slice(5, 10))
    expect(e.calls.get).toEqual([OBIS])
  })
})

describe('edge cache: CORS and the key gates', () => {
  it('a hit keeps CORS: the echoed Origin for a matching key (with Vary), * keyless, x-om-cache exposed', async () => {
    const e = await edgeRig()
    await (await e.run(get(`/${OBIS}`))).arrayBuffer()
    await e.settle()
    const keyed = await e.run(get(`/${OBIS}?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9', origin: ORIGIN } }))
    expect(keyed.headers.get('x-om-cache')).toBe('hit')
    expect(keyed.headers.get('access-control-allow-origin')).toBe(ORIGIN)
    expect(keyed.headers.get('vary')).toContain('Origin')
    expect(keyed.headers.get('access-control-expose-headers')).toContain('content-range')
    expect(keyed.headers.get('access-control-expose-headers')).toContain('x-om-cache')
    expect(e.points.at(-1)!.blobs.slice(0, 5)).toEqual([GOOD_KEY, 'erddap-places', 'parquet', ORIGIN, 'free'])
    await keyed.arrayBuffer()
    const anon = await e.run(get(`/${OBIS}`, { headers: { range: 'bytes=0-9', origin: ORIGIN } }))
    expect(anon.headers.get('access-control-allow-origin')).toBe('*')
    await anon.arrayBuffer()
    // the checks run before the cache: a bad key or origin is still a 403, the anonymous limit still a 429
    const bad = await e.run(get(`/${OBIS}?key=WRONGKEY123456`, { headers: { range: 'bytes=0-9' } }))
    expect(bad.status).toBe(403)
    const evil = await e.run(get(`/${OBIS}?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9', origin: 'https://evil.example.com' } }))
    expect(evil.status).toBe(403)
    const limited = await (await edgeRig({ anonOk: false })).run(get(`/${OBIS}`, { headers: { range: 'bytes=0-9' } }))
    expect(limited.status).toBe(429)
  })

  it('regression: a keyless unlisted read is never served from the cache, even when a copy sits at its URL', async () => {
    const e = await edgeRig()
    // a keyed unlisted read stores nothing
    const keyed = await e.run(get(`/unlisted/gazetteer/mr_eez/places.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9' } }))
    expect(keyed.status).toBe(206)
    expect(keyed.headers.get('x-om-cache')).toBeNull()
    expect(keyed.headers.get('cache-control')).not.toContain('immutable')
    await keyed.arrayBuffer()
    await e.settle()
    expect(await e.cache.match(edgeCacheKey('gazetteer/mr_eez/places.parquet'))).toBeUndefined()
    expect(await e.cache.match(edgeCacheKey('unlisted/gazetteer/mr_eez/places.parquet'))).toBeUndefined()
    // plant copies at both possible URLs: keyless is still 403, keyed still reads the UNLISTED bucket
    for (const k of ['gazetteer/mr_eez/places.parquet', 'unlisted/gazetteer/mr_eez/places.parquet']) {
      await e.cache.put(edgeCacheKey(k), new Response('POISON', { headers: { [SIZE_HEADER]: '6', 'cache-control': IMMUTABLE_CACHE_CONTROL } }))
    }
    const anon = await e.run(get('/unlisted/gazetteer/mr_eez/places.parquet', { headers: { range: 'bytes=0-9' } }))
    expect(anon.status).toBe(403)
    expect((await anon.json() as { error: string }).error).toBe('key_required')
    const again = await e.run(get(`/unlisted/gazetteer/mr_eez/places.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9' } }))
    expect(again.status).toBe(206)
    expect(await bytes(again)).toEqual(UNLISTED_PARQUET.slice(0, 10))
  })

  it('mutable keys keep their headers and never enter the cache (gazetteer, basemap, json)', async () => {
    const e = await edgeRig()
    for (const [path, cc] of [['/gazetteer/mpa/places.parquet', 'public, max-age=300'], ['/basemap/gebco/far.pmtiles', 'public, max-age=300'],
      ['/gazetteer/layers.json', 'public, max-age=60']] as const) {
      const res = await e.run(get(path, { headers: { range: 'bytes=0-9' } }))
      expect([200, 206], path).toContain(res.status)
      expect(res.headers.get('cache-control'), path).toBe(cc)
      expect(res.headers.get('x-om-cache'), path).toBeNull()
      await res.arrayBuffer()
    }
    await e.settle()
    for (const k of ['gazetteer/mpa/places.parquet', 'basemap/gebco/far.pmtiles', 'gazetteer/layers.json']) {
      expect(await e.cache.match(edgeCacheKey(k)), k).toBeUndefined()
    }
  })
})

describe('edge cache: the cap', () => {
  it('an object of exactly the cap is kept whole and sliced', async () => {
    const e = await edgeRig()
    const miss = await e.run(get(`/${COG_AT_CAP}`, { headers: { range: 'bytes=-16' } }))
    expect(miss.headers.get('x-om-cache')).toBe('miss')
    await miss.arrayBuffer()
    await e.settle()
    const hit = await e.run(get(`/${COG_AT_CAP}`, { headers: { range: 'bytes=-16' } }))
    expect(hit.headers.get('x-om-cache')).toBe('hit')
    expect(hit.headers.get('content-range')).toBe(`bytes ${EDGE_CACHE_MAX_BYTES - 16}-${EDGE_CACHE_MAX_BYTES - 1}/${EDGE_CACHE_MAX_BYTES}`)
    expect(await bytes(hit)).toEqual(new Uint8Array(16).fill(1))
  })

  it('one byte over: ranges pass through to R2 every time, with the immutable header, and nothing is stored', async () => {
    const e = await edgeRig()
    for (let i = 0; i < 2; i++) {
      const res = await e.run(get(`/${COG_OVER_CAP}`, { headers: { range: 'bytes=0-15' } }))
      expect(res.status).toBe(206)
      expect(res.headers.get('x-om-cache')).toBe('pass')
      expect(res.headers.get('cache-control')).toBe(IMMUTABLE_CACHE_CONTROL)
      expect(await bytes(res)).toEqual(new Uint8Array(16).fill(2))
      await e.settle()
    }
    expect(e.calls.get).toEqual([COG_OVER_CAP, COG_OVER_CAP])   // the two ranges, no whole-object fetch
    expect(await e.cache.match(edgeCacheKey(COG_OVER_CAP))).toBeUndefined()
  })
})

describe('edge cache: off', () => {
  it('without a ctx, and on the workers.dev preview, an immutable key is served from R2 with the immutable header', async () => {
    const r = rig()
    const plain = await handle(get(`/${OBIS}`, { headers: { range: 'bytes=0-9' } }), r.env, now)
    expect(plain.headers.get('cache-control')).toBe(IMMUTABLE_CACHE_CONTROL)
    expect(plain.headers.get('x-om-cache')).toBe('pass')
    await plain.arrayBuffer()
    const e = await edgeRig()
    const preview = await e.run(new Request(`https://om-gazetteer.ben-f07.workers.dev/${OBIS}`, { headers: { range: 'bytes=0-9' } }))
    expect(preview.headers.get('x-om-cache')).toBe('pass')
    await preview.arrayBuffer()
    await e.settle()
    expect(e.calls.get).toEqual([OBIS])
    expect(await e.cache.match(edgeCacheKey(OBIS))).toBeUndefined()
  })
})
