// the Reports section and the values download of the place page, their rules in plain functions (tested on the
// indicators fixtures): which report presets of the indicators app include the place, the SanctuaryWatch bundle of a
// sanctuary (built by the indicators app's Report view: Export, "SanctuaryWatch bundle (zip)"), the values files of the
// place's indicators, and the summary line of the Indicators section from `rollups`.
import { INDICATORS_APP, rollups, valuesUrl } from '@oceanmetrics/catalog/indicators'
import type { CoverageRow, IndicatorsManifest, Rollup } from '@oceanmetrics/catalog/indicators'

/** the values collection of the indicators app's default selection (`coll:places`, the sanctuaries) */
export const DEFAULT_SELECTION_COLL = 'places'

const enc = (s: string) => encodeURIComponent(s).replace(/%3A/gi, ':')

/** the indicators app's Report view over a selection (`pi=`, the indicators viewer's hash; none = the default selection) */
export const reportHref = (pi: string | null, app = INDICATORS_APP) => `${app}#view=report${pi ? `&pi=${enc(pi)}` : ''}`

export interface ReportPreset { title: string; note: string; href: string }

/**
 * the report presets that include the place: the place alone (whenever the catalog computed it), the default selection when
 * its values are in `coll:places` (the sanctuaries), and each manifest place set whose groups hold one of the place's
 * gazetteer collections (`political`: mr_eez and fao_high_seas)
 */
export function reportPresets(placeId: string, name: string, rows: readonly Pick<CoverageRow, 'place_id' | 'coll'>[],
  manifest: Pick<IndicatorsManifest, 'place_sets'>, placeColls: readonly string[], app = INDICATORS_APP): ReportPreset[] {
  const mine = rows.filter((r) => r.place_id === placeId)
  if (!mine.length) return []
  const out: ReportPreset[] = [{ title: `${name} alone`, note: 'every indicator of this place, as cards', href: reportHref(placeId, app) }]
  if (mine.some((r) => r.coll === DEFAULT_SELECTION_COLL)) {
    out.push({ title: 'The sanctuaries', note: 'the indicators app\'s default selection, which holds this place', href: reportHref(null, app) })
  }
  for (const s of manifest.place_sets ?? []) {
    if (s.groups.some((g) => placeColls.includes(g))) out.push({ title: s.title, note: s.note ?? `the set ${s.id}`, href: reportHref(`set:${s.id}`, app) })
  }
  return out
}

/** a sanctuary (`NMS:*`) has a SanctuaryWatch bundle: the Report view of the place builds it (Export, "SanctuaryWatch bundle (zip)") */
export const swBundleHref = (placeId: string, app = INDICATORS_APP): string | null => (/^NMS:/.test(placeId) ? reportHref(placeId, app) : null)

// ---- the values files ----

export interface ValuesFile { indicator: string; coll: string; url: string }

/** the values parquet of each indicator the place has rows for, once each, in the order of the rows; one without a file is left out */
export function valuesFiles(rows: readonly Pick<CoverageRow, 'place_id' | 'coll' | 'indicator'>[], manifest: Pick<IndicatorsManifest, 'indicators'>,
  placeId: string, base: string): ValuesFile[] {
  const seen = new Set<string>()
  const out: ValuesFile[] = []
  for (const r of rows) {
    if (r.place_id !== placeId) continue
    const k = `${r.indicator}\u0001${r.coll}`
    if (seen.has(k)) continue
    seen.add(k)
    const ind = manifest.indicators.find((i) => i.id === r.indicator)
    const url = ind ? valuesUrl(base, ind, r.coll) : null
    if (url) out.push({ indicator: r.indicator, coll: r.coll, url })
  }
  return out
}

// ---- the summary line ----

/** "44 indicators with a value: 3 above, 20 within, 5 below its own record, 16 without a status; latest 2025-07." */
export function summaryLine(r: Pick<Rollup, 'above' | 'within' | 'below' | 'none' | 'nodata' | 'cells' | 'latest'> | null | undefined): string | null {
  if (!r) return null
  const n = r.cells - r.nodata
  if (n <= 0) return null
  const st = [`${r.above} above`, `${r.within} within`, `${r.below} below`].join(', ')
  return `${n} ${n === 1 ? 'indicator' : 'indicators'} with a value: ${st} the place's own record${r.none ? `, ${r.none} without a status` : ''}${r.latest ? `; latest ${r.latest.label}` : ''}.`
}

/** the place's roll-up (one place of `rollups`) */
export const placeRollup = (rows: CoverageRow[], placeId: string): Rollup | null => rollups(rows.filter((r) => r.place_id === placeId)).places[0] ?? null
