// the analytics privacy check in a real browser (the atlas's e2e/fixtures/analytics-privacy, for this app): the built
// app is opened with a place polygon, a report title and a search in its url, moved by pushState, replaceState and the
// hash, and every gtag() call and every request must stay clean of them. gtag.js itself is never fetched: every request
// off this origin is aborted, so the check is hermetic. GA4's "page changes based on browser history events" setting
// is outside any code (@oceanmetrics/nav README "Analytics").
//   node scripts/ga-e2e.mjs --id G-TEST000000    (after a build with VITE_GA_ID=G-TEST000000: the tag, anonymize_ip)
//   node scripts/ga-e2e.mjs                      (after a build without it: no tag, no dataLayer)
//   [--url http://localhost:4173/] [--path /] [--keep view]   (default: `vite preview` of dist/ on 4173)
import { spawn } from 'node:child_process'
import { chromium } from 'playwright'

const arg = (k, d) => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] ?? d : d }
const ID = arg('--id', '')
const PATH = arg('--path', '/')
const KEEP = arg('--keep', '').split(',').filter(Boolean)   // the bar's data-ga-keep, if the app sets one
const PORT = 4173
const FORBIDDEN = ['pl=', 'g1.', 'AAAA', 'secret', 'my+search', 'my%20search']
const DIRTY = '?q=my+search&t=secret#view=report&pl=g1.test.AAAA&t=secret&title=My+secret+report'

const answers = async (url) => { try { return (await fetch(url)).ok } catch { return false } }
async function server() {
  const given = arg('--url', '')
  if (given) return { url: given.replace(/\/?$/, '/'), stop: () => {} }
  const p = spawn('npx', ['vite', 'preview', '--port', String(PORT), '--strictPort'], { stdio: 'ignore' })
  const url = `http://localhost:${PORT}/`
  for (let i = 0; i < 80 && !(await answers(url)); i++) await new Promise((r) => setTimeout(r, 250))
  if (!(await answers(url))) { p.kill(); throw new Error(`vite preview did not answer on ${url}`) }
  return { url, stop: () => p.kill() }
}

const fails = []
const check = (ok, what) => { console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`); if (!ok) fails.push(what) }
const clean = (label, text) => { for (const t of FORBIDDEN) check(!text.includes(t), `${label} carries no "${t}"`) }

const srv = await server()
const browser = await chromium.launch({ channel: 'chrome' }).catch(() => chromium.launch())
try {
  const page = await browser.newPage()
  const origin = new URL(srv.url).origin, offsite = []
  await page.route('**/*', (route) => {
    const r = route.request()
    if (r.url().startsWith(origin)) return route.continue()
    offsite.push(`${r.url()} ${r.postData() ?? ''}`)
    return route.abort()
  })
  const start = new URL(PATH.replace(/^\//, ''), srv.url).href + DIRTY
  await page.goto(start, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('om-nav', { state: 'attached', timeout: 20_000 })
  await page.waitForTimeout(1500)
  const tags = () => page.$$eval('script[src*="googletagmanager.com"]', (s) => s.map((x) => x.src))
  const layer = () => page.evaluate(() => JSON.stringify((window.dataLayer ?? []).map((a) => Array.from(a))))
  if (!ID) {
    check((await tags()).length === 0, 'no gtag.js script tag on the page')
    check(await page.evaluate(() => window.dataLayer === undefined), 'no dataLayer')
    check(!offsite.some((u) => /google-analytics|googletagmanager|analytics\.google/.test(u)), 'no request to a GA host')
  } else {
    check(JSON.stringify(await tags()) === JSON.stringify([`https://www.googletagmanager.com/gtag/js?id=${ID}`]), `one gtag.js script tag for ${ID}`)
    await page.evaluate(() => {
      history.pushState(null, '', location.pathname.replace(/\/?$/, '/') + 'next' + '?q=my+search&t=secret#pl=g1.test.BAAAA&t=secret')
      history.replaceState(null, '', location.pathname + '?t=secret#pl=g1.test.CAAAA')
      location.hash = '#pl=g1.test.DAAAA&t=secret'
    })
    await page.waitForTimeout(300)
    const calls = JSON.parse(await layer())
    const config = calls.find((c) => c[0] === 'config')
    check(config?.[1] === ID, 'gtag config for the id')
    check(config?.[2]?.anonymize_ip === true, 'anonymize_ip: true')
    check(config?.[2]?.allow_google_signals === false && config?.[2]?.allow_ad_personalization_signals === false, 'no Google signals, no ad personalization')
    check(config?.[2]?.send_page_view === false, "send_page_view: false (gtag.js sends no page_view of its own)")
    const views = calls.filter((c) => c[0] === 'event' && c[1] === 'page_view').map((c) => c[2].page_location)
    console.log('     page_view locations:', views.join(' | '))
    check(views.length >= 2, 'a page_view on load and one on the history change')
    check(views.every((v) => !v.includes('#') && [...new URL(v).searchParams.keys()].every((k) => KEEP.includes(k))),
      `no page_location holds a fragment, or a query key but the kept ones (${KEEP.join(',') || 'none'})`)
    clean('every gtag() call', JSON.stringify(calls))
  }
  clean('every request off this origin', offsite.join('\n'))
} finally {
  await browser.close()
  srv.stop()
}
console.log(fails.length ? `ga-e2e: ${fails.length} FAILED` : 'ga-e2e: ok')
process.exit(fails.length ? 1 : 0)
