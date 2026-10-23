// the analytics check of a build (@oceanmetrics/nav README "Analytics"): no page ships a gtag.js script tag (only the
// bar's data-ga adds one, at run time), and a measurement id is in the build exactly when one was given.
//   node scripts/check-ga.mjs [dist] [--id G-XXXXXXXXXX]      (no --id, or an empty one: no id may be anywhere)
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative } from 'node:path'

const ID_RE = /\bG-[A-Z0-9]{6,16}\b/g
const TAG_RE = /<script[^>]*googletagmanager\.com/i
const LOADER = 'googletagmanager.com/gtag/js?id='

const walk = (dir) => readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? walk(join(dir, e.name)) : [join(dir, e.name)])

/** the problems of the build in `dist` for the id `id` ('' = analytics off); an empty list is a pass */
export function checkGa(dist, id = '') {
  const problems = [], ids = new Set()
  let loader = false
  for (const f of walk(dist).filter((f) => /\.(html?|m?js)$/.test(f))) {
    const s = readFileSync(f, 'utf8')
    if (/\.html?$/.test(f) && TAG_RE.test(s)) problems.push(`${relative(dist, f)}: a gtag.js script tag in the page`)
    for (const m of s.matchAll(ID_RE)) ids.add(m[0])
    loader ||= s.includes(LOADER)
  }
  const stray = [...ids].filter((x) => x !== id).sort()
  if (stray.length) problems.push(`a measurement id that was not given: ${stray.join(', ')}`)
  if (id && !ids.has(id)) problems.push(`the given id ${id} is not in the build`)
  if (id && !loader) problems.push('the bar in the build has no analytics loader (@oceanmetrics/nav >= 0.2.0)')
  return problems
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const i = process.argv.indexOf('--id')
  const id = (i > 0 ? process.argv[i + 1] ?? '' : '').trim()
  const dist = process.argv[2] && !process.argv[2].startsWith('--') ? process.argv[2] : 'dist'
  const problems = checkGa(dist, id)
  for (const p of problems) console.error(`check-ga: ${p}`)
  console.log(problems.length ? 'check-ga: FAIL' : `check-ga: ok (${id ? `id ${id} present, no script tag in the pages` : 'off: no id, no script tag'})`)
  process.exit(problems.length ? 1 : 0)
}
