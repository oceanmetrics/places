// the ways in to the map's features from the Place page (Ben 2026-10-23: he could not find the layer under the map or Then vs
// Now without asking): the map's empty state names what can go under it with a one-click default (MUR SST at the latest
// month), and "Then vs Now" opens the indicators Map at this place with compare on, in the viewer's hash grammar (its
// CLAUDE.md: view, ind, pi, grain, t, t2, layer, place). plain rules; LayerUnder.svelte and Place.svelte only draw them.

/** the indicators viewer, where the compare mode lives */
export const INDICATORS_APP = 'https://oceanmetrics.io/indicators/'
/** the one-click layer under the map: MUR SST, monthly (t absent = the dataset's latest month) */
export const DEFAULT_LAYER = 'grid:jplMURSST41mday:sst'
/** the indicator the compare view opens on: sea surface temperature, the sanctuaries' lead series */
export const COMPARE_IND = 'erddap:dhw_5km:CRW_SST:mean'
/** Then is this many years before Now (July 2024 against July 2016, as the shoot script's compare view) */
export const THEN_YEARS = 8
/** what the map says when no layer is under it */
export const EMPTY_LAYER_LINE = 'Add a layer under the map: sea surface temperature, chlorophyll, …'

const MONTH = /^(\d{4})-(0[1-9]|1[0-2])$/

/** a period as a month: "2024-07-15" -> "2024-07", "2024" -> "2024-01" (as the month picker shows it), else null */
export function monthOf(t: string | null | undefined): string | null {
  const s = (t ?? '').trim()
  if (/^\d{4}$/.test(s)) return `${s}-01`
  const m = s.slice(0, 7)
  return MONTH.test(m) ? m : null
}

/** the same month `years` years before: "2024-07" -> "2016-07" */
export function yearsBefore(month: string, years = THEN_YEARS): string | null {
  const m = MONTH.exec(monthOf(month) ?? '')
  return m ? `${String(Number(m[1]) - years).padStart(4, '0')}-${m[2]}` : null
}

/** Now: the month the picker shows (`t=`), else the layer's last time as a month, else null */
export function nowMonth(t: string | null | undefined, layerTime: readonly (string | null)[] | null | undefined): string | null {
  return monthOf(t) ?? monthOf(layerTime?.[1] ?? null)
}

const enc = (s: string) => encodeURIComponent(s).replace(/%3A/gi, ':')

/**
 * the indicators Map at this place with compare on: Now is `t`, Then the same month THEN_YEARS earlier, the layer the one
 * under the place's map. a sanctuary (the `places` collection) opens over all the sanctuaries (`pi=coll:places`), any other
 * place over itself alone. null without a month to compare
 */
export function compareHref(o: { place: string; layer: string; t: string | null; coll?: string | null }, app = INDICATORS_APP): string | null {
  const now = monthOf(o.t), then = now ? yearsBefore(now) : null
  if (!now || !then) return null
  const pi = o.coll === 'places' ? 'coll:places' : enc(o.place)
  return `${app}#view=map&ind=${COMPARE_IND}&pi=${pi}&grain=month&t=${now}&t2=${then}&layer=${enc(o.layer)}&place=${enc(o.place)}`
}

/** the in-page anchors of the hero line, in the page's order */
export const PAGE_ANCHORS = [
  { id: 'map', label: 'map' },
  { id: 'indicators', label: 'indicators' },
  { id: 'species', label: 'species' },
  { id: 'layers', label: 'layers' },
  { id: 'reports', label: 'reports' },
] as const

/** a click on a link to a part of this same page (same path and query, a hash): the browser scrolls, the router keeps out */
export function inPageAnchor(a: { pathname: string; search: string; hash: string }, here: { pathname: string; search: string }): boolean {
  return !!a.hash && a.pathname === here.pathname && a.search === here.search
}
