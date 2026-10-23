/// <reference types="node" />
// consumer checks: the place page's indicators slot over @oceanmetrics/catalog's cards (the rules themselves are tested
// in oceanmetrics/platform packages/catalog). what is checked here is this site's wiring: the catalog base, the
// package's readers and cards on the copied fixtures, the dated "not computed yet" note, the Reproduce block and the
// citation with the place clause, and the glyphs.
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import {
  absenceText, cardsFor, COVERAGE_COLUMNS, coverageFor, DEFAULT_INDICATORS_BASE, EVERY_PLACE_NOTE, EVERY_PLACE_WEEK, footerLine,
  loadCoverage, loadManifest, resolveIndicatorsBase, slotFor, type CoverageRow, type IndicatorsManifest,
} from './indicators'

// synthetic fixtures: fixtures/indicators.json and fixtures/coverage.parquet (made by fixtures/make_coverage.sql)
const fx = (name: string) => new URL(`./fixtures/${name}`, import.meta.url)
const MANIFEST = JSON.parse(readFileSync(fx('indicators.json'), 'utf8')) as IndicatorsManifest
const PARQUET = readFileSync(fx('coverage.parquet'))
const BASE = 'https://x.test/ind/'

/** a fetch that serves the fixtures under `base` and 404s anything else; it records the urls asked for */
function fakeFetch(base = BASE) {
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
const load = async () => (ROWS.length ? ROWS : (ROWS = await loadCoverage(BASE, { fetch: fakeFetch().f })))

describe('the catalog base', () => {
  it('takes ?indicators= over VITE_INDICATORS_BASE over the default, with a trailing slash', () => {
    expect(resolveIndicatorsBase('', undefined)).toBe('https://storage.oceanmetrics.io/indicators/')
    expect(resolveIndicatorsBase('?base=https://g/', 'https://env.test/ind')).toBe('https://env.test/ind/')
    expect(resolveIndicatorsBase('?indicators=http://127.0.0.1:8080/catalog', 'https://env.test/ind/')).toBe('http://127.0.0.1:8080/catalog/')
    expect(resolveIndicatorsBase('?indicators=', '  ')).toBe(DEFAULT_INDICATORS_BASE)
  })
})

describe('loading through the package', () => {
  it('reads indicators.json and coverage.parquet from the base, and says which file failed', async () => {
    const { f, asked } = fakeFetch()
    expect((await loadManifest('https://x.test/ind', f)).version).toBe('2026.10.22')
    expect(asked).toEqual(['https://x.test/ind/indicators.json'])
    await expect(loadManifest('https://other.test/', f)).rejects.toThrow('indicators.json: HTTP 404 at https://other.test/')
    await expect(loadCoverage('https://other.test/', { fetch: f })).rejects.toThrow('coverage.parquet: HTTP 404 at https://other.test/')
  })

  it('coverage comes projected to the card columns, with plain numbers', async () => {
    const rows = await load()
    expect(rows).toHaveLength(13)
    expect(Object.keys(rows[0]).sort()).toEqual([...COVERAGE_COLUMNS].sort())
    expect(typeof rows[0].n_periods).toBe('number')
  })
})

describe('the slot of the place page', () => {
  it('a sanctuary: four cards, the two leads first, no OBIS line', async () => {
    const s = slotFor(coverageFor(await load(), 'NMS:A'), MANIFEST, 'NMS:A', { title: 'Sanctuaries' }, BASE)
    expect(s.cards.map((c) => c.id)).toEqual(['erddap:baa', 'erddap:sst', 'cmems:chl', 'erddap:short'])
    expect([s.first, s.total, s.noStatus, s.absence]).toEqual([2, 4, null, null])
  })

  it('a card carries the citation with the place clause and the Reproduce block under the catalog base', async () => {
    const sst = slotFor(await load(), MANIFEST, 'NMS:A', null, BASE).cards.find((c) => c.id === 'erddap:sst')!
    expect([sst.value, sst.unit, sst.period, sst.caption]).toEqual(['15.66', '°C', '2025', 'Within its own record · trend flat'])
    expect(sst.citation).toContain('erddap:sst, place NMS:A, CC BY 4.0')
    expect(sst.reproduce.valuesUrl).toBe('https://x.test/ind/values/indicator=erddap:sst/coll=places/data.parquet')
    expect(sst.reproduce.snippet).toBe("SELECT time_grain, time, value, n FROM read_parquet('https://x.test/ind/values/indicator=erddap:sst/coll=places/data.parquet') WHERE place_id = 'NMS:A' ORDER BY time_grain, time;")
    expect(sst.reproduce.hash).toBe('3889c27c6041')
    expect(sst.href).toBe('https://oceanmetrics.io/indicators/#view=place&place=NMS:A&coll=places&ind=erddap:sst')
  })

  it('a card without a values file in the manifest has no snippet', async () => {
    const c = cardsFor(await load(), MANIFEST, { placeId: 'NMS:A' }).find((x) => x.id === 'erddap:short')!
    expect([c.reproduce.valuesUrl, c.reproduce.snippet]).toEqual([null, null])
  })

  it('an EEZ: the OBIS series that are not leads fold into the no-status-rule line', async () => {
    const s = slotFor(await load(), MANIFEST, 'MRGID:1', { title: 'EEZ' }, BASE)
    expect(s.cards.map((c) => c.id)).toEqual(['obis:species', 'sdg:mpa'])
    expect(s.noStatus?.text).toBe('No status rule for 3 OBIS series, 1 of them above: counts of records and species track sampling effort, so they are shown as values, not as a status.')
  })

  it('regression: no data here is a place with coverage rows whose values are all null, naming the layer', async () => {
    const s = slotFor(await load(), MANIFEST, 'NMS:EMPTY', { title: 'Sanctuaries' })
    expect(s.absence).toEqual(absenceText('nodata', 'NMS:EMPTY', { layerTitle: 'Sanctuaries' }))
    expect(s.cards).toEqual([])
  })

  it('regression: not computed yet is a place with no coverage rows, and names the week from this site, not the package', () => {
    const a = slotFor([], MANIFEST, 'BOEM:OCS-A 0486', { title: 'Wind leases' }).absence!
    expect(a.text).toBe('Not computed yet. Nobody has computed indicators for this place: compute it in ERDDAP Places, or ask for it in Indicators. Indicators for every gazetteer place arrive in build week 3, 2026-11-13 to 11-19.')
    expect(EVERY_PLACE_NOTE).toContain(EVERY_PLACE_WEEK)
    expect([a.href, a.more?.[0].href]).toEqual(['https://oceanmetrics.io/erddap-places/#place=BOEM:OCS-A 0486', 'https://oceanmetrics.io/indicators/#view=place&place=BOEM:OCS-A%200486'])
  })

  it('the footer line', () => {
    expect(footerLine(44)).toBe("44 indicators · statuses are statistical, relative to each place's own record · from the Ocean Metrics indicators catalog")
  })
})

describe('the glyphs', async () => {
  const { GLYPH_PATHS } = await import('./glyphs')
  it('one path per status and trend glyph class the cards give, each a different shape', () => {
    const keys = ['st-above', 'st-within', 'st-below', 'st-none', 'tr-up', 'tr-flat', 'tr-down']
    expect(Object.keys(GLYPH_PATHS).sort()).toEqual(keys.sort())
    expect(new Set(Object.values(GLYPH_PATHS)).size).toBe(keys.length)
  })
})
