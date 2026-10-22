// path handling and classification ----

export type PathClass = 'stac' | 'parquet' | 'pmtiles' | 'other' | 'unlisted'

/** which R2 bucket a path reads: `BUCKET` (the public catalog) or `UNLISTED` (copies kept out of the catalog) */
export type Store = 'public' | 'unlisted'

/** how a path is gated: `open` keyless, `anonymous` keyless through the anonymous rate limit, `key` a valid key or 403 */
export type Gate = 'open' | 'anonymous' | 'key'

export const LICENSE_LINK = '<https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"'

/** request path prefix of the unlisted bucket: `/unlisted/gazetteer/<slug>/...` reads `gazetteer/<slug>/...` from UNLISTED */
export const UNLISTED_PREFIX = 'unlisted/'

/** bucket and R2 object key for a request path, or null when the path is not under `gazetteer/` (or
 *  `unlisted/gazetteer/`) or is unsafe. Both buckets use the same `gazetteer/...` key layout. */
export function target(pathname: string): { store: Store, key: string } | null {
  let p: string
  try { p = decodeURIComponent(pathname) } catch { return null }
  p = p.replace(/^\/+/, '')
  let store: Store = 'public'
  if (p.startsWith(UNLISTED_PREFIX)) { store = 'unlisted'; p = p.slice(UNLISTED_PREFIX.length) }
  if (!p.startsWith('gazetteer/') || p.endsWith('/')) return null
  if (p.split('/').some(seg => seg === '..' || seg === '.' || seg === '')) return null
  return { store, key: p }
}

/** R2 object key for a public request path (see `target`), or null. */
export function objectKey(pathname: string): string | null {
  const t = target(pathname)
  return t && t.store === 'public' ? t.key : null
}

/** path class and gate. Public: by extension, and only `.parquet` / `.pmtiles` outside `gazetteer/index/` fall to the
 *  anonymous tier without a key; everything else is open. Unlisted: class `unlisted`, every path needs a valid key
 *  except `gazetteer/index/` (the small `unlisted.json` listing), which is open like the public index. */
export function classify(key: string, store: Store = 'public'): { cls: PathClass, gate: Gate } {
  const lower = key.toLowerCase()
  const index = lower.startsWith('gazetteer/index/')
  if (store === 'unlisted') return { cls: 'unlisted', gate: index ? 'open' : 'key' }
  const archive: Gate = index ? 'open' : 'anonymous'
  if (lower.endsWith('.parquet')) return { cls: 'parquet', gate: archive }
  if (lower.endsWith('.pmtiles')) return { cls: 'pmtiles', gate: archive }
  if (lower.endsWith('.json'))    return { cls: 'stac',    gate: 'open' }
  return { cls: 'other', gate: 'open' }
}

const TYPES: Record<string, string> = {
  json:    'application/json',
  parquet: 'application/vnd.apache.parquet',
  pmtiles: 'application/octet-stream',
  md:      'text/markdown; charset=utf-8',
  txt:     'text/plain; charset=utf-8',
  html:    'text/html; charset=utf-8',
  jpg:     'image/jpeg',
  jpeg:    'image/jpeg',
  png:     'image/png',
}

export function guessContentType(key: string): string {
  const ext = key.split('.').pop()?.toLowerCase() ?? ''
  return TYPES[ext] ?? 'application/octet-stream'
}
