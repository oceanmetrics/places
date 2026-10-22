// screenshots of the place page with the live catalogs: each place at 390 px and 1280 px, light and dark, from the top of
// the page to the end of the Indicators section -> docs/shots/place_<id>_<width>_<theme>.png. look at them.
//   node scripts/shoot.mjs [--url http://localhost:5180/] [--only NMS:CINMS] [--out docs/shots]
// without --url it serves dist/ with `vite preview` (run `npm run build` first). headless Chrome through Playwright: the
// installed Google Chrome (channel "chrome"), else Playwright's own chromium (`npx playwright install chromium`).
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : d }
const OUT = resolve(ROOT, arg('--out', 'docs/shots'))
const ONLY = arg('--only', '')
const PLACES = ['NMS:CINMS', 'MRGID:8439']   // a sanctuary with status cards; an EEZ with OBIS series (no status rule) and SDG
const WIDTHS = [390, 1280]
const THEMES = ['light', 'dark']
const PORT = 4173

const answers = async (url) => { try { return (await fetch(url)).ok } catch { return false } }

async function server() {
  const given = arg('--url', '')
  if (given) return { url: given.endsWith('/') ? given : given + '/', stop: () => {} }
  if (!existsSync(resolve(ROOT, 'dist/index.html'))) throw new Error('no dist/: run `npm run build` first, or pass --url')
  const p = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], { cwd: ROOT, stdio: 'ignore' })
  const url = `http://localhost:${PORT}/`
  for (let i = 0; i < 60 && !(await answers(url)); i++) await new Promise((r) => setTimeout(r, 250))
  if (!(await answers(url))) { p.kill(); throw new Error(`vite preview did not answer on ${url}`) }
  return { url, stop: () => p.kill() }
}

async function browser() {
  try { return await chromium.launch({ channel: 'chrome' }) } catch { return chromium.launch() }
}

const { url, stop } = await server()
const b = await browser()
mkdirSync(OUT, { recursive: true })
const saved = []
try {
  for (const id of PLACES.filter((p) => !ONLY || p === ONLY)) {
    for (const width of WIDTHS) {
      for (const theme of THEMES) {
        const ctx = await b.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1, colorScheme: theme, isMobile: width < 600, hasTouch: width < 600 })
        await ctx.addInitScript((t) => { try { localStorage.setItem('om-theme', t) } catch { /* no storage */ } }, theme)
        const page = await ctx.newPage()
        await page.goto(`${url}p/${id}`, { waitUntil: 'domcontentloaded' })
        // the section has finished loading (cards, an absence or an error), and the map has had time to draw
        await page.waitForFunction(() => { const s = document.querySelector('section.indicators'); return s && !s.querySelector('[aria-live]') }, null, { timeout: 60000 })
        await page.waitForTimeout(2500)
        // the window is made as tall as the page down to the end of the section (the map redraws at its real size, which a
        // full-page capture of a short window does not give it), then shot as it is
        const box = await page.locator('section.indicators').boundingBox()
        await page.setViewportSize({ width, height: Math.ceil((box?.y ?? 0) + (box?.height ?? 900) + 16) })
        await page.waitForTimeout(2000)
        const scrollW = await page.evaluate(() => document.documentElement.scrollWidth)
        if (scrollW > width) console.warn(`  ${id} ${width}px ${theme}: page is ${scrollW}px wide (horizontal overflow)`)
        const file = resolve(OUT, `place_${id.replace(/[^\w.-]+/g, '_')}_${width}_${theme}.png`)
        await page.screenshot({ path: file })
        saved.push(relative(process.cwd(), file))
        await ctx.close()
      }
    }
  }
} finally {
  await b.close()
  stop()
}
for (const f of saved) console.log(f)
