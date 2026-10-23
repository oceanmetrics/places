// the indicators slot of the place page: thin wiring over @oceanmetrics/catalog/indicators, which holds the one
// implementation of the indicator cards (readers, cards, the three absences, the OBIS fold, Reproduce) shared with the
// indicators viewer. what stays here is this site's own: where the catalog is read from, and the dated sentence of
// "not computed yet".
import { DEFAULT_INDICATORS_BASE, slash, slotFor as slotOf } from '@oceanmetrics/catalog/indicators'
import type { CoverageRow, IndicatorsManifest, Slot } from '@oceanmetrics/catalog/indicators'

export {
  absenceFor, absenceText, cardsFor, COVERAGE_COLUMNS, coverageFor, DEFAULT_INDICATORS_BASE, footerLine,
  foldSeriesWithoutRule, INDICATORS_APP, loadCoverage, loadManifest, methodLabel, periodOf, pickRow, placeCitation,
  placeViewHref, SHOWN_FIRST,
} from '@oceanmetrics/catalog/indicators'
export type {
  Absence, AbsenceKind, CoverageRow, IndicatorCard, IndicatorsManifest, Reproduce, Slot, StatusGlyph, TrendGlyph,
} from '@oceanmetrics/catalog/indicators'

/** the catalog root: `?indicators=` > VITE_INDICATORS_BASE > https://storage.oceanmetrics.io/indicators/ (trailing slash always) */
export function resolveIndicatorsBase(search: string, env?: string | null): string {
  const q = new URLSearchParams(search).get('indicators')?.trim()
  return slash(q || env?.trim() || DEFAULT_INDICATORS_BASE)
}

export const INDICATORS_BASE = resolveIndicatorsBase(
  typeof location !== 'undefined' ? location.search : '',
  import.meta.env?.VITE_INDICATORS_BASE as string | undefined,
)

/** when indicators for every gazetteer place arrive; the sentence goes when build week 3 ships (2026-11-19) */
export const EVERY_PLACE_WEEK = 'build week 3, 2026-11-13 to 11-19'
export const EVERY_PLACE_NOTE = `Indicators for every gazetteer place arrive in ${EVERY_PLACE_WEEK}.`

/** what the section shows for a place: its cards, the folded OBIS line, or the absence; values urls under INDICATORS_BASE */
export const slotFor = (rows: CoverageRow[], manifest: IndicatorsManifest, placeId: string, layer?: { title?: string } | null, base = INDICATORS_BASE): Slot =>
  slotOf(rows, manifest, placeId, { layerTitle: layer?.title, note: EVERY_PLACE_NOTE, base })
