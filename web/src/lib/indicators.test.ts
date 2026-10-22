/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  cardsFor, COVERAGE_COLUMNS, DEFAULT_INDICATORS_BASE, emptyState, footerLine, loadCoverage, loadCoverageFor, loadManifest,
  methodName, periodOf, pickRow, placeViewHref, resolveIndicatorsBase, rowsFor, slotFor, type CoverageRow, type IndicatorsManifest,
} from './indicators'

// synthetic fixtures: fixtures/indicators.json and fixtures/coverage.parquet (made by fixtures/make_coverage.sql)
const fx = (name: string) => new URL(`./fixtures/${name}`, import.meta.url)
const MANIFEST = JSON.parse(readFileSync(fx('indicators.json'), 'utf8')) as IndicatorsManifest
const PARQUET = readFileSync(fx('coverage.parquet'))

/** a fetch that serves the fixtures under `base` and 404s anything else; it records the urls asked for */
function fakeFetch(base = 'https://x.test/ind/') {
  const asked: string[] = []
  const f = (async (input: RequestInfo | URL) => {
    const url = String(input)
    asked.push(url)
    if (url === base + 'indicators.json') return new Response(JSON.stringify(MANIFEST), { status: 200 })
    if (url === base + 'coverage.parquet') return new Response(new Uint8Array(PARQUET), { status: 200 })
    return new Response('nope', { status: 404 })
  }) as typeof fetch
  return { f, asked }
}

let ROWS: CoverageRow[] = []
const load = async () => (ROWS.length ? ROWS : (ROWS = await loadCoverage(fakeFetch().f, 'https://x.test/ind/')))

describe('the catalog base', () => {
  it('takes ?indicators= over VITE_INDICATORS_BASE over the default, with a trailing slash', () => {
    expect(resolveIndicatorsBase('', undefined)).toBe('https://storage.oceanmetrics.io/indicators/')
    expect(resolveIndicatorsBase('?base=https://g/', 'https://env.test/ind')).toBe('https://env.test/ind/')
    expect(resolveIndicatorsBase('?indicators=http://127.0.0.1:8080/catalog', 'https://env.test/ind/')).toBe('http://127.0.0.1:8080/catalog/')
    expect(resolveIndicatorsBase('?indicators=', '  ')).toBe(DEFAULT_INDICATORS_BASE)
  })
})

describe('loading', () => {
  it('reads indicators.json from the base, and says which file failed', async () => {
    const { f, asked } = fakeFetch('https://x.test/ind/')
    expect((await loadManifest(f, 'https://x.test/ind')).version).toBe('2026.10.22')
    expect(asked).toEqual(['https://x.test/ind/indicators.json'])
    await expect(loadManifest(f, 'https://other.test/')).rejects.toThrow('indicators.json: HTTP 404 at https://other.test/')
    await expect(loadCoverage(f, 'https://other.test/')).rejects.toThrow('coverage.parquet: HTTP 404 at https://other.test/')
  })

  it('reads coverage.parquet projected to the card columns, with plain numbers', async () => {
    const rows = await load()
    expect(rows).toHaveLength(13)
    expect(Object.keys(rows[0]).sort()).toEqual([...COVERAGE_COLUMNS].sort())
    expect(rows[0]).toMatchObject({ place_id: 'NMS:A', indicator: 'erddap:sst', time_grain: 'year', n_periods: 30, last_value: 15.6605, status: 'within', trend: 'flat' })
    expect(typeof rows[0].n_periods).toBe('number')
  })

  it('keeps one place', async () => {
    const { f } = fakeFetch()
    const rows = await loadCoverageFor('MRGID:1', f, 'https://x.test/ind/')
    expect(rows.map((r) => `${r.indicator}/${r.time_grain}`)).toEqual([
      'obis:species/year', 'obis:species/all', 'obis:es50/year', 'obis:density:fish/year', 'obis:density:fish/decade', 'sdg:mpa/year',
    ])
  })
})

describe('the row and the period of a card', () => {
  it('takes the status grain first, else the next grain with a value', async () => {
    const rows = rowsFor(await load(), 'MRGID:1')
    expect(pickRow(rows.filter((r) => r.indicator === 'obis:species'), { status_grain: 'year' })?.time_grain).toBe('year')
    expect(pickRow(rows.filter((r) => r.indicator === 'obis:density:fish'), { status_grain: 'year' })?.time_grain).toBe('decade')
    expect(pickRow([], { status_grain: 'year' })).toBeNull()
  })

  it('formats the period by grain', () => {
    expect(periodOf({ last_time: '2025-01-01', time_grain: 'year' })).toBe('2025')
    expect(periodOf({ last_time: '2025-07-01', time_grain: 'month' })).toBe('2025-07')
    expect(periodOf({ last_time: '2020-01-01', time_grain: 'decade' })).toBe('the 2020s')
    expect(periodOf({ last_time: null, time_grain: 'all' })).toBe('all years')
  })

  it('names the method', () => {
    expect(methodName({ status_method: 'iea-sd', status_grain: 'year', recent: 5 })).toBe('iea-sd: the mean of the last 5 years against 1 SD of the long-term mean (IEA)')
    expect(methodName({ status_method: 'names-pct', status_grain: 'year' })).toBe('names-pct: the recent mean against the 10th and 90th percentiles of the record (NaMES)')
    expect(methodName({ status_method: 'values', status_grain: 'year' })).toBe('values: the last value, with no status rule')
  })
})

describe('the deep link', () => {
  it('opens the indicators Place view on the place, its values collection and the indicator', () => {
    expect(placeViewHref('NMS:CINMS', 'places', 'erddap:dhw_5km:CRW_SST:mean'))
      .toBe('https://oceanmetrics.io/indicators/#view=place&place=NMS:CINMS&coll=places&ind=erddap:dhw_5km:CRW_SST:mean')
    expect(placeViewHref('MRGID:8439')).toBe('https://oceanmetrics.io/indicators/#view=place&place=MRGID:8439')
    expect(placeViewHref('X:a b/c', 'mr_eez')).toBe('https://oceanmetrics.io/indicators/#view=place&place=X:a%20b%2Fc&coll=mr_eez')
  })
})

describe('cards', () => {
  it('a sanctuary: leads first, then by series; an indicator the manifest lacks is left out', async () => {
    const cards = cardsFor(rowsFor(await load(), 'NMS:A'), MANIFEST)
    expect(cards.map((c) => c.id)).toEqual(['erddap:baa', 'erddap:sst', 'cmems:chl', 'erddap:short'])
  })

  it('a status card: every field', async () => {
    const sst = cardsFor(rowsFor(await load(), 'NMS:A'), MANIFEST).find((c) => c.id === 'erddap:sst')
    expect(sst).toEqual({
      id: 'erddap:sst', title: 'Sea surface temperature', series: 'sst', seriesTitle: 'Sea surface temperature', lead: true,
      coll: 'places', grain: 'year', value: '15.66', unit: '°C', period: '2025',
      status: 'within', trend: 'flat', glyph: 'st-within', trendGlyph: 'tr-flat',
      statusWord: 'within its own record', caption: 'Within its own record · trend flat',
      sentence: 'SST in A over the last 5 years (2021–2025) was within 1 SD of its 1996–2025 mean, and changed by less than 1 SD.',
      method: 'iea-sd: the mean of the last 5 years against 1 SD of the long-term mean (IEA)',
      citation: 'NOAA Coral Reef Watch. 2018, updated daily. Daily Global 5km Satellite Coral Bleaching Heat Stress Monitoring.',
      href: 'https://oceanmetrics.io/indicators/#view=place&place=NMS:A&coll=places&ind=erddap:sst',
      hasRule: true, obis: false,
    })
  })

  it('above with a trend; a citation made from the dataset title, producers and DOI', async () => {
    const chl = cardsFor(rowsFor(await load(), 'NMS:A'), MANIFEST).find((c) => c.id === 'cmems:chl')!
    expect([chl.value, chl.unit, chl.glyph, chl.trendGlyph, chl.caption]).toEqual(['1.27', 'mg m⁻³', 'st-above', 'tr-up', 'Above its own record · trend up'])
    expect(chl.citation).toBe('Copernicus Marine Service; Global Ocean Biogeochemistry Hindcast; https://doi.org/10.48670/moi-00019')
  })

  it('a rule with too short a record says why there is no status', async () => {
    const c = cardsFor(rowsFor(await load(), 'NMS:A'), MANIFEST).find((x) => x.id === 'erddap:short')!
    expect([c.value, c.period, c.status, c.glyph, c.trendGlyph, c.statusWord, c.caption, c.citation])
      .toEqual(['9.24', '2023', null, 'st-none', null, 'no status', 'No status: 1 year of record, fewer than the 10 a status needs', ''])
  })

  it('a categorical card: the largest class and its share, no unit, no status', async () => {
    const c = cardsFor(rowsFor(await load(), 'NMS:A'), MANIFEST).find((x) => x.id === 'erddap:baa')!
    expect([c.value, c.unit, c.glyph, c.statusWord, c.caption, c.citation, c.hasRule])
      .toEqual(['No Stress 82%', '', 'st-none', 'no status rule', 'Categorical: shown as class shares, no status', "only the indicator's own citation", false])
  })

  it('an EEZ: OBIS and SDG values, and a decade period when the status grain is empty', async () => {
    const cards = cardsFor(rowsFor(await load(), 'MRGID:1'), MANIFEST)
    expect(cards.map((c) => [c.id, c.value, c.unit, c.period, c.caption, c.obis])).toEqual([
      ['obis:species', '1234', 'species', '2024', 'No status rule: shown as a value', true],
      ['sdg:mpa', '12.3', '%', '2023', 'No status rule: shown as a value', false],
      ['obis:es50', '45.3', 'species', '2024', 'No status rule: shown as a value', true],
      ['obis:density:fish', '0.50', 'records km⁻²', 'the 2020s', 'No status rule: shown as a value', true],
    ])
    expect(cards[3].href).toBe('https://oceanmetrics.io/indicators/#view=place&place=MRGID:1&coll=mr_eez&ind=obis:density:fish')
  })
})

describe('the three absences', () => {
  it('have three distinct texts', () => {
    const nodata = emptyState('nodata', 'NMS:A', { title: 'National Marine Sanctuaries' })
    const notcomputed = emptyState('notcomputed', 'BOEM:OCS-A 0486')
    const nostatus = emptyState('nostatus', 'MRGID:8439', null, 63)
    expect(nodata).toEqual({ kind: 'nodata', text: 'No data here: the indicators catalog covers National Marine Sanctuaries, but none of its indicators has a value for this place.' })
    expect(notcomputed).toEqual({
      kind: 'notcomputed',
      text: 'Not computed yet. Indicators for every gazetteer place arrive in build week 3, 2026-11-13 to 11-19; until then compute one in ERDDAP Places.',
      href: 'https://oceanmetrics.io/erddap-places/#place=BOEM:OCS-A 0486', linkText: 'ERDDAP Places',
    })
    expect(nostatus).toEqual({
      kind: 'nostatus',
      text: 'No status rule for 63 OBIS series: counts of records and species track sampling effort, so they are shown as values, not as a status.',
      href: 'https://oceanmetrics.io/indicators/#view=place&place=MRGID:8439', linkText: 'All 63 in Indicators',
    })
    expect(new Set([nodata.text, notcomputed.text, nostatus.text]).size).toBe(3)
  })

  it('no data here: the place has rows without values, or its layer is covered and it has none', async () => {
    const rows = await load()
    expect(slotFor(rowsFor(rows, 'NMS:EMPTY'), MANIFEST, 'NMS:EMPTY', { title: 'Sanctuaries', collection: 'places' }).absence?.kind).toBe('nodata')
    expect(slotFor([], MANIFEST, 'NMS:NEW', { title: 'Sanctuaries', collection: 'places' }).absence?.kind).toBe('nodata')
  })

  it('not computed yet: the catalog does not cover the layer', () => {
    const s = slotFor([], MANIFEST, 'BOEM:X', { title: 'Wind leases', collection: 'boem_wind_leases' })
    expect(s).toEqual({ cards: [], first: 0, noStatus: null, total: 0, absence: emptyState('notcomputed', 'BOEM:X') })
    expect(slotFor([], MANIFEST, 'BOEM:X', null).absence?.kind).toBe('notcomputed')
  })
})

describe('the slot', () => {
  it('a sanctuary: four cards, the two leads first, no OBIS line', async () => {
    const s = slotFor(rowsFor(await load(), 'NMS:A'), MANIFEST, 'NMS:A', { collection: 'places' })
    expect([s.cards.length, s.first, s.total, s.noStatus, s.absence]).toEqual([4, 2, 4, null, null])
  })

  it('an EEZ: the OBIS series that are not leads fold into the no-status-rule line', async () => {
    const s = slotFor(rowsFor(await load(), 'MRGID:1'), MANIFEST, 'MRGID:1', { collection: 'mr_eez' })
    expect(s.cards.map((c) => c.id)).toEqual(['obis:species', 'sdg:mpa'])
    expect([s.first, s.total, s.absence]).toEqual([2, 4, null])
    expect(s.noStatus).toEqual(emptyState('nostatus', 'MRGID:1', null, 3, 1))
    expect(s.noStatus?.text).toBe('No status rule for 3 OBIS series, 1 of them above: counts of records and species track sampling effort, so they are shown as values, not as a status.')
  })

  it('the footer line', () => {
    expect(footerLine(44)).toBe("44 indicators · statuses are statistical, relative to each place's own record · from the Ocean Metrics indicators catalog")
    expect(footerLine(1)).toBe("1 indicator · statuses are statistical, relative to each place's own record · from the Ocean Metrics indicators catalog")
  })
})

describe('the glyphs', async () => {
  const { GLYPH_PATHS } = await import('./glyphs')
  it('one path per status and trend glyph, each a different shape', () => {
    const keys = ['st-above', 'st-within', 'st-below', 'st-none', 'tr-up', 'tr-flat', 'tr-down']
    expect(Object.keys(GLYPH_PATHS).sort()).toEqual(keys.sort())
    expect(new Set(Object.values(GLYPH_PATHS)).size).toBe(keys.length)
  })
})
