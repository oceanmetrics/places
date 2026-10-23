// the pure parts of the link-preview shells (scripts/prerender-shells.mjs): titles, descriptions, JSON-LD, the head rewrite.
// no I/O here, so src/lib/shells.test.ts can assert them on synthetic rows. README "Deep links and link previews".

export const SITE_NAME = 'Ocean Metrics'
export const SITE_ORIGIN = 'https://oceanmetrics.io'

/** text for an HTML element or a double- or single-quoted attribute. */
export const esc = (s) =>
  String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

/** the tab title of a Place page; the app sets the same string once it has mounted (Place.svelte). */
export const placeTitle = (name) => `${name} · Places · ${SITE_NAME}`
/** the tab title of a layer page. */
export const layerPageTitle = (title) => `${title} · Places · ${SITE_NAME}`

const words = (s) => String(s ?? '').replace(/_/g, ' ').trim()

/** the credit without the shared "Processed by Ocean Metrics." tail: "NOAA Office of National Marine Sanctuaries". */
export function creditOf(attribution) {
  return String(attribution ?? '').replace(/\s*Processed by Ocean Metrics\.?\s*$/i, '').replace(/\.\s*$/, '').trim()
}

/** the authority to name: the layer's, else the credit's first sentence, else the index row's code (NMS). */
export function authorityName(place, layer) {
  return layer?.authority || creditOf(place?.attribution || layer?.attribution) || place?.authority || ''
}

const kmFmt = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 })

/** one sentence for the description meta and the preview card: what the place is, where it is listed, who publishes it. */
export function placeDescription(place, layer) {
  const kind = words(place.place_type) || 'place'
  const article = /^[aeiou]/i.test(kind) ? 'an' : 'a'
  const where = layer?.title ? ` in ${layer.title}` : ''
  const auth = authorityName(place, layer)
  const area = place.area_km2 != null && Number.isFinite(Number(place.area_km2)) && Number(place.area_km2) > 0 ? ` (${kmFmt.format(Number(place.area_km2))} km²)` : ''
  return `${place.name} (${place.place_id}) is ${article} ${kind}${area}${where}${auth ? `, from ${auth}` : ''}. Its boundary, indicators, species and the layers that cover it, in the ${SITE_NAME} marine gazetteer.`
}

export function layerDescription(layer) {
  const auth = layer.authority || creditOf(layer.attribution)
  const n = layer.n != null ? `${kmFmt.format(layer.n)} ${words(layer.place_type) || 'place'}${layer.n === 1 ? '' : 's'}` : 'places'
  const lic = layer.license ? `, licence ${layer.license}` : ''
  return `${layer.title}: ${n}${auth ? ` from ${auth}` : ''}${lic}. Browse the layer, its credit and its data in the ${SITE_NAME} marine gazetteer.`
}

const wrapLon = (x) => (x > 180 ? x - 360 : x < -180 ? x + 360 : x)

/** schema.org GeoShape box is "south west north east" (lat lon lat lon); an unwrapped index bbox (east beyond 180) is wrapped back. */
export function geoBox(bbox) {
  if (!Array.isArray(bbox) || bbox.length !== 4 || bbox.some((x) => !Number.isFinite(Number(x)))) return null
  const [w, s, e, n] = bbox.map(Number)
  return `${s} ${wrapLon(w)} ${n} ${wrapLon(e)}`
}

/** JSON-LD for a place: schema.org Place with name, identifier, url and geo as a GeoShape box. */
export function placeJsonLd(place, url) {
  const box = geoBox(place.bbox)
  return {
    '@context': 'https://schema.org',
    '@type': 'Place',
    name: place.name,
    identifier: place.place_id,
    url,
    ...(box ? { geo: { '@type': 'GeoShape', box } } : {}),
  }
}

/** JSON-LD for a layer page: a schema.org Dataset. */
export function layerJsonLd(layer, url) {
  const box = geoBox(layer.bbox)
  return {
    '@context': 'https://schema.org',
    '@type': 'Dataset',
    name: layer.title,
    identifier: layer.slug,
    url,
    ...(layer.license_url || layer.license ? { license: layer.license_url || layer.license } : {}),
    ...(box ? { spatialCoverage: { '@type': 'Place', geo: { '@type': 'GeoShape', box } } } : {}),
  }
}

/** JSON inside a <script>: a "<" is escaped so no name can close the element or open a comment. */
export const jsonScript = (obj) => JSON.stringify(obj).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026')

/** the page's absolute url: origin + app base ('/places/') + path ('p/NMS:CINMS/'). */
export const pageUrl = (origin, base, path) => `${origin.replace(/\/+$/, '')}/${(base + path).replace(/^\/+/, '')}`

/**
 * the built index.html with this page's head: title, description, canonical, Open Graph, Twitter card, JSON-LD.
 * throws when index.html has no <title> or description meta (the template moved).
 * @param {string} html
 * @param {{ title: string, description: string, url: string, image: string, jsonld?: object | null, type?: string }} page
 */
export function renderShell(html, { title, description, url, image, jsonld = null, type = 'website' }) {
  const titleRe = /<title>[\s\S]*?<\/title>/
  const descRe = /<meta name="description"[^>]*>/
  if (!titleRe.test(html) || !descRe.test(html)) throw new Error('index.html has no <title> or <meta name="description">: the shell template changed')
  const tags = [
    `<link rel="canonical" href="${esc(url)}" />`,
    `<meta property="og:site_name" content="${esc(SITE_NAME)} Places" />`,
    `<meta property="og:type" content="${esc(type)}" />`,
    `<meta property="og:title" content="${esc(title)}" />`,
    `<meta property="og:description" content="${esc(description)}" />`,
    `<meta property="og:url" content="${esc(url)}" />`,
    `<meta property="og:image" content="${esc(image)}" />`,
    `<meta name="twitter:card" content="summary" />`,
    `<meta name="twitter:title" content="${esc(title)}" />`,
    `<meta name="twitter:description" content="${esc(description)}" />`,
    `<meta name="twitter:image" content="${esc(image)}" />`,
    ...(jsonld ? [`<script type="application/ld+json">${jsonScript(jsonld)}</script>`] : []),
  ].map((t) => `    ${t}`).join('\n')
  // function replacers: the text holds "$&"-like sequences a string replacement would expand
  return html
    .replace(titleRe, () => `<title>${esc(title)}</title>\n${tags}`)
    .replace(descRe, () => `<meta name="description" content="${esc(description)}" />`)
}

/** the folder name of a shell under dist/p or dist/l, or null when the id cannot be one (a slash, "..", empty). */
export function shellFolder(id) {
  const s = String(id ?? '')
  return !s || s === '.' || s === '..' || /[\/\\\0]/.test(s) ? null : s
}

/** the app base ('/places/') the built index.html was made for, read from its module script. */
export function baseOfIndex(html) {
  const m = /<script[^>]*type="module"[^>]*src="([^"]*?)assets\//.exec(html)
  return m ? m[1] : null
}

/** the ids to render: the sanctuaries (`NMS:` rows of the index), then --ids / PRERENDER_IDS; a guard against a runaway list. */
export function chooseIds(indexIds, extra, { prefix = 'NMS:', limit = 100 } = {}) {
  const all = [...new Set([...indexIds.filter((i) => i.startsWith(prefix)), ...extra])]
  if (all.length > limit) throw new Error(`${all.length} places to render is more than --limit ${limit}: raise --limit on purpose`)
  return all
}

/** "a,b c" -> ['a', 'b', 'c'] */
export const splitIds = (s) => String(s ?? '').split(/[\s,]+/).filter(Boolean)
