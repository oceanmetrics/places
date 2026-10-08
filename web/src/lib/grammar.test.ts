import { describe, expect, it } from 'vitest'
import { buildSearch, parseLayers, parseView, serializeLayers } from './grammar'

describe('layers= grammar', () => {
  it('parses slug-only entries in order', () => {
    expect(parseLayers('a,b')).toEqual([
      { slug: 'a', colour: null, opacity: null, width: null },
      { slug: 'b', colour: null, opacity: null, width: null },
    ])
  })

  it('parses colour, opacity and width', () => {
    expect(parseLayers('boem_wind_leases:1b7f9e:0.5:2')).toEqual([
      { slug: 'boem_wind_leases', colour: '#1b7f9e', opacity: 0.5, width: 2 },
    ])
  })

  it('accepts a leading # and upper case, normalising to lower case', () => {
    expect(parseLayers('a:#1B7F9E')?.[0].colour).toBe('#1b7f9e')
  })

  it('skips fields with an empty slot', () => {
    expect(parseLayers('a::0.3')).toEqual([{ slug: 'a', colour: null, opacity: 0.3, width: null }])
    expect(parseLayers('a:::1.5')).toEqual([{ slug: 'a', colour: null, opacity: null, width: 1.5 }])
  })

  it('nulls out-of-range or malformed fields', () => {
    expect(parseLayers('a:zzz:2:9')).toEqual([{ slug: 'a', colour: null, opacity: null, width: null }])
    expect(parseLayers('a:12345:-1:0.1')).toEqual([{ slug: 'a', colour: null, opacity: null, width: null }])
  })

  it('rounds opacity to 2 dp and width to 0.5', () => {
    expect(parseLayers('a::0.456:1.3')).toEqual([{ slug: 'a', colour: null, opacity: 0.46, width: 1.5 }])
  })

  it('drops empty slugs and duplicate slugs (first wins)', () => {
    expect(parseLayers(',a,:ff0000,a:ff0000')?.map((l) => [l.slug, l.colour])).toEqual([['a', null]])
  })

  it('distinguishes absent (null), off ([]) and a list', () => {
    expect(parseLayers(null)).toBeNull()
    expect(parseLayers('')).toBeNull()
    expect(parseLayers('off')).toEqual([])
  })

  it('serialises, dropping trailing empty fields and the #', () => {
    expect(serializeLayers([
      { slug: 'a', colour: null, opacity: null, width: null },
      { slug: 'b', colour: '#1b7f9e', opacity: null, width: null },
      { slug: 'c', colour: null, opacity: 0.5, width: null },
      { slug: 'd', colour: '#ff0000', opacity: 0.25, width: 2 },
      { slug: 'e', colour: null, opacity: null, width: 3.5 },
    ])).toBe('a,b:1b7f9e,c::0.5,d:ff0000:0.25:2,e:::3.5')
    expect(serializeLayers([])).toBe('off')
  })

  it('round-trips parse(serialize(x)) for every field combination', () => {
    const ls = [
      { slug: 'boem_wind_leases', colour: '#1b7f9e', opacity: 0.5, width: 2 },
      { slug: 'noaa_aoa_socal', colour: null, opacity: 0.75, width: null },
      { slug: 'x', colour: '#000000', opacity: 0, width: 0.5 },
      { slug: 'y', colour: null, opacity: null, width: 4 },
      { slug: 'z', colour: null, opacity: 1, width: null },
    ]
    expect(parseLayers(serializeLayers(ls))).toEqual(ls)
    expect(serializeLayers(parseLayers('a:1b7f9e:0.5:2,b,c::0.1')!)).toBe('a:1b7f9e:0.5:2,b,c::0.1')
  })
})

describe('view in the query string', () => {
  it('reads layers and place, place ids keeping their colon', () => {
    expect(parseView('?layers=a:ff0000,b&place=NMS:PMNM')).toEqual({
      layers: [
        { slug: 'a', colour: '#ff0000', opacity: null, width: null },
        { slug: 'b', colour: null, opacity: null, width: null },
      ],
      place: 'NMS:PMNM',
    })
    expect(parseView('')).toEqual({ layers: null, place: null })
  })

  it('writes layers and place, round-tripping through parseView', () => {
    const v = { layers: [{ slug: 'a', colour: '#ff0000', opacity: 0.5, width: 2 }, { slug: 'b', colour: null, opacity: null, width: null }], place: 'AOA:N1' }
    const s = buildSearch(v)
    expect(s).toBe('?layers=a:ff0000:0.5:2,b&place=AOA:N1')
    expect(parseView(s)).toEqual(v)
  })

  it('keeps unrelated parameters and removes cleared ones', () => {
    expect(buildSearch({ place: null }, '?base=http://x/&place=A:1&layers=a')).toBe('?base=http:%2F%2Fx%2F&layers=a')
    expect(buildSearch({ layers: null }, '?theme=dark&layers=a')).toBe('?theme=dark')
    expect(buildSearch({ layers: [] })).toBe('?layers=off')
    expect(buildSearch({}, '')).toBe('')
  })
})
