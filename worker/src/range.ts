// single-range parsing and conditional requests ----

export type ByteRange = { offset: number, length?: number } | { suffix: number }

/** Parse a single `bytes=` range. Returns null for absent, malformed, non-bytes or multi-range headers
 *  (RFC 9110: a recipient may ignore Range, then the full 200 is served). */
export function parseRange(header: string | null): ByteRange | null {
  if (!header) return null
  const m = /^\s*bytes\s*=\s*(\d*)\s*-\s*(\d*)\s*$/i.exec(header)
  if (!m) return null
  const [, a, b] = m
  if (a === '' && b === '') return null
  if (a === '') {
    const n = Number(b)
    return n > 0 ? { suffix: n } : null
  }
  const start = Number(a)
  if (b === '') return { offset: start }
  const end = Number(b)
  if (end < start) return null
  return { offset: start, length: end - start + 1 }
}

/** resolve a range against a known size: inclusive start/end, or 'unsatisfiable' */
export function resolveRange(r: ByteRange, size: number): { start: number, end: number } | 'unsatisfiable' {
  if ('suffix' in r) {
    if (size === 0) return 'unsatisfiable'
    return { start: Math.max(0, size - r.suffix), end: size - 1 }
  }
  if (r.offset >= size) return 'unsatisfiable'
  const end = r.length === undefined ? size - 1 : Math.min(size - 1, r.offset + r.length - 1)
  return { start: r.offset, end }
}

function etagList(h: string): string[] {
  return h.split(',').map(s => s.trim()).filter(Boolean)
}
const bare = (e: string) => e.replace(/^W\//, '')

/** evaluate If-Match / If-None-Match against the current ETag (quoted, as R2 `httpEtag`).
 *  Returns the status to answer with, or null to proceed. */
export function preconditionStatus(headers: Headers, etag: string): 304 | 412 | null {
  const ifMatch = headers.get('if-match')
  if (ifMatch) {
    const list = etagList(ifMatch)
    if (!list.includes('*') && !list.some(e => !e.startsWith('W/') && e === etag)) return 412
  }
  const none = headers.get('if-none-match')
  if (none) {
    const list = etagList(none)
    if (list.includes('*') || list.some(e => bare(e) === bare(etag))) return 304
  }
  return null
}
