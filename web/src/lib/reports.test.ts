/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { loadCoverage, type CoverageRow, type IndicatorsManifest } from './indicators'
import { placeRollup, reportHref, reportPresets, summaryLine, swBundleHref, valuesFiles } from './reports'

const fx = (name: string) => new URL(`./fixtures/${name}`, import.meta.url)
const MANIFEST = JSON.parse(readFileSync(fx('indicators.json'), 'utf8')) as IndicatorsManifest
const PARQUET = readFileSync(fx('coverage.parquet'))
const BASE = 'https://x.test/ind/'
const f = (async (u: RequestInfo | URL) => (String(u) === BASE + 'coverage.parquet' ? new Response(new Uint8Array(PARQUET)) : new Response('', { status: 404 }))) as typeof fetch
let ROWS: CoverageRow[] = []
const load = async () => (ROWS.length ? ROWS : (ROWS = await loadCoverage(BASE, { fetch: f })))
const APP = 'https://oceanmetrics.io/indicators/'

describe('the report presets that include the place', () => {
  it('a sanctuary: the place alone, the default selection, and the manifest set of its gazetteer collection', async () => {
    const p = reportPresets('NMS:A', 'A', await load(), MANIFEST, ['noaa_sanctuaries', 'places'])
    expect(p.map((x) => [x.title, x.href])).toEqual([
      ['A alone', `${APP}#view=report&pi=NMS:A`],
      ['The sanctuaries', `${APP}#view=report`],
      ['National Marine Sanctuaries', `${APP}#view=report&pi=set:sanctuaries`],
    ])
  })

  it('an EEZ outside the default selection and outside every set: the place alone', async () => {
    expect(reportPresets('MRGID:1', 'Z', await load(), MANIFEST, ['mr_eez']).map((x) => x.title)).toEqual(['Z alone'])
  })

  it('the political set for an EEZ when the manifest has it', async () => {
    const m = { place_sets: [{ id: 'political', title: 'Ocean by jurisdiction', groups: ['mr_eez', 'fao_high_seas'] }] }
    expect(reportPresets('MRGID:1', 'Z', await load(), m, ['mr_eez']).map((x) => x.href)).toEqual([`${APP}#view=report&pi=MRGID:1`, `${APP}#view=report&pi=set:political`])
  })

  it('nothing for a place nobody computed', async () => {
    expect(reportPresets('NMS:NONE', 'N', await load(), MANIFEST, ['noaa_sanctuaries'])).toEqual([])
  })

  it('a SanctuaryWatch bundle for NMS:* places only, through the Report view', () => {
    expect(swBundleHref('NMS:CINMS')).toBe(`${APP}#view=report&pi=NMS:CINMS`)
    expect(swBundleHref('MRGID:8439')).toBeNull()
    expect(reportHref('A B:1')).toBe(`${APP}#view=report&pi=A%20B:1`)
  })
})

describe('the values files of the place', () => {
  it('one per indicator and values collection with a path; an indicator without a file or not in the manifest is left out', async () => {
    expect(valuesFiles(await load(), MANIFEST, 'NMS:A', BASE)).toEqual([
      { indicator: 'erddap:sst', coll: 'places', url: `${BASE}values/indicator=erddap:sst/coll=places/data.parquet` },
      { indicator: 'cmems:chl', coll: 'places', url: `${BASE}values/indicator=cmems:chl/coll=places/data.parquet` },
      { indicator: 'erddap:baa', coll: 'places', url: `${BASE}values/indicator=erddap:baa/coll=places/data.parquet` },
    ])
  })
})

describe('the summary line of the Indicators section', () => {
  it('counts the statuses over the indicators with a value, and names the latest period', async () => {
    expect(summaryLine(placeRollup(await load(), 'NMS:A'))).toMatch(/^5 indicators with a value: 1 above, 1 within, 0 below the place's own record, 3 without a status; latest .+\.$/)
  })

  it('says nothing for a place with no value', async () => {
    expect(summaryLine(placeRollup(await load(), 'NMS:EMPTY'))).toBeNull()
    expect(summaryLine(null)).toBeNull()
  })
})
