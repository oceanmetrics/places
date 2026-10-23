import { PatientFetchError } from '@oceanmetrics/engine'
import { describe, expect, it } from 'vitest'
import {
  axisSteps, boxCells, erddapEntries, gridCredit, gridKeyParts, gridTitle, isAuxVariable, layerChoices, legendLine, overBudget,
  periodLabel, problemText, stepDate, toErddapLayer, unitLabel, withRetries,
} from './gridLayer'

const MUR = toErddapLayer('jplMURSST41mday', {
  title: 'JPL MUR SST v4.1 — monthly mean', 'erddap:protocol': 'griddap', 'erddap:base_url': 'https://erddap.oceanmetrics.io/erddap',
  'erddap-places:status': 'pending',
  'cube:variables': { sst: { type: 'data', description: 'sea surface temperature monthly mean', unit: 'degree_C' }, nobs: { type: 'data' }, mask: { type: 'data' } },
  'cube:dimensions': { time: { step: 'P1M' }, latitude: { step: 0.01 }, longitude: { step: 0.01 } },
  extent: { spatial: { bbox: [[-179.99, -89.99, 180, 89.99]] }, temporal: { interval: [['2002-06-16T00:00:00Z', '2026-09-16T00:00:00Z']] } },
  providers: [{ name: 'NASA JPL PO.DAAC', roles: ['producer'] }, { name: 'Ocean Metrics', roles: ['host'] }],
})
const BOTTLE = toErddapLayer('calcofi_bottle', { title: 'CalCOFI Bottle', 'erddap:protocol': 'tabledap', 'cube:variables': { temperature: { type: 'data' } } })
const DHW = toErddapLayer('dhw_5km', { title: 'Coral Reef Watch', 'cube:variables': { CRW_SST: { type: 'data', description: 'sea surface temperature' } } })

describe('the ERDDAP collections of the gazetteer catalog', () => {
  it('lists the erddap children by their folder name (ERDDAP\'s own spelling)', () => {
    expect(erddapEntries({ links: [
      { rel: 'root', href: './catalog.json' },
      { rel: 'child', href: './erddap/jplMURSST41mday/collection.json', title: 'MUR' },
      { rel: 'child', href: './places/collection.json', title: 'Places' },
      { rel: 'child', href: 'erddap/dhw_5km/collection.json' },
    ] })).toEqual([{ id: 'jplMURSST41mday', title: 'MUR' }, { id: 'dhw_5km', title: 'dhw_5km' }])
  })

  it('reads a collection: data variables, bbox, days, the finer step, host, producers, pending', () => {
    expect(MUR.variables.map((v) => v.name)).toEqual(['sst', 'nobs', 'mask'])
    expect([MUR.bbox, MUR.time, MUR.step, MUR.spacing, MUR.host, MUR.producers, MUR.pending]).toEqual([
      [-179.99, -89.99, 180, 89.99], ['2002-06-16', '2026-09-16'], 'P1M', 0.01, 'erddap.oceanmetrics.io', ['NASA JPL PO.DAAC'], true])
    expect([DHW.protocol, DHW.bbox, DHW.time]).toEqual(['griddap', null, [null, null]])
  })
})

describe('the layer picker', () => {
  it('offers none, then each field of the gridded collections by title; no tabledap, no masks or counts', () => {
    expect(layerChoices([MUR, BOTTLE, DHW], null)).toEqual([
      { value: '', label: 'None' },
      { value: 'grid:dhw_5km:CRW_SST', label: 'Sea surface temperature (CRW_SST)', group: 'Coral Reef Watch' },
      { value: 'grid:jplMURSST41mday:sst', label: 'Sea surface temperature monthly mean (sst)', group: 'JPL MUR SST v4.1 — monthly mean' },
    ])
  })

  it('keeps a layer the link names that the catalog does not list, right after none', () => {
    expect(layerChoices([DHW], 'erddap:other:v').slice(0, 2)).toEqual([{ value: '', label: 'None' }, { value: 'grid:other:v', label: 'other:v', group: 'From the link' }])
  })

  it('knows the auxiliary bands', () => {
    expect(['mask', 'nobs', 'analysis_error', 'randomError', 'precipitationQualityIndex', 'sst', 'CRW_DHW'].map(isAuxVariable)).toEqual([true, true, true, true, true, false, false])
  })

  it('splits a grid key into its dataset and variable', () => {
    expect(gridKeyParts('grid:jplMURSST41mday:sst')).toEqual({ id: 'jplMURSST41mday', variable: 'sst' })
    expect(gridKeyParts('grid:dhw_5km')).toEqual({ id: 'dhw_5km', variable: null })
    expect(gridKeyParts('cog:x')).toBeNull()
    expect(gridKeyParts(null)).toBeNull()
  })
})

describe('the cell budget of the place', () => {
  it('counts the cells of a box, a partial cell as one', () => {
    expect(boxCells([0, 0, 1, 1], [0.25, 0.25])).toBe(16)
    expect(boxCells([0, 0, 0.01, 0.01], [0.05, 0.05])).toBe(1)
  })

  it('passes CINMS at 0.01 degrees and refuses a lobe over the request budget', () => {
    expect(overBudget([{ bbox: [-120.6, 33.4, -118.9, 34.2] }], [0.01, 0.01])).toBeNull()
    expect(overBudget([{ bbox: [-180, 0, -170, 10] }], [0.01, 0.01])).toMatch(/too large to slice at this grid \(1,000,000 cells a step, at most 250,000 a request\)/)
    expect(overBudget([0, 10, 20, 30].map((x) => ({ bbox: [x, 0, x + 4, 4] })), [0.01, 0.01])).toMatch(/640,000 cells a step/)
  })

  it('reads the axis steps, 0.05 when not stated', () => {
    expect(axisSteps({ 'cube:dimensions': { longitude: { step: 0.25 }, latitude: { step: '0.25' } } })).toEqual([0.25, 0.25])
    expect(axisSteps(null)).toEqual([0.05, 0.05])
  })
})

describe('the period', () => {
  it('asks for the first day of a year or a month; null is the latest', () => {
    expect(['2024', '2024-07', '2024-07-15', null].map(stepDate)).toEqual(['2024-01-01', '2024-07-01', '2024-07-15', null])
  })

  it('says a period as the legend does', () => {
    expect(['2024', '2024-07-01', '2024-07-15'].map(periodLabel)).toEqual(['2024', 'Jul 2024', '15 Jul 2024'])
  })
})

describe('the legend line and the credit', () => {
  const base = { title: 'Sea surface temperature from MUR', t: '2024-07-01', via: 'grid slice', problem: null, units: '°C' }
  it('says loading until the slice is in, then the range', () => {
    expect(legendLine(base)).toBe('Layer: Sea surface temperature from MUR at Jul 2024 · grid slice · loading the slice…')
    expect(legendLine({ ...base, ramp: { min: 15.04, max: 20.2 } })).toBe('Layer: Sea surface temperature from MUR at Jul 2024 · grid slice · 15.0 to 20.2 °C')
    expect(legendLine({ ...base, t: null, problem: 'no data: x' })).toBe('Layer: Sea surface temperature from MUR at the latest time · grid slice · no data: x')
  })

  it('titles and credits the layer from its dataset', () => {
    const title = gridTitle('JPL MUR', { name: 'sst', description: 'sea surface temperature' })
    expect(title).toBe('Sea surface temperature from JPL MUR')
    expect(gridCredit(title, ['NASA JPL PO.DAAC'], 'erddap.oceanmetrics.io')).toBe('Sea surface temperature from JPL MUR (NASA JPL PO.DAAC), sliced in the browser from ERDDAP at erddap.oceanmetrics.io')
  })

  it('says Celsius and Kelvin as °C, drops a unitless 1', () => {
    expect(['degree_C', 'Celsius', 'K', '1', null, 'mg m-3'].map(unitLabel)).toEqual(['°C', '°C', '°C', null, null, 'mg m-3'])
  })

  it('says a failed request by its host and status, not its url', () => {
    expect(problemText(new Error('https://erddap.oceanmetrics.io/erddap/griddap/jplMURSST41mday.json?latitude%5B(33.3):1:(34.2)%5D: 404'))).toBe('erddap.oceanmetrics.io did not answer (HTTP 404); try again later')
    expect(problemText(new Error('the place has no polygon'))).toBe('the place has no polygon')
  })

  it('says a request the engine gave up on (PatientFetchError) in its own words: the host, the last status and the tries', () => {
    const e = new PatientFetchError('erddap.oceanmetrics.io', 'HTTP 503 Service Unavailable', 6, 'https://erddap.oceanmetrics.io/erddap/griddap/jplMURSST41mday.parquet?x', 503)
    expect(problemText(e)).toBe('erddap.oceanmetrics.io did not answer (HTTP 503 Service Unavailable, 6 tries)')
  })
})

describe('a server that drops requests', () => {
  it('asks again until it answers, at most `tries` times', async () => {
    let n = 0
    expect(await withRetries(async () => { if (++n < 3) throw new Error('404'); return 'ok' }, 4, 0)).toBe('ok')
    expect(n).toBe(3)
    n = 0
    await expect(withRetries(async () => { n++; throw new Error('404') }, 2, 0)).rejects.toThrow('404')
    expect(n).toBe(2)
  })

  it('stops at once when the caller has gone', async () => {
    const c = new AbortController()
    c.abort(new Error('gone'))
    await expect(withRetries(async () => 'never', 4, 0, c.signal)).rejects.toThrow('gone')
  })
})
