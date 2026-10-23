// the site's size budget: gzip sizes (level 9) of the built JS and CSS by what loads when (README "Size budget"). raise a
// line only with the reason written in the README. chunks are told apart by Vite's manifest (build.manifest): a chunk
// belongs to a lazy root when only that root's static imports reach it.
//   entry JS   what index.html loads up front (its module script and modulepreloads): the router, the pages, the places
//              client with hyparquet and its codecs, the indicator cards
//   map JS     PlacesMap.svelte's chunk and what only it reaches: MapLibre 6, @oceanmetrics/map, the basemap and the slot
//   engine JS  map/gridSource.ts's chunk (on the first slice of a layer under the map): @oceanmetrics/engine, Apache Arrow,
//              the mask, DuckDB-WASM's JS API
//   rest JS    the other lazy chunks: the species reader, the values download (hyparquet-writer)
// outside every line, and printed: DuckDB-WASM's worker scripts and wasm (fetched by the engine's worker), MapLibre's
// worker (.mjs), and geotiff's decoders that @oceanmetrics/map's COG protocol would import (never: no cog slot here).
//   node scripts/size-budget.mjs      (after npm run build)
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { gzipSync } from 'node:zlib'

const DIST = new URL('../dist/assets/', import.meta.url).pathname
// set 2026-10-23 from a measurement (entry 155.7, map 299.3, engine 63.2, rest 17.8, CSS 3.5, map CSS 10.4 kB) with about 10 % headroom
const BUDGET = { jsEntry: 172_000, jsMap: 330_000, jsEngine: 70_000, jsRest: 24_000, css: 5_000, cssMap: 12_000 }   // bytes, gzip

const files = readdirSync(DIST)
const manifest = JSON.parse(readFileSync(join(DIST, '..', '.vite', 'manifest.json'), 'utf8'))
const fileOf = (k) => manifest[k].file.replace(/^assets\//, '')
const closure = (k, seen = new Set()) => { if (seen.has(k) || !manifest[k]) return seen; seen.add(k); for (const i of manifest[k].imports ?? []) closure(i, seen); return seen }
const roots = Object.keys(manifest).filter((k) => manifest[k].isEntry || manifest[k].isDynamicEntry)
const reachedBy = new Map()
for (const r of roots) for (const k of closure(r)) { const f = fileOf(k); reachedBy.set(f, [...(reachedBy.get(f) ?? []), r]) }
const cssOf = new Map()
for (const r of roots) for (const k of closure(r)) for (const c of manifest[k].css ?? []) { const f = c.replace(/^assets\//, ''); cssOf.set(f, [...(cssOf.get(f) ?? []), r]) }
const onlyFrom = (test, by = reachedBy) => (f) => { const rs = by.get(f) ?? []; return rs.length > 0 && rs.every(test) }
const isMap = onlyFrom((r) => r.endsWith('src/lib/PlacesMap.svelte'))
const isEngine = onlyFrom((r) => r.endsWith('src/lib/map/gridSource.ts'))
const isCog = onlyFrom((r) => /maplibre-cog-protocol|geotiff/.test(r))
const isDuck = (f) => f.startsWith('duckdb-')
const gz = (f) => gzipSync(readFileSync(join(DIST, f)), { level: 9 }).length
const all = files.filter((f) => f.endsWith('.js')).map((f) => ({ f, gz: gz(f) }))
const outside = all.filter((x) => isDuck(x.f) || isCog(x.f))
const js = all.filter((x) => !outside.includes(x))
const css = files.filter((f) => f.endsWith('.css')).map((f) => ({ f, gz: gz(f) }))
const sum = (xs) => xs.reduce((s, x) => s + x.gz, 0)
const html = readFileSync(join(DIST, '..', 'index.html'), 'utf8')
const upfront = new Set([...html.matchAll(/(?:src|href)="[^"]*\/assets\/([^"/]+\.js)"/g)].map((m) => m[1]))
if (!upfront.size) throw new Error('size budget: found no script in dist/index.html')
const isMapCss = onlyFrom((r) => r.endsWith('src/lib/PlacesMap.svelte'), cssOf)
const rows = [
  ['entry JS', sum(js.filter((x) => upfront.has(x.f))), BUDGET.jsEntry],
  ['map JS', sum(js.filter((x) => isMap(x.f) && !upfront.has(x.f))), BUDGET.jsMap],
  ['engine JS', sum(js.filter((x) => isEngine(x.f))), BUDGET.jsEngine],
  ['rest JS', sum(js.filter((x) => !upfront.has(x.f) && !isMap(x.f) && !isEngine(x.f))), BUDGET.jsRest],
  ['CSS', sum(css.filter((x) => !isMapCss(x.f))), BUDGET.css],
  ['map CSS', sum(css.filter((x) => isMapCss(x.f))), BUDGET.cssMap],
]
let over = false
for (const [name, got, max] of rows) {
  const ok = got <= max
  over ||= !ok
  console.log(`${ok ? 'ok  ' : 'OVER'} ${name.padEnd(10)} ${(got / 1000).toFixed(1).padStart(6)} kB gzip (budget ${max / 1000} kB)`)
}
const kb = (n) => `${(n / 1000).toFixed(1)} kB`
const wasm = files.filter((f) => f.endsWith('.wasm'))
const workers = files.filter((f) => f.endsWith('.mjs'))
console.log(`     (not budgeted) DuckDB-WASM workers ${kb(sum(outside.filter((x) => isDuck(x.f))))} gzip, wasm ${wasm.map((f) => `${f.split('-').slice(0, 2).join('-')} ${kb(gz(f))}`).join(', ')} gzip; ` +
  `MapLibre worker (.mjs) ${kb(workers.reduce((s, f) => s + gz(f), 0))}; COG decoders ${kb(sum(outside.filter((x) => isCog(x.f))))} (never requested); raw wasm ${kb(wasm.reduce((s, f) => s + statSync(join(DIST, f)).size, 0))}`)
process.exit(over ? 1 : 0)
