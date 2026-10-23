// path handling and classification ----

/** metric class (blob3): `stac` any json; `parquet`, `pmtiles`, `tif` by extension; `data` other data files
 *  (duckdb, zip, gz, fgb, unknown extensions); `other` keyless metadata (md, html, images, txt, csv, `credits`);
 *  `unlisted` the unlisted bucket and `atlas-restricted/` */
export type PathClass = 'stac' | 'parquet' | 'pmtiles' | 'tif' | 'data' | 'other' | 'unlisted'

/** which R2 bucket a path reads: `BUCKET` (the public catalog) or `UNLISTED` (copies kept out of the catalog) */
export type Store = 'public' | 'unlisted'

/** how a path is gated: `open` keyless, `anonymous` keyless through the anonymous rate limit, `key` a valid key or 403 */
export type Gate = 'open' | 'anonymous' | 'key'

export const LICENSE_LINK = '<https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"'

/** request path prefix of the unlisted bucket: `/unlisted/gazetteer/<slug>/...` reads `gazetteer/<slug>/...` from UNLISTED */
export const UNLISTED_PREFIX = 'unlisted/'

/** first path segments served from the public bucket (keyless metadata, data through the key tiers) */
export const PUBLIC_PREFIXES: readonly string[] = ['gazetteer', 'indicators', 'atlas', 'obis-h3', 'basemap', 'marine-atlas', 'issues']

/** first path segments in the public bucket that need a key for every file (served like `/unlisted/`, class `unlisted`) */
export const RESTRICTED_PREFIXES: readonly string[] = ['atlas-restricted']

/** objects at the bucket root that are served; every other root object (and `backups/`) is a 404 */
export const ROOT_FILES: readonly string[] = ['index.html', 'README.md']

/** the 404 message for a path outside the served prefixes */
export const SERVED_MESSAGE = 'served prefixes: ' +
  [...PUBLIC_PREFIXES.map(p => `/${p}/`), '/unlisted/gazetteer/ (key)', ...RESTRICTED_PREFIXES.map(p => `/${p}/ (key)`),
    ...ROOT_FILES.map(f => `/${f}`)].join(', ')

/** a resolved request path: bucket, R2 object key and the metric prefix (first segment, `root` for root files) */
export interface Target { store: Store, key: string, prefix: string }

/** bucket and R2 object key for a request path, or null when the path is outside the served prefixes or is unsafe.
 *  A folder URL (ending in `/`, or the bare `/`) reads `index.html` under it (the old Caddy's `/marine-atlas/` rewrite);
 *  it is a 404 later when that object does not exist. Both buckets use the same `gazetteer/...` key layout. */
export function target(pathname: string): Target | null {
  let p: string
  try { p = decodeURIComponent(pathname) } catch { return null }
  p = p.replace(/^\/+/, '')
  let store: Store = 'public'
  if (p.startsWith(UNLISTED_PREFIX)) {
    store = 'unlisted'; p = p.slice(UNLISTED_PREFIX.length)
    if (!p.startsWith('gazetteer/')) return null
  }
  if (p === '' || p.endsWith('/')) p += 'index.html'
  const segs = p.split('/')
  if (segs.some(seg => seg === '..' || seg === '.' || seg === '')) return null
  if (segs.length === 1) return store === 'public' && ROOT_FILES.includes(p) ? { store, key: p, prefix: 'root' } : null
  const first = segs[0]
  if (store === 'unlisted') return { store, key: p, prefix: 'unlisted' }
  if (!PUBLIC_PREFIXES.includes(first) && !RESTRICTED_PREFIXES.includes(first)) return null
  return { store, key: p, prefix: first }
}

/** R2 object key for a public request path (see `target`), or null. */
export function objectKey(pathname: string): string | null {
  const t = target(pathname)
  return t && t.store === 'public' ? t.key : null
}

/** keyless by type everywhere public: catalogs, manifests, pages, thumbnails, and the Atom feeds (`indicators/feeds/*.xml`,
 *  `.atom`), so a feed reader polling them never meets the anonymous data limiter */
const KEYLESS_EXT = new Set(['json', 'md', 'html', 'png', 'jpg', 'jpeg', 'txt', 'csv', 'svg', 'atom', 'xml'])
/** data by type (key tiers and the anonymous limiter); any extension not listed in either set is data too */
const DATA_EXT: Record<string, PathClass> = {
  parquet: 'parquet', pmtiles: 'pmtiles', tif: 'tif', tiff: 'tif', duckdb: 'data', zip: 'data', gz: 'data', fgb: 'data',
}

/** lower-cased extension of the last path segment, '' when it has none */
export function extOf(key: string): string {
  const base = key.slice(key.lastIndexOf('/') + 1).toLowerCase()
  const i = base.lastIndexOf('.')
  return i > 0 ? base.slice(i + 1) : ''
}

/** path class and gate. Public: by type, not prefix: json/md/html/png/jpg/txt/csv/svg/atom/xml (and an extensionless `credits`)
 *  are open; parquet/pmtiles/tif/duckdb/zip/gz/fgb and unknown extensions are data, which falls to the anonymous tier
 *  without a key, except under `gazetteer/index/` (open). `atlas-restricted/...`: class `unlisted`, every file needs a key.
 *  Unlisted bucket: class `unlisted`, every path needs a key except `gazetteer/index/` (the `unlisted.json` listing). */
export function classify(key: string, store: Store = 'public'): { cls: PathClass, gate: Gate } {
  const lower = key.toLowerCase()
  const index = lower.startsWith('gazetteer/index/')
  if (store === 'unlisted') return { cls: 'unlisted', gate: index ? 'open' : 'key' }
  if (RESTRICTED_PREFIXES.some(p => lower.startsWith(`${p}/`))) return { cls: 'unlisted', gate: 'key' }
  const ext = extOf(lower)
  if (ext === 'json') return { cls: 'stac', gate: 'open' }
  if (KEYLESS_EXT.has(ext) || lower.endsWith('/credits')) return { cls: 'other', gate: 'open' }
  return { cls: DATA_EXT[ext] ?? 'data', gate: index ? 'open' : 'anonymous' }
}

/** object key of the licence/credits page whose existence turns on the `Link` header for a prefix other than gazetteer */
export const creditsKey = (prefix: string): string => `${prefix}/index/credits`

const TYPES: Record<string, string> = {
  json:    'application/json',
  parquet: 'application/vnd.apache.parquet',
  pmtiles: 'application/vnd.pmtiles',
  tif:     'image/tiff',
  tiff:    'image/tiff',
  csv:     'text/csv; charset=utf-8',
  md:      'text/markdown; charset=utf-8',
  txt:     'text/plain; charset=utf-8',
  html:    'text/html; charset=utf-8',
  jpg:     'image/jpeg',
  jpeg:    'image/jpeg',
  png:     'image/png',
  svg:     'image/svg+xml',
  atom:    'application/atom+xml; charset=utf-8',
  xml:     'application/xml; charset=utf-8',
  zip:     'application/zip',
  gz:      'application/gzip',
}

export function guessContentType(key: string): string {
  return TYPES[extOf(key)] ?? 'application/octet-stream'
}

/** stored content types that say nothing; the extension guess replaces them */
export const GENERIC_TYPES = new Set(['application/octet-stream', 'binary/octet-stream'])

// immutable keys (the edge cache) ----

/** data types that may be immutable; JSON, html, md, txt, csv, xml/atom (catalogs, manifests, feeds) never are */
export const IMMUTABLE_EXT = new Set(['parquet', 'pmtiles', 'tif', 'tiff', 'fgb'])

/** a content-addressed marine-atlas file name: the hash, optionally `_3857` (the Web Mercator copy of the same hash) */
const HASH_NAME = /^[0-9a-f]{16,64}(_3857)?\.(tif|tiff|pmtiles)$/

/** a release or schema version folder: `v20261012`, `v2` */
const VERSION_DIR = /^v\d+$/

/** MIRRORED in shell by is_immutable() in oceanmetrics/platform scripts/om-publish.sh (which refuses to overwrite such a key with
 *  different bytes; its yes/no tables in scripts/om-publish.test.ts are this file's test/edge.test.ts): change both together.
 *  may this object be served with `Cache-Control: public, max-age=31536000, immutable` and kept in the edge cache?
 *  Only public data files whose key names their content, from the catalogs' publish layouts (2026-10-23):
 *    obis-h3/v<digits>/**             a release folder (`obis-h3/v20261012/species_flat/res=3/p=<cell>.parquet`)
 *    marine-atlas/**\/<hash>.tif|pmtiles, <hash>_3857.tif   content-addressed (`cog/`, `native/`, `cog_3857/`, `v7/cog_3857/`)
 *    atlas/<collection>/**\/v<digits>/**  a versioned folder below the collection (`aquamaps_native/registry/v2/registry.parquet`)
 *    basemap/<set>/**\/v<digits>/**      a versioned folder (none yet: `basemap/gebco/core.pmtiles` is rebuilt in place)
 *  Never: any JSON or other metadata type (`latest.json`, `collection.json`, `release.json`, `layers.json`, feeds),
 *  `_history/`, `gazetteer/` (`<slug>/places.parquet` is replaced per version, no version folder), `indicators/`,
 *  `issues/`, the root files, `atlas-restricted/` and the unlisted bucket. The contract this sets for publishers: a key
 *  that matches is never rewritten with other bytes (an amendment adds files or starts a new version folder). */
export function isImmutable(key: string, store: Store = 'public'): boolean {
  if (store !== 'public') return false
  const segs = key.split('/')
  if (segs.length < 3 || segs.some(s => s === '' || s === '_history')) return false
  if (!IMMUTABLE_EXT.has(extOf(key))) return false
  const dirs = segs.slice(1, -1)
  switch (segs[0]) {
    case 'obis-h3':      return VERSION_DIR.test(segs[1])
    case 'marine-atlas': return HASH_NAME.test(segs[segs.length - 1])
    case 'atlas':
    case 'basemap':      return dirs.slice(1).some(d => VERSION_DIR.test(d))
    default:             return false
  }
}
