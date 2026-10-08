// path handling and classification ----

export type PathClass = 'stac' | 'parquet' | 'pmtiles' | 'other'

export const LICENSE_LINK = '<https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"'

/** R2 object key for a request path, or null when the path is not under `gazetteer/` or is unsafe. */
export function objectKey(pathname: string): string | null {
  let p: string
  try { p = decodeURIComponent(pathname) } catch { return null }
  p = p.replace(/^\/+/, '')
  if (!p.startsWith('gazetteer/') || p.endsWith('/')) return null
  if (p.split('/').some(seg => seg === '..' || seg === '.' || seg === '')) return null
  return p
}

/** path class (by extension) and whether archives under it require a key or fall to the anonymous tier.
 *  Only `.parquet` and `.pmtiles` outside `gazetteer/index/` are gated; everything else is keyless. */
export function classify(key: string): { cls: PathClass, gated: boolean } {
  const lower = key.toLowerCase()
  const open  = lower.startsWith('gazetteer/index/')
  if (lower.endsWith('.parquet')) return { cls: 'parquet', gated: !open }
  if (lower.endsWith('.pmtiles')) return { cls: 'pmtiles', gated: !open }
  if (lower.endsWith('.json'))    return { cls: 'stac',    gated: false }
  return { cls: 'other', gated: false }
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
