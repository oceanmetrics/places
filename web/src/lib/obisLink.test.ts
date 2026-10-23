// the Place page's "Species on the map" link: the cases of the atlas's tests/obis/placeLink.test.ts (the CINMS url byte
// for byte, a box across 180, the zoom clamps), plus the collection href that carries it until the atlas catalog lists obis_h3.
import { describe, expect, it } from 'vitest'
import { cameraForBbox, OBIS_COLLECTION_HREF, placeObisUrl } from './obisLink'

// what the atlas writes (placeObisUrl in oceanmetrics/atlas), without the interim collection
const CINMS = 'https://oceanmetrics.io/atlas/?c=obis_h3&i=all&dim.indicator=es&dim.period=all&res=auto&map=-119.75,33.725,8.38#pl=p.NMS%253ACINMS.Channel%2520Islands'
const cinms = { placeId: 'NMS:CINMS', name: 'Channel Islands', bbox: [-120.65, 33.2, -118.85, 34.25] }

describe('placeObisUrl', () => {
  it('CINMS: the OBIS layer, the place selected, the camera on its box (the atlas url byte for byte)', () => {
    expect(placeObisUrl({ ...cinms, collection: '' })).toBe(CINMS)
  })

  it('carries the OBIS collection href until the atlas catalog lists obis_h3, before the hash', () => {
    expect(OBIS_COLLECTION_HREF).toBe('https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/obis-h3/collection.json')
    expect(placeObisUrl(cinms)).toBe(
      'https://oceanmetrics.io/atlas/?c=obis_h3&i=all&dim.indicator=es&dim.period=all&res=auto&map=-119.75,33.725,8.38' +
      '&collection=https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/obis-h3/collection.json#pl=p.NMS%253ACINMS.Channel%2520Islands')
    expect(placeObisUrl(cinms).split('#')[0]).toContain(`&collection=${OBIS_COLLECTION_HREF}`)
  })

  it('an EOV, an indicator, a period; another app; no box, no camera', () => {
    const url = placeObisUrl({ placeId: 'MRGID:8432', item: 'seabirds', indicator: 'n', period: '1990s', app: 'https://staging.example/atlas', collection: '' })
    expect(url.startsWith('https://staging.example/atlas/?c=obis_h3&i=seabirds&dim.indicator=n&dim.period=1990s&res=auto#pl=')).toBe(true)
    expect(url).not.toContain('map=')
  })

  it('a refused id opens the layer without the place, never throws', () => {
    const url = placeObisUrl({ placeId: '', collection: '' })
    expect(url).not.toContain('#pl=')
    expect(url).toContain('c=obis_h3')
  })
})

describe('cameraForBbox', () => {
  it('frames a small box close, a large one far, clamped 1..10', () => {
    expect(cameraForBbox([-1, -1, 1, 1])!.zoom).toBeCloseTo(8.23, 2)
    expect(cameraForBbox([-0.01, -0.01, 0.01, 0.01])!.zoom).toBe(10)
    expect(cameraForBbox([-180, -90, 180, 90])!.zoom).toBe(1)
  })

  it('across the antimeridian (Papahanaumokuakea: east past 180 or below west)', () => {
    const a = cameraForBbox([177.8, 18.5, 199.0, 32.0])!
    const b = cameraForBbox([177.8, 18.5, -161.0, 32.0])!
    expect(a).toEqual(b)
    expect(a.lon).toBeCloseTo(-171.6, 1)
    expect(placeObisUrl({ placeId: 'NMS:PMNM', name: 'Papahanaumokuakea', bbox: [177.8, 18.5, -161.0, 32.0], collection: '' })).toContain('&map=-171.6,25.25,')
  })

  it('a malformed box is null', () => {
    expect(cameraForBbox(null)).toBeNull()
    expect(cameraForBbox([0, 10, 1, 5])).toBeNull()
    expect(cameraForBbox([0, Number.NaN, 1, 5])).toBeNull()
    expect(cameraForBbox([0, 1, 2])).toBeNull()
  })
})
