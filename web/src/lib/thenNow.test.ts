import { describe, expect, it } from 'vitest'
import { compareHref, DEFAULT_LAYER, inPageAnchor, monthOf, nowMonth, PAGE_ANCHORS, yearsBefore } from './thenNow'

describe('monthOf', () => {
  it('reads a month, a day and a year as the month picker does', () => {
    expect(monthOf('2024-07')).toBe('2024-07')
    expect(monthOf('2024-07-15')).toBe('2024-07')
    expect(monthOf('2024')).toBe('2024-01')
    expect(monthOf('2026-09-16T00:00:00Z')).toBe('2026-09')
  })
  it('is null for nothing or a bad period', () => {
    expect(monthOf(null)).toBeNull()
    expect(monthOf('')).toBeNull()
    expect(monthOf('2024-13')).toBeNull()
    expect(monthOf('July')).toBeNull()
  })
})

describe('yearsBefore', () => {
  it('is the same month eight years earlier by default', () => {
    expect(yearsBefore('2024-07')).toBe('2016-07')
    expect(yearsBefore('2026-01', 10)).toBe('2016-01')
  })
  it('is null for a bad month', () => expect(yearsBefore('nope')).toBeNull())
})

describe('nowMonth', () => {
  it('prefers the chosen period, then the layer\'s latest time', () => {
    expect(nowMonth('2024-07', ['2002-06-16', '2026-09-16'])).toBe('2024-07')
    expect(nowMonth(null, ['2002-06-16', '2026-09-16'])).toBe('2026-09')
    expect(nowMonth(null, ['2002-06-16', null])).toBeNull()
    expect(nowMonth(null, null)).toBeNull()
  })
})

describe('compareHref', () => {
  it('opens the indicators Map over the sanctuaries with compare on (the logged answer of 2026-10-23)', () => {
    expect(compareHref({ place: 'NMS:CINMS', layer: DEFAULT_LAYER, t: '2024-07', coll: 'places' })).toBe(
      'https://oceanmetrics.io/indicators/#view=map&ind=erddap:dhw_5km:CRW_SST:mean&pi=coll:places&grain=month&t=2024-07&t2=2016-07&layer=grid:jplMURSST41mday:sst&place=NMS:CINMS')
  })
  it('opens any other place over itself, its id escaped but its colon kept', () => {
    expect(compareHref({ place: 'MR:8439/a', layer: 'grid:dhw_5km:CRW_SST', t: '2026-09-16', coll: 'mr_eez' })).toBe(
      'https://oceanmetrics.io/indicators/#view=map&ind=erddap:dhw_5km:CRW_SST:mean&pi=MR:8439%2Fa&grain=month&t=2026-09&t2=2018-09&layer=grid:dhw_5km:CRW_SST&place=MR:8439%2Fa')
  })
  it('takes another app base', () => {
    expect(compareHref({ place: 'NMS:FGBNMS', layer: DEFAULT_LAYER, t: '2025', coll: 'places' }, 'http://localhost:5181/')).toBe(
      'http://localhost:5181/#view=map&ind=erddap:dhw_5km:CRW_SST:mean&pi=coll:places&grain=month&t=2025-01&t2=2017-01&layer=grid:jplMURSST41mday:sst&place=NMS:FGBNMS')
  })
  it('is null without a month to compare', () => {
    expect(compareHref({ place: 'NMS:CINMS', layer: DEFAULT_LAYER, t: null, coll: 'places' })).toBeNull()
  })
})

describe('the hero line', () => {
  it('names the five parts of the page in order', () => {
    expect(PAGE_ANCHORS.map((a) => a.label).join(' · ')).toBe('map · indicators · species · layers · reports')
  })
  it('lets the browser scroll to a part of the same page, and only that', () => {
    const here = { pathname: '/places/p/NMS:CINMS', search: '?layer=grid:jplMURSST41mday:sst' }
    expect(inPageAnchor({ ...here, hash: '#species' }, here)).toBe(true)
    expect(inPageAnchor({ ...here, hash: '' }, here)).toBe(false)
    expect(inPageAnchor({ pathname: '/places/p/NMS:FGBNMS', search: here.search, hash: '#species' }, here)).toBe(false)
    expect(inPageAnchor({ pathname: here.pathname, search: '', hash: '#species' }, here)).toBe(false)
  })
})
