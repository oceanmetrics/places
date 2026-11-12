// folder listings: a folder URL with no stored index.html lists the bucket under it ----
import { PUBLIC_PREFIXES, ROOT_FILES, type Store } from './paths'

/** R2's page limit; one listing page holds at most this many folders plus objects */
export const LIST_LIMIT = 1000

/** a listing's response header */
export const LISTING_CACHE_CONTROL = 'public, max-age=60'

/** one object row of a listing; `key` is the request path without the leading `/` (`unlisted/` prefixed for the
 *  unlisted bucket), so `https://storage.oceanmetrics.io/<key>` reads it */
export interface ListedObject { key: string, size: number, uploaded: string, etag: string }

/** the JSON body of a listing: `folders` are names relative to `prefix` ending in `/`, sorted; `objects` sorted by key;
 *  `cursor` the next page's `?cursor=`, null on the last page */
export interface Listing { prefix: string, folders: string[], objects: ListedObject[], cursor: string | null }

/** the bad cursor error, so the caller answers 400 instead of 500 */
export class BadCursor extends Error {}

/** list one page under `folder` (an R2 prefix ending in `/`, or `''` for the bucket root). At the root only the served
 *  prefixes and root files appear (never `backups/` or another unserved key); a folder marker object (key = prefix) is
 *  left out. */
export async function listFolder(bucket: R2Bucket, store: Store, folder: string, cursor: string | null,
  limit: number = LIST_LIMIT): Promise<Listing> {
  let page: R2Objects
  try {
    page = await bucket.list({ prefix: folder, delimiter: '/', limit, ...(cursor ? { cursor } : {}) })
  } catch (e) {
    if (cursor) throw new BadCursor(String(e))
    throw e
  }
  const root    = store === 'public' && folder === ''
  const urlBase = store === 'unlisted' ? 'unlisted/' : ''
  const folders = page.delimitedPrefixes
    .map(p => p.slice(folder.length))
    .filter(n => n !== '/' && (!root || PUBLIC_PREFIXES.includes(n.slice(0, -1))))
    .sort()
  const objects = page.objects
    .filter(o => o.key !== folder && (!root || ROOT_FILES.includes(o.key)))
    .sort((a, b) => a.key < b.key ? -1 : a.key > b.key ? 1 : 0)
    .map(o => ({ key: urlBase + o.key, size: o.size, uploaded: o.uploaded.toISOString(), etag: o.etag }))
  return { prefix: urlBase + folder, folders, objects, cursor: page.truncated ? page.cursor : null }
}

/** JSON when asked by `?format=json` or by an Accept that names application/json and not text/html (a browser's
 *  Accept names text/html, so it gets the page); `?format=html` forces the page */
export function wantsJson(request: Request, url: URL): boolean {
  const f = url.searchParams.get('format')
  if (f === 'json') return true
  if (f === 'html') return false
  const accept = (request.headers.get('accept') ?? '').toLowerCase()
  return accept.includes('application/json') && !accept.includes('text/html')
}

const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')

/** a relative link to a name under the current folder: each segment percent-encoded (a `:` or `?` in a name can never
 *  turn into a scheme or a query) */
const rel = (name: string): string => name.split('/').map(encodeURIComponent).join('/')

/** the plain HTML page of a listing: one table, relative links, a `..` link (not at the root or the top of
 *  `/unlisted/gazetteer/`), a next-page link by `?cursor=` only (never `?key=` or another query parameter), the title
 *  the prefix, the footer naming the Worker and the page cursor */
export function listingHtml(l: Listing, cursor: string | null): string {
  const title = `/${l.prefix}`
  const top   = l.prefix === '' || l.prefix === 'unlisted/gazetteer/'
  const rows: string[] = []
  if (!top) rows.push('<tr><td><a href="../">..</a></td><td></td><td></td><td></td></tr>')
  for (const f of l.folders) rows.push(`<tr><td><a href="${esc(rel(f))}">${esc(f)}</a></td><td></td><td></td><td></td></tr>`)
  for (const o of l.objects) {
    const name = o.key.slice(l.prefix.length)
    rows.push(`<tr><td><a href="${esc(rel(name))}">${esc(name)}</a></td><td class="n">${o.size.toLocaleString('en-US')}</td>` +
      `<td>${esc(o.uploaded)}</td><td><code>${esc(o.etag)}</code></td></tr>`)
  }
  if (l.folders.length === 0 && l.objects.length === 0) rows.push('<tr><td colspan="4">(empty)</td></tr>')
  const next = l.cursor ? `<p><a href="?cursor=${esc(encodeURIComponent(l.cursor))}">next page</a></p>\n` : ''
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>
body { font: 14px/1.45 system-ui, sans-serif; margin: 1.5rem 1rem; max-width: 72rem; }
table { border-collapse: collapse; width: 100%; }
th, td { text-align: left; padding: .2rem 1rem .2rem 0; border-bottom: 1px solid #ddd; vertical-align: top; }
td.n { text-align: right; font-variant-numeric: tabular-nums; }
footer { margin-top: 1rem; color: #666; font-size: 12px; }
</style>
</head>
<body>
<h1>${esc(title)}</h1>
<table>
<thead><tr><th>name</th><th>size (bytes)</th><th>uploaded (UTC)</th><th>etag</th></tr></thead>
<tbody>
${rows.join('\n')}
</tbody>
</table>
${next}<footer>listed by the om-gazetteer Worker (storage.oceanmetrics.io) · page cursor: ${cursor ? `<code>${esc(cursor)}</code>` : 'first page'}</footer>
</body>
</html>
`
}
