// storage front: keys, CORS, ranges, metering over the R2 buckets ----
import type { Env, KeyConfig } from './env'
import { applyCors, originAllowed } from './cors'
import { classify, creditsKey, GENERIC_TYPES, guessContentType, isImmutable, LICENSE_LINK, SERVED_MESSAGE, target } from './paths'
import { conditionalStatus, ifRangeAllows, parseRange, preconditionStatus, resolveRange, type ByteRange } from './range'
import { CACHE_STATUS_HEADER, EDGE_CACHE_MAX_BYTES, IMMUTABLE_CACHE_CONTROL, lookup, SIZE_HEADER, storeCopy, type Edge } from './edge'
import { evaluateCap, getUsage, rollupUsage, secondsToNextMonth, writeMetric, type Metric } from './meter'

const KEY_RE        = /^[A-Za-z0-9_-]{8,64}$/
const FULLFILE_DEFAULT = 16 * 1024 * 1024
const CREDITS_TTL_MS   = 10 * 60 * 1000

/** per-isolate cache: does `<prefix>/index/credits` exist (so its data carries a `Link` header)? */
const creditsSeen = new Map<string, { link: string | null, at: number }>()

/** the `Link` header for a resolved path: the gazetteer credits for gazetteer (public and unlisted); for any other
 *  prefix only when `<prefix>/index/credits` exists in the public bucket (looked up once per isolate per 10 min) */
async function licenseLink(env: Env, store: 'public' | 'unlisted', prefix: string, now: number): Promise<string | null> {
  if (store === 'unlisted' || prefix === 'gazetteer') return LICENSE_LINK
  if (prefix === 'root') return null
  const hit = creditsSeen.get(prefix)
  if (hit && now - hit.at < CREDITS_TTL_MS) return hit.link
  let link: string | null = null
  try {
    const k = creditsKey(prefix)
    if (await env.BUCKET.head(k)) link = `<https://storage.oceanmetrics.io/${k}>; rel="license"`
  } catch { /* a failed lookup only drops the header */ }
  creditsSeen.set(prefix, { link, at: now })
  return link
}

/** first segment of a request path, for the metric prefix of a path that resolved to nothing */
function firstSegment(pathname: string): string {
  let p = pathname
  try { p = decodeURIComponent(pathname) } catch { /* keep raw */ }
  return p.replace(/^\/+/, '').split('/')[0].slice(0, 64)
}

/** what `handle` needs from the runtime besides the bindings: the request's `waitUntil` and the Cache API cache
 *  (default `caches.default`). Without a ctx the edge cache is off (the immutable header still applies). */
export interface HandleOptions {
  ctx?:   Pick<ExecutionContext, 'waitUntil'>
  cache?: Cache | null
}

/** the edge cache for this request, or null: off without a ctx or Cache API, and on the workers.dev preview (its Cache
 *  API stores nothing, so a fill would only add R2 reads) */
function edgeFor(url: URL, opts: HandleOptions): Edge | null {
  if (!opts.ctx || url.hostname.endsWith('.workers.dev')) return null
  const cache = opts.cache !== undefined ? opts.cache : (typeof caches !== 'undefined' ? caches.default : null)
  if (!cache) return null
  const ctx = opts.ctx
  return { cache, waitUntil: p => ctx.waitUntil(p) }
}

/** the whole request flow; `now` is injectable for tests */
export async function handle(request: Request, env: Env, now: Date = new Date(), opts: HandleOptions = {}): Promise<Response> {
  const url    = new URL(request.url)
  const origin = request.headers.get('origin') ?? ''
  const m: Metric = { key: '', app: '', cls: 'other', origin, tier: 'open', method: request.method, path: url.pathname, status: 0, bytes: 0,
    prefix: firstSegment(url.pathname) }
  let allowOrigin = '*'

  // finish a response: CORS on every response, one metric row
  const finish = (res: Response, bytes = 0): Response => {
    const r = new Response(res.body, res)
    applyCors(r.headers, allowOrigin)
    m.status = r.status
    m.bytes  = bytes
    writeMetric(env, m)
    return r
  }
  const err = (status: number, body: Record<string, unknown>, extra: Record<string, string> = {}): Response =>
    finish(Response.json(body, { status, headers: { 'cache-control': 'no-store', ...extra } }))

  if (request.method === 'OPTIONS') {
    // preflight: always `*` (the actual response echoes a specific origin only for a matching key)
    return finish(new Response(null, { status: 204 }))
  }
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return err(405, { error: 'method_not_allowed', message: 'GET, HEAD and OPTIONS only' }, { allow: 'GET, HEAD, OPTIONS' })
  }

  const t = target(url.pathname)
  if (!t) return err(404, { error: 'not_found', message: SERVED_MESSAGE })
  const objKey = t.key
  const bucket = t.store === 'unlisted' ? env.UNLISTED : env.BUCKET
  m.path   = t.store === 'unlisted' ? `unlisted/${objKey}` : objKey
  m.prefix = t.prefix
  const linkP  = licenseLink(env, t.store, t.prefix, now.getTime())   // cached; runs alongside the key lookup
  if (!bucket) return err(404, { error: 'not_found' })

  const { cls, gate } = classify(objKey, t.store)
  m.cls = cls

  // key resolution ----
  const keyId = url.searchParams.get('key') ?? ''
  let cfg: KeyConfig | null = null
  if (keyId && KEY_RE.test(keyId)) {
    cfg = await env.KEYS.get<KeyConfig>(`key:${keyId}`, { type: 'json', cacheTtl: 60 })
  }
  const usable = cfg !== null && !cfg.disabled

  let usageHeader = ''
  if (gate === 'open') {
    // keyless content: a valid key only attributes the request, a bad or stale key is ignored (never a 403)
    if (usable) {
      m.key = keyId; m.app = cfg!.app; m.tier = cfg!.tier ?? 'free'
      if (origin && originAllowed(origin, cfg!.origins)) allowOrigin = origin
    }
  } else if (!keyId && gate === 'key') {
    // unlisted copies: no anonymous tier
    return err(403, { error: 'key_required',
      message: 'this path needs ?key=<your key> (see https://storage.oceanmetrics.io/gazetteer/credits)' })
  } else if (!keyId) {
    // anonymous tier: low rate limit instead of a 403, so existing keyless apps keep working
    m.tier = 'anonymous'
    const ip = request.headers.get('cf-connecting-ip') ?? 'unknown'
    const { success } = await env.ANON_LIMITER.limit({ key: ip })
    if (!success) {
      return err(429, { error: 'rate_limited', tier: 'anonymous',
        message: 'anonymous archive reads are rate limited; add ?key=<your key> (see https://storage.oceanmetrics.io/gazetteer/credits)' },
        { 'retry-after': '60' })
    }
  } else {
    if (!usable) {
      return err(403, { error: 'invalid_key', message: 'unknown, malformed or disabled key' })
    }
    m.key = keyId; m.app = cfg!.app; m.tier = cfg!.tier ?? 'free'
    if (origin) {
      if (!originAllowed(origin, cfg!.origins)) {
        // `*` so the page can read the 403 instead of seeing an opaque network error
        return err(403, { error: 'origin_not_allowed', message: 'this key is not enabled for this origin', app: cfg!.app })
      }
      allowOrigin = origin
    }
    if (env.KEY_LIMITER) {
      const { success } = await env.KEY_LIMITER.limit({ key: keyId })
      if (!success) return err(429, { error: 'rate_limited', key: keyId, message: 'per-key request rate exceeded' }, { 'retry-after': '10' })
    }
    const usage = evaluateCap(await getUsage(env, keyId, now), cfg!)
    if (usage.state === 'hard') {
      return err(429, { error: 'monthly_cap_exceeded', key: keyId, app: cfg!.app, cap_bytes: usage.cap, used_bytes: usage.used,
        message: `key ${keyId} reached its monthly cap of ${usage.cap} bytes` },
        { 'retry-after': String(secondsToNextMonth(now)), 'x-om-usage': `used=${usage.used}; cap=${usage.cap}; pct=${usage.pct}; state=hard` })
    }
    if (usage.state === 'soft') usageHeader = `used=${usage.used}; cap=${usage.cap}; pct=${usage.pct}; state=soft`
  }

  // object (serve() reclassifies m.cls to `fullfile` for a flagged un-ranged parquet read) ----
  // immutable keys (public data whose key names its content) go through the edge cache; key and limit checks are above,
  // so a copy is only ever served to a request that passed them, and the unlisted bucket is never cached
  const immutable = isImmutable(objKey, t.store)
  const served = await serve(request, bucket, objKey, m, env, await linkP, immutable, immutable ? edgeFor(url, opts) : null)
  // anonymous full-file reads (flagged by serve) draw on their own, lower budget on top of the general one
  if (m.tier === 'anonymous' && (m.cls as string) === 'fullfile' && env.ANON_FULLFILE_LIMITER) {
    const ip = request.headers.get('cf-connecting-ip') ?? 'unknown'
    const { success } = await env.ANON_FULLFILE_LIMITER.limit({ key: ip })
    if (!success) {
      await served.res.body?.cancel()
      return err(429, { error: 'rate_limited', tier: 'anonymous',
        message: 'anonymous full-file reads are rate limited; send a Range header or add ?key=<your key> (see https://storage.oceanmetrics.io/gazetteer/credits)' },
        { 'retry-after': '60' })
    }
  }
  if (usageHeader) served.res.headers.set('x-om-usage', usageHeader)
  return finish(served.res, served.bytes)

}

interface Served { res: Response, bytes: number }

function baseHeaders(obj: R2Object, objKey: string, link: string | null, immutable = false): Headers {
  const h = new Headers()
  obj.writeHttpMetadata(h)
  // a missing or generic stored type (rclone's octet-stream) gives way to the extension guess
  const stored = (h.get('content-type') ?? '').split(';')[0].trim().toLowerCase()
  if (!stored || GENERIC_TYPES.has(stored)) h.set('content-type', guessContentType(objKey))
  if (immutable) h.set('cache-control', IMMUTABLE_CACHE_CONTROL)
  else if (!h.has('cache-control')) h.set('cache-control', /\.(json|html)$/i.test(objKey) ? 'public, max-age=60' : 'public, max-age=300')
  h.set('etag', obj.httpEtag)
  h.set('accept-ranges', 'bytes')
  h.set('last-modified', obj.uploaded.toUTCString())
  if (link) h.set('link', link)
  return h
}

function toR2Range(r: ByteRange): R2Range {
  return 'suffix' in r ? { suffix: r.suffix } : r.length === undefined ? { offset: r.offset } : { offset: r.offset, length: r.length }
}

function notFound(): Served {
  return { res: Response.json({ error: 'not_found' }, { status: 404, headers: { 'cache-control': 'no-store' } }), bytes: 0 }
}
function unsatisfiable(size: number): Served {
  return { res: new Response(null, { status: 416, headers: { 'content-range': `bytes */${size}`, 'accept-ranges': 'bytes' } }), bytes: 0 }
}

/** the un-ranged duckdb-wasm >= 1.30 whole-file signature is observable, not blocked
 *  (an unlisted parquet keeps its `unlisted` class but gets the same warning) */
function flagFullFile(m: Metric, env: Env, objKey: string, size: number, h: Headers): void {
  const limit = Number(env.FULLFILE_BYTES ?? FULLFILE_DEFAULT)
  if ((m.cls === 'parquet' || (m.cls === 'unlisted' && objKey.toLowerCase().endsWith('.parquet'))) && size > limit) {
    if (m.cls === 'parquet') m.cls = 'fullfile'
    h.set('x-om-warn', 'full-file-read; send a Range header (duckdb-wasm >=1.30: db.open({filesystem:{forceFullHTTPReads:false}}))')
  }
}

/** a GET or HEAD answered from the edge copy: the same preconditions, If-Range, Range and headers as from R2 */
async function fromCopy(request: Request, copy: Response, objKey: string, m: Metric, env: Env, link: string | null): Promise<Served> {
  const h = new Headers(copy.headers)
  const size = Number(h.get(SIZE_HEADER))
  h.delete(SIZE_HEADER)
  h.set('cache-control', IMMUTABLE_CACHE_CONTROL)
  h.set(CACHE_STATUS_HEADER, 'hit')
  if (link) h.set('link', link); else h.delete('link')
  const etag = h.get('etag') ?? ''
  const lastModified = h.get('last-modified') ?? ''
  const drop = async () => { await copy.body?.cancel() }

  const pre = conditionalStatus(request.headers, etag, lastModified)
  if (pre) { await drop(); h.delete('content-length'); return { res: new Response(null, { status: pre, headers: h }), bytes: 0 } }

  let range = parseRange(request.headers.get('range'))
  if (range && !ifRangeAllows(request.headers, etag, lastModified)) range = null
  const isHead = request.method === 'HEAD'
  if (range) {
    const r = resolveRange(range, size)
    if (r === 'unsatisfiable') { await drop(); return unsatisfiable(size) }
    const len = r.end - r.start + 1
    h.set('content-range', `bytes ${r.start}-${r.end}/${size}`)
    h.set('content-length', String(len))
    if (isHead) { await drop(); return { res: new Response(null, { status: 206, headers: h }), bytes: 0 } }
    const buf = await copy.arrayBuffer()
    return { res: new Response(buf.slice(r.start, r.end + 1), { status: 206, headers: h }), bytes: len }
  }
  h.set('content-length', String(size))
  if (isHead) { await drop(); return { res: new Response(null, { status: 200, headers: h }), bytes: 0 } }
  flagFullFile(m, env, objKey, size, h)
  return { res: new Response(copy.body, { status: 200, headers: h }), bytes: size }
}

async function serve(request: Request, bucket: R2Bucket, objKey: string, m: Metric, env: Env, link: string | null,
  immutable = false, edge: Edge | null = null): Promise<Served> {
  const isHead = request.method === 'HEAD'
  let range    = parseRange(request.headers.get('range'))

  if (edge) {
    const copy = await lookup(edge, objKey)
    if (copy) return fromCopy(request, copy, objKey, m, env, link)
  }
  // edge status of an R2 answer for an immutable key; a copy is stored after the response for an object within the cap
  const cacheStatus = (size: number): string => edge && size <= EDGE_CACHE_MAX_BYTES ? 'miss' : 'pass'
  const fillLater = (obj: R2Object, h: Headers) => {
    if (edge && obj.size <= EDGE_CACHE_MAX_BYTES) storeCopy(edge, objKey, h, obj.size, async () => {
      const full = await bucket.get(objKey)
      if (!full || !('body' in full)) return null
      if (full.httpEtag !== obj.httpEtag) { await full.body.cancel(); return null }   // replaced meanwhile: no copy
      return full.body
    })
  }

  if (isHead) {
    const obj = await bucket.head(objKey)
    if (!obj) return notFound()
    const h = baseHeaders(obj, objKey, link, immutable)
    if (immutable) { h.set(CACHE_STATUS_HEADER, cacheStatus(obj.size)); fillLater(obj, h) }
    const pre = preconditionStatus(request.headers, obj.httpEtag)
    if (pre) return { res: new Response(null, { status: pre, headers: h }), bytes: 0 }
    if (range && !ifRangeAllows(request.headers, obj.httpEtag, obj.uploaded.toUTCString())) range = null
    if (range) {
      const r = resolveRange(range, obj.size)
      if (r === 'unsatisfiable') return unsatisfiable(obj.size)
      h.set('content-range', `bytes ${r.start}-${r.end}/${obj.size}`)
      h.set('content-length', String(r.end - r.start + 1))
      return { res: new Response(null, { status: 206, headers: h }), bytes: 0 }
    }
    h.set('content-length', String(obj.size))
    return { res: new Response(null, { status: 200, headers: h }), bytes: 0 }
  }

  // If-Range: R2 does not evaluate it, so a ranged request carrying one checks the validator first
  if (range && request.headers.has('if-range')) {
    const head = await bucket.head(objKey)
    if (head && !ifRangeAllows(request.headers, head.httpEtag, head.uploaded.toUTCString())) range = null
  }

  let obj: R2Object | R2ObjectBody | null
  try {
    obj = await bucket.get(objKey, { onlyIf: request.headers, ...(range ? { range: toR2Range(range) } : {}) })
  } catch (e) {
    if (!range) throw e
    const head = await bucket.head(objKey)
    if (!head) return notFound()
    return unsatisfiable(head.size)
  }
  if (!obj) return notFound()

  const h = baseHeaders(obj, objKey, link, immutable)
  if (immutable) h.set(CACHE_STATUS_HEADER, cacheStatus(obj.size))
  if (!('body' in obj)) {
    // precondition failed inside R2: say which one
    const pre = preconditionStatus(request.headers, obj.httpEtag) ?? 304
    return { res: new Response(null, { status: pre, headers: h }), bytes: 0 }
  }

  if (range) {
    const r = obj.range && 'offset' in obj.range && obj.range.offset !== undefined && obj.range.length !== undefined
      ? { start: obj.range.offset, end: obj.range.offset + obj.range.length - 1 }
      : resolveRange(range, obj.size)
    if (r === 'unsatisfiable') return unsatisfiable(obj.size)
    const len = r.end - r.start + 1
    h.set('content-range', `bytes ${r.start}-${r.end}/${obj.size}`)
    h.set('content-length', String(len))
    if (immutable) fillLater(obj, h)
    return { res: new Response(obj.body, { status: 206, headers: h }), bytes: len }
  }

  h.set('content-length', String(obj.size))
  flagFullFile(m, env, objKey, obj.size, h)
  let body: ReadableStream = obj.body
  if (immutable && edge && obj.size <= EDGE_CACHE_MAX_BYTES) {
    // the whole object is already on its way: one branch to the client, one into the cache
    const [toClient, toCache] = obj.body.tee()
    body = toClient
    storeCopy(edge, objKey, h, obj.size, toCache)
  }
  return { res: new Response(body, { status: 200, headers: h }), bytes: obj.size }
}

export default {
  fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    return handle(request, env, new Date(), { ctx })
  },
  // cron: */15 * * * *  (monthly byte totals into KV; stub until the Cloudflare account exists)
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(rollupUsage(env).then(r => console.log('rollup', JSON.stringify(r))))
  },
} satisfies ExportedHandler<Env>
