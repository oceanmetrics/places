// pure helpers shared by the pages (kept free of the DOM and the map so they are unit-tested)
import type { Layer } from '@oceanmetrics/places'

export const DEFAULT_BASE = 'https://storage.oceanmetrics.io/gazetteer/'
export const REPO_URL     = 'https://github.com/oceanmetrics/places'
export const CALCOFI_EXPLORE = 'https://calcofi.io/explore/'
export const ERDDAP_PLACES   = 'https://oceanmetrics.io/erddap-places/'

export const slash = (b: string) => (b.endsWith('/') ? b : b + '/')

/** the path prefix the site is served under: '' at the root, '/places' on GitHub Pages (vite --base). */
export const APP_BASE = (import.meta.env?.BASE_URL ?? '/').replace(/\/+$/, '')

// routes ----
export type Route =
  | { name: 'home' }
  | { name: 'place'; id: string }
  | { name: 'layer'; slug: string }
  | { name: 'credits' }
  | { name: 'docs' }
  | { name: 'notfound' }

/** which page a pathname is. Place ids carry a colon (and sometimes a slash, encoded), so the rest of the path is the id. */
export function matchRoute(pathname: string, appBase = APP_BASE): Route {
  if (appBase && pathname.startsWith(appBase)) pathname = pathname.slice(appBase.length)
  const p = pathname.replace(/\/+$/, '') || '/'
  if (p === '/') return { name: 'home' }
  if (p === '/credits') return { name: 'credits' }
  if (p === '/docs') return { name: 'docs' }
  const m = /^\/([pl])\/(.+)$/.exec(p)
  if (m) {
    let v = m[2]
    try { v = decodeURIComponent(v) } catch { /* keep the raw text */ }
    return m[1] === 'p' ? { name: 'place', id: v } : { name: 'layer', slug: v }
  }
  return { name: 'notfound' }
}

/** the path of a place page; the colon is left readable. */
export const placePath = (id: string) => '/p/' + encodeURIComponent(id).replace(/%3A/gi, ':')
export const layerPath = (slug: string) => '/l/' + encodeURIComponent(slug)

// URLs ----
export const stacRoot       = (base: string) => `${slash(base)}catalog.json`
export const layersJsonUrl  = (base: string) => `${slash(base)}index/layers.json`
export const parquetUrl     = (base: string, slug: string) => `${slash(base)}${slug}/places.parquet`
export const readmeUrl      = (base: string, slug: string) => `${slash(base)}${slug}/README.md`
export const collectionUrl  = (base: string, slug: string) => `${slash(base)}${slug}/collection.json`

/** the page's own links live under APP_BASE and keep a `base=` override so a staging gazetteer stays selected while browsing. */
export function withBase(path: string, base: string, defaultBase = DEFAULT_BASE, appBase = APP_BASE): string {
  path = appBase + path
  if (slash(base) === slash(defaultBase)) return path
  const [p, q = ''] = path.split('?')
  const params = new URLSearchParams(q)
  params.set('base', base)
  return `${p}?${params.toString().replace(/%3A/gi, ':').replace(/%2F/gi, '/')}`
}

// grouping and formatting ----
/** layers grouped by authority (sorted, "Other" last), each group sorted by title. */
export function groupByAuthority(layers: Layer[]): Array<{ authority: string; layers: Layer[] }> {
  const m = new Map<string, Layer[]>()
  for (const l of layers) {
    const k = l.authority?.trim() || 'Other'
    if (!m.has(k)) m.set(k, [])
    m.get(k)!.push(l)
  }
  return [...m.entries()]
    .sort(([a], [b]) => (a === 'Other' ? 1 : b === 'Other' ? -1 : a.localeCompare(b)))
    .map(([authority, ls]) => ({ authority, layers: ls.slice().sort((a, b) => a.title.localeCompare(b.title)) }))
}

export const fmtN = (n: number | null | undefined) => (n == null ? '–' : n.toLocaleString('en-US'))

export function fmtDate(d: string | null | undefined): string {
  if (!d) return '–'
  return /^\d{4}-\d{2}-\d{2}/.test(d) ? d.slice(0, 10) : d
}

/** the layer's own colour (fill, else line, else circle), for the swatch and the colour input. */
export function defaultColour(layer: Layer | undefined): string {
  const p = layer?.paint
  const c = p?.fill?.['fill-color'] ?? p?.line?.['line-color'] ?? p?.circle?.['circle-color']
  return typeof c === 'string' && /^#[0-9a-f]{6}$/i.test(c) ? c.toLowerCase() : '#e08a1e'
}

/** the authority a place_id belongs to: the text before the first colon. */
export const authorityOf = (placeId: string) => (placeId.includes(':') ? placeId.slice(0, placeId.indexOf(':')) : '')

/**
 * the layer a place belongs to. `collection` (from a getPlace feature or a search hit) is exact and wins;
 * without it, layers whose authority matches the id prefix (the collection slug is also tried), then the one
 * whose place_type matches the row's, else the first.
 */
export function layerForPlace(layers: Layer[], placeId: string, props: Record<string, unknown> = {}, collection?: string): Layer | undefined {
  if (collection) {
    const hit = layers.find((l) => l.collection === collection)
    if (hit) return hit
  }
  const auth = authorityOf(placeId).toLowerCase()
  let c = layers.filter((l) => (l.authority ?? '').toLowerCase() === auth || l.slug.toLowerCase() === auth)
  if (!c.length) return undefined
  if (c.length > 1) {
    const t = String(props.place_type ?? '')
    const same = c.filter((l) => l.place_type === t)
    if (same.length) c = same
  }
  return c[0]
}

// "use in" deep links ----
export const calcofiLink = (slug: string) => `${CALCOFI_EXPLORE}?layers=${encodeURIComponent(slug)}`
export const erddapLink  = (placeId: string) => `${ERDDAP_PLACES}#place=${placeId}`

// download ----
const sqlQuote = (s: string) => `'${s.replace(/'/g, "''")}'`

/** DuckDB SQL that reads one place from the collection parquet and writes it as GeoJSON (until a download endpoint exists). */
export function geojsonSql(url: string, placeId: string): string {
  return [
    'INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;',
    `COPY (`,
    `  SELECT * EXCLUDE (geometry, bbox), ST_GeomFromWKB(geometry) AS geometry`,
    `  FROM read_parquet(${sqlQuote(url)})`,
    `  WHERE place_id = ${sqlQuote(placeId)}`,
    `) TO ${sqlQuote(placeId.replace(/[^\w.-]+/g, '_') + '.geojson')} WITH (FORMAT GDAL, DRIVER 'GeoJSON');`,
  ].join('\n')
}

/** the read_parquet snippets for /docs, for one parquet URL. */
export const recipes = (url: string) => ({
  duckdb: `INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;
SELECT place_id, name, status, ST_AsText(ST_GeomFromWKB(geometry)) AS wkt
FROM read_parquet('${url}')
WHERE bbox.xmin <= -117 AND bbox.xmax >= -125     -- bbox pushdown: west, east
  AND bbox.ymin <=   42 AND bbox.ymax >=   32;    --                south, north`,
  python: `import duckdb, geopandas as gpd, shapely
con = duckdb.connect(); con.sql("INSTALL httpfs; LOAD httpfs")
df = con.sql("""
  SELECT place_id, name, status, geometry
  FROM read_parquet('${url}')
  WHERE bbox.xmin <= -117 AND bbox.xmax >= -125 AND bbox.ymin <= 42 AND bbox.ymax >= 32""").df()
gdf = gpd.GeoDataFrame(df.drop(columns="geometry"), geometry=shapely.from_wkb(df["geometry"].map(bytes)), crs=4326)`,
  r: `library(DBI); library(duckdb); library(sf)
con <- dbConnect(duckdb()); dbExecute(con, "INSTALL httpfs; LOAD httpfs")
d <- dbGetQuery(con, "
  SELECT place_id, name, status, geometry
  FROM read_parquet('${url}')
  WHERE bbox.xmin <= -117 AND bbox.xmax >= -125 AND bbox.ymin <= 42 AND bbox.ymax >= 32")
x <- st_sf(d[c("place_id", "name", "status")], geometry = st_as_sfc(structure(d$geometry, class = "WKB")), crs = 4326)`,
})

/** a property value as table text (objects as JSON, empty as an en dash). */
export function fmtValue(v: unknown): string {
  if (v == null || v === '') return '–'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

// attribution html ----
const ALLOWED_TAGS = new Set(['a', 'b', 'i', 'em', 'strong', 'br', 'span', 'cite'])
const escText = (s: string) => s.replace(/</g, '&lt;').replace(/>/g, '&gt;')
const escAttr = (s: string) => s.replace(/&(?![a-zA-Z#0-9]+;)/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

/**
 * attribution_html comes from a manifest whose base URL can be overridden (`?base=`), so it is not trusted:
 * keep a handful of inline tags, links only with an http(s) href (opened in a new tab), drop every other tag
 * and every attribute.
 */
export function sanitizeHtml(html: string): string {
  return (html ?? '').split(/(<[^>]*>)/).map((seg) => {
    if (!seg.startsWith('<')) return escText(seg)
    const m = /^<(\/?)([a-zA-Z][a-zA-Z0-9]*)([^>]*)>$/.exec(seg)
    if (!m) return escText(seg)
    const [, close, name, attrs] = m, tag = name.toLowerCase()
    if (!ALLOWED_TAGS.has(tag)) return ''
    if (close) return tag === 'br' ? '' : `</${tag}>`
    if (tag !== 'a') return `<${tag}>`
    const h = /\bhref\s*=\s*(?:"([^"]*)"|'([^']*)')/i.exec(attrs)
    const href = (h?.[1] ?? h?.[2] ?? '').trim()
    return /^https?:\/\//i.test(href) ? `<a href="${escAttr(href)}" target="_blank" rel="noopener noreferrer">` : '<a>'
  }).join('')
}
