import { describe, expect, it } from 'vitest'
import { atlasEncode, atlasHref, boxesMeet, childUrls, coverLine, erddapLayer, isGlobal, layersCovering, placeToken, type Box, type CoverLayer } from './layers'
import { toErddapLayer } from './map/gridLayer'

const CINMS: Box = [-120.6, 33.4, -118.9, 34.2]
const PMNM: Box = [177.8, 19.4, 199.0, 31.8] // unwrapped, as the index writes it

describe('boxes meet', () => {
  it('in plain longitudes', () => {
    expect(boxesMeet(CINMS, [-125, 30, -115, 40])).toBe(true)
    expect(boxesMeet(CINMS, [-100, 20, -80, 30])).toBe(false)
    expect(boxesMeet(CINMS, [-125, 40, -115, 50])).toBe(false)
  })

  it('across the antimeridian, unwrapped or crossing', () => {
    expect(boxesMeet(PMNM, [-170, 20, -160, 30])).toBe(true) // the east part, at -165
    expect(boxesMeet(PMNM, [170, 20, -170, 30])).toBe(true) // a crossing box (west > east)
    expect(boxesMeet(PMNM, [-150, 20, -140, 30])).toBe(false)
    expect(boxesMeet([175, 0, -175, 10], [-178, 5, -176, 6])).toBe(true)
  })

  it('a box round the globe meets every place', () => {
    expect(boxesMeet(PMNM, [-180, -90, 180, 90])).toBe(true)
  })
})

describe('the layers covering a place', () => {
  const layers: CoverLayer[] = [
    { id: 'aquamaps_eov', title: 'AquaMaps EOV share', source: 'atlas', bbox: [-180, -90, 180, 90] },
    { id: 'biotrack_indicators', title: 'BioTrack', source: 'atlas', bbox: [-97.9, 11.8, -43.9, 56.5] },
    { id: 'msens-v8-gm', title: 'NOAA SEFSC', source: 'atlas', bbox: [-180, -18, 180, 75] },
    { id: 'dhw_5km', title: 'CRW', source: 'erddap', bbox: [-180, -89.975, 180, 89.975] },
    { id: 'calcofi_bottle', title: 'CalCOFI', source: 'erddap', bbox: [-164.1, 18.4, -106.0, 51.1] },
    { id: 'none', title: 'no extent', source: 'atlas', bbox: null },
  ]

  it('keeps those whose extent meets the box: atlas then ERDDAP, global ones last in each', () => {
    const hits = layersCovering({ bbox: CINMS }, layers)
    expect(hits.map((h) => [h.id, h.global])).toEqual([['msens-v8-gm', false], ['aquamaps_eov', true], ['calcofi_bottle', false], ['dhw_5km', true]])
  })

  it('leaves out a regional layer elsewhere and a layer without an extent; nothing without a box', () => {
    expect(layersCovering({ bbox: [100, -10, 110, 0] }, layers).map((h) => h.id)).toEqual(['msens-v8-gm', 'aquamaps_eov', 'dhw_5km'])
    expect(layersCovering({ bbox: null }, layers)).toEqual([])
  })

  it('calls an extent global only round the globe and near pole to pole', () => {
    expect([isGlobal([-180, -90, 180, 90]), isGlobal([-179.99, -89.99, 180, 89.99]), isGlobal([-180, -18, 180, 75]), isGlobal(null)]).toEqual([true, true, false, false])
  })

  it('says how many are global', () => {
    const h = layersCovering({ bbox: CINMS }, layers)
    expect(coverLine(h)).toBe("4 layers meet this place's box; 2 of them are global (the whole ocean), so the box says little about where each has data here. A check by data cell waits on the atlas collections' H3 cells.")
    expect(coverLine(h.filter((x) => !x.global))).toBe("2 layers meet this place's box.")
    expect(coverLine([])).toBe("No atlas or ERDDAP layer meets this place's box.")
  })
})

describe('the atlas link with the place', () => {
  it('encodes as the atlas g1 names do (the fixture of atlas docs/gazetteer-places.md)', () => {
    expect(placeToken('BOEM:OCS-P 0562', 'OCS-P 0562')).toBe('p.BOEM%3AOCS-P%200562.OCS-P%200562')
    expect(placeToken('NMS:CINMS', 'Channel Islands')).toBe('p.NMS%3ACINMS.Channel%20Islands')
    expect(placeToken('MPAINV:CA-123')).toBe('p.MPAINV%3ACA-123.')
    expect(placeToken('A.B~C:D', 'St. George ~ Basin')).toBe('p.A%2EB%7EC%3AD.St%2E%20George%20%7E%20Basin')
    expect(atlasEncode('é')).toBe('%C3%A9')
  })

  it('cuts a long name at 60 encoded characters, never inside a character; refuses an id over 120', () => {
    const t = placeToken('NMS:CINMS', 'Channel Islands National Marine Sanctuary and the waters around it')!
    const name = t.split('.')[2]
    expect(name.length).toBeLessThanOrEqual(60)
    expect(name).toBe('Channel%20Islands%20National%20Marine%20Sanctuary%20and%20th')
    expect(placeToken('X:' + 'a'.repeat(200))).toBeNull()
  })

  it('opens the collection with the place in the hash, escaped once more for the atlas\'s URLSearchParams', () => {
    const href = atlasHref('aquamaps_eov', 'NMS:CINMS', 'Channel Islands')
    expect(href).toBe('https://oceanmetrics.io/atlas/?c=aquamaps_eov#pl=p.NMS%253ACINMS.Channel%2520Islands')
    expect(new URLSearchParams(new URL(href).hash.slice(1)).get('pl')).toBe('p.NMS%3ACINMS.Channel%20Islands')
  })
})

describe('the collections', () => {
  it('makes a catalog\'s children absolute', () => {
    expect(childUrls({ links: [{ rel: 'root', href: './catalog.json' }, { rel: 'child', href: './aquamaps_eov/collection.json' }, { rel: 'child', href: 'https://file.marinesensitivity.org/stac/v7/bl/collection.json' }] },
      'https://x/atlas/catalog.json')).toEqual(['https://x/atlas/aquamaps_eov/collection.json', 'https://file.marinesensitivity.org/stac/v7/bl/collection.json'])
  })

  it('gives a gridded ERDDAP layer its grid key (the first field that is not a mask), a station layer none', () => {
    const mur = erddapLayer(toErddapLayer('jplMURSST41mday', { title: 'MUR', 'erddap:base_url': 'https://e.org/erddap', 'cube:variables': { mask: {}, sst: {} },
      'cube:dimensions': { longitude: { step: 0.01 }, latitude: { step: 0.01 } }, extent: { spatial: { bbox: [[-180, -90, 180, 90]] }, temporal: { interval: [['2002-06-16', null]] } } }))
    expect([mur.layerKey, mur.note]).toEqual(['grid:jplMURSST41mday:sst', 'grid, 0.01° · 2002 to now · ERDDAP at e.org'])
    expect(erddapLayer(toErddapLayer('calcofi_bottle', { 'erddap:protocol': 'tabledap', 'cube:variables': { temperature: {} } })).layerKey).toBeUndefined()
  })
})
