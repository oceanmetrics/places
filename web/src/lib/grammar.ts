// the shared URL grammar (plan §7), the same as CalCOFI explore:
//   ?layers=slug[:colour][:opacity][:width],…   draw order, first on top; `layers=off` = none
//   &place=<place_id>
//   &proj=mercator                               the map projection; absent = globe (the default)
//   &layer=<kind>:<id>[:<variable>]               the layer under the map (@oceanmetrics/map's slot key, e.g.
//                                                grid:jplMURSST41mday:sst); absent = none
//   &t=<period>                                  the period the layer is drawn at: 2024, 2024-07 or 2024-07-15; absent =
//                                                the dataset's latest. the same `t` as the indicators app's hash
// colour = 6 hex digits without `#` (a leading `#` is accepted), opacity 0..1 (2 dp), width 0.5..4 px (0.5 steps).

export interface LayerSel {
  slug   : string
  colour : string | null
  opacity: number | null
  width  : number | null
}

export interface ViewState {
  /** null = the parameter is absent (no layers chosen); [] = `layers=off` */
  layers: LayerSel[] | null
  place : string | null
  proj  : Projection
  /** the layer under the map as its slot key (`grid:jplMURSST41mday:sst`), null for none */
  layer : string | null
  /** the period of the layer: `2024`, `2024-07` or `2024-07-15`; null = the latest */
  t     : string | null
}

export type Projection = 'globe' | 'mercator'

const HEX = /^#?([0-9a-fA-F]{6})$/

const clean = (n: number, f: (x: number) => number) => f(n)

/** parse the value of `layers=`; unparseable fields become null, an entry without a slug is dropped. */
export function parseLayers(v: string | null | undefined): LayerSel[] | null {
  if (v == null || v === '') return null
  if (v === 'off') return []
  const out: LayerSel[] = [], seen = new Set<string>()
  for (const e of v.split(',')) {
    const [slug, c, o, w] = e.split(':')
    if (!slug || seen.has(slug)) continue
    seen.add(slug)
    const hex = c ? HEX.exec(c) : null
    out.push({
      slug,
      colour : hex ? '#' + hex[1].toLowerCase() : null,
      opacity: o !== undefined && o !== '' && isFinite(+o) && +o >= 0 && +o <= 1 ? clean(+o, (x) => Math.round(x * 100) / 100) : null,
      width  : w !== undefined && w !== '' && isFinite(+w) && +w >= 0.5 && +w <= 4 ? clean(+w, (x) => Math.round(x * 2) / 2) : null,
    })
  }
  return out.length ? out : null
}

/** the value of `layers=` for a list (`off` for an empty list); trailing empty fields are dropped. */
export function serializeLayers(ls: LayerSel[]): string {
  if (!ls.length) return 'off'
  return ls.map((l) => {
    const f = [l.slug, l.colour ? l.colour.replace(/^#/, '').toLowerCase() : '', l.opacity != null ? String(l.opacity) : '', l.width != null ? String(l.width) : '']
    while (f.length > 1 && f[f.length - 1] === '') f.pop()
    return f.join(':')
  }).join(',')
}

const PERIOD = /^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$/

/** a period as `t=` takes it (a year, a month or a day), else null */
export const parsePeriod = (v: string | null | undefined): string | null => (v && PERIOD.test(v.trim()) ? v.trim() : null)

/** a slot key as `layer=` takes it: `<kind>:<id>[:<variable>]` with a known kind (`erddap:` is read as `grid:`), else null */
export function parseLayerParam(v: string | null | undefined): string | null {
  const m = /^(grid|cog|h3|erddap):([\w.-]+)(?::([\w.-]+))?$/.exec((v ?? '').trim())
  return m ? `${m[1] === 'erddap' ? 'grid' : m[1]}:${m[2]}${m[3] ? `:${m[3]}` : ''}` : null
}

/** read the view from a query string (with or without the leading `?`). */
export function parseView(search: string): ViewState {
  const p = new URLSearchParams(search)
  return {
    layers: parseLayers(p.get('layers')), place: p.get('place') || null, proj: p.get('proj') === 'mercator' ? 'mercator' : 'globe',
    layer : parseLayerParam(p.get('layer')), t: parsePeriod(p.get('t')),
  }
}

/** view settings that follow the user from page to page (not part of a page's own state): the projection, and the
 * layer under the map at its period, so the same place in another layer opens on the same layer */
export const CARRIED = ['proj', 'layer', 't'] as const

/**
 * add the carried settings of the current query to an in-app url that does not set them itself, so a page change
 * keeps e.g. `proj=mercator`. `url` is a path with an optional query (and hash).
 */
export function carryView(url: string, current: string): string {
  const cur = new URLSearchParams(current)
  const [rest, hash = ''] = url.split('#')
  const [path, q = ''] = rest.split('?')
  const p = new URLSearchParams(q)
  let changed = false
  for (const k of CARRIED) if (!p.has(k) && cur.has(k)) { p.set(k, cur.get(k)!); changed = true }
  if (!changed) return url
  const s = p.toString().replace(/%3A/gi, ':').replace(/%2C/gi, ',').replace(/%2F/gi, '/')
  return path + (s ? '?' + s : '') + (hash ? '#' + hash : '')
}

/**
 * write the view into a query string, keeping every other parameter (e.g. `base`, `theme`).
 * place ids carry a colon; it is left unescaped so links read well.
 */
export function buildSearch(view: Partial<ViewState>, current = ''): string {
  const p = new URLSearchParams(current)
  if ('layers' in view) {
    if (view.layers == null) p.delete('layers'); else p.set('layers', serializeLayers(view.layers))
  }
  if ('place' in view) {
    if (!view.place) p.delete('place'); else p.set('place', view.place)
  }
  if ('proj' in view) {
    if (view.proj === 'mercator') p.set('proj', 'mercator'); else p.delete('proj')
  }
  if ('layer' in view) {
    const l = parseLayerParam(view.layer)
    if (l) p.set('layer', l); else p.delete('layer')
  }
  if ('t' in view) {
    const t = parsePeriod(view.t)
    if (t) p.set('t', t); else p.delete('t')
  }
  const s = p.toString().replace(/%3A/gi, ':').replace(/%2C/gi, ',')
  return s ? '?' + s : ''
}
