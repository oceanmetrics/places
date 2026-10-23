import { describe, expect, it } from 'vitest'
import { BASEMAP_URL, DEFAULT_TILES } from '@oceanmetrics/map'
import { BASEMAP_BUCKET, placesBeforeId, styleCredit, tilesAt, themeOf } from './basemap'

describe('the basemap tiers', () => {
  it('reads every tier from the bucket\'s path-style url until the storage host serves basemap/', () => {
    const t = tilesAt(DEFAULT_TILES, BASEMAP_URL)
    for (const u of [t.core, t.far, t.contours, t.names, t.land, ...(t.regional ?? [])]) expect(u?.startsWith(BASEMAP_BUCKET)).toBe(true)
    expect(t.core).toBe(`${BASEMAP_BUCKET}gebco/core.pmtiles`)
  })

  it('leaves a tier elsewhere and a null tier as they are', () => {
    expect(tilesAt({ core: 'https://x/core.pmtiles', far: `${BASEMAP_URL}gebco/far.pmtiles`, contours: null, names: null, land: null }, BASEMAP_URL))
      .toEqual({ core: 'https://x/core.pmtiles', far: `${BASEMAP_BUCKET}gebco/far.pmtiles`, regional: undefined, contours: null, names: null, land: null })
  })

  it('maps the app theme to the style theme', () => {
    expect([themeOf(true), themeOf(false)]).toEqual(['dark', 'light'])
  })
})

describe('where the place layers go', () => {
  it('under the first text above the land mask: the undersea names, not the isobath labels under the mask', () => {
    const layers = [
      { id: 'background', type: 'background' }, { id: 'water', type: 'fill' }, { id: 'gebco-shade', type: 'hillshade' },
      { id: 'gebco-contour-label', type: 'symbol' }, { id: 'land', type: 'fill' }, { id: 'water-inland', type: 'fill' },
      { id: 'gebco-names-1', type: 'symbol' }, { id: 'road', type: 'line' }, { id: 'place_town', type: 'symbol' },
    ]
    expect(placesBeforeId(layers)).toBe('gebco-names-1')
  })

  it('under CARTO\'s first label on the boot style (no tiers), and on top when there is no text', () => {
    expect(placesBeforeId([{ id: 'background', type: 'background' }, { id: 'water', type: 'fill' }, { id: 'waterway_label', type: 'symbol' }])).toBe('waterway_label')
    expect(placesBeforeId([{ id: 'background', type: 'background' }])).toBeNull()
  })
})

describe('the basemap credit', () => {
  it('is every source\'s attribution once', () => {
    expect(styleCredit({ sources: { a: { attribution: '© CARTO' }, b: { attribution: 'GEBCO' }, c: { attribution: 'GEBCO' }, d: {} } })).toBe('© CARTO · GEBCO')
    expect(styleCredit(null)).toBe('')
  })
})
