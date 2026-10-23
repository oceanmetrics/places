// the layer under the place map, its rules in plain functions: the ERDDAP collections of the gazetteer's STAC catalog
// (`erddap/<dataset id>/collection.json`), the "Layer under the map" choices, the cell budget of one place's lobes, the
// date a period asks for, the title, the legend line and the credit. the wiring (`@oceanmetrics/map` `gridSlot` over the
// engine's `sliceSource` in DuckDB-WASM) is gridKind.ts and the lazy gridSource.ts. no MapLibre, no DuckDB here.
//
// the slice is the place's own lobes (one ERDDAP request per lobe, each masked by the place itself, `placeLobes`), as the
// indicators Map slices its places: never a box over the whole map.
import { parseLayerParam } from '../grammar'

/** the gazetteer's STAC root at the bucket's path-style url (answers CORS for every read; the storage host 302s) */
export const GAZETTEER_STAC = 'https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/'
export const erddapCollectionUrl = (datasetId: string, root = GAZETTEER_STAC) => `${root}erddap/${datasetId}/collection.json`

export const hostOf = (url: string) => { try { return new URL(url).host } catch { return url } }

// ---- the ERDDAP collections of the catalog ----

/** the ERDDAP children of the gazetteer's catalog.json: the dataset id (the folder name, ERDDAP's own spelling) and title */
export function erddapEntries(catalog: { links?: { rel?: string; href?: string; title?: string }[] } | null | undefined): { id: string; title: string }[] {
  const out: { id: string; title: string }[] = []
  for (const l of catalog?.links ?? []) {
    const m = l.rel === 'child' ? /^(?:\.\/)?erddap\/([^/]+)\/collection\.json$/.exec(l.href ?? '') : null
    if (m) out.push({ id: m[1], title: l.title ?? m[1] })
  }
  return out
}

export interface GridVariable { name: string; description: string | null; unit: string | null }

/** what the page reads of an ERDDAP collection: enough for the picker, the layers list and the slot */
export interface ErddapLayer {
  /** ERDDAP's dataset id, the slot key's id */
  id: string
  title: string
  protocol: 'griddap' | 'tabledap' | string
  /** the data variables, in the collection's order */
  variables: GridVariable[]
  bbox: [number, number, number, number] | null
  /** first and last time ("2002-06-16", null when open) */
  time: [string | null, string | null]
  /** the time step (P1D, P1M) and the finer axis step in degrees */
  step: string | null
  spacing: number | null
  host: string
  producers: string[]
  pending: boolean
  /** the collection as published (the engine's `toDataset` reads it) */
  raw: unknown
}

interface StacCollection {
  title?: string
  'erddap:protocol'?: string
  'erddap:base_url'?: string
  'erddap-places:status'?: string
  'cube:variables'?: Record<string, { type?: string; description?: string; unit?: string | null }>
  'cube:dimensions'?: Record<string, { step?: number | string | null } | undefined>
  extent?: { spatial?: { bbox?: number[][] }; temporal?: { interval?: (string | null)[][] } }
  providers?: { name?: string; roles?: string[] }[]
}

const day = (s: string | null | undefined) => (s ? s.slice(0, 10) : null)

/** an ERDDAP collection.json as the page reads it */
export function toErddapLayer(id: string, c: StacCollection): ErddapLayer {
  const b = c.extent?.spatial?.bbox?.[0]
  const iv = c.extent?.temporal?.interval?.[0] ?? []
  const d = c['cube:dimensions'] ?? {}
  const steps = [d.longitude?.step ?? d.lon?.step, d.latitude?.step ?? d.lat?.step].map(Number).filter((x) => x > 0)
  const t = d.time?.step
  return {
    id, title: c.title ?? id, protocol: c['erddap:protocol'] ?? 'griddap',
    variables: Object.entries(c['cube:variables'] ?? {}).filter(([, v]) => (v.type ?? 'data') === 'data')
      .map(([name, v]) => ({ name, description: v.description ?? null, unit: v.unit ?? null })),
    bbox: b && b.length === 4 && b.every(Number.isFinite) ? (b as [number, number, number, number]) : null,
    time: [day(iv[0]), day(iv[1])],
    step: typeof t === 'string' ? t : null,
    spacing: steps.length ? Math.min(...steps) : null,
    host: hostOf(c['erddap:base_url'] ?? ''),
    producers: producersOf(c),
    pending: c['erddap-places:status'] === 'pending',
    raw: c,
  }
}

/** the producers and licensors of a STAC collection */
export function producersOf(c: { providers?: { name?: string; roles?: string[] }[] } | null | undefined): string[] {
  return (c?.providers ?? []).filter((p) => p.name && p.roles?.some((r) => r === 'producer' || r === 'licensor')).map((p) => p.name as string)
}

// ---- the picker ----

/** variables that are not a field to look at: masks, observation counts, error and quality bands */
export const isAuxVariable = (name: string) => /^(mask|nobs)$|error$|qualityindex$/i.test(name)

export interface LayerChoice { value: string; label: string; group?: string }

/**
 * "Layer under the map": none, then one entry per variable of each gridded ERDDAP collection (tabledap stations are not a
 * grid), the collections by title; a layer the link names that is not among them comes right after none
 */
export function layerChoices(layers: readonly ErddapLayer[], current: string | null): LayerChoice[] {
  const out: LayerChoice[] = [{ value: '', label: 'None' }]
  const grids = layers.filter((l) => l.protocol === 'griddap').sort((a, b) => a.title.localeCompare(b.title))
  const listed: LayerChoice[] = []
  for (const l of grids) {
    for (const v of l.variables) {
      if (isAuxVariable(v.name)) continue
      listed.push({ value: `grid:${l.id}:${v.name}`, label: `${capital(v.description || v.name)} (${v.name})`, group: l.title })
    }
  }
  const cur = parseLayerParam(current)
  if (cur && !listed.some((c) => c.value === cur)) out.push({ value: cur, label: cur.replace(/^grid:/, ''), group: 'From the link' })
  return [...out, ...listed]
}

const capital = (s: string) => s.charAt(0).toUpperCase() + s.slice(1)

/** the slot key's parts: `grid:<id>:<variable>` -> { id, variable } (null for another kind or a bad key) */
export function gridKeyParts(key: string | null): { id: string; variable: string | null } | null {
  const k = parseLayerParam(key)
  const m = k ? /^grid:([^:]+)(?::(.+))?$/.exec(k) : null
  return m ? { id: m[1], variable: m[2] ?? null } : null
}

// ---- the cell budget ----

/** one lobe's request is at most this many cells a step (as the indicators Map: PMNM's west lobe at 0.05° is about 100,000) */
export const MAX_LOBE_CELLS = 250_000
/** all lobes of the place together, a step */
export const MAX_SLICE_CELLS = 600_000

/** the cells a box covers on a grid of `step` degrees (both axes), counting a partial cell as one */
export function boxCells(bbox: readonly number[], step: readonly [number, number]): number {
  const [w, s, e, n] = bbox
  return Math.max(1, Math.ceil(Math.abs(e - w) / step[0])) * Math.max(1, Math.ceil(Math.abs(n - s) / step[1]))
}

/** why the place's lobes cannot be sliced at this grid, or null when they fit the budget */
export function overBudget(lobes: readonly { bbox: readonly number[] }[], step: readonly [number, number],
  limits = { lobe: MAX_LOBE_CELLS, total: MAX_SLICE_CELLS }): string | null {
  const each = lobes.map((l) => boxCells(l.bbox, step))
  const total = each.reduce((s, c) => s + c, 0)
  if (each.some((c) => c > limits.lobe) || total > limits.total) {
    return `the place is too large to slice at this grid (${total.toLocaleString('en-US')} cells a step, at most ${limits.lobe.toLocaleString('en-US')} a request)`
  }
  return null
}

/** a grid's axis steps in degrees [lon, lat] from its STAC `cube:dimensions` (0.05 when not stated) */
export function axisSteps(c: { 'cube:dimensions'?: Record<string, { step?: number | string | null } | undefined> } | null | undefined): [number, number] {
  const d = c?.['cube:dimensions'] ?? {}
  const num = (v: unknown) => (Number(v) > 0 ? Number(v) : 0.05)
  return [num(d.longitude?.step ?? d.lon?.step), num(d.latitude?.step ?? d.lat?.step)]
}

// ---- the time asked for ----

/** the step's date of a period (`t=`: "2024-07" -> "2024-07-01", "2024" -> "2024-01-01"); null stays null (the latest) */
export function stepDate(t: string | null | undefined): string | null {
  if (!t) return null
  const [y, m = '01', d = '01'] = t.slice(0, 10).split('-')
  return /^\d{4}$/.test(y) ? `${y}-${m.padStart(2, '0')}-${d.padStart(2, '0')}` : null
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** a period as the legend says it: "2024", "Jul 2024", "15 Jul 2024" */
export function periodLabel(t: string): string {
  const [y, m, d] = t.slice(0, 10).split('-')
  if (!m) return y
  const mon = MONTHS[Number(m) - 1] ?? m
  return d && d !== '01' ? `${Number(d)} ${mon} ${y}` : `${mon} ${y}`
}

// ---- the title, the legend line and the credit ----

/** how the slice is drawn: in the browser, from the dataset's own server */
export const gridVia = (host: string) => `grid slice in the browser (DuckDB-WASM) from ERDDAP at ${host}`

/** the layer's title: its variable as the dataset describes it, from the dataset */
export function gridTitle(title: string, v: Pick<GridVariable, 'name' | 'description'>): string {
  return `${capital(v.description || v.name)} from ${title}`
}

/** the credit line: the layer, the organisations that produce or license it, and where it is read from */
export function gridCredit(title: string, producers: readonly string[], host: string): string {
  return `${title}${producers.length ? ` (${producers.join('; ')})` : ''}, sliced in the browser from ERDDAP at ${host}`
}

/** the unit as the legend says it: Celsius in any spelling, and Kelvin (the engine converts it), as °C */
export function unitLabel(unit: string | null | undefined): string | null {
  const u = (unit ?? '').trim()
  if (!u || u === '1' || u.toLowerCase() === 'none') return null
  if (/^(c|celsius|deg(ree)?s?_?c(elsius)?|°c|k|kelvin|degree_?k(elvin)?)$/i.test(u)) return '°C'
  return u
}

const num = (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2))

/** what the line reads of the slot's legend (`@oceanmetrics/map` LegendSpec) */
export interface LegendLike {
  title: string
  t: string | null
  via: string
  problem: string | null
  units?: string | null
  ramp?: { min: number; max: number } | null
  classes?: unknown[] | null
}

/**
 * "Layer: <title> at <period> · <via>", then its range ("12.3 to 30.1 °C") once the slice is in, "loading the slice…"
 * until then, and "· <problem>" when something went wrong
 */
export function legendLine(l: LegendLike): string {
  const at = l.t ? periodLabel(l.t) : 'the latest time'
  const range = l.ramp ? ` · ${num(l.ramp.min)} to ${num(l.ramp.max)}${l.units ? ` ${l.units}` : ''}` : ''
  const state = l.problem ? ` · ${l.problem}` : l.ramp || l.classes?.length ? '' : ' · loading the slice…'
  return `Layer: ${l.title} at ${at} · ${l.via}${range}${state}`
}

// ---- a server that drops requests ----

/**
 * `fn` again after a pause when it fails, at most `tries` times in all: the ERDDAP mirror answers the same request 404 and
 * 200 by turns (two backends, one without the dataset; seen 2026-10-23), so one failure is not an answer. an aborted
 * signal stops at once
 */
export async function withRetries<T>(fn: () => Promise<T>, tries = 4, ms = 1500, signal?: AbortSignal): Promise<T> {
  let last: unknown
  for (let i = 0; i < tries; i++) {
    if (signal?.aborted) throw signal.reason ?? new DOMException('aborted', 'AbortError')
    try { return await fn() } catch (e) {
      last = e
      if (signal?.aborted) throw e
      if (i < tries - 1 && ms > 0) await new Promise((r) => setTimeout(r, ms * (i + 1)))
    }
  }
  throw last
}

/** a failure as the legend says it: the host and the status, never the whole request url */
export function problemText(e: unknown): string {
  const m = String((e as Error)?.message ?? e)
  const url = /https?:\/\/([^/\s]+)\S*/.exec(m)
  const status = /:\s*(\d{3})\b/.exec(m)?.[1]
  return url ? `${url[1]} did not answer${status ? ` (HTTP ${status})` : ''}; try again later` : m
}
