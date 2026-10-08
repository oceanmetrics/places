// bindings and per-key config ----

/** worker bindings (see wrangler.toml) */
export interface Env {
  /** R2 bucket holding the `gazetteer/...` key layout */
  BUCKET: R2Bucket
  /** KV: `key:<id>` -> KeyConfig (JSON); `usage:<id>:<YYYY-MM>` -> bytes this month (written by the rollup) */
  KEYS: KVNamespace
  /** Analytics Engine dataset, one data point per request */
  METRICS: AnalyticsEngineDataset
  /** Workers rate-limit binding for keyless archive reads (keyed by client ip) */
  ANON_LIMITER: RateLimit
  /** optional rate-limit binding applied per key id to keyed archive reads */
  KEY_LIMITER?: RateLimit
  /** un-ranged GET of a parquet larger than this many bytes is flagged `fullfile` (default 16 MiB) */
  FULLFILE_BYTES?: string
  /** Analytics Engine dataset name, used by the rollup SQL (default om_gazetteer) */
  AE_DATASET?: string
  /** rollup only: Cloudflare account id and an API token with Account Analytics:Read (secret) */
  CF_ACCOUNT_ID?: string
  CF_API_TOKEN?: string
}

/** value stored under KV `key:<id>` */
export interface KeyConfig {
  /** human-readable app name, written to every metric row */
  app: string
  /** browser Origin allow-list; `*` inside a pattern is a wildcard (`https://*.example.org`, `http://localhost:*`).
   *  Requests with no Origin header (curl, R, QGIS) pass. Empty or missing list = any origin. */
  origins?: string[]
  /** monthly response-byte cap; 0 or missing = uncapped */
  monthly_cap_bytes?: number
  /** fraction of the cap at which X-OM-Usage warns (default 0.8) */
  soft_pct?: number
  /** free | supporter | pro | internal ... (free text, recorded in metrics) */
  tier?: string
  /** true = key refused (403) without deleting it */
  disabled?: boolean
}
