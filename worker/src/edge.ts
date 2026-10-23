// edge cache for immutable objects (Cache API, per Cloudflare data center) ----

/** objects at or under this size are kept whole in the edge cache and every Range is sliced from the copy; larger
 *  immutable objects pass their ranges through to R2 (with the immutable header, so a browser keeps them) */
export const EDGE_CACHE_MAX_BYTES = 8 * 1024 * 1024

/** the response header of an immutable key (`isImmutable` in paths.ts) */
export const IMMUTABLE_CACHE_CONTROL = 'public, max-age=31536000, immutable'

/** cache keys live on the production host whatever host served the request, so a purge by URL is the public URL */
export const EDGE_ORIGIN = 'https://storage.oceanmetrics.io'

/** stored with each cached copy: the object's size (the body length, which a cached Response may not declare) */
export const SIZE_HEADER = 'x-om-size'

/** what the edge cache did for a response: `hit` served from the copy, `miss` from R2 (a copy is being stored),
 *  `pass` from R2 (over the cap, or no copy stored); absent on mutable keys */
export const CACHE_STATUS_HEADER = 'x-om-cache'

/** the Cache API key of an object: its public URL, without the query (so `?key=` never splits or leaks into it) */
export function edgeCacheKey(objKey: string): Request {
  const path = encodeURI(objKey).replace(/\?/g, '%3F').replace(/#/g, '%23')
  return new Request(`${EDGE_ORIGIN}/${path}`)
}

/** the cache and the request's waitUntil; null turns the edge cache off (no ctx, no Cache API, the workers.dev host) */
export interface Edge {
  cache: Cache
  waitUntil: (p: Promise<unknown>) => void
}

/** per-isolate set of keys whose copy is being stored, so a burst of misses fetches the object once */
const filling = new Set<string>()

/** store a whole object (status 200) under its key after the response has gone; errors only skip the copy */
export function storeCopy(edge: Edge, objKey: string, headers: Headers, size: number,
  body: ReadableStream | (() => Promise<ReadableStream | null>)): void {
  if (filling.has(objKey) || size > EDGE_CACHE_MAX_BYTES) {
    if (typeof body !== 'function') body.cancel().catch(() => {})
    return
  }
  filling.add(objKey)
  const h = new Headers(headers)
  for (const k of ['content-range', 'link', 'x-om-warn', 'x-om-usage', CACHE_STATUS_HEADER]) h.delete(k)
  h.set('content-length', String(size))
  h.set(SIZE_HEADER, String(size))
  h.set('cache-control', IMMUTABLE_CACHE_CONTROL)
  const job = (async () => {
    const stream = typeof body === 'function' ? await body() : body
    if (!stream) return
    await edge.cache.put(edgeCacheKey(objKey), new Response(stream, { status: 200, headers: h }))
  })().catch(e => console.log('edge cache put', objKey, String(e))).finally(() => filling.delete(objKey))
  edge.waitUntil(job)
}

/** the cached copy of an object, or null (a failed lookup is a miss) */
export async function lookup(edge: Edge, objKey: string): Promise<Response | null> {
  try {
    const r = await edge.cache.match(edgeCacheKey(objKey))
    if (!r || r.status !== 200 || !r.headers.has(SIZE_HEADER)) { await r?.body?.cancel(); return null }
    return r
  } catch {
    return null
  }
}
