// screenshots of the home page (docs/shots/home_<width>_<theme>.png, with the shared bar's menu open at 390 px: home_390_<theme>_menu.png)
// and of the place page with the live catalogs: each place at 390 px and 1280 px, light and dark, in two parts:
// the top of the page (title, map with its layer, the start of Indicators) -> docs/shots/place_<id>_<width>_<theme>.png,
// and the sections after Indicators (Species, Layers, Reports) -> place_<id>_<width>_<theme>_sections.png. look at them.
//   node scripts/shoot.mjs [--url http://localhost:5180/] [--only NMS:CINMS | --only home] [--out docs/shots]
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
// the CPO task force's two sanctuaries (2026-11-16); CINMS with the layer under the map at a period
const PLACES = [
  { id: 'NMS:CINMS', query: '?layer=grid:jplMURSST41mday:sst&t=2024-07' },
  { id: 'NMS:FGBNMS', query: '' },
]
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
  for (const width of ONLY && ONLY !== 'home' ? [] : WIDTHS) {
    for (const theme of THEMES) {
      const ctx = await b.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1, colorScheme: theme, isMobile: width < 600, hasTouch: width < 600 })
      await ctx.addInitScript((t) => { try { localStorage.setItem('om-theme', t) } catch { /* no storage */ } }, theme)
      const page = await ctx.newPage()
      await page.goto(url, { waitUntil: 'domcontentloaded' })
      await page.waitForFunction(() => document.querySelector('om-nav')?.shadowRoot?.querySelector('[part=bar]') && document.querySelector('.home input#q') && !document.querySelector('.loading'), null, { timeout: 120000 })
      await page.waitForTimeout(2500)
      const scrollW = await page.evaluate(() => document.documentElement.scrollWidth)
      if (scrollW > width) console.warn(`  home ${width}px ${theme}: page is ${scrollW}px wide (horizontal overflow)`)
      const shot = resolve(OUT, `home_${width}_${theme}.png`)
      await page.screenshot({ path: shot })
      saved.push(relative(process.cwd(), shot))
      if (width < 600) {
        await page.locator('om-nav').locator('[part=menu]').click()
        await page.waitForTimeout(400)
        const menu = resolve(OUT, `home_${width}_${theme}_menu.png`)
        await page.screenshot({ path: menu })
        saved.push(relative(process.cwd(), menu))
      }
      await ctx.close()
    }
  }
  for (const { id, query } of PLACES.filter((p) => !ONLY || p.id === ONLY)) {
    for (const width of WIDTHS) {
      for (const theme of THEMES) {
        const ctx = await b.newContext({ viewport: { width, height: 900 }, deviceScaleFactor: 1, colorScheme: theme, isMobile: width < 600, hasTouch: width < 600 })
        await ctx.addInitScript((t) => { try { localStorage.setItem('om-theme', t) } catch { /* no storage */ } }, theme)
        const page = await ctx.newPage()
        await page.goto(`${url}p/${id}${query}`, { waitUntil: 'domcontentloaded' })
        // every section has finished loading (no `.loading` note left), the layer's slice is in (or said why not), and the
        // map has had time to draw
        await page.waitForFunction(() => document.querySelector('section.indicators') && !document.querySelector('.loading'), null, { timeout: 120000 })
        if (query.includes('layer=')) await page.waitForFunction(() => { const l = document.querySelector('.legend'); return l && !/loading the slice/.test(l.textContent ?? '') }, null, { timeout: 120000 })
        await page.waitForTimeout(2500)
        const base = `place_${id.replace(/[^\w.-]+/g, '_')}_${width}_${theme}`
        // the top: the window is made as tall as the page down to the first row of cards (the map redraws at its real
        // size, which a full-page capture of a short window does not give it), then shot as it is
        const card = await page.locator('section.indicators article').first().boundingBox()
        const ind = await page.locator('section.indicators').boundingBox()
        const end = card ? card.y + card.height : (ind?.y ?? 0) + Math.min(ind?.height ?? 900, 400)
        await page.setViewportSize({ width, height: Math.ceil(end + 16) })
        await page.waitForTimeout(2000)
        const scrollW = await page.evaluate(() => document.documentElement.scrollWidth)
        if (scrollW > width) console.warn(`  ${id} ${width}px ${theme}: page is ${scrollW}px wide (horizontal overflow)`)
        const top = resolve(OUT, `${base}.png`)
        await page.screenshot({ path: top })
        // the sections after Indicators: from the Species heading to the end of Reports
        const from = await page.locator('#species-h').boundingBox()
        const to = await page.locator('#reports-h').locator('..').boundingBox()
        if (from && to) {
          const y0 = Math.floor(from.y - 8), y1 = Math.ceil(to.y + to.height + 8)
          const more = resolve(OUT, `${base}_sections.png`)
          await page.screenshot({ path: more, fullPage: true, clip: { x: 0, y: y0, width, height: y1 - y0 } })
          saved.push(relative(process.cwd(), more))
        }
        saved.push(relative(process.cwd(), top))
        await ctx.close()
      }
    }
  }
} finally {
  await b.close()
  stop()
}
for (const f of saved) console.log(f)
