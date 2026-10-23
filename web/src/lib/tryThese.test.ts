import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'
import { parseView } from './grammar'
import { matchRoute } from './helpers'
import { ATLAS_OBIS_GLOBE, TRY_THESE } from './tryThese'
import { DEFAULT_LAYER } from './thenNow'

const get = (id: string) => TRY_THESE.find((t) => t.id === id)!

describe('Try these', () => {
  it('five examples in the order the page shows them, three Place pages then the two ways out', () => {
    expect(TRY_THESE.map((t) => t.id)).toEqual(['cinms-sst', 'fgbnms', 'senegal-eez', 'then-now', 'obis-globe'])
    expect(TRY_THESE.map((t) => t.kind)).toEqual(['place', 'place', 'place', 'out', 'out'])
    for (const t of TRY_THESE) { expect(t.label.length, t.id).toBeGreaterThan(8); expect(t.note, t.id).toMatch(/^[A-Z].*\.$/) }
  })

  it('every Place link is a Place page of the router, with the id the page reads', () => {
    const ids = { 'cinms-sst': 'NMS:CINMS', fgbnms: 'NMS:FGBNMS', 'senegal-eez': 'MRGID:8371' }
    for (const [id, place] of Object.entries(ids)) {
      const [path] = get(id).to.split('?')
      const r = matchRoute(path)
      expect(r, id).toMatchObject({ name: 'place' })
      expect(decodeURIComponent(path.replace('/p/', '')), id).toBe(place)
    }
  })

  it('Channel Islands has the SST layer under the map, in the grammar that reads it; the others carry no layer', () => {
    const q = get('cinms-sst').to.split('?')[1]
    expect(parseView('?' + q).layer).toBe(DEFAULT_LAYER)
    expect(get('fgbnms').to).toBe('/p/NMS:FGBNMS')
    expect(get('senegal-eez').to).toBe('/p/MRGID:8371')
  })

  it('Then vs Now is the indicators viewer at the Channel Islands with compare on (t2 present), as the web site and the viewer carry it', () => {
    const u = get('then-now').to
    expect(u.startsWith('https://oceanmetrics.io/indicators/#view=map&')).toBe(true)
    expect(u).toContain('&t=2024-07&t2=2016-07&')
    expect(u).toContain('&place=NMS:CINMS')
    expect(u).toContain('&layer=grid:jplMURSST41mday:sst')
  })

  it('the atlas link is the OBIS layer\'s species richness (indicator sp, all years) on the atlas app', () => {
    expect(get('obis-globe').to).toBe(ATLAS_OBIS_GLOBE)
    const u = new URL(ATLAS_OBIS_GLOBE)
    expect(u.origin + u.pathname).toBe('https://oceanmetrics.io/atlas/')
    expect(Object.fromEntries(u.searchParams)).toEqual({ c: 'obis_h3', i: 'all', 'dim.indicator': 'sp', 'dim.period': 'all' })
  })

  it('every way out is https on oceanmetrics.io', () => {
    for (const t of TRY_THESE.filter((x) => x.kind === 'out')) expect(new URL(t.to).host, t.id).toBe('oceanmetrics.io')
  })

  it('a way out opens in a new tab (the router would take a same-origin oceanmetrics.io link for one of its own pages); a Place page goes through the router', () => {
    const src = readFileSync(new URL('./TryThese.svelte', import.meta.url), 'utf8')
    const out = /\{:else\}\s*<a ([^>]*)>/.exec(src)![1]
    expect(out).toContain('target="_blank"')
    expect(out).toContain('rel="noopener"')
    const place = /\{#if t\.kind === 'place'\}\s*<a ([^>]*)>/.exec(src)![1]
    expect(place).not.toContain('target=')
    expect(place).toContain('withBase(t.to, BASE)')
  })
})
