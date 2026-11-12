// folder listings: a folder URL with no stored index.html lists the bucket under it ----
import { beforeAll, describe, expect, it } from 'vitest'
import { env } from 'cloudflare:test'
import { handle } from '../src/index'
import { isImmutable } from '../src/paths'
import { LISTING_CACHE_CONTROL, type Listing } from '../src/listing'
import { GOOD_KEY, ORIGIN, PARQUET, get, now, rig, seed } from './helpers'

const run = (r: ReturnType<typeof rig>, req: Request, listLimit?: number) =>
  handle(req, r.env, now, listLimit ? { listLimit } : {})
const IP = '203.0.113.9'
const anon = (init: RequestInit = {}) => ({ ...init, headers: { 'cf-connecting-ip': IP, ...(init.headers ?? {}) } })
const JSON_ACCEPT = { headers: { accept: 'application/json' } }

const T = 'marine-atlas/v11/tables/'
const SMALL = 'a,b\n1,2\n'

beforeAll(async () => {
  await seed()
  const put = (k: string, v: Uint8Array | string) => env.BUCKET.put(k, v)
  // put out of order on purpose: the listing sorts
  await put(`${T}zeta.parquet`, PARQUET)
  await put(`${T}alpha.csv`, SMALL)
  await put(`${T}sub_b/x.parquet`, PARQUET)
  await put(`${T}sub_a/y.parquet`, PARQUET)
  await put(`${T}sub_a/deeper/z.parquet`, PARQUET)
  await put(`${T}place=NMS:CINMS.xml`, '<feed/>')
  await put(`${T}<b>&odd.csv`, SMALL)
  await put(T, '')                                            // a folder marker object: never a row
  // a folder whose stored index.html wins
  await put('marine-atlas/v11/index.html', '<html>v11 page</html>')
  await put('marine-atlas/v11/release.json', '{}')
  // paging: five files
  for (const n of ['p1', 'p2', 'p3', 'p4', 'p5']) await put(`indicators/paged/${n}.csv`, SMALL)
  // an immutable-looking folder
  await put('obis-h3/v20261012/species_flat/res=3/p=81283ffffffffff.parquet', PARQUET)
  // restricted and unserved
  await put('atlas-restricted/coll/data.parquet', PARQUET)
  await put('backups/db.dump', 'SECRET')
  await put('backups/index.html', '<html>backups</html>')
  // the root: served prefixes and root files appear, nothing else
  await put('README.md', '# root')
  await put('nc.parquet', PARQUET)
})

describe('HTML listing (default)', () => {
  it('folders first (sorted), then files sorted by key with size, uploaded and etag; relative links, .., title, footer', async () => {
    const r = rig()
    const res = await run(r, get(`/${T}`, anon()))
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toBe('text/html; charset=utf-8')
    expect(res.headers.get('cache-control')).toBe(LISTING_CACHE_CONTROL)
    expect(res.headers.get('vary')).toContain('Accept')
    const html = await res.text()
    expect(res.headers.get('content-length')).toBe(String(new TextEncoder().encode(html).byteLength))
    expect(html).toContain(`<title>/${T}</title>`)
    expect(html).toContain(`<h1>/${T}</h1>`)
    const hrefs = [...html.matchAll(/href="([^"]*)"/g)].map(m => m[1])
    expect(hrefs).toEqual(['../', 'sub_a/', 'sub_b/', '%3Cb%3E%26odd.csv', 'alpha.csv', 'place%3DNMS%3ACINMS.xml', 'zeta.parquet'])
    const zeta = (await env.BUCKET.head(`${T}zeta.parquet`))!
    expect(html).toContain(`<a href="zeta.parquet">zeta.parquet</a></td><td class="n">40,000</td><td>${zeta.uploaded.toISOString()}</td><td><code>${zeta.etag}</code></td>`)
    expect(html).toContain('<td class="n">8</td>')                                // alpha.csv, 8 bytes
    expect(html).toContain('&lt;b&gt;&amp;odd.csv')                               // escaped, never raw markup
    expect(html).not.toContain('<b>&odd')
    expect(html).toMatch(/<footer>listed by the om-gazetteer Worker \(storage\.oceanmetrics\.io\) · page cursor: first page<\/footer>/)
    expect(html).not.toContain('next page')
    expect(html).not.toContain('<script')
  })

  it('metered like a read: class listing, the anonymous tier through the limiter, the folder path and the bytes', async () => {
    const r = rig()
    const res = await run(r, get(`/${T}`, anon()))
    const n = (await res.arrayBuffer()).byteLength
    expect(r.limited.anon).toEqual([IP])
    expect(r.points).toHaveLength(1)
    expect(r.points[0].blobs).toEqual(['', '', 'listing', '', 'anonymous', 'GET', T, 'marine-atlas'])
    expect(r.points[0].doubles).toEqual([n, 200])
  })

  it('a folder marker object (key = the prefix) is not a row', async () => {
    const res = await run(rig(), get(`/${T}?format=json`))
    const l = await res.json() as Listing
    expect(l.objects.map(o => o.key)).not.toContain(T)
    expect(l.folders).not.toContain('/')
  })
})

describe('JSON listing', () => {
  it('Accept: application/json gives { prefix, folders, objects, cursor } exactly', async () => {
    const res = await run(rig(), get(`/${T}`, JSON_ACCEPT))
    expect(res.status).toBe(200)
    expect(res.headers.get('content-type')).toBe('application/json; charset=utf-8')
    expect(res.headers.get('cache-control')).toBe('public, max-age=60')
    const l = await res.json() as Listing
    const meta = async (k: string) => { const o = (await env.BUCKET.head(k))!; return { key: k, size: o.size, uploaded: o.uploaded.toISOString(), etag: o.etag } }
    expect(l).toEqual({
      prefix:  T,
      folders: ['sub_a/', 'sub_b/'],
      objects: [await meta(`${T}<b>&odd.csv`), await meta(`${T}alpha.csv`), await meta(`${T}place=NMS:CINMS.xml`), await meta(`${T}zeta.parquet`)],
      cursor:  null,
    })
    expect(Object.keys(l.objects[0])).toEqual(['key', 'size', 'uploaded', 'etag'])
  })

  it('?format=json gives the same body; a browser Accept (text/html, */*) and ?format=html give the page', async () => {
    const a = await (await run(rig(), get(`/${T}`, JSON_ACCEPT))).text()
    const b = await (await run(rig(), get(`/${T}?format=json`))).text()
    expect(b).toBe(a)
    const browser = await run(rig(), get(`/${T}`, { headers: { accept: 'text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8' } }))
    expect(browser.headers.get('content-type')).toBe('text/html; charset=utf-8')
    await browser.arrayBuffer()
    const forced = await run(rig(), get(`/${T}?format=html`, JSON_ACCEPT))
    expect(forced.headers.get('content-type')).toBe('text/html; charset=utf-8')
    await forced.arrayBuffer()
  })
})

describe('paging by ?cursor=', () => {
  it('a truncated page carries the cursor; the next page by ?cursor= finishes the folder, nothing twice', async () => {
    const r = rig()
    const keys: string[] = []
    let cursor: string | null = null
    let pages = 0
    do {
      const q: string = cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''
      const res = await run(r, get(`/indicators/paged/?format=json${q}`), 2)
      expect(res.status).toBe(200)
      const l = await res.json() as Listing
      expect(l.objects.length).toBeLessThanOrEqual(2)
      keys.push(...l.objects.map(o => o.key))
      cursor = l.cursor
      pages++
    } while (cursor && pages < 10)
    expect(pages).toBe(3)
    expect(keys).toEqual(['p1', 'p2', 'p3', 'p4', 'p5'].map(n => `indicators/paged/${n}.csv`))
  })

  it('HTML: a next-page link with only ?cursor=, and the footer names the page cursor', async () => {
    const first = await (await run(rig(), get('/indicators/paged/'), 2)).text()
    const m = first.match(/<a href="\?cursor=([^"]+)">next page<\/a>/)
    expect(m).not.toBeNull()
    const cursor = decodeURIComponent(m![1].replace(/&amp;/g, '&'))
    const second = await (await run(rig(), get(`/indicators/paged/?cursor=${encodeURIComponent(cursor)}`), 2)).text()
    expect(second).toContain('p3.csv')
    expect(second).not.toContain('p1.csv')
    expect(second).toContain(`page cursor: <code>${cursor}</code>`)
  })

  it('fault: a cursor R2 refuses is a 400 bad_cursor with CORS, not a 500', async () => {
    // local R2 accepts any cursor, so a bucket that refuses one stands in for the real R2 error
    const r = rig()
    const real = r.env.BUCKET
    r.env.BUCKET = new Proxy(real, { get: (t, k) => k === 'list'
      ? (o: R2ListOptions) => o.cursor ? Promise.reject(new Error('list: invalid cursor')) : t.list(o)
      : (t[k as keyof R2Bucket] as Function).bind(t) }) as R2Bucket
    const res = await run(r, get('/indicators/paged/?cursor=not-a-real-cursor!!'))
    expect(res.status).toBe(400)
    expect(res.headers.get('access-control-allow-origin')).toBe('*')
    expect((await res.json() as { error: string }).error).toBe('bad_cursor')
  })
})

describe('the root and a stored index.html', () => {
  it('the root lists only the served prefixes and root files (never backups/ or nc.parquet) when no index.html is stored', async () => {
    await env.BUCKET.delete('index.html')
    const res = await run(rig(), get('/?format=json'))
    expect(res.status).toBe(200)
    const l = await res.json() as Listing
    expect(l.prefix).toBe('')
    expect(l.folders).toEqual(['gazetteer/', 'indicators/', 'marine-atlas/', 'obis-h3/'])
    expect(l.objects.map(o => o.key)).toEqual(['README.md'])
    const html = await (await run(rig(), get('/'))).text()
    expect(html).toContain('<title>/</title>')
    expect(html).not.toContain('href="../"')                                     // no .. at the root
    expect(html).not.toContain('backups')
    expect(html).not.toContain('atlas-restricted')
  })

  it('a stored index.html still wins: the root and a subfolder serve it as before (class other, open tier)', async () => {
    await env.BUCKET.put('index.html', '<html>root page</html>')
    const r = rig()
    const root = await run(r, get('/', anon()))
    expect(root.status).toBe(200)
    expect(await root.text()).toBe('<html>root page</html>')
    const v11 = await run(r, get('/marine-atlas/v11/', anon({ headers: { accept: 'application/json' } })))
    expect(v11.status).toBe(200)
    expect(await v11.text()).toBe('<html>v11 page</html>')
    expect(r.points.map(p => p.blobs[2])).toEqual(['other', 'other'])
    expect(r.points.map(p => p.blobs[4])).toEqual(['open', 'open'])
    expect(r.limited.anon).toEqual([])
  })

  it('fault: a folder with nothing under it is a 404, as before', async () => {
    const res = await run(rig(), get('/marine-atlas/no-such-folder/'))
    expect(res.status).toBe(404)
    expect((await res.json() as { error: string }).error).toBe('not_found')
    expect(res.headers.get('access-control-allow-origin')).toBe('*')
  })
})

describe('tiers: unlisted, restricted, backups', () => {
  it('/unlisted/gazetteer/ without a key: 403 key_required; with the key: 200, keys in request-path form, class unlisted', async () => {
    const r = rig()
    const no = await run(r, get('/unlisted/gazetteer/?format=json', anon()))
    expect(no.status).toBe(403)
    expect((await no.json() as { error: string }).error).toBe('key_required')
    const deep = await run(r, get('/unlisted/gazetteer/mr_eez/', anon()))
    expect(deep.status).toBe(403)
    await deep.arrayBuffer()
    expect(r.limited.anon).toEqual([])
    const yes = await run(r, get(`/unlisted/gazetteer/?format=json&key=${GOOD_KEY}`))
    expect(yes.status).toBe(200)
    const l = await yes.json() as Listing
    expect(l).toEqual({ prefix: 'unlisted/gazetteer/', folders: ['index/', 'mr_eez/'], objects: [], cursor: null })
    const sub = await run(r, get(`/unlisted/gazetteer/mr_eez/?format=json&key=${GOOD_KEY}`))
    expect((await sub.json() as Listing).objects.map(o => o.key)).toEqual(
      ['README.md', 'places.parquet', 'places.pmtiles'].map(n => `unlisted/gazetteer/mr_eez/${n}`))
    expect(r.points.map(p => p.blobs[2])).toEqual(['unlisted', 'unlisted', 'unlisted', 'unlisted'])
    expect(r.points[2].blobs.slice(0, 2)).toEqual([GOOD_KEY, 'erddap-places'])
    expect(r.points[2].blobs[6]).toBe('unlisted/gazetteer/')
  })

  it('/atlas-restricted/ without a key: 403; with the key: 200', async () => {
    const no = await run(rig(), get('/atlas-restricted/coll/'))
    expect(no.status).toBe(403)
    expect((await no.json() as { error: string }).error).toBe('key_required')
    const yes = await run(rig(), get(`/atlas-restricted/coll/?format=json&key=${GOOD_KEY}`))
    expect(yes.status).toBe(200)
    expect((await yes.json() as Listing).objects.map(o => o.key)).toEqual(['atlas-restricted/coll/data.parquet'])
  })

  it('regression: backups/ is a 404 listing or not, key or not, json or not', async () => {
    for (const p of ['/backups/', '/backups/?format=json', `/backups/?key=${GOOD_KEY}`, '/backups//', '/%62ackups/']) {
      const res = await run(rig(), get(p))
      expect(res.status, p).toBe(404)
      const body = await res.text()
      expect(body, p).not.toContain('db.dump')
      expect(body, p).not.toContain('SECRET')
    }
  })

  it('fault: a wrong key on a listing is 403 invalid_key; a wrong Origin for a good key 403 origin_not_allowed', async () => {
    const bad = await run(rig(), get('/marine-atlas/v11/tables/?key=WRONGKEY123456'))
    expect(bad.status).toBe(403)
    expect((await bad.json() as { error: string }).error).toBe('invalid_key')
    const wo = await run(rig(), get(`/marine-atlas/v11/tables/?key=${GOOD_KEY}`, { headers: { origin: 'https://evil.example.com' } }))
    expect(wo.status).toBe(403)
    expect((await wo.json() as { error: string }).error).toBe('origin_not_allowed')
  })

  it('fault: over the anonymous limit a listing is a 429 with Retry-After; a keyed listing skips that limiter', async () => {
    const r = rig({ anonOk: false })
    const res = await run(r, get(`/${T}`, anon()))
    expect(res.status).toBe(429)
    expect(res.headers.get('retry-after')).toBe('60')
    expect((await res.json() as { tier: string }).tier).toBe('anonymous')
    const keyed = await run(r, get(`/${T}?key=${GOOD_KEY}`, anon()))
    expect(keyed.status).toBe(200)
    await keyed.arrayBuffer()
    expect(r.limited.anon).toEqual([IP])
    expect(r.limited.key).toEqual([GOOD_KEY])
  })
})

describe('HEAD, CORS, keys', () => {
  it('HEAD: the GET headers (type, length, cache-control) with no body, metered as 0 bytes', async () => {
    const r = rig()
    const getRes = await run(r, get(`/${T}`))
    const body = await getRes.text()
    const head = await run(r, get(`/${T}`, { method: 'HEAD' }))
    expect(head.status).toBe(200)
    expect(head.headers.get('content-type')).toBe('text/html; charset=utf-8')
    expect(head.headers.get('content-length')).toBe(String(new TextEncoder().encode(body).byteLength))
    expect(head.headers.get('cache-control')).toBe(LISTING_CACHE_CONTROL)
    expect(await head.text()).toBe('')
    expect(r.points[1].blobs[5]).toBe('HEAD')
    expect(r.points[1].doubles).toEqual([0, 200])
  })

  it('CORS as on objects: * keyless; a valid key with its Origin echoes it with Vary Accept and Origin', async () => {
    const open = await run(rig(), get(`/${T}`))
    expect(open.headers.get('access-control-allow-origin')).toBe('*')
    expect(open.headers.get('access-control-allow-methods')).toBe('GET, HEAD, OPTIONS')
    expect(open.headers.get('access-control-expose-headers')).toContain('etag')
    await open.arrayBuffer()
    const keyed = await run(rig(), get(`/${T}?key=${GOOD_KEY}`, { headers: { origin: ORIGIN } }))
    expect(keyed.headers.get('access-control-allow-origin')).toBe(ORIGIN)
    expect(keyed.headers.get('vary')).toBe('Accept, Origin')
    await keyed.arrayBuffer()
    const pre = await run(rig(), get(`/${T}`, { method: 'OPTIONS', headers: { origin: ORIGIN } }))
    expect(pre.status).toBe(204)
  })

  it('regression: ?key= is never echoed into the page, its links or the JSON', async () => {
    for (const path of [`/indicators/paged/?key=${GOOD_KEY}`, `/indicators/paged/?key=${GOOD_KEY}&format=json`,
      `/unlisted/gazetteer/mr_eez/?key=${GOOD_KEY}`]) {
      const res = await run(rig(), get(path), 2)
      expect(res.status, path).toBe(200)
      const text = await res.text()
      expect(text, path).not.toContain(GOOD_KEY)
      expect(text, path).not.toContain('key=')
    }
  })
})

describe('isImmutable never matches a folder', () => {
  for (const k of ['obis-h3/v20261012/', 'marine-atlas/cog_3857/', 'atlas/aquamaps_native/registry/v2/', '']) {
    it(`${k || '(root)'} -> mutable`, () => expect(isImmutable(k)).toBe(false))
  }

  it('a listing of an immutable-looking folder gets the listing cache header, never the immutable one or the edge cache', async () => {
    const res = await run(rig(), get('/obis-h3/v20261012/species_flat/res=3/'))
    expect(res.status).toBe(200)
    expect(res.headers.get('cache-control')).toBe(LISTING_CACHE_CONTROL)
    expect(res.headers.get('x-om-cache')).toBeNull()
    expect(await res.text()).toContain('p%3D81283ffffffffff.parquet')
  })
})

describe('through the real worker entrypoint (wrangler.toml bindings)', () => {
  it('a listing on the wire: HTML, JSON and HEAD', async () => {
    const { SELF } = await import('cloudflare:test')
    const url = `https://storage.oceanmetrics.io/${T}`
    const html = await SELF.fetch(url)
    expect(html.status).toBe(200)
    expect(await html.text()).toContain('zeta.parquet')
    const json = await SELF.fetch(url, JSON_ACCEPT)
    expect((await json.json() as Listing).folders).toEqual(['sub_a/', 'sub_b/'])
    const head = await SELF.fetch(url, { method: 'HEAD' })
    expect(head.status).toBe(200)
    expect(Number(head.headers.get('content-length'))).toBeGreaterThan(0)
  })
})
