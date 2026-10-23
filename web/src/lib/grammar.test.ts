import { describe, expect, it } from 'vitest'
import { buildSearch, carryView, EOV_KEYS, parseEov, parseTaxon, parseLayerParam, parseLayers, parsePeriod, parseView, serializeLayers } from './grammar'

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
      proj: 'globe',
      layer: null,
      t: null,
      eov: null,
      taxon: null,
    })
    expect(parseView('')).toEqual({ layers: null, place: null, proj: 'globe', layer: null, t: null, eov: null, taxon: null })
  })

  it('writes layers and place, round-tripping through parseView', () => {
    const v = { layers: [{ slug: 'a', colour: '#ff0000', opacity: 0.5, width: 2 }, { slug: 'b', colour: null, opacity: null, width: null }], place: 'AOA:N1', proj: 'globe' as const, layer: null, t: null, eov: null, taxon: null }
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

  it('carries proj=mercator to another page unless the target sets proj itself', () => {
    expect(carryView('/p/NMS:MBNMS', '?layers=a&proj=mercator')).toBe('/p/NMS:MBNMS?proj=mercator')
    expect(carryView('/?layers=b&place=X:1', '?proj=mercator')).toBe('/?layers=b&place=X:1&proj=mercator')
    expect(carryView('/l/a?base=http://x/#top', '?proj=mercator')).toBe('/l/a?base=http://x/&proj=mercator#top')
    expect(carryView('/p/X:1?proj=globe', '?proj=mercator')).toBe('/p/X:1?proj=globe')
    expect(carryView('/credits', '?layers=a')).toBe('/credits')
  })

  it('defaults to the globe; proj=mercator is the only value written', () => {
    expect(parseView('?proj=mercator').proj).toBe('mercator')
    expect(parseView('?proj=globe').proj).toBe('globe')
    expect(parseView('?proj=lambert').proj).toBe('globe')
    expect(buildSearch({ proj: 'mercator' }, '?layers=a')).toBe('?layers=a&proj=mercator')
    expect(buildSearch({ proj: 'globe' }, '?layers=a&proj=mercator')).toBe('?layers=a')
  })

  it('reads and writes the layer under the map and its period', () => {
    const v = parseView('?layer=grid:jplMURSST41mday:sst&t=2024-07')
    expect([v.layer, v.t]).toEqual(['grid:jplMURSST41mday:sst', '2024-07'])
    expect(buildSearch({ layer: 'grid:dhw_5km:CRW_SST', t: '2024' }, '?proj=mercator')).toBe('?proj=mercator&layer=grid:dhw_5km:CRW_SST&t=2024')
    expect(buildSearch({ layer: null, t: null }, '?layer=grid:a:b&t=2024&x=1')).toBe('?x=1')
  })

  it('takes a known slot kind only, and reads erddap: as grid:', () => {
    expect(parseLayerParam('erddap:dhw_5km:CRW_SST')).toBe('grid:dhw_5km:CRW_SST')
    expect(parseLayerParam('cog:aquamaps_eov')).toBe('cog:aquamaps_eov')
    expect(parseLayerParam('wms:x')).toBeNull()
    expect(parseLayerParam('grid:')).toBeNull()
    expect(parseLayerParam('grid:a b')).toBeNull()
  })

  it('takes a year, a month or a day as the period', () => {
    expect(['2024', '2024-07', '2024-07-15'].map(parsePeriod)).toEqual(['2024', '2024-07', '2024-07-15'])
    expect(['24', '2024-13', '2024-07-32', 'latest', ''].map(parsePeriod)).toEqual([null, null, null, null, null])
  })

  it('carries the layer and its period to another page, as it does proj', () => {
    expect(carryView('/p/MRGID:8439', '?layer=grid:jplMURSST41mday:sst&t=2024-07')).toBe('/p/MRGID:8439?layer=grid:jplMURSST41mday:sst&t=2024-07')
  })
})

describe('eov= and taxon= (the Species section\'s filters)', () => {
  it('reads the seven groups, and nothing else (absent, "all", an unknown key, the wrong case)', () => {
    for (const k of EOV_KEYS) expect(parseEov(k)).toBe(k)
    expect(EOV_KEYS.length).toBe(7)
    expect([parseEov(null), parseEov(''), parseEov('all'), parseEov('macroalgae'), parseEov('Fish'), parseEov(' fish ')]).toEqual([null, null, null, null, null, 'fish'])
  })

  it('reads a taxon as the typed name, single-spaced, two to 100 characters', () => {
    expect([parseTaxon('Cetacea'), parseTaxon('  Thunnus   albacares '), parseTaxon('x'), parseTaxon(''), parseTaxon(null), parseTaxon('a'.repeat(101))]).toEqual(['Cetacea', 'Thunnus albacares', null, null, null, null])
  })

  it('parses them in the view, null when absent or invalid', () => {
    expect(parseView('?eov=seabirds&taxon=Aves')).toMatchObject({ eov: 'seabirds', taxon: 'Aves' })
    expect(parseView('?eov=bogus')).toMatchObject({ eov: null, taxon: null })
    expect(parseView('')).toMatchObject({ eov: null, taxon: null })
  })

  it('writes them and removes them, keeping every other parameter', () => {
    const q = buildSearch({ eov: 'fish', taxon: 'Scombridae' }, '?layer=grid:jplMURSST41mday:sst&t=2024-07&base=x')
    expect(q).toBe('?layer=grid:jplMURSST41mday:sst&t=2024-07&base=x&eov=fish&taxon=Scombridae')
    expect(buildSearch({ eov: null }, q)).toBe('?layer=grid:jplMURSST41mday:sst&t=2024-07&base=x&taxon=Scombridae')
    expect(buildSearch({ taxon: null, eov: null }, q)).toBe('?layer=grid:jplMURSST41mday:sst&t=2024-07&base=x')
    expect(buildSearch({ eov: 'bogus', taxon: ' ' }, '?eov=fish&taxon=Aves')).toBe('')
  })

  it('leaves them alone when the other parameters change', () => {
    expect(buildSearch({ layer: 'grid:a:b', t: '2024' }, '?eov=fish&taxon=Aves')).toBe('?eov=fish&taxon=Aves&layer=grid:a:b&t=2024')
  })

  it('round-trips parse(build(x)) for every group and for names with spaces, quotes and accents', () => {
    for (const eov of EOV_KEYS) expect(parseView(buildSearch({ eov }, '')).eov).toBe(eov)
    for (const taxon of ['Cetacea', 'Thunnus albacares', "Delphinus d'orbigny", 'Müller & Co', 'Aves/Reptilia?', 'a=b&c=d', 'Ünïcode núm']) {
      expect(parseView(buildSearch({ taxon, eov: 'fish' }, '?proj=mercator'))).toMatchObject({ taxon, eov: 'fish', proj: 'mercator' })
    }
  })

  it('does not carry them from place to place (they belong to one place\'s list)', () => {
    expect(carryView('/p/NMS:FGBNMS', '?eov=fish&taxon=Aves&proj=mercator')).toBe('/p/NMS:FGBNMS?proj=mercator')
  })
})
