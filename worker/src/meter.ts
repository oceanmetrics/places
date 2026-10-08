// metering: usage caps, Analytics Engine data points, monthly rollup ----
import type { Env, KeyConfig } from './env'
import type { PathClass } from './paths'

/** UTC month label `YYYY-MM` */
export function monthLabel(d: Date): string {
  return d.toISOString().slice(0, 7)
}

/** seconds until the first instant of next UTC month (Retry-After for a hard cap) */
export function secondsToNextMonth(d: Date): number {
  const next = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 1)
  return Math.max(1, Math.ceil((next - d.getTime()) / 1000))
}

export const usageKvKey = (id: string, month: string) => `usage:${id}:${month}`

export type CapState = 'ok' | 'soft' | 'hard'

export interface Usage { state: CapState, used: number, cap: number, pct: number }

/** compare month-to-date bytes with the key's cap. No cap (0/missing) is always `ok`. */
export function evaluateCap(used: number, cfg: KeyConfig): Usage {
  const cap = cfg.monthly_cap_bytes ?? 0
  if (!cap || cap <= 0) return { state: 'ok', used, cap: 0, pct: 0 }
  const soft = cfg.soft_pct ?? 0.8
  const state: CapState = used >= cap ? 'hard' : used >= cap * soft ? 'soft' : 'ok'
  return { state, used, cap, pct: Math.round((used / cap) * 1000) / 10 }
}

export async function getUsage(env: Env, id: string, now: Date): Promise<number> {
  const v = await env.KEYS.get(usageKvKey(id, monthLabel(now)), { cacheTtl: 60 })
  const n = v === null ? 0 : Number(v)
  return Number.isFinite(n) ? n : 0
}

/** one request's metric row. Analytics Engine layout (keep in step with the rollup SQL and the README):
 *    index1  key id, or `anon`
 *    blob1   key id ('' when keyless)   blob2 app   blob3 path class (stac|parquet|pmtiles|other|fullfile)
 *    blob4   origin                     blob5 tier (anonymous|open|<key tier>)   blob6 method   blob7 object path
 *    double1 response bytes             double2 http status */
export interface Metric {
  key:    string
  app:    string
  cls:    PathClass | 'fullfile'
  origin: string
  tier:   string
  method: string
  path:   string
  status: number
  bytes:  number
}

export function writeMetric(env: Env, m: Metric): void {
  try {
    env.METRICS.writeDataPoint({
      indexes: [(m.key || 'anon').slice(0, 96)],
      blobs:   [m.key, m.app, m.cls, m.origin, m.tier, m.method, m.path],
      doubles: [m.bytes, m.status],
    })
  } catch {
    // metering must never break serving
  }
}

/** Monthly rollup STUB. Sums response bytes per key since the start of the UTC month from the Analytics Engine SQL
 *  API and writes `usage:<key>:<YYYY-MM>` to KV, which the request path reads to apply soft/hard caps.
 *  Needs CF_ACCOUNT_ID + CF_API_TOKEN; without them it does nothing. The real, account-verified rollup (including the
 *  80 % email and a D1 history table) lands when the Cloudflare account exists: this SQL has not been run against it. */
export async function rollupUsage(
  env: Env, now: Date = new Date(), fetchFn: typeof fetch = fetch
): Promise<{ skipped: string } | { keys: number, month: string }> {
  if (!env.CF_ACCOUNT_ID || !env.CF_API_TOKEN) return { skipped: 'CF_ACCOUNT_ID / CF_API_TOKEN not set' }
  const month = monthLabel(now)
  const start = `${month}-01 00:00:00`
  const sql   = `SELECT blob1 AS key, SUM(_sample_interval * double1) AS bytes FROM ${env.AE_DATASET ?? 'om_gazetteer'} ` +
    `WHERE timestamp >= toDateTime('${start}') AND blob1 != '' GROUP BY key FORMAT JSON`
  const res = await fetchFn(`https://api.cloudflare.com/client/v4/accounts/${env.CF_ACCOUNT_ID}/analytics_engine/sql`, {
    method: 'POST', headers: { authorization: `Bearer ${env.CF_API_TOKEN}` }, body: sql })
  if (!res.ok) throw new Error(`analytics engine sql ${res.status}`)
  const body = await res.json() as { data?: { key: string, bytes: number | string }[] }
  const rows = body.data ?? []
  await Promise.all(rows.map(r =>
    env.KEYS.put(usageKvKey(r.key, month), String(Math.round(Number(r.bytes))), { expirationTtl: 60 * 60 * 24 * 40 })))
  return { keys: rows.length, month }
}
