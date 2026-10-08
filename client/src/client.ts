import { asyncBufferFromUrl, parquetMetadataAsync, parquetReadObjects } from 'hyparquet'
import type { AsyncBuffer, FileMetaData } from 'hyparquet'
import { compressors } from 'hyparquet-compressors'
import { addLayerSpec, removeLayerSpec } from './map'
import { geometryBBox, unwrapAntimeridian } from './unwrap'
import { wkbToGeometry } from './wkb'
import type {
  AddLayerOptions, BBox, ClientConfig, CreditRef, GetPlaceOptions, IndexPlace, Layer, MapLike, PlaceFeature, SearchOptions,
} from './types'

export const DEFAULT_BASE = 'https://storage.oceanmetrics.io/gazetteer/'
const FOOTER_GUESS = 16 * 1024
const SUFFIX = /\s*Processed by Ocean Metrics\.?\s*$/i

// helpers ----
const slash = (b: string) => (b.endsWith('/') ? b : b + '/')
const norm = (s: string) => s.normalize('NFD').replace(/\p{M}/gu, '').toLowerCase().trim()
const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
const arr = <T>(x: T | T[] | undefined): T[] => (x === undefined ? [] : Array.isArray(x) ? x : [x])

/** hyparquet returns BigInt for int64 and Date for timestamps; make a value JSON-friendly. */
function plain(v: unknown): unknown {
  if (typeof v === 'bigint') return Number(v)
  if (v instanceof Date) return v.toISOString()
  if (Array.isArray(v)) return v.map(plain)
  return v
}

function toBBox(b: any): BBox | null {
  if (!b) return null
  if (Array.isArray(b)) return [Number(b[0]), Number(b[1]), Number(b[2]), Number(b[3])]
  return [Number(b.xmin), Number(b.ymin), Number(b.xmax), Number(b.ymax)]
}

function toLonLat(c: any): [number, number] | null {
  if (!c) return null
  if (Array.isArray(c)) return [Number(c[0]), Number(c[1])]
  const x = c.x ?? c.lon ?? c.lng, y = c.y ?? c.lat
  return x === undefined ? null : [Number(x), Number(y)]
}

/**
 * do two [w, s, e, n] boxes intersect? `a` may cross the antimeridian (w > e); `b` (an index bbox) may be unwrapped,
 * i.e. its east edge beyond 180 (a place cut at the antimeridian is indexed as 177..199): it is also tried shifted by -360.
 */
export function bboxIntersects(a: BBox, b: BBox): boolean {
  if (!(a[1] <= b[3] && a[3] >= b[1])) return false
  const lon = (w: number, e: number, x0: number, x1: number) => w <= x1 && e >= x0
  const hit = (x0: number, x1: number) => (a[0] <= a[2] ? lon(a[0], a[2], x0, x1) : lon(a[0], 180, x0, x1) || lon(-180, a[2], x0, x1))
  return hit(b[0], b[2]) || (b[2] > 180 && hit(b[0] - 360, b[2] - 360))
}

/** the credit line for attribution strings: deduped; the shared "Processed by Ocean Metrics." said once at the end. */
export function creditLine(parts: string[]): string {
  const seen = new Set<string>(), cores: string[] = []
  let processed = false
  for (const raw of parts) {
    const t = raw.replace(/\s+/g, ' ').trim()
    if (!t) continue
    if (SUFFIX.test(t)) processed = true
    const core = t.replace(SUFFIX, '').replace(/[.;\s]+$/, '')
    if (core && !seen.has(core)) { seen.add(core); cores.push(core) }
  }
  if (!cores.length) return processed ? 'Processed by Ocean Metrics.' : ''
  return cores.join('; ') + '.' + (processed ? ' Processed by Ocean Metrics.' : '')
}

// the client ----
/** create a client bound to one gazetteer root; the module-level functions use a default client (see `configure`). */
export function createClient(initial: ClientConfig = {}) {
  let cfg: ClientConfig = { ...initial }
  let layersP: Promise<Layer[]> | null = null
  let indexP: Promise<IndexPlace[]> | null = null
  const files = new Map<string, Promise<{ file: AsyncBuffer; metadata: FileMetaData }>>()
  const found = new Map<string, string>()      // place_id -> slug, once looked up

  const base = () => slash(cfg.base ?? DEFAULT_BASE)
  const doFetch = () => cfg.fetch ?? globalThis.fetch.bind(globalThis)
  // layers.json is published at index/layers.json; the root copy is the fallback (and the only copy of older publishes)
  const layersUrl = () => cfg.layersUrl ?? `${base()}index/layers.json`
  const layersFallbackUrl = () => (cfg.layersUrl ? null : `${base()}layers.json`)
  const indexUrl = () => cfg.indexUrl ?? `${base()}index/places_index.parquet`
  const parquetUrl = (slug: string) => (cfg.parquetUrl ? cfg.parquetUrl(slug) : `${base()}${slug}/places.parquet`)

  /** change the gazetteer root, URLs or fetch; clears the caches. */
  function configure(next: ClientConfig) {
    cfg = { ...cfg, ...next }
    layersP = indexP = null
    files.clear()
    found.clear()
  }

  // one range-readable handle per parquet url, its footer read once (a 16 kB tail read, not hyparquet's 512 kB guess)
  const open = (url: string) => {
    if (!files.has(url)) {
      const p = asyncBufferFromUrl({ url, fetch: doFetch() }).then(async (file) => ({ file, metadata: await parquetMetadataAsync(file, { initialFetchSize: FOOTER_GUESS }) }))
      files.set(url, p)
      p.catch(() => files.delete(url))
    }
    return files.get(url)!
  }

  // layers ----
  /** the layers manifest (layers.json), cached; `refresh` re-fetches. */
  function listLayers(opts: { refresh?: boolean } = {}): Promise<Layer[]> {
    if (!layersP || opts.refresh) {
      const url = layersUrl(), alt = layersFallbackUrl()
      layersP = doFetch()(url).then(async (r) => {
        if (!r.ok && alt && (r.status === 404 || r.status === 403)) {
          const r2 = await doFetch()(alt)           // index/ missing: try the root copy
          if (r2.ok) r = r2
        }
        if (!r.ok) throw new Error(`layers.json: ${r.status} ${r.statusText} (${url})`)
        const j = await r.json()
        return (Array.isArray(j) ? j : j.layers) as Layer[]
      })
      layersP.catch(() => { layersP = null })
    }
    return layersP
  }

  async function getLayer(slug: string): Promise<Layer> {
    const l = (await listLayers()).find((x) => x.slug === slug)
    if (!l) throw new Error(`unknown layer "${slug}"`)
    return l
  }

  async function addLayer(map: MapLike, slug: string, opts: AddLayerOptions = {}): Promise<string[]> {
    return addLayerSpec(map, await getLayer(slug), opts)
  }
  const removeLayer = (map: MapLike, slug: string): void => removeLayerSpec(map, slug)

  // index + search ----
  function loadIndex(): Promise<IndexPlace[]> {
    if (!indexP) {
      indexP = open(indexUrl())
        .then((f) => parquetReadObjects({ ...f, compressors, utf8: false }))
        .then((rows) => rows.map((r: any): IndexPlace => ({
          place_id: String(r.place_id), name: String(r.name ?? ''), authority: String(r.authority ?? ''),
          place_type: String(r.place_type ?? ''), geom_type: r.geom_type == null ? null : String(r.geom_type),
          collection: String(r.collection ?? ''), bbox: toBBox(r.bbox)!,
          // live schema: centroid_lon / centroid_lat (doubles); the pre-0.1.1 `centroid` list is still read
          centroid: r.centroid_lon != null && r.centroid_lat != null ? [Number(r.centroid_lon), Number(r.centroid_lat)] : toLonLat(r.centroid),
          area_km2: r.area_km2 == null ? null : Number(r.area_km2), license: r.license ?? null,
          attribution: r.attribution ?? null, version: r.version ?? null,
          updated: r.updated == null ? null : (plain(r.updated) as string),
        })))
      indexP.catch(() => { indexP = null })
    }
    return indexP
  }

  /**
   * search places_index.parquet by name or place_id. Every whitespace-separated word of `q` must occur
   * (case and accent insensitive); results rank exact name, name prefix, word prefix, then substring, larger areas first.
   * a place_id is unique within a collection, not across them (`BOEM:OCS-P 0562` is in two collections): every
   * (collection, place_id) is its own hit; pass the hit's `collection` to `getPlace` as `slug`.
   */
  async function search(q: string, opts: SearchOptions = {}): Promise<IndexPlace[]> {
    const { bbox, limit = 20 } = opts
    const types = arr(opts.type).map(norm), auths = arr(opts.authority).map(norm)
    const query = norm(q ?? ''), words = query.split(/\s+/).filter(Boolean)
    const scored: Array<[number, IndexPlace]> = []
    for (const p of await loadIndex()) {
      if (types.length && !types.includes(norm(p.place_type))) continue
      if (auths.length && !auths.includes(norm(p.authority))) continue
      if (bbox && p.bbox && !bboxIntersects(bbox, p.bbox)) continue
      let score = 0
      if (words.length) {
        const name = norm(p.name), id = norm(p.place_id), hay = `${name} ${id}`
        if (!words.every((w) => hay.includes(w))) continue
        score = id === query ? 0 : name === query ? 0 : name.startsWith(query) ? 1
          : name.split(/[\s\-_/,()]+/).some((w) => w.startsWith(words[0])) ? 2 : 3
      }
      scored.push([score, p])
    }
    scored.sort((a, b) => a[0] - b[0] || (b[1].area_km2 ?? 0) - (a[1].area_km2 ?? 0) || a[1].name.localeCompare(b[1].name)
      || a[1].collection.localeCompare(b[1].collection))
    return scored.slice(0, limit).map((s) => s[1])
  }

  // places ----
  async function candidateSlugs(id: string): Promise<string[]> {
    const cached = found.get(id)
    if (cached) return [cached]
    const authority = id.split(':')[0]
    const layers = await listLayers()
    const rank = (l: Layer) => (l.authority === authority ? 0 : l.authority == null ? 1 : 2)
    return [...layers].sort((a, b) => rank(a) - rank(b)).map((l) => l.slug)
  }

  /**
   * one place as a GeoJSON Feature (`id` = place_id), read from the collection parquet by id with a filtered
   * range read (only the row group holding the id is fetched). `null` if no collection has it.
   * `unwrap: true` unwraps antimeridian-split parts into contiguous longitudes beyond 180 (see `unwrapAntimeridian`).
   * `slug` pins the collection (no guessing): use it from a search hit's `collection`, since a place_id can occur in
   * more than one collection and an unpinned lookup returns the first (the id's authority first, then manifest order).
   */
  async function getPlace(id: string, opts: GetPlaceOptions = {}): Promise<PlaceFeature | null> {
    for (const slug of opts.slug ? [opts.slug] : await candidateSlugs(id)) {
      let rows: Record<string, any>[]
      try {
        rows = await parquetReadObjects({ ...(await open(parquetUrl(slug))), filter: { place_id: { $eq: id } }, compressors, utf8: false })
      } catch (e) {
        // a layer listed in the manifest without a parquet (404) cannot hold the id: try the next one
        if (/\b404\b/.test(String((e as Error)?.message))) continue
        throw e
      }
      const r: any = rows.find((x: any) => x.place_id === id)
      if (!r) continue
      if (!opts.slug) found.set(id, slug)       // a pinned lookup says nothing about where an unpinned one should look
      const { geometry: raw, bbox: rawBox, ...rest } = r
      let geometry = raw instanceof Uint8Array ? wkbToGeometry(raw) : raw
      if (opts.unwrap) geometry = unwrapAntimeridian(geometry)
      const properties = Object.fromEntries(Object.entries(rest).map(([k, v]) => [k, plain(v)]))
      const bbox = opts.unwrap ? geometryBBox(geometry) : (toBBox(rawBox) ?? geometryBBox(geometry))
      return { type: 'Feature', id, bbox, properties, geometry } as PlaceFeature
    }
    return null
  }

  /**
   * the deduped credit line for what is on screen. Pass place ids ("BOEM:OCS-P 0561", read from the index), search hits
   * or `{ collection, place_id }` pairs, and/or layer slugs ("boem_wind_leases", read from layers.json). A bare id that
   * occurs in several collections credits all of them (pass a hit or a pair to pin one). Unknown ids and slugs are skipped.
   * `html: true` returns the layer's `attribution_html` (links) and escapes the index's plain text.
   */
  async function creditsFor(refs: CreditRef | CreditRef[], opts: { html?: boolean } = {}): Promise<string> {
    const list = arr(refs)
    const slugs = list.filter((r): r is string => typeof r === 'string' && !r.includes(':'))
    const ids = list.filter((r) => typeof r !== 'string' || r.includes(':'))
    const parts: string[] = []
    if (slugs.length) {
      const layers = await listLayers()
      for (const s of slugs) {
        const l = layers.find((x) => x.slug === s)
        if (l) parts.push(opts.html ? l.attribution_html : l.attribution)
      }
    }
    if (ids.length) {
      // keyed on (collection, place_id): the id alone is not unique across collections
      const byKey = new Map<string, IndexPlace>(), byId = new Map<string, IndexPlace[]>()
      for (const p of await loadIndex()) {
        byKey.set(`${p.collection}\u0000${p.place_id}`, p)
        byId.set(p.place_id, [...(byId.get(p.place_id) ?? []), p])
      }
      for (const r of ids) {
        const hits = typeof r === 'string' ? byId.get(r) ?? []
          : r.collection ? [byKey.get(`${r.collection}\u0000${r.place_id}`)] : byId.get(r.place_id) ?? []
        for (const h of hits) if (h?.attribution) parts.push(opts.html ? esc(h.attribution) : h.attribution)
      }
    }
    return creditLine(parts)
  }

  return { configure, listLayers, getLayer, addLayer, removeLayer, search, getPlace, creditsFor }
}

// the default client ----
const def = createClient()
export const configure = def.configure
export const listLayers = def.listLayers
export const getLayer = def.getLayer
export const addLayer = def.addLayer
export const removeLayer = def.removeLayer
export const search = def.search
export const getPlace = def.getPlace
export const creditsFor = def.creditsFor
