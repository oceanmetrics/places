// the indicators slot of the place page: read the indicators catalog (indicators.json + coverage.parquet), make the
// cards of one place, and say which of the three absences applies (no data here, not computed yet, no status rule).
// plain functions: fetch is passed in, so the tests read synthetic fixtures without a network. statuses are never
// computed here: the status, trend and sentence come from coverage.parquet, which the indicators repo builds with
// `@oceanmetrics/status`; this module only formats them (with that package's own period and number helpers).
import { fmt, grainNoun, periodLabel, type Grain } from '@oceanmetrics/status'
import { parquetReadObjects } from 'hyparquet'
import { erddapLink, slash } from './helpers'

export const DEFAULT_INDICATORS_BASE = 'https://storage.oceanmetrics.io/indicators/'
/** the indicators app, whose Place view is the deep view of a place */
export const INDICATORS_APP = 'https://oceanmetrics.io/indicators/'

/** the catalog root: `?indicators=` > VITE_INDICATORS_BASE > https://storage.oceanmetrics.io/indicators/ (trailing slash always) */
export function resolveIndicatorsBase(search: string, env?: string | null): string {
  const q = new URLSearchParams(search).get('indicators')?.trim()
  return slash(q || env?.trim() || DEFAULT_INDICATORS_BASE)
}

export const INDICATORS_BASE = resolveIndicatorsBase(
  typeof location !== 'undefined' ? location.search : '',
  import.meta.env?.VITE_INDICATORS_BASE as string | undefined,
)

// the manifest (the fields the cards need; indicators.json has more) ----
export type StatusWord = 'above' | 'within' | 'below'
export type TrendWord = 'up' | 'flat' | 'down'

export interface ManifestIndicator {
  id: string
  title: string
  short?: string
  unit?: string
  unit_label?: string
  decimals?: number
  kind: 'continuous' | 'categorical'
  classes?: Record<string, string>
  series: string
  series_title?: string
  lead: boolean
  status_method: string
  status_grain: Grain
  recent?: number
  method?: { kind: string; summary: string; code?: string }
  producer?: { name: string; url?: string }
  dataset?: { id: string; title: string; citation?: string | null; doi?: string | null; providers?: { name: string; roles: string[] }[] }
  citation?: string
  collections?: { coll: string }[]
}

export interface IndicatorsManifest {
  version: string
  indicators: ManifestIndicator[]
}

/** read indicators.json */
export async function loadManifest(fetchFn: typeof fetch = fetch, base = INDICATORS_BASE): Promise<IndicatorsManifest> {
  const r = await fetchFn(slash(base) + 'indicators.json')
  if (!r.ok) throw new Error(`indicators.json: HTTP ${r.status} at ${slash(base)}`)
  return (await r.json()) as IndicatorsManifest
}

// coverage.parquet (one row per place x indicator x grain) ----
/** the columns the cards read; the rest of the file (the sparkline, above all) is not decoded */
export const COVERAGE_COLUMNS = [
  'place_id', 'coll', 'indicator', 'time_grain', 'n_periods', 'last_time', 'last_value', 'last_class',
  'status_method', 'status', 'trend', 'why', 'sentence',
] as const

export interface CoverageRow {
  place_id: string
  coll: string
  indicator: string
  time_grain: Grain
  n_periods: number
  last_time: string | null
  last_value: number | null
  last_class: string | null
  status_method: string | null
  status: StatusWord | null
  trend: TrendWord | null
  why: string | null
  sentence: string | null
}

/** hyparquet gives int64 as bigint: the rows carry plain numbers */
const toNumber = (v: unknown) => (typeof v === 'bigint' ? Number(v) : (v as number | null))

/** every row of coverage.parquet, projected to COVERAGE_COLUMNS (the whole file is fetched: one cacheable request) */
export async function loadCoverage(fetchFn: typeof fetch = fetch, base = INDICATORS_BASE): Promise<CoverageRow[]> {
  const r = await fetchFn(slash(base) + 'coverage.parquet')
  if (!r.ok) throw new Error(`coverage.parquet: HTTP ${r.status} at ${slash(base)}`)
  const file = await r.arrayBuffer()
  const rows = await parquetReadObjects({ file, columns: [...COVERAGE_COLUMNS] })
  return rows.map((o) => ({ ...o, n_periods: toNumber(o.n_periods) ?? 0, last_value: toNumber(o.last_value) }) as CoverageRow)
}

/** the coverage rows of one place */
export const rowsFor = (rows: CoverageRow[], placeId: string) => rows.filter((r) => r.place_id === placeId)

export async function loadCoverageFor(placeId: string, fetchFn: typeof fetch = fetch, base = INDICATORS_BASE): Promise<CoverageRow[]> {
  return rowsFor(await loadCoverage(fetchFn, base), placeId)
}

// cards ----
export type StatusGlyph = 'st-above' | 'st-within' | 'st-below' | 'st-none'
export type TrendGlyph = 'tr-up' | 'tr-flat' | 'tr-down'

export interface IndicatorCard {
  id: string
  title: string
  series: string
  seriesTitle: string
  lead: boolean
  /** the values collection the row was read from (the deep link's `coll`) */
  coll: string
  grain: Grain
  /** the last value as text, without the unit ("16.05"; "No Stress 82%" for a categorical one; "–" for none) */
  value: string
  unit: string
  /** the last period, by grain: "2025", "2025-07", "the 2020s", "all years" */
  period: string
  status: StatusWord | null
  trend: TrendWord | null
  glyph: StatusGlyph
  trendGlyph: TrendGlyph | null
  /** the status in words, relative to the place's own record ("within its own record") or why there is none */
  statusWord: string
  /** the one-line caption under the value */
  caption: string
  /** the status method's deterministic sentence, from coverage.parquet */
  sentence: string
  /** the status method, by name */
  method: string
  citation: string
  /** the indicators app's Place view of this place, opened on this indicator */
  href: string
  /** the method is a status rule (iea-sd, names-pct): a status is possible, given a long enough record */
  hasRule: boolean
  /** an OBIS series (a count that tracks sampling effort: never a status) */
  obis: boolean
}

const RULES = new Set(['iea-sd', 'names-pct'])

export const STATUS_WORDS: Record<StatusWord, string> = {
  above : 'above its own record',
  within: 'within its own record',
  below : 'below its own record',
}

/** the method by name, as the card's "Method" line says it */
export function methodName(ind: Pick<ManifestIndicator, 'status_method' | 'status_grain' | 'recent'>): string {
  const recent = ind.recent ?? 5
  switch (ind.status_method) {
    case 'iea-sd'   : return `iea-sd: the mean of the last ${recent} ${grainNoun(ind.status_grain, recent)} against 1 SD of the long-term mean (IEA)`
    case 'names-pct': return `names-pct: the recent mean against the 10th and 90th percentiles of the record (NaMES)`
    case 'values'   : return 'values: the last value, with no status rule'
    default         : return ind.status_method
  }
}

/** the dataset's citation line; the indicator's own citation when the dataset has none */
export function citationOf(ind: ManifestIndicator): string {
  const d = ind.dataset
  if (d?.citation) return d.citation
  if (d?.title) {
    const who = (d.providers ?? []).filter((p) => p.roles.includes('producer') || p.roles.includes('licensor')).map((p) => p.name)
    return [who.join(', '), d.title, d.doi ?? ''].filter(Boolean).join('; ')
  }
  return ind.citation ?? ''
}

/** ids keep their colons and pipes readable, as the indicators app writes them */
const enc = (s: string) => encodeURIComponent(s).replace(/%3A/gi, ':').replace(/%7C/gi, '|')

/** the indicators app's Place view: `#view=place&place=<id>[&coll=<coll>][&ind=<indicator>]` (indicators viewer/src/lib/hash.ts) */
export function placeViewHref(placeId: string, coll?: string | null, indicator?: string | null): string {
  const parts = ['view=place', 'place=' + enc(placeId)]
  if (coll) parts.push('coll=' + enc(coll))
  if (indicator) parts.push('ind=' + enc(indicator))
  return `${INDICATORS_APP}#${parts.join('&')}`
}

/** the grains tried for a card, in order (as the indicators Matrix picks a cell's row): the status grain, then year, month, decade, day, all */
export const grainOrder = (statusGrain: Grain): Grain[] => [...new Set<Grain>([statusGrain, 'year', 'month', 'decade', 'day', 'all'])]

/** the row a card shows: the first in grainOrder with a value; null when none has one */
export function pickRow(rows: CoverageRow[], ind: Pick<ManifestIndicator, 'status_grain'>): CoverageRow | null {
  for (const g of grainOrder(ind.status_grain)) {
    const r = rows.find((x) => x.time_grain === g && x.last_value != null)
    if (r) return r
  }
  return null
}

/** the last period as a reader says it */
export function periodOf(row: Pick<CoverageRow, 'last_time' | 'time_grain'>): string {
  if (row.time_grain === 'all') return 'all years'
  return row.last_time ? periodLabel(row.last_time, row.time_grain) : ''
}

function card(ind: ManifestIndicator, row: CoverageRow, placeId: string): IndicatorCard {
  const categorical = ind.kind === 'categorical'
  const hasRule = RULES.has(ind.status_method)
  const status = hasRule ? row.status : null
  const trend = hasRule ? row.trend : null
  const value = categorical
    ? `${ind.classes?.[row.last_class ?? ''] ?? row.last_class ?? ''} ${fmt((row.last_value ?? 0) * 100, 0)}%`.trim()
    : fmt(row.last_value, ind.decimals ?? 2)
  const statusWord = status ? STATUS_WORDS[status] : hasRule ? 'no status' : 'no status rule'
  let caption: string
  if (status) caption = `${statusWord[0].toUpperCase()}${statusWord.slice(1)}${trend ? ` · trend ${trend}` : ''}`
  else if (categorical) caption = 'Categorical: shown as class shares, no status'
  else if (hasRule) caption = `No status: ${row.why ?? 'not enough record'}`
  else caption = 'No status rule: shown as a value'
  return {
    id: ind.id, title: ind.title, series: ind.series, seriesTitle: ind.series_title ?? ind.series, lead: ind.lead,
    coll: row.coll, grain: row.time_grain, value, unit: categorical ? '' : (ind.unit_label ?? ind.unit ?? ''), period: periodOf(row),
    status, trend, glyph: status ? `st-${status}` : 'st-none', trendGlyph: trend ? `tr-${trend}` : null,
    statusWord, caption, sentence: row.sentence ?? '', method: methodName(ind), citation: citationOf(ind),
    href: placeViewHref(placeId, row.coll, ind.id), hasRule, obis: ind.id.startsWith('obis:'),
  }
}

/** leads first, then by series, then by title */
const byLeadSeries = (a: IndicatorCard, b: IndicatorCard) =>
  Number(b.lead) - Number(a.lead) || a.series.localeCompare(b.series) || a.title.localeCompare(b.title)

/** one card per indicator of the place with a value; an indicator the manifest does not list is left out */
export function cardsFor(rows: CoverageRow[], manifest: IndicatorsManifest): IndicatorCard[] {
  const byInd = new Map<string, CoverageRow[]>()
  for (const r of rows) byInd.set(r.indicator, [...(byInd.get(r.indicator) ?? []), r])
  const out: IndicatorCard[] = []
  for (const ind of manifest.indicators) {
    const rs = byInd.get(ind.id)
    const row = rs && pickRow(rs, ind)
    if (row) out.push(card(ind, row, row.place_id))
  }
  return out.sort(byLeadSeries)
}

// the three absences ----
export type AbsenceKind = 'nodata' | 'notcomputed' | 'nostatus'

export interface Absence {
  kind: AbsenceKind
  text: string
  /** where the reader goes next, and the link's words */
  href?: string
  linkText?: string
}

/** the build week that brings indicators to every gazetteer place */
export const EVERY_PLACE_WEEK = 'build week 3, 2026-11-13 to 11-19'

/**
 * the words of each absence, kept distinct: "no data here" (the catalog covers the place's layer and has no value for
 * it), "not computed yet" (the catalog does not cover the layer yet), "no status rule" (OBIS series: counts that track
 * sampling effort, shown as values; `n` is their number, `shown` how many of them are cards above: the leads).
 */
export function emptyState(kind: AbsenceKind, placeId: string, layer?: { title?: string } | null, n = 0, shown = 0): Absence {
  switch (kind) {
    case 'nodata':
      return { kind, text: `No data here: the indicators catalog covers ${layer?.title ?? "this place's layer"}, but none of its indicators has a value for this place.` }
    case 'notcomputed':
      return {
        kind, text: `Not computed yet. Indicators for every gazetteer place arrive in ${EVERY_PLACE_WEEK}; until then compute one in ERDDAP Places.`,
        href: erddapLink(placeId), linkText: 'ERDDAP Places',
      }
    case 'nostatus':
      return {
        kind, text: `No status rule for ${n} OBIS series${shown ? `, ${shown} of them above` : ''}: counts of records and species track sampling effort, so they are shown as values, not as a status.`,
        href: placeViewHref(placeId), linkText: `All ${n} in Indicators`,
      }
  }
}

/** does the catalog compute any indicator for the collection? */
export const covers = (manifest: IndicatorsManifest, collection: string | undefined) =>
  !!collection && manifest.indicators.some((i) => i.collections?.some((c) => c.coll === collection))

// the slot ----
export interface Slot {
  /** the cards shown as cards, leads first (the OBIS series that are not leads are folded into `noStatus`) */
  cards: IndicatorCard[]
  /** how many cards show before "Show all": the leads, or the first SHOWN_FIRST when there are none */
  first: number
  /** the folded OBIS series, as one line; null when there are none */
  noStatus: Absence | null
  /** indicators of the place with a value (cards and folded series) */
  total: number
  /** no data here / not computed yet; null when there are cards */
  absence: Absence | null
}

export const SHOWN_FIRST = 6

/** what the section shows for a place: its cards, the folded OBIS line, or the absence */
export function slotFor(rows: CoverageRow[], manifest: IndicatorsManifest, placeId: string, layer?: { title?: string; collection?: string } | null): Slot {
  const all = cardsFor(rows, manifest)
  const cards = all.filter((c) => !(c.obis && !c.lead))
  const obis = all.filter((c) => c.obis)
  const leads = cards.filter((c) => c.lead).length
  let absence: Absence | null = null
  if (!all.length) absence = emptyState(rows.length || covers(manifest, layer?.collection) ? 'nodata' : 'notcomputed', placeId, layer)
  return {
    cards, first: Math.min(cards.length, leads || SHOWN_FIRST),
    noStatus: obis.length ? emptyState('nostatus', placeId, layer, obis.length, obis.filter((c) => c.lead).length) : null,
    total: all.length, absence,
  }
}

/** the section's footer line */
export const footerLine = (n: number) =>
  `${n} indicator${n === 1 ? '' : 's'} · statuses are statistical, relative to each place's own record · from the Ocean Metrics indicators catalog`
