// objects stored with Content-Encoding (gzip boot.json): served once-encoded, through the real entrypoint ----
// the runtime re-encodes a Response whose headers carry Content-Encoding unless it was built with encodeBody: 'manual',
// and that only shows on the wire, so these tests go through SELF (the deployed fetch handler) and read the raw bytes
// with encodeResponseBody: 'manual' (no transparent decode on the test side either)
import { beforeAll, describe, expect, it } from 'vitest'
import { env, SELF } from 'cloudflare:test'
import { seed } from './helpers'

const HOST     = 'https://storage.oceanmetrics.io'
const BOOT     = 'marine-atlas/v7/app/boot.json'
const PLAIN    = 'marine-atlas/v7/app/plain.json'
const OBIS_GZ  = 'obis-h3/v1/species_flat/res=3/p=812a3ffffffffff.parquet'
const JSON_TXT = JSON.stringify({ schema: 1, ver: 'v7', layers: Array.from({ length: 200 }, (_, i) => ({ id: i, name: `layer ${i}` })) })
const PARQ     = new Uint8Array(50_000).map((_, i) => (i * 31 + 7) % 239)

async function gzip(data: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new CompressionStream('gzip'))).arrayBuffer())
}
async function gunzip(data: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await new Response(new Blob([data]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer())
}
/** the response as sent on the wire: raw bytes, never decoded by the test's fetch */
const wire = (path: string, init: RequestInit = {}) =>
  SELF.fetch(`${HOST}/${path}`, { ...init, encodeResponseBody: 'manual' } as RequestInit)
const bytes = async (res: Response) => new Uint8Array(await res.arrayBuffer())

let BOOT_GZ: Uint8Array
let PARQ_GZ: Uint8Array

beforeAll(async () => {
  await seed()
  BOOT_GZ = await gzip(new TextEncoder().encode(JSON_TXT))
  PARQ_GZ = await gzip(PARQ)
  await env.BUCKET.put(BOOT, BOOT_GZ, { httpMetadata: { contentType: 'application/json', contentEncoding: 'gzip' } })
  await env.BUCKET.put(PLAIN, JSON_TXT, { httpMetadata: { contentType: 'application/json' } })
  await env.BUCKET.put(OBIS_GZ, PARQ_GZ, { httpMetadata: { contentType: 'application/vnd.apache.parquet', contentEncoding: 'gzip' } })
})

describe('content-encoding: a gzip object is served with one layer', () => {
  it('regression: GET with Accept-Encoding gzip sends the stored gzip bytes and the header (one gunzip parses)', async () => {
    const res = await wire(BOOT, { headers: { 'accept-encoding': 'gzip' } })
    expect(res.status).toBe(200)
    expect(res.headers.get('content-encoding')).toBe('gzip')
    const body = await bytes(res)
    expect(body).toEqual(BOOT_GZ)
    expect(JSON.parse(new TextDecoder().decode(await gunzip(body)))).toEqual(JSON.parse(JSON_TXT))
  })

  it('GET with Accept-Encoding identity sends the same stored bytes (the header is the runtime\'s call, not asserted)', async () => {
    const res = await wire(BOOT, { headers: { 'accept-encoding': 'identity' } })
    expect(res.status).toBe(200)
    expect(await bytes(res)).toEqual(BOOT_GZ)
  })

  it('HEAD carries content-encoding: gzip and the stored length', async () => {
    const res = await wire(BOOT, { method: 'HEAD', headers: { 'accept-encoding': 'gzip' } })
    expect(res.status).toBe(200)
    expect(res.headers.get('content-encoding')).toBe('gzip')
    expect(res.headers.get('content-length')).toBe(String(BOOT_GZ.length))
  })

  it('a Range of an encoded object is a range of the stored gzip bytes, with the stored header (as R2/S3)', async () => {
    const res = await wire(BOOT, { headers: { 'accept-encoding': 'gzip', range: 'bytes=0-9' } })
    expect(res.status).toBe(206)
    expect(res.headers.get('content-encoding')).toBe('gzip')
    expect(res.headers.get('content-range')).toBe(`bytes 0-9/${BOOT_GZ.length}`)
    expect(await bytes(res)).toEqual(BOOT_GZ.slice(0, 10))
  })

  it('a plain object is unchanged: no content-encoding, the body byte for byte', async () => {
    const res = await wire(PLAIN, { headers: { 'accept-encoding': 'identity' } })
    expect(res.status).toBe(200)
    expect(res.headers.get('content-encoding')).toBeNull()
    expect(new TextDecoder().decode(await bytes(res))).toBe(JSON_TXT)
  })

  it('edge cache: an immutable encoded key serves the stored bytes on the miss and from the copy on the hit', async () => {
    const miss = await wire(OBIS_GZ, { headers: { 'accept-encoding': 'gzip' } })
    expect(miss.status).toBe(200)
    expect(miss.headers.get('x-om-cache')).toBe('miss')
    expect(miss.headers.get('content-encoding')).toBe('gzip')
    expect(await bytes(miss)).toEqual(PARQ_GZ)
    // the copy is stored in waitUntil after the response: poll until a hit
    let hit: Response | null = null
    for (let i = 0; i < 50 && !hit; i++) {
      const r = await wire(OBIS_GZ, { headers: { 'accept-encoding': 'gzip' } })
      if (r.headers.get('x-om-cache') === 'hit') hit = r
      else { await r.arrayBuffer(); await new Promise(ok => setTimeout(ok, 50)) }
    }
    expect(hit, 'no edge-cache hit after the miss').not.toBeNull()
    expect(hit!.headers.get('content-encoding')).toBe('gzip')
    const body = await bytes(hit!)
    expect(body).toEqual(PARQ_GZ)
    expect(await gunzip(body)).toEqual(PARQ)
    const ranged = await wire(OBIS_GZ, { headers: { 'accept-encoding': 'gzip', range: 'bytes=100-199' } })
    expect(ranged.status).toBe(206)
    expect(ranged.headers.get('x-om-cache')).toBe('hit')
    expect(await bytes(ranged)).toEqual(PARQ_GZ.slice(100, 200))
  })
})
