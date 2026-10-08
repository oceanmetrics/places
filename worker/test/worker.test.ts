import { beforeAll, describe, expect, it } from 'vitest'
import { env } from 'cloudflare:test'
import { handle } from '../src/index'
import { rollupUsage } from '../src/meter'
import { CAP_KEY, GOOD_KEY, ORIGIN, PARQUET, PMTILES, get, now, rig, seed } from './helpers'

const LICENSE = '<https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"'
const run = (r: ReturnType<typeof rig>, req: Request) => handle(req, r.env, now)

beforeAll(seed)

describe('keyless content', () => {
  it('serves STAC json without a key, with CORS *, the licence Link and a stac metric', async () => {
    const r = rig()
    const res = await run(r, get('/gazetteer/catalog.json'))
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ type: 'Catalog' })
    expect(res.headers.get('access-control-allow-origin')).toBe('*')
    expect(res.headers.get('link')).toBe(LICENSE)
    expect(res.headers.get('etag')).toBeTruthy()
    expect(r.limited.anon).toEqual([])
    expect(r.points).toHaveLength(1)
    expect(r.points[0].blobs.slice(0, 6)).toEqual(['', '', 'stac', '', 'open', 'GET'])
    expect(r.points[0].doubles).toEqual([(await env.BUCKET.head('gazetteer/catalog.json'))!.size, 200])
  })

  it('layers.json, README and the index/ prefix are keyless and never touch the anonymous limiter', async () => {
    const r = rig({ anonOk: false })
    for (const p of ['/gazetteer/layers.json', '/gazetteer/README.md', '/gazetteer/credits', '/gazetteer/index/crosswalk.parquet']) {
      const res = await run(r, get(p, { headers: { range: 'bytes=0-9' } }))
      expect([200, 206], p).toContain(res.status)
      await res.arrayBuffer()
    }
    expect(r.limited.anon).toEqual([])
  })

  it('regression: a wrong or stale key on keyless STAC is ignored, never a 403', async () => {
    const res = await run(rig(), get('/gazetteer/catalog.json?key=totallywrongkey1'))
    expect(res.status).toBe(200)
  })
})

describe('keyed archives', () => {
  it('ranged parquet with a valid key: 206 with range headers, exact bytes, echoed origin, metered', async () => {
    const r = rig()
    const res = await run(r, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=100-199', origin: ORIGIN } }))
    expect(res.status).toBe(206)
    expect(res.headers.get('content-range')).toBe('bytes 100-199/40000')
    expect(res.headers.get('content-length')).toBe('100')
    expect(res.headers.get('accept-ranges')).toBe('bytes')
    expect(res.headers.get('etag')).toMatch(/^"[0-9a-f]+"$/)
    expect(res.headers.get('link')).toBe(LICENSE)
    expect(res.headers.get('access-control-allow-origin')).toBe(ORIGIN)
    expect(res.headers.get('vary')).toContain('Origin')
    expect(res.headers.get('access-control-allow-headers')).toBe('range, if-match, if-none-match')
    expect(res.headers.get('access-control-expose-headers')).toContain('content-range')
    expect(new Uint8Array(await res.arrayBuffer())).toEqual(PARQUET.slice(100, 200))
    expect(r.points[0].indexes).toEqual([GOOD_KEY])
    expect(r.points[0].blobs.slice(0, 5)).toEqual([GOOD_KEY, 'erddap-places', 'parquet', ORIGIN, 'free'])
    expect(r.points[0].doubles).toEqual([100, 206])
  })

  it('open-ended, suffix and out-of-range requests', async () => {
    const r = rig()
    const k = `?key=${GOOD_KEY}`
    const open = await run(r, get(`/gazetteer/mpa/places.pmtiles${k}`, { headers: { range: 'bytes=9990-' } }))
    expect(open.status).toBe(206)
    expect(open.headers.get('content-range')).toBe('bytes 9990-9999/10000')
    expect(new Uint8Array(await open.arrayBuffer())).toEqual(PMTILES.slice(9990))
    const suf = await run(r, get(`/gazetteer/mpa/places.pmtiles${k}`, { headers: { range: 'bytes=-16' } }))
    expect(suf.headers.get('content-range')).toBe('bytes 9984-9999/10000')
    expect(new Uint8Array(await suf.arrayBuffer())).toEqual(PMTILES.slice(9984))
    const bad = await run(r, get(`/gazetteer/mpa/places.pmtiles${k}`, { headers: { range: 'bytes=20000-30000' } }))
    expect(bad.status).toBe(416)
    expect(bad.headers.get('content-range')).toBe('bytes */10000')
    expect(bad.headers.get('access-control-allow-origin')).toBe('*')
  })

  it('wrong key: 403 WITH CORS so the page can read the status (regression: opaque network error)', async () => {
    const r = rig()
    const res = await run(r, get('/gazetteer/mpa/places.parquet?key=WRONGKEY123456', { headers: { origin: ORIGIN } }))
    expect(res.status).toBe(403)
    expect(res.headers.get('access-control-allow-origin')).toBe('*')
    expect(res.headers.get('access-control-expose-headers')).toContain('etag')
    expect((await res.json() as { error: string }).error).toBe('invalid_key')
    expect(r.points[0].doubles[1]).toBe(403)
  })

  it('malformed, disabled and origin-mismatched keys are 403 with CORS; no Origin header (curl, R) passes', async () => {
    const r = rig()
    for (const key of ['x', 'disabledkey_1234']) {
      const res = await run(r, get(`/gazetteer/mpa/places.parquet?key=${key}`))
      expect(res.status).toBe(403)
      expect(res.headers.get('access-control-allow-origin')).toBe('*')
    }
    const wrongOrigin = await run(r, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { headers: { origin: 'https://evil.example.com', range: 'bytes=0-9' } }))
    expect(wrongOrigin.status).toBe(403)
    expect(wrongOrigin.headers.get('access-control-allow-origin')).toBe('*')
    expect((await wrongOrigin.json() as { error: string }).error).toBe('origin_not_allowed')
    const noOrigin = await run(r, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9' } }))
    expect(noOrigin.status).toBe(206)
    expect(noOrigin.headers.get('access-control-allow-origin')).toBe('*')
    const local = await run(r, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { headers: { origin: 'http://localhost:5173', range: 'bytes=0-9' } }))
    expect(local.status).toBe(206)
    expect(local.headers.get('access-control-allow-origin')).toBe('http://localhost:5173')
  })
})

describe('anonymous tier', () => {
  it('keyless parquet is allowed (not a 403) and metered as the anonymous tier through the rate limiter', async () => {
    const r = rig()
    const res = await run(r, get('/gazetteer/mpa/places.parquet', { headers: { range: 'bytes=0-99', 'cf-connecting-ip': '203.0.113.9' } }))
    expect(res.status).toBe(206)
    expect(r.limited.anon).toEqual(['203.0.113.9'])
    expect(r.points[0].blobs.slice(0, 5)).toEqual(['', '', 'parquet', '', 'anonymous'])
    expect(r.points[0].indexes).toEqual(['anon'])
  })

  it('over the anonymous rate limit: 429 with CORS and Retry-After', async () => {
    const res = await run(rig({ anonOk: false }), get('/gazetteer/mpa/places.pmtiles', { headers: { range: 'bytes=0-99', origin: ORIGIN } }))
    expect(res.status).toBe(429)
    expect(res.headers.get('access-control-allow-origin')).toBe('*')
    expect(res.headers.get('retry-after')).toBe('60')
    expect((await res.json() as { error: string }).error).toBe('rate_limited')
  })
})

describe('HEAD', () => {
  it('HEAD: right headers, no body', async () => {
    const res = await run(rig(), get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { method: 'HEAD' }))
    expect(res.status).toBe(200)
    expect(res.headers.get('content-length')).toBe('40000')
    expect(res.headers.get('accept-ranges')).toBe('bytes')
    expect(res.headers.get('etag')).toBeTruthy()
    expect(res.headers.get('link')).toBe(LICENSE)
    expect(await res.text()).toBe('')
  })

  it('HEAD with Range: bytes=0- answers 206 + Content-Range + full Content-Length (duckdb-wasm reliable-HEAD check)', async () => {
    const r = rig()
    const res = await run(r, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { method: 'HEAD', headers: { range: 'bytes=0-', origin: ORIGIN } }))
    expect(res.status).toBe(206)
    expect(res.headers.get('content-range')).toBe('bytes 0-39999/40000')
    expect(res.headers.get('content-length')).toBe('40000')
    expect(res.headers.get('access-control-allow-origin')).toBe(ORIGIN)
    expect(await res.text()).toBe('')
    expect(r.points[0].doubles).toEqual([0, 206])
  })

  it('GET Range: bytes=0-0 probe returns 206 with a 1-byte body', async () => {
    const res = await run(rig(), get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-0' } }))
    expect(res.status).toBe(206)
    expect(res.headers.get('content-range')).toBe('bytes 0-0/40000')
    expect((await res.arrayBuffer()).byteLength).toBe(1)
  })
})

describe('conditional requests', () => {
  it('ETag passthrough: If-None-Match -> 304, If-Match mismatch -> 412, If-Match match -> 206', async () => {
    const r = rig()
    const k = `/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`
    const etag = (await run(r, get(k, { method: 'HEAD' }))).headers.get('etag')!
    const nm = await run(r, get(k, { headers: { 'if-none-match': etag } }))
    expect(nm.status).toBe(304)
    expect(nm.headers.get('etag')).toBe(etag)
    expect(nm.headers.get('access-control-allow-origin')).toBe('*')
    const pf = await run(r, get(k, { headers: { 'if-match': '"nope"', range: 'bytes=0-9' } }))
    expect(pf.status).toBe(412)
    const ok = await run(r, get(k, { headers: { 'if-match': etag, range: 'bytes=0-9' } }))
    expect(ok.status).toBe(206)
    const hnm = await run(r, get(k, { method: 'HEAD', headers: { 'if-none-match': etag } }))
    expect(hnm.status).toBe(304)
  })
})

describe('byte caps', () => {
  it('hard cap: 429 with CORS, a JSON body naming the key and the cap, Retry-After to month end', async () => {
    await env.KEYS.put(`usage:${CAP_KEY}:2026-10`, '1000')
    const r = rig()
    const res = await run(r, get(`/gazetteer/mpa/places.parquet?key=${CAP_KEY}`, { headers: { range: 'bytes=0-9', origin: ORIGIN } }))
    expect(res.status).toBe(429)
    expect(res.headers.get('access-control-allow-origin')).toBe(ORIGIN)
    expect(res.headers.get('access-control-expose-headers')).toContain('retry-after')
    expect(Number(res.headers.get('retry-after'))).toBe(16 * 86400 + 12 * 3600)
    const body = await res.json() as Record<string, unknown>
    expect(body).toMatchObject({ error: 'monthly_cap_exceeded', key: CAP_KEY, cap_bytes: 1000, used_bytes: 1000 })
    expect(r.points[0].doubles).toEqual([0, 429])
  })

  it('soft cap: still served, with an X-OM-Usage warning', async () => {
    await env.KEYS.put(`usage:${CAP_KEY}:2026-10`, '600')
    const res = await run(rig(), get(`/gazetteer/mpa/places.parquet?key=${CAP_KEY}`, { headers: { range: 'bytes=0-9' } }))
    expect(res.status).toBe(206)
    expect(res.headers.get('x-om-usage')).toBe('used=600; cap=1000; pct=60; state=soft')
  })

  it('under the soft threshold there is no warning, and last month\'s total does not count', async () => {
    await env.KEYS.put(`usage:${CAP_KEY}:2026-10`, '10')
    await env.KEYS.put(`usage:${CAP_KEY}:2026-09`, '999999')
    const res = await run(rig(), get(`/gazetteer/mpa/places.parquet?key=${CAP_KEY}`, { headers: { range: 'bytes=0-9' } }))
    expect(res.status).toBe(206)
    expect(res.headers.get('x-om-usage')).toBeNull()
  })
})

describe('abuse guard', () => {
  it('un-ranged GET of a parquet over the threshold: 200, metric class fullfile, warning header', async () => {
    const r = rig({ FULLFILE_BYTES: '10000' })
    const res = await run(r, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`))
    expect(res.status).toBe(200)
    expect(res.headers.get('x-om-warn')).toContain('full-file-read')
    expect((await res.arrayBuffer()).byteLength).toBe(40000)
    expect(r.points[0].blobs[2]).toBe('fullfile')
    expect(r.points[0].doubles).toEqual([40000, 200])
  })

  it('ranged reads, small files and pmtiles are not flagged', async () => {
    const small = rig({ FULLFILE_BYTES: '100000' })
    await (await run(small, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`))).arrayBuffer()
    expect(small.points[0].blobs[2]).toBe('parquet')
    const big = rig({ FULLFILE_BYTES: '10' })
    await (await run(big, get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-99' } }))).arrayBuffer()
    await (await run(big, get(`/gazetteer/mpa/places.pmtiles?key=${GOOD_KEY}`))).arrayBuffer()
    expect(big.points.map(p => p.blobs[2])).toEqual(['parquet', 'pmtiles'])
  })
})

describe('protocol edges', () => {
  it('OPTIONS preflight: 204 with CORS', async () => {
    const res = await run(rig(), get(`/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`, { method: 'OPTIONS', headers: { origin: ORIGIN } }))
    expect(res.status).toBe(204)
    expect(res.headers.get('access-control-allow-origin')).toBe('*')
    expect(res.headers.get('access-control-allow-methods')).toContain('HEAD')
    expect(res.headers.get('access-control-allow-headers')).toContain('range')
  })

  it('404 outside /gazetteer/, 404 for a missing object, 405 for POST, all with CORS', async () => {
    const r = rig()
    for (const [req, status] of [
      [get('/other/file.json'), 404],
      [get('/gazetteer/nope.json'), 404],
      [get('/gazetteer/../secret.json'), 404],
      [get(`/gazetteer/mpa/missing.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9' } }), 404],
      [get('/gazetteer/catalog.json', { method: 'POST', body: 'x' }), 405],
    ] as [Request, number][]) {
      const res = await run(r, req)
      expect(res.status, req.url).toBe(status)
      expect(res.headers.get('access-control-allow-origin')).toBe('*')
      await res.arrayBuffer()
    }
  })

  it('multi-range and malformed Range are ignored (full 200), per RFC 9110', async () => {
    const r = rig()
    for (const range of ['bytes=0-9,20-29', 'bytes=abc', 'items=0-9']) {
      const res = await run(r, get('/gazetteer/catalog.json', { headers: { range } }))
      expect(res.status, range).toBe(200)
      await res.arrayBuffer()
    }
  })
})

describe('monthly rollup stub', () => {
  it('does nothing without account credentials', async () => {
    expect(await rollupUsage(rig().env, now)).toEqual({ skipped: 'CF_ACCOUNT_ID / CF_API_TOKEN not set' })
  })

  it('writes usage:<key>:<month> from the Analytics Engine SQL response', async () => {
    let seen = { url: '', sql: '', auth: '' }
    const fake = (async (url: string, init: RequestInit) => {
      seen = { url, sql: String(init.body), auth: (init.headers as Record<string, string>).authorization }
      return Response.json({ data: [{ key: 'rolled_key_12345', bytes: '12345.4' }] })
    }) as unknown as typeof fetch
    const r = rig({ CF_ACCOUNT_ID: 'acct', CF_API_TOKEN: 'tok' })
    expect(await rollupUsage(r.env, now, fake)).toEqual({ keys: 1, month: '2026-10' })
    expect(seen.url).toBe('https://api.cloudflare.com/client/v4/accounts/acct/analytics_engine/sql')
    expect(seen.sql).toContain("toDateTime('2026-10-01 00:00:00')")
    expect(seen.auth).toBe('Bearer tok')
    expect(await env.KEYS.get('usage:rolled_key_12345:2026-10')).toBe('12345')
  })
})

describe('through the real worker entrypoint (wrangler.toml bindings)', () => {
  it('HEAD + Range and ranged GET keep their headers on the wire', async () => {
    const { SELF } = await import('cloudflare:test')
    const url = `${'https://storage.oceanmetrics.io'}/gazetteer/mpa/places.parquet?key=${GOOD_KEY}`
    const head = await SELF.fetch(url, { method: 'HEAD', headers: { range: 'bytes=0-', origin: ORIGIN } })
    expect(head.status).toBe(206)
    expect(head.headers.get('content-range')).toBe('bytes 0-39999/40000')
    expect(head.headers.get('content-length')).toBe('40000')
    expect(head.headers.get('access-control-allow-origin')).toBe(ORIGIN)
    const get = await SELF.fetch(url, { headers: { range: 'bytes=10-19' } })
    expect(get.status).toBe(206)
    expect(get.headers.get('content-length')).toBe('10')
    expect(new Uint8Array(await get.arrayBuffer())).toEqual(PARQUET.slice(10, 20))
    const bad = await SELF.fetch(`${url}x`)
    expect(bad.status).toBe(403)
    expect(bad.headers.get('access-control-allow-origin')).toBe('*')
  })
})
