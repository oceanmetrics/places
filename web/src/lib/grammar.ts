// the shared URL grammar (plan §7), the same as CalCOFI explore:
//   ?layers=slug[:colour][:opacity][:width],…   draw order, first on top; `layers=off` = none
//   &place=<place_id>
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
}

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

/** read the view from a query string (with or without the leading `?`). */
export function parseView(search: string): ViewState {
  const p = new URLSearchParams(search)
  return { layers: parseLayers(p.get('layers')), place: p.get('place') || null }
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
  const s = p.toString().replace(/%3A/gi, ':').replace(/%2C/gi, ',')
  return s ? '?' + s : ''
}
