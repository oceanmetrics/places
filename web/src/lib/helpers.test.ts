import { describe, expect, it } from 'vitest'
import type { Layer } from '@oceanmetrics/places'
import {
  authorityOf, calcofiLink, defaultColour, erddapLink, fmtDate, fmtN, fmtValue, geojsonSql, groupByAuthority,
  layerForPlace, matchRoute, parquetUrl, placePath, sanitizeHtml, stacRoot, withBase,
} from './helpers'

const L = (o: Partial<Layer>): Layer => ({
  slug: 's', title: 'S', collection: 's', pmtiles: '', source_layer: 's', geom_type: 'MultiPolygon', n: null, updated: null,
  version: null, paint: {}, authority: null, place_type: null, bbox: null, attribution: '', attribution_html: '',
  license: null, license_url: null, citation: '', ...o,
})

describe('routes', () => {
  it('matches the five pages', () => {
    expect(matchRoute('/')).toEqual({ name: 'home' })
    expect(matchRoute('/credits/')).toEqual({ name: 'credits' })
    expect(matchRoute('/docs')).toEqual({ name: 'docs' })
    expect(matchRoute('/l/boem_wind_leases')).toEqual({ name: 'layer', slug: 'boem_wind_leases' })
    expect(matchRoute('/nope')).toEqual({ name: 'notfound' })
  })

  it('keeps the colon of a place id, raw or encoded, and decodes a slash', () => {
    expect(matchRoute('/p/NMS:PMNM')).toEqual({ name: 'place', id: 'NMS:PMNM' })
    expect(matchRoute('/p/NMS%3APMNM')).toEqual({ name: 'place', id: 'NMS:PMNM' })
    expect(matchRoute('/p/MR%3A8439%2Fa')).toEqual({ name: 'place', id: 'MR:8439/a' })
  })

  it('serves under an app base prefix (GitHub Pages /places/)', () => {
    expect(matchRoute('/places/', '/places')).toEqual({ name: 'home' })
    expect(matchRoute('/places', '/places')).toEqual({ name: 'home' })
    expect(matchRoute('/places/credits', '/places')).toEqual({ name: 'credits' })
    expect(matchRoute('/places/p/NMS:PMNM', '/places')).toEqual({ name: 'place', id: 'NMS:PMNM' })
    expect(withBase('/l/a', 'https://storage.oceanmetrics.io/gazetteer', undefined, '/places')).toBe('/places/l/a')
    expect(withBase('/?layers=a', 'http://h/', undefined, '/places')).toBe('/places/?layers=a&base=http://h/')
  })

  it('round-trips a place id through placePath', () => {
    for (const id of ['NMS:PMNM', 'AOA:N 1', 'X:a/b']) expect(matchRoute(placePath(id))).toEqual({ name: 'place', id })
    expect(placePath('NMS:PMNM')).toBe('/p/NMS:PMNM')
  })
})

describe('urls', () => {
  it('builds data urls whatever the trailing slash', () => {
    expect(parquetUrl('https://x/g', 'a')).toBe('https://x/g/a/places.parquet')
    expect(stacRoot('https://x/g/')).toBe('https://x/g/catalog.json')
  })

  it('carries a non-default base through internal links only', () => {
    expect(withBase('/l/a', 'https://storage.oceanmetrics.io/gazetteer')).toBe('/l/a')
    expect(withBase('/l/a', 'http://localhost:8080/')).toBe('/l/a?base=http://localhost:8080/')
    expect(withBase('/?layers=a', 'http://h/')).toBe('/?layers=a&base=http://h/')
  })

  it('builds the use-in deep links', () => {
    expect(calcofiLink('boem_wind_leases')).toBe('https://calcofi.io/explore/?layers=boem_wind_leases')
    expect(erddapLink('NMS:PMNM')).toBe('https://oceanmetrics.io/erddap-places/#place=NMS:PMNM')
  })
})

describe('layers', () => {
  it('groups by authority, Other last, titles sorted', () => {
    const g = groupByAuthority([
      L({ slug: 'a', title: 'Zed', authority: 'NOAA' }), L({ slug: 'b', title: 'Alpha', authority: 'NOAA' }),
      L({ slug: 'c', title: 'C', authority: null }), L({ slug: 'd', title: 'D', authority: 'BOEM' }),
    ])
    expect(g.map((x) => x.authority)).toEqual(['BOEM', 'NOAA', 'Other'])
    expect(g[1].layers.map((l) => l.title)).toEqual(['Alpha', 'Zed'])
  })

  it('finds the default colour in fill, line then circle, else a fallback', () => {
    expect(defaultColour(L({ paint: { fill: { 'fill-color': '#112233' } } }))).toBe('#112233')
    expect(defaultColour(L({ paint: { line: { 'line-color': '#AABBCC' } } }))).toBe('#aabbcc')
    expect(defaultColour(L({ paint: { circle: { 'circle-color': 'red' } } }))).toBe('#e08a1e')
    expect(defaultColour(undefined)).toBe('#e08a1e')
  })

  it('picks the layer of a place by authority prefix, then place_type', () => {
    const ls = [L({ slug: 'a', authority: 'BOEM', place_type: 'lease' }), L({ slug: 'b', authority: 'BOEM', place_type: 'area' }), L({ slug: 'c', authority: 'NMS' })]
    expect(authorityOf('BOEM:x:1')).toBe('BOEM')
    expect(layerForPlace(ls, 'NMS:PMNM')?.slug).toBe('c')
    expect(layerForPlace(ls, 'BOEM:1', { place_type: 'area' })?.slug).toBe('b')
    expect(layerForPlace(ls, 'BOEM:1')?.slug).toBe('a')
    expect(layerForPlace(ls, 'ZZZ:1')).toBeUndefined()
  })

  it('the feature collection wins over the authority guess (regression: NMS:PMNM in the authority-less legacy places layer)', () => {
    const ls = [L({ slug: 'noaa_sanctuaries', collection: 'noaa_sanctuaries', authority: 'ONMS' }), L({ slug: 'places', collection: 'places', authority: null })]
    expect(layerForPlace(ls, 'NMS:PMNM', {}, 'places')?.slug).toBe('places')
    expect(layerForPlace(ls, 'NMS:PMNM')).toBeUndefined()          // no collection, no authority match: undefined, not a guess
    expect(layerForPlace(ls, 'ONMS:MBNMS', {}, 'nope')?.slug).toBe('noaa_sanctuaries')   // unknown collection falls back
  })
})

describe('theme', () => {
  it('an explicit choice wins, else the OS preference', async () => {
    const { effectiveDark } = await import('./helpers')
    expect(effectiveDark('dark', false)).toBe(true)
    expect(effectiveDark('light', true)).toBe(false)
    expect(effectiveDark(null, true)).toBe(true)
    expect(effectiveDark(undefined, false)).toBe(false)
    expect(effectiveDark('garbage', true)).toBe(true)   // an unknown value is no choice
  })
})

describe('formatting and sql', () => {
  it('formats counts, dates and values', () => {
    expect(fmtN(12345)).toBe('12,345')
    expect(fmtN(null)).toBe('–')
    expect(fmtDate('2026-09-30T12:00:00Z')).toBe('2026-09-30')
    expect(fmtDate(null)).toBe('–')
    expect(fmtValue(null)).toBe('–')
    expect(fmtValue({ a: 1 })).toBe('{"a":1}')
    expect(fmtValue(3)).toBe('3')
  })

  it('writes a GeoJSON copy-SQL with quotes escaped', () => {
    const sql = geojsonSql('https://x/g/a/places.parquet', "AOA:O'Brien")
    expect(sql).toContain("read_parquet('https://x/g/a/places.parquet')")
    expect(sql).toContain("WHERE place_id = 'AOA:O''Brien'")
    expect(sql).toContain("TO 'AOA_O_Brien.geojson'")
  })
})

describe('sanitizeHtml', () => {
  it('keeps text and https links, forcing a new tab', () => {
    expect(sanitizeHtml('BOEM, <a href="https://www.boem.gov/">data</a>. Processed by <b>Ocean Metrics</b>.'))
      .toBe('BOEM, <a href="https://www.boem.gov/" target="_blank" rel="noopener noreferrer">data</a>. Processed by <b>Ocean Metrics</b>.')
  })

  it('drops script and event handlers (regression: a ?base= manifest must not run code)', () => {
    expect(sanitizeHtml('<script>alert(1)</script>x')).toBe('alert(1)x')
    expect(sanitizeHtml('<img src=x onerror=alert(1)>y')).toBe('y')
    expect(sanitizeHtml('<a href="javascript:alert(1)" onclick="e()">z</a>')).toBe('<a>z</a>')
    expect(sanitizeHtml('<b onmouseover="e()">q</b>')).toBe('<b>q</b>')
  })

  it('escapes a stray angle bracket', () => {
    expect(sanitizeHtml('a < b')).toBe('a &lt; b')
  })
})
