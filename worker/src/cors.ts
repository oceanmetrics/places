// CORS ----

export const ALLOW_HEADERS  = 'range, if-match, if-none-match'
export const EXPOSE_HEADERS = 'etag, content-range, accept-ranges, content-length, link, retry-after, x-om-usage, x-om-warn'

/** does `origin` match any allow-list pattern? `*` alone matches anything; `*` inside a pattern is a wildcard. */
export function originAllowed(origin: string, patterns: string[] | undefined): boolean {
  if (!patterns || patterns.length === 0) return true
  const o = origin.toLowerCase()
  return patterns.some(p => {
    const pl = p.toLowerCase()
    if (pl === '*') return true
    if (!pl.includes('*')) return pl === o
    const re = new RegExp('^' + pl.split('*').map(s => s.replace(/[.+?^${}()|[\]\\]/g, '\\$&')).join('[^/]*') + '$')
    return re.test(o)
  })
}

/** apply CORS to a header set. `allowOrigin` is the echoed origin (with Vary) or `*`. */
export function applyCors(h: Headers, allowOrigin: string): void {
  h.set('access-control-allow-origin', allowOrigin)
  if (allowOrigin !== '*') h.append('vary', 'Origin')
  h.set('access-control-allow-headers', ALLOW_HEADERS)
  h.set('access-control-allow-methods', 'GET, HEAD, OPTIONS')
  h.set('access-control-expose-headers', EXPOSE_HEADERS)
  h.set('access-control-max-age', '86400')
}
