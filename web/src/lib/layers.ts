// "Layers that cover this place": the atlas collections (Ocean Metrics' species and biodiversity layers, and the
// MarineSensitivity ones by reference) and the gazetteer's ERDDAP layers whose extent meets the place's box, with a link
// into the atlas that carries the place (its `p.` token, atlas docs/gazetteer-places.md) or onto this page's own map
// (`layer=`). plain functions, tested; the reading is the small `loadAtlasCollections` at the end.
//
// an extent is a box, and most of these layers are global, so "meets the box" says little: the line says how many are
// global. a check of where each layer has data (each collection's H3 cells against the place's H3 membership) waits on the
// atlas collections' H3 twins.
import type { ErddapLayer } from './map/gridLayer'
import { isAuxVariable } from './map/gridLayer'

export const ATLAS_APP = 'https://oceanmetrics.io/atlas/'
/** the atlas catalog at the bucket's path-style url (CORS for every read; the storage host 302s) */
export const ATLAS_CATALOG = 'https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/atlas/catalog.json'

export type Box = [number, number, number, number]

export interface CoverLayer {
  /** the collection's id (the atlas's `c=`, or the ERDDAP dataset id) */
  id: string
  title: string
  source: 'atlas' | 'erddap'
  bbox: Box | null
  /** a short line under the title: licence, protocol, period */
  note?: string
  /** the grid key a gridded ERDDAP layer is drawn under the map with */
  layerKey?: string
}

export interface Covering extends CoverLayer {
  /** the extent is the whole ocean: it meets every place */
  global: boolean
}

// ---- boxes ----

/** a box's longitudes as one interval on an unwrapped axis: a box crossing ±180 (west > east) runs past 180 */
const lonSpan = (b: Box): [number, number] => (b[0] <= b[2] ? [b[0], b[2]] : [b[0], b[2] + 360])

/** do two [w, s, e, n] boxes meet? either may cross ±180 (west > east) or be unwrapped (east beyond 180) */
export function boxesMeet(a: Box, b: Box): boolean {
  if (a[1] > b[3] || b[1] > a[3]) return false
  const [a0, a1] = lonSpan(a), [b0, b1] = lonSpan(b)
  if (a1 - a0 >= 360 || b1 - b0 >= 360) return true
  return [-360, 0, 360].some((k) => a0 <= b1 + k && b0 + k <= a1)
}

/** the extent runs round the globe and from pole to pole, give or take a cell */
export const isGlobal = (b: Box | null): boolean => !!b && b[0] <= b[2] && b[2] - b[0] >= 359 && b[3] - b[1] >= 170

/**
 * the layers whose extent meets the place's box, global ones last within each source (atlas, then ERDDAP), each kept in
 * the order given; a layer without an extent is left out (nothing says it covers the place)
 */
export function layersCovering(place: { bbox: Box | null }, layers: readonly CoverLayer[]): Covering[] {
  if (!place.bbox) return []
  const hits = layers.filter((l) => l.bbox && boxesMeet(place.bbox!, l.bbox)).map((l) => ({ ...l, global: isGlobal(l.bbox) }))
  const rank = (c: Covering) => (c.source === 'atlas' ? 0 : 2) + (c.global ? 1 : 0)
  return hits.map((c, i) => ({ c, i })).sort((x, y) => rank(x.c) - rank(y.c) || x.i - y.i).map((x) => x.c)
}

/** "6 layers meet this place's box; 5 of them are global, so the box says little about where each has data." */
export function coverLine(hits: readonly Covering[]): string {
  const n = hits.length, g = hits.filter((h) => h.global).length
  if (!n) return 'No atlas or ERDDAP layer meets this place\'s box.'
  const head = `${n} ${n === 1 ? 'layer meets' : 'layers meet'} this place's box`
  if (!g) return `${head}.`
  const which = g === n ? (n === 1 ? 'it is global' : 'all of them are global') : `${g} of them ${g === 1 ? 'is' : 'are'} global`
  return `${head}; ${which} (the whole ocean), so the box says little about where each has data here. A check by data cell waits on the atlas collections' H3 cells.`
}

// ---- the atlas link with the place ----

/** the atlas's `g1` name encoding: `A-Za-z0-9_-` as they are, every other UTF-8 byte as `%XX` in upper case */
export function atlasEncode(s: string): string {
  let out = ''
  for (const b of new TextEncoder().encode(s)) {
    const c = String.fromCharCode(b)
    out += /[A-Za-z0-9_-]/.test(c) ? c : '%' + b.toString(16).toUpperCase().padStart(2, '0')
  }
  return out
}

/** the longest start of `name` whose encoding fits `max` characters (never half a character) */
function fitName(name: string, max: number): string {
  let out = ''
  for (const ch of name) {
    const next = out + atlasEncode(ch)
    if (next.length > max) break
    out = next
  }
  return out
}

/** the atlas's place-by-reference token: `p.<id>.<name>`, the id at most 120 encoded characters, the name at most 60 */
export function placeToken(id: string, name = ''): string | null {
  const enc = atlasEncode(id)
  if (!enc || enc.length > 120) return null
  return `p.${enc}.${fitName(name.trim(), 60)}`
}

/** the atlas opened on a collection with the place: `?c=<id>#pl=<token>` (the hash value as the atlas's URLSearchParams reads it back) */
export function atlasHref(collectionId: string, placeId: string, name = '', app = ATLAS_APP): string {
  const q = new URLSearchParams({ c: collectionId }).toString()
  const tok = placeToken(placeId, name)
  return `${app}?${q}${tok ? '#' + new URLSearchParams({ pl: tok }).toString() : ''}`
}

// ---- the collections ----

interface StacLike {
  id?: string
  title?: string
  license?: string
  extent?: { spatial?: { bbox?: number[][] } }
}

const boxOf = (c: StacLike): Box | null => {
  const b = c.extent?.spatial?.bbox?.[0]
  return b && b.length === 4 && b.every(Number.isFinite) ? (b as Box) : null
}

/** an atlas collection.json as a layer that may cover a place */
export const atlasLayer = (c: StacLike): CoverLayer | null =>
  c.id ? { id: c.id, title: c.title ?? c.id, source: 'atlas', bbox: boxOf(c), note: c.license ? `licence ${c.license}` : undefined } : null

/** an ERDDAP collection of the gazetteer as a layer that may cover a place, with its grid key when it is a grid */
export function erddapLayer(l: ErddapLayer): CoverLayer {
  const v = l.variables.find((x) => !isAuxVariable(x.name))
  const period = l.time[0] ? ` · ${l.time[0].slice(0, 4)} to ${l.time[1]?.slice(0, 4) ?? 'now'}` : ''
  return {
    id: l.id, title: l.title, source: 'erddap', bbox: l.bbox,
    note: `${l.protocol === 'griddap' ? 'grid' : 'stations (tabledap)'}${l.spacing ? `, ${l.spacing}°` : ''}${period} · ERDDAP at ${l.host}`,
    layerKey: l.protocol === 'griddap' && v ? `grid:${l.id}:${v.name}` : undefined,
  }
}

/** the children of a STAC catalog, made absolute against the catalog's url */
export function childUrls(catalog: { links?: { rel?: string; href?: string }[] }, catalogUrl: string): string[] {
  return (catalog.links ?? []).filter((l) => l.rel === 'child' && l.href).map((l) => new URL(l.href!, catalogUrl).href)
}

let atlas: Promise<CoverLayer[]> | null = null

/** the atlas catalog's collections, read once a page (one that does not answer is left out) */
export function loadAtlasCollections(fetchFn: typeof fetch = fetch): Promise<CoverLayer[]> {
  atlas ??= (async () => {
    const r = await fetchFn(ATLAS_CATALOG)
    if (!r.ok) throw new Error(`atlas catalog.json: HTTP ${r.status}`)
    const got = await Promise.all(childUrls(await r.json(), ATLAS_CATALOG).map(async (u) => {
      try { const c = await fetchFn(u); return c.ok ? atlasLayer(await c.json()) : null } catch { return null }
    }))
    return got.filter((l): l is CoverLayer => !!l)
  })()
  atlas.catch(() => { atlas = null })
  return atlas
}
