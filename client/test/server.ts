import { createServer } from 'node:http'
import { readFile, stat } from 'node:fs/promises'
import { join, normalize } from 'node:path'
import type { AddressInfo } from 'node:net'

export const FIXTURES = new URL('./fixtures/', import.meta.url).pathname

/** serve test/fixtures over HTTP with HEAD and Range support, counting the bytes sent per path. */
export async function serveFixtures() {
  const bytes = new Map<string, number>()
  const requests: string[] = []
  const server = createServer(async (req, res) => {
    try {
      const path = normalize(decodeURIComponent(new URL(req.url!, 'http://x').pathname)).replace(/^\/+/, '')
      const file = join(FIXTURES, path)
      if (!file.startsWith(FIXTURES)) throw new Error('outside')
      const size = (await stat(file)).size
      requests.push(`${req.method} ${path} ${req.headers.range ?? ''}`.trim())
      const type = path.endsWith('.json') ? 'application/json' : 'application/octet-stream'
      if (req.method === 'HEAD') { res.writeHead(200, { 'content-length': size, 'accept-ranges': 'bytes', 'content-type': type }); return res.end() }
      const m = /bytes=(\d*)-(\d*)/.exec(req.headers.range ?? '')
      const buf = await readFile(file)
      let [start, end] = [0, size - 1]
      if (m) { if (m[1] === '') start = size - Number(m[2]); else { start = Number(m[1]); if (m[2]) end = Math.min(Number(m[2]), size - 1) } }
      const body = buf.subarray(start, end + 1)
      bytes.set(path, (bytes.get(path) ?? 0) + body.length)
      res.writeHead(m ? 206 : 200, { 'content-length': body.length, 'content-type': type, 'accept-ranges': 'bytes',
        ...(m ? { 'content-range': `bytes ${start}-${end}/${size}` } : {}) })
      res.end(body)
    } catch { res.writeHead(404); res.end() }
  })
  await new Promise<void>((r) => server.listen(0, '127.0.0.1', r))
  const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}/`
  return { base, bytes, requests, close: () => new Promise<void>((r) => server.close(() => r())) }
}
