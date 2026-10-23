// writes a shell per deep link into dist/ after `vite build`: the built index.html with the page's own <title>, description,
// Open Graph / Twitter tags, canonical and JSON-LD, so GitHub Pages answers 200 (not the 404.html fallback) and crawlers and chat
// link previews read something. The app mounts as usual over the shell. README "Deep links and link previews".
//   node scripts/prerender-shells.mjs [--ids=NMS:X,MPAINV:Y] [--limit=100] [--data=<gazetteer url>] [--origin=https://oceanmetrics.io] [--dist=dist]
//   env: PRERENDER_IDS (more ids, comma or space separated), PRERENDER_BASE, PRERENDER_ORIGIN, PRERENDER_SKIP=1 (build offline, no shells)
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { createClient } from '@oceanmetrics/places'
import {
  baseOfIndex, chooseIds, layerDescription, layerJsonLd, layerPageTitle, pageUrl, placeDescription, placeJsonLd, placeTitle,
  renderShell, shellFolder, splitIds, SITE_NAME, SITE_ORIGIN,
} from './shell-lib.mjs'

const arg = (k) => process.argv.find((a) => a.startsWith(`--${k}=`))?.slice(k.length + 3)
if (process.env.PRERENDER_SKIP === '1') { console.log('prerender-shells: skipped (PRERENDER_SKIP=1)'); process.exit(0) }

const DIST   = resolve(arg('dist') ?? new URL('../dist', import.meta.url).pathname)
const BASE   = arg('data') ?? process.env.PRERENDER_BASE ?? 'https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/'
const ORIGIN = arg('origin') ?? process.env.PRERENDER_ORIGIN ?? SITE_ORIGIN
const LIMIT  = Number(arg('limit') ?? process.env.PRERENDER_LIMIT ?? 100)
const EXTRA  = [...splitIds(arg('ids')), ...splitIds(process.env.PRERENDER_IDS)]

const html = readFileSync(join(DIST, 'index.html'), 'utf8')
const appBase = baseOfIndex(html)
if (appBase == null) throw new Error(`${DIST}/index.html: no module script under assets/; run vite build first`)
const image = pageUrl(ORIGIN, appBase, 'favicon.svg')   // the only image in web/public; an SVG preview image shows in few chat apps (README)

const write = (rel, shell) => {
  const file = join(DIST, rel, 'index.html')
  mkdirSync(join(DIST, rel), { recursive: true })
  writeFileSync(file, shell)
}

const client = createClient({ base: BASE })
const [index, layers] = await Promise.all([client.loadIndex(), client.listLayers()])
const byCollection = new Map(layers.map((l) => [l.collection, l]))
const byId = new Map()
for (const p of index) if (!byId.has(p.place_id)) byId.set(p.place_id, p)   // the first copy is the agency's own layer

const ids = chooseIds([...byId.keys()], EXTRA, { limit: LIMIT })
if (!ids.some((i) => i.startsWith('NMS:'))) throw new Error(`no NMS: places in the index at ${BASE}: refusing to publish without the sanctuaries`)

let nPlaces = 0
for (const id of ids) {
  const place = byId.get(id), folder = shellFolder(id)
  if (!place || !folder) { console.warn(`prerender-shells: skipped ${id} (${place ? 'not a usable folder name' : 'not in the index'})`); continue }
  const url = pageUrl(ORIGIN, appBase, `p/${folder}/`)
  write(`p/${folder}`, renderShell(html, {
    title: placeTitle(place.name), description: placeDescription(place, byCollection.get(place.collection)), url, image, jsonld: placeJsonLd(place, url),
  }))
  nPlaces++
}

let nLayers = 0
for (const l of layers) {
  const folder = shellFolder(l.slug)
  if (!folder) continue
  const url = pageUrl(ORIGIN, appBase, `l/${folder}/`)
  write(`l/${folder}`, renderShell(html, { title: layerPageTitle(l.title), description: layerDescription(l), url, image, jsonld: layerJsonLd(l, url) }))
  nLayers++
}

for (const [path, name, text] of [
  ['credits', 'Credits', 'The sources, licences and credits of the layers in the marine gazetteer.'],
  ['docs', 'Docs', 'How to search, cite and reuse the Ocean Metrics marine gazetteer.'],
]) {
  write(path, renderShell(html, { title: `${name} · ${SITE_NAME} marine gazetteer`, description: `${text}`, url: pageUrl(ORIGIN, appBase, `${path}/`), image }))
}

console.log(`prerender-shells: ${nPlaces} places, ${nLayers} layers, credits and docs under ${DIST} (app base ${appBase}, data ${BASE})`)
