// gazetteer front: keys, CORS, ranges, metering over the R2 bucket ----
import type { Env, KeyConfig } from './env'
import { applyCors, originAllowed } from './cors'
import { classify, guessContentType, LICENSE_LINK, objectKey } from './paths'
import { parseRange, preconditionStatus, resolveRange, type ByteRange } from './range'
import { evaluateCap, getUsage, rollupUsage, secondsToNextMonth, writeMetric, type Metric } from './meter'

const KEY_RE        = /^[A-Za-z0-9_-]{8,64}$/
const FULLFILE_DEFAULT = 16 * 1024 * 1024

/** the whole request flow; `now` is injectable for tests */
export async function handle(request: Request, env: Env, now: Date = new Date()): Promise<Response> {
  const url    = new URL(request.url)
  const origin = request.headers.get('origin') ?? ''
  const m: Metric = { key: '', app: '', cls: 'other', origin, tier: 'open', method: request.method, path: url.pathname, status: 0, bytes: 0 }
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

  const objKey = objectKey(url.pathname)
  if (!objKey) return err(404, { error: 'not_found', message: 'paths are served under /gazetteer/' })
  m.path = objKey

  const { cls, gated } = classify(objKey)
  m.cls = cls

  // key resolution ----
  const keyId = url.searchParams.get('key') ?? ''
  let cfg: KeyConfig | null = null
  if (keyId && KEY_RE.test(keyId)) {
    cfg = await env.KEYS.get<KeyConfig>(`key:${keyId}`, { type: 'json', cacheTtl: 60 })
  }
  const usable = cfg !== null && !cfg.disabled

  let usageHeader = ''
  if (!gated) {
    // keyless content: a valid key only attributes the request, a bad or stale key is ignored (never a 403)
    if (usable) {
      m.key = keyId; m.app = cfg!.app; m.tier = cfg!.tier ?? 'free'
      if (origin && originAllowed(origin, cfg!.origins)) allowOrigin = origin
    }
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
  const served = await serve(request, env, objKey, m)
  if (usageHeader) served.res.headers.set('x-om-usage', usageHeader)
  return finish(served.res, served.bytes)

}

interface Served { res: Response, bytes: number }

function baseHeaders(obj: R2Object, objKey: string): Headers {
  const h = new Headers()
  obj.writeHttpMetadata(h)
  if (!h.has('content-type')) h.set('content-type', guessContentType(objKey))
  if (!h.has('cache-control')) h.set('cache-control', objKey.endsWith('.json') ? 'public, max-age=60' : 'public, max-age=300')
  h.set('etag', obj.httpEtag)
  h.set('accept-ranges', 'bytes')
  h.set('last-modified', obj.uploaded.toUTCString())
  h.set('link', LICENSE_LINK)
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

async function serve(request: Request, env: Env, objKey: string, m: Metric): Promise<Served> {
  const isHead = request.method === 'HEAD'
  const range  = parseRange(request.headers.get('range'))

  if (isHead) {
    const obj = await env.BUCKET.head(objKey)
    if (!obj) return notFound()
    const h = baseHeaders(obj, objKey)
    const pre = preconditionStatus(request.headers, obj.httpEtag)
    if (pre) return { res: new Response(null, { status: pre, headers: h }), bytes: 0 }
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

  let obj: R2Object | R2ObjectBody | null
  try {
    obj = await env.BUCKET.get(objKey, { onlyIf: request.headers, ...(range ? { range: toR2Range(range) } : {}) })
  } catch (e) {
    if (!range) throw e
    const head = await env.BUCKET.head(objKey)
    if (!head) return notFound()
    return unsatisfiable(head.size)
  }
  if (!obj) return notFound()

  const h = baseHeaders(obj, objKey)
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
    return { res: new Response(obj.body, { status: 206, headers: h }), bytes: len }
  }

  // un-ranged: the duckdb-wasm >= 1.30 whole-file signature is observable, not blocked
  const limit = Number(env.FULLFILE_BYTES ?? FULLFILE_DEFAULT)
  if (m.cls === 'parquet' && obj.size > limit) {
    m.cls = 'fullfile'
    h.set('x-om-warn', 'full-file-read; send a Range header (duckdb-wasm >=1.30: db.open({filesystem:{forceFullHTTPReads:false}}))')
  }
  h.set('content-length', String(obj.size))
  return { res: new Response(obj.body, { status: 200, headers: h }), bytes: obj.size }
}

export default {
  fetch(request: Request, env: Env): Promise<Response> {
    return handle(request, env)
  },
  // cron: */15 * * * *  (monthly byte totals into KV; stub until the Cloudflare account exists)
  async scheduled(_controller: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    ctx.waitUntil(rollupUsage(env).then(r => console.log('rollup', JSON.stringify(r))))
  },
} satisfies ExportedHandler<Env>
