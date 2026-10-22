import { env } from 'cloudflare:test'
import type { Env, KeyConfig } from '../src/env'

export const ORIGIN = 'https://apps.example.org'
export const HOST   = 'https://storage.oceanmetrics.io'

export const GOOD_KEY = 'goodkey_12345678'
export const CAP_KEY  = 'capkey_123456789'

export const PARQUET = new Uint8Array(40_000).map((_, i) => (i * 7 + 3) % 251)
export const PMTILES = new Uint8Array(10_000).map((_, i) => (i * 13 + 1) % 253)
export const UNLISTED_PARQUET = new Uint8Array(30_000).map((_, i) => (i * 11 + 5) % 241)

export interface Point { indexes: string[], blobs: string[], doubles: number[] }

export interface Rig { env: Env, points: Point[], limited: { anon: string[], key: string[] } }

/** a worker env over the real (miniflare) R2 + KV with fake metrics and limiters */
export function rig(over: Partial<Env> & { anonOk?: boolean } = {}): Rig {
  const points: Point[] = []
  const limited = { anon: [] as string[], key: [] as string[] }
  const { anonOk = true, ...rest } = over
  const e = {
    BUCKET:  env.BUCKET,
    UNLISTED: env.UNLISTED,
    KEYS:    env.KEYS,
    METRICS: { writeDataPoint: (p: Point) => { points.push(p) } },
    ANON_LIMITER: { limit: async ({ key }: { key: string }) => { limited.anon.push(key); return { success: anonOk } } },
    KEY_LIMITER:  { limit: async ({ key }: { key: string }) => { limited.key.push(key); return { success: true } } },
    ...rest,
  } as unknown as Env
  return { env: e, points, limited }
}

export async function seed(): Promise<void> {
  const put = (k: string, v: ArrayBuffer | Uint8Array | string) => env.BUCKET.put(k, v)
  await put('gazetteer/catalog.json', JSON.stringify({ type: 'Catalog' }))
  await put('gazetteer/layers.json', JSON.stringify([]))
  await put('gazetteer/README.md', '# gazetteer')
  await put('gazetteer/credits', 'credits')
  await put('gazetteer/mpa/places.parquet', PARQUET)
  await put('gazetteer/mpa/places.pmtiles', PMTILES)
  await put('gazetteer/index/crosswalk.parquet', PARQUET)
  // unlisted bucket: same key layout, different objects (so a test can tell which bucket answered)
  const putU = (k: string, v: ArrayBuffer | Uint8Array | string) => env.UNLISTED.put(k, v)
  await putU('gazetteer/mr_eez/places.parquet', UNLISTED_PARQUET)
  await putU('gazetteer/mr_eez/places.pmtiles', PMTILES)
  await putU('gazetteer/mr_eez/README.md', '# unlisted copy')
  await putU('gazetteer/index/unlisted.json', JSON.stringify({ collections: [{ slug: 'mr_eez' }] }))
  const keys: Record<string, KeyConfig> = {
    [GOOD_KEY]: { app: 'erddap-places', origins: [ORIGIN, 'http://localhost:*'], monthly_cap_bytes: 1_000_000, tier: 'free' },
    [CAP_KEY]:  { app: 'capped-app', origins: [], monthly_cap_bytes: 1000, soft_pct: 0.5, tier: 'free' },
    disabledkey_1234: { app: 'old-app', disabled: true },
  }
  for (const [k, v] of Object.entries(keys)) await env.KEYS.put(`key:${k}`, JSON.stringify(v))
}

export const get = (path: string, init: RequestInit = {}) => new Request(`${HOST}${path}`, init)

export const now = new Date('2026-10-15T12:00:00Z')
