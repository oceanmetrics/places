// the pure parts of the prerendered link-preview shells (scripts/shell-lib.mjs, scripts/prerender-shells.mjs)
import { describe, expect, it } from 'vitest'
import {
  authorityName, baseOfIndex, chooseIds, creditOf, esc, geoBox, jsonScript, layerDescription, layerJsonLd, pageUrl, placeDescription,
  placeJsonLd, placeTitle, renderShell, shellFolder, splitIds,
} from '../../scripts/shell-lib.mjs'
import { matchRoute } from './helpers'

const place = {
  place_id: 'NMS:CINMS', name: 'Channel Islands National Marine Sanctuary', authority: 'NMS', place_type: 'protected_area',
  collection: 'places', bbox: [-120.6, 33.4, -119.0, 34.6], area_km2: 4294.6,
  attribution: 'NOAA Office of National Marine Sanctuaries. Processed by Ocean Metrics.',
}
const layer = { slug: 'places', title: 'National Marine Sanctuaries (NMS codes)', authority: null, attribution: place.attribution, n: 18, place_type: 'protected_area', license: 'CC-BY-4.0', license_url: 'https://creativecommons.org/licenses/by/4.0/', bbox: [-171, -15, -66, 49] }

const INDEX = `<!doctype html><html><head>
<meta name="description" content="Search, browse and cite." />
<script type="module" crossorigin src="/places/assets/index-abc.js"></script>
<title>Places · Ocean Metrics marine gazetteer</title>
</head><body><div id="app"></div></body></html>`

describe('titles and descriptions', () => {
  it('titles a place "<name> · Places · Ocean Metrics"', () => {
    expect(placeTitle(place.name)).toBe('Channel Islands National Marine Sanctuary · Places · Ocean Metrics')
  })

  it('names the authority from the layer, else the credit without the shared tail, else the code', () => {
    expect(authorityName(place, { authority: 'NOAA' })).toBe('NOAA')
    expect(authorityName(place, layer)).toBe('NOAA Office of National Marine Sanctuaries')
    expect(authorityName({ authority: 'NMS' }, null)).toBe('NMS')
    expect(creditOf('X Agency. Processed by Ocean Metrics.')).toBe('X Agency')
  })

  it('describes a place with its layer title, authority, kind and area', () => {
    expect(placeDescription(place, layer)).toBe(
      'Channel Islands National Marine Sanctuary (NMS:CINMS) is a protected area (4,295 km²) in National Marine Sanctuaries (NMS codes), '
      + 'from NOAA Office of National Marine Sanctuaries. Its boundary, indicators, species and the layers that cover it, in the Ocean Metrics marine gazetteer.')
  })

  it('says "an" before a vowel, and copes with no layer, no area and no authority', () => {
    const d = placeDescription({ place_id: 'X:1', name: 'Zed', place_type: 'eez' }, null)
    expect(d.startsWith('Zed (X:1) is an eez. Its boundary')).toBe(true)
  })

  it('describes a layer by count, authority and licence', () => {
    expect(layerDescription(layer)).toContain('National Marine Sanctuaries (NMS codes): 18 protected areas from NOAA Office of National Marine Sanctuaries, licence CC-BY-4.0.')
    expect(layerDescription({ ...layer, n: 1 })).toContain(': 1 protected area from')
  })
})

describe('JSON-LD', () => {
  it('is a schema.org Place with name, identifier, url and a GeoShape box (south west north east)', () => {
    expect(placeJsonLd(place, 'https://oceanmetrics.io/places/p/NMS:CINMS/')).toEqual({
      '@context': 'https://schema.org', '@type': 'Place', name: place.name, identifier: 'NMS:CINMS',
      url: 'https://oceanmetrics.io/places/p/NMS:CINMS/', geo: { '@type': 'GeoShape', box: '33.4 -120.6 34.6 -119' },
    })
  })

  it('wraps an unwrapped east edge back into -180..180 and leaves the box out without a bbox', () => {
    expect(geoBox([177, -20, 199, -10])).toBe('-20 177 -10 -161')
    expect(geoBox(null)).toBeNull()
    expect(geoBox([1, 2, 3])).toBeNull()
    expect('geo' in placeJsonLd({ ...place, bbox: null }, 'u')).toBe(false)
  })

  it('makes a layer a Dataset with its licence', () => {
    const j = layerJsonLd(layer, 'u')
    expect(j['@type']).toBe('Dataset')
    expect(j.license).toBe('https://creativecommons.org/licenses/by/4.0/')
  })

  it('never lets a name close the script element', () => {
    const s = jsonScript(placeJsonLd({ ...place, name: '</script><script>alert(1)</script> & "q"' }, 'u'))
    expect(s).not.toContain('<')
    expect(s).not.toContain('>')
    expect(JSON.parse(s).name).toBe('</script><script>alert(1)</script> & "q"')
  })
})

describe('the shell', () => {
  const shell = renderShell(INDEX, {
    title: placeTitle(place.name), description: placeDescription(place, layer), url: 'https://oceanmetrics.io/places/p/NMS:CINMS/',
    image: 'https://oceanmetrics.io/places/favicon.svg', jsonld: placeJsonLd(place, 'https://oceanmetrics.io/places/p/NMS:CINMS/'),
  })

  it('swaps the title and description and adds canonical, Open Graph, Twitter and JSON-LD', () => {
    expect(shell).toContain('<title>Channel Islands National Marine Sanctuary · Places · Ocean Metrics</title>')
    expect(shell).not.toContain('Search, browse and cite.')
    expect(shell.match(/<meta name="description"/g)).toHaveLength(1)
    expect(shell).toContain('<link rel="canonical" href="https://oceanmetrics.io/places/p/NMS:CINMS/" />')
    expect(shell).toContain('<meta property="og:type" content="website" />')
    expect(shell).toContain('<meta property="og:url" content="https://oceanmetrics.io/places/p/NMS:CINMS/" />')
    expect(shell).toContain('<meta property="og:image" content="https://oceanmetrics.io/places/favicon.svg" />')
    expect(shell).toContain('<meta name="twitter:card" content="summary" />')
    expect(shell).toContain('<script type="application/ld+json">')
    expect(shell).toContain('<script type="module" crossorigin src="/places/assets/index-abc.js"></script>')   // the app still mounts
    expect(shell).toContain('<div id="app"></div>')
  })

  it('escapes <, &, and quotes in a name, in the title and every attribute', () => {
    const nasty = `Tom's "Reef" <b> & Co`
    const s = renderShell(INDEX, { title: placeTitle(nasty), description: `A "d" <i> & 'e' $& $1`, url: 'https://x/?a=1&b="2"', image: 'i' })
    expect(s).toContain(`<title>Tom&#39;s &quot;Reef&quot; &lt;b&gt; &amp; Co · Places · Ocean Metrics</title>`)
    expect(s).toContain(`<meta name="description" content="A &quot;d&quot; &lt;i&gt; &amp; &#39;e&#39; $&amp; $1" />`)
    expect(s).toContain('content="https://x/?a=1&amp;b=&quot;2&quot;"')
    expect(s).not.toContain('<b>')
    expect(esc(`<&"'>`)).toBe('&lt;&amp;&quot;&#39;&gt;')
  })

  it('throws when the template has no title or description meta', () => {
    expect(() => renderShell('<html></html>', { title: 't', description: 'd', url: 'u', image: 'i' })).toThrow(/template changed/)
  })

  it('reads the app base from the built module script, and builds absolute urls from it', () => {
    expect(baseOfIndex(INDEX)).toBe('/places/')
    expect(baseOfIndex(INDEX.replace('/places/assets', '/assets'))).toBe('/')
    expect(pageUrl('https://oceanmetrics.io/', '/places/', 'p/NMS:CINMS/')).toBe('https://oceanmetrics.io/places/p/NMS:CINMS/')
    expect(pageUrl('https://oceanmetrics.io', '/', 'credits/')).toBe('https://oceanmetrics.io/credits/')
  })
})

describe('which places', () => {
  const ix = ['NMS:A', 'MPAINV:1', 'NMS:B', 'NMS:A']
  it('takes the NMS: sanctuaries, then the extra ids, once each', () => {
    expect(chooseIds(ix, ['MPAINV:1', 'NMS:B'])).toEqual(['NMS:A', 'NMS:B', 'MPAINV:1'])
  })
  it('refuses a list over the limit rather than cutting it', () => {
    expect(() => chooseIds(ix, ['X:1'], { limit: 2 })).toThrow(/--limit 2/)
  })
  it('splits a comma or space separated list and refuses ids that are not folder names', () => {
    expect(splitIds('NMS:A, NMS:B  X:1')).toEqual(['NMS:A', 'NMS:B', 'X:1'])
    expect(splitIds(undefined)).toEqual([])
    expect(shellFolder('NMS:CINMS')).toBe('NMS:CINMS')
    for (const bad of ['', '..', 'a/b', 'a\\b']) expect(shellFolder(bad)).toBeNull()
  })
})

describe('the router meets a shell\'s folder url', () => {
  it('accepts the trailing slash GitHub Pages redirects to, with and without the app base', () => {
    expect(matchRoute('/places/p/NMS:CINMS/', '/places')).toEqual({ name: 'place', id: 'NMS:CINMS' })
    expect(matchRoute('/places/p/NMS%3ACINMS/', '/places')).toEqual({ name: 'place', id: 'NMS:CINMS' })
    expect(matchRoute('/p/NMS:CINMS/')).toEqual({ name: 'place', id: 'NMS:CINMS' })
    expect(matchRoute('/places/l/boem_wind_leases/', '/places')).toEqual({ name: 'layer', slug: 'boem_wind_leases' })
    expect(matchRoute('/places/credits/', '/places')).toEqual({ name: 'credits' })
    expect(matchRoute('/places/docs/', '/places')).toEqual({ name: 'docs' })
  })
})
