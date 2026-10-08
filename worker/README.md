# om-gazetteer Worker

Cloudflare Worker that fronts `https://storage.oceanmetrics.io/gazetteer/*` from an R2 bucket (same key layout as the
S3 bucket today). It adds `?key=` access keys with Origin allow-lists, correct Range/HEAD/ETag/CORS behaviour for
DuckDB-WASM and pmtiles-js, per-request metering and monthly byte caps. Design: project plan section 9, decisions D7 and
D8; client behaviour: `notes/om/plans_todo/2026-10-08_duckdb-wasm-key-spike.md`.

**Status: code and tests only. Nothing is deployed and no Cloudflare account call has been made.** Steps that need the
account or DNS are marked **BEN-DOES**.

## Behaviour

| Request | Result |
|---|---|
| `*.json` (STAC, `layers.json`, `versions.json`), README/AGENTS md, thumbnails, `credits`, anything under `gazetteer/index/` | keyless. A `?key=` is used only for attribution; a wrong or stale one is ignored, never a 403 |
| `*.parquet`, `*.pmtiles` with a valid `?key=` | served; Origin must match the key's allow-list (no Origin header, as from curl/R/QGIS, passes) |
| same, no key | **anonymous tier**: served, but through the `ANON_LIMITER` rate-limit binding (per client IP); over the limit is a 429, not a 403 |
| same, unknown/malformed/disabled key, or wrong Origin | 403 JSON (`invalid_key`, `origin_not_allowed`) |
| key at or over its monthly byte cap | 429 JSON `{error:"monthly_cap_exceeded", key, cap_bytes, used_bytes}`, `Retry-After` to the start of next UTC month |
| key at or over `soft_pct` (default 80 %) of its cap | served, with `X-OM-Usage: used=...; cap=...; pct=...; state=soft` |
| un-ranged GET of a parquet over `FULLFILE_BYTES` (16 MiB) | 200 (not blocked), metric class `fullfile`, `X-OM-Warn: full-file-read ...` |

HTTP details: single `Range` honoured with 206 + `Content-Range`/`Content-Length`/`Accept-Ranges` (R2 range reads;
multi-range and malformed `Range` are ignored per RFC 9110, giving a 200); suffix and open-ended ranges; 416 with
`Content-Range: bytes */size`; HEAD and `HEAD + Range: bytes=0-` answer with headers only (206 for the latter, which is what
duckdb-wasm's reliable-HEAD check needs); `ETag` passthrough, `If-Match` (412) and `If-None-Match` (304). CORS is on every
response including 403/429/404/416: `Access-Control-Allow-Origin` is the request Origin when a valid key's allow-list matches
(with `Vary: Origin`), otherwise `*`; allows `range, if-match, if-none-match`; exposes
`etag, content-range, accept-ranges, content-length, link, retry-after, x-om-usage, x-om-warn`. Data responses carry
`Link: <https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"` (upload an object at `gazetteer/credits`).
`If-Range` is not implemented (neither client sends it).

Keys are low-grade, rotatable attribution keys, not secrets: they sit in URLs, history and logs.

## Metering

One Analytics Engine data point per request (every response, errors included):

| field | content |
|---|---|
| `index1` | key id, or `anon` |
| `blob1`..`blob7` | key id (`''` if keyless), app, class (`stac`/`parquet`/`pmtiles`/`other`/`fullfile`), Origin, tier (`anonymous`, `open` for keyless content, else the key's tier), method, object path |
| `double1`, `double2` | response bytes (the declared body length: a ranged GET is its range, HEAD/304/errors are 0), HTTP status |

Bytes are charged when the response starts, not when the body finishes, so an aborted download over-counts slightly.

Caps use `usage:<key>:<YYYY-MM>` in KV, written by the scheduled handler (`*/15 * * * *`). **The rollup in
`src/meter.ts` (`rollupUsage`) is a stub**: it builds the Analytics Engine SQL (`SUM(_sample_interval * double1)` grouped by
`blob1` since the start of the UTC month) and is unit-tested against a fake fetch, but it has never run against the real API
and needs `CF_ACCOUNT_ID` plus the `CF_API_TOKEN` secret to do anything. The 80 % email and a D1 history table are not built.
Consequence: a cap is enforced with up to ~15 minutes of lag, and it is a billing guard, not a hard real-time limit.

## Develop and test

```sh
cd worker
npm install
npm test            # vitest + @cloudflare/vitest-plugin (workerd via miniflare), 31 tests
npm run typecheck
```

Tests use the real local R2 and KV from `wrangler.toml` with fake Analytics Engine and rate-limit bindings. In a sandbox
where the default temp dir is read-only, run with `TMPDIR=<writable dir> npm test`. The tests need no Cloudflare login.
(`@cloudflare/vitest-pool-workers` is deprecated and renamed `@cloudflare/vitest-plugin`; this uses the new one.)

## Deploy runbook

1. **BEN-DOES** Create/choose the Cloudflare account; add `oceanmetrics.io` as a zone (import DNS records, then switch
   nameservers at the registrar). Diff the Caddyfile before cutover (plan section 9, Migration).
2. **BEN-DOES** `npx wrangler login` (inside `worker/`).
3. **BEN-DOES** R2 bucket: `npx wrangler r2 bucket create oceanmetrics-io-public` (R2 names cannot contain dots, hence
   `-io-`). Then `rclone sync` the S3 bucket's `gazetteer/` prefix into it, keeping the `gazetteer/` key prefix. Set the
   object `Content-Type` as you copy (`.parquet`, `.pmtiles`, `.json`); the Worker falls back to an extension guess. Upload
   `gazetteer/credits` (the licence/credits page the Link header points to). Do not add public access or CORS rules to the
   bucket: the Worker is the only reader.
4. **BEN-DOES** KV: `npx wrangler kv namespace create KEYS`, paste the printed id over `REPLACE_WITH_KV_NAMESPACE_ID` in
   `wrangler.toml`.
5. **BEN-DOES** Analytics Engine: enable it for the account (dashboard, Workers > Analytics Engine); the dataset
   `om_gazetteer` is created on first write.
6. **BEN-DOES** Rate-limit bindings: nothing to create, they are declared in `wrangler.toml` (`ANON_LIMITER` 120 requests per
   60 s per IP; `KEY_LIMITER` 1200 per 60 s per key). `namespace_id` values are arbitrary numbers unique in the account.
   The anonymous number is a guess: one DuckDB query on an archive is 5 to 30+ requests (see the spike), so tune it from
   `blob5 = 'anonymous'` rows.
7. **BEN-DOES** Rollup (optional until you want caps): `npx wrangler secret put CF_API_TOKEN` (token with Account >
   Account Analytics > Read) and uncomment/set `CF_ACCOUNT_ID` in `[vars]`.
8. **BEN-DOES** `npx wrangler deploy` (stages on the `*.workers.dev` URL; check `curl -I <url>/gazetteer/catalog.json`).
   Stage on `storage-next.oceanmetrics.io` first as the plan says, by temporarily setting the route pattern to it.
9. **BEN-DOES** Production route once DNS is in Cloudflare: uncomment `routes` in `wrangler.toml`
   (`storage.oceanmetrics.io/*`), deploy, then retire the Caddy VM after a week.
10. Smoke test (replace the key): `curl -sI -H 'Range: bytes=0-' 'https://storage.oceanmetrics.io/gazetteer/<collection>/places.parquet?key=<id>'`
    should be `206` with `Content-Range`. Client reminder from the spike: duckdb-wasm >= 1.30 must open with
    `db.open({filesystem:{forceFullHTTPReads:false}})` or it downloads whole files (these show up as `fullfile`).

## Minting keys

A key is a KV entry `key:<id>`. The id is 8 to 64 chars of `A-Za-z0-9_-`; `openssl rand -hex 12` is fine. Value fields:
`app`, `origins` (list; `*` is a wildcard inside a pattern, an empty/missing list allows any Origin), `monthly_cap_bytes`
(0/missing = uncapped), `soft_pct` (default 0.8), `tier`, `disabled`. **BEN-DOES** (needs the account):

```sh
mint() {  # mint <app> <tier> <monthly_cap_bytes> <origin>...
  local app=$1 tier=$2 cap=$3; shift 3
  local id; id=$(openssl rand -hex 12)
  local origins; origins=$(printf '%s\n' "$@" | jq -R . | jq -sc .)
  npx wrangler kv key put --binding KEYS "key:$id" \
    "$(jq -nc --arg app "$app" --arg tier "$tier" --argjson cap "$cap" --argjson o "$origins" \
        '{app:$app, tier:$tier, monthly_cap_bytes:$cap, origins:$o}')" && echo "$app  key=$id"
}

# proposed free-tier cap 200 GB/month each (revisit after a month of logs); confirm each site's real origins first
mint erddap-places  free 214748364800 https://oceanmetrics.io http://localhost:*
mint obis-hex       free 214748364800 https://oceanmetrics.io http://localhost:*
mint calcofi-explore free 214748364800 https://calcofi.io http://localhost:*
mint msens-atlas    free 214748364800 https://marinesensitivity.org https://app.marinesensitivity.org https://preview.marinesensitivity.org http://localhost:*
```

Origins are scheme + host (+ port), never a path: `https://oceanmetrics.io` covers `/erddap-places/` and `/obis-hex/`.
Put each id in that app's config as `?key=<id>` on its parquet/pmtiles URLs. Rotate: mint a new id, ship it, then
`npx wrangler kv key put --binding KEYS key:<old> '{"app":"...","disabled":true}'`. Inspect/raise a cap:
`npx wrangler kv key get --binding KEYS key:<id>`, then put the edited JSON back (the Worker caches key reads 60 s).
Usage for a key: `npx wrangler kv key get --binding KEYS usage:<id>:<YYYY-MM>`.
