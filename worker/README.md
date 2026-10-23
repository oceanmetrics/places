# om-gazetteer Worker

Cloudflare Worker that fronts `https://storage.oceanmetrics.io/*` from an R2 bucket (same key layout as the S3 bucket
`oceanmetrics.io-public` today): every published prefix (`gazetteer`, `indicators`, `atlas`, `obis-h3`, `basemap`,
`marine-atlas`, `issues`, the root `index.html` and `README.md`), the key-only `atlas-restricted/` and the unlisted bucket at
`/unlisted/gazetteer/`. `backups/` and everything else is a 404. It adds `?key=` access keys with Origin allow-lists, correct Range/HEAD/ETag/CORS behaviour for
DuckDB-WASM and pmtiles-js, per-request metering and monthly byte caps. Design: project plan section 9, decisions D7 and
D8; client behaviour: `notes/om/plans_todo/2026-10-08_duckdb-wasm-key-spike.md`.

**Status (2026-10-22): deployed to the workers.dev preview `https://om-gazetteer.ben-f07.workers.dev` on the Ocean Metrics
Cloudflare account (buckets `oceanmetrics-io-public-enam` and `oceanmetrics-io-unlisted-enam`, US location ENAM since
2026-10-23, KV `KEYS`, Analytics Engine
`om_gazetteer`); the S3 → R2 mirror runs from the Mac mini with rclone; since the DNS cutover of 2026-10-23 (17:55 PT)
`storage.oceanmetrics.io` is the Worker's custom domain and serves production (the preview stays).** Steps that need the
account or DNS are marked **BEN-DOES**.

## Behaviour

Which paths are served (`target()` in `src/paths.ts`):

| Request path | Result |
|---|---|
| `/gazetteer/...`, `/indicators/...`, `/atlas/...`, `/obis-h3/...`, `/basemap/...`, `/marine-atlas/...`, `/issues/...` | served from `BUCKET` (`oceanmetrics-io-public-enam`), gated by type (next table) |
| `/index.html`, `/README.md` (and `/`, which reads `index.html`) | served, keyless; every other root object (`nc.parquet`, `indicators.pmtiles`) is a 404 |
| a folder URL ending in `/` (`/marine-atlas/`, `/marine-atlas/cog/`) | serves `index.html` under it when that object exists, else 404 (the old Caddy's `/marine-atlas/` rewrite) |
| `/atlas-restricted/...` (restricted atlas collections, not linked from `catalog.json`) | served from `BUCKET` like `/unlisted/`: every file (json included) needs a valid key, **no anonymous tier**, metric class `unlisted`; keyless is 403 `key_required` |
| `/unlisted/gazetteer/...` | served from `UNLISTED` (below) |
| `/backups/...` and anything else | 404 JSON `{error:"not_found", message:"served prefixes: ..."}`, key or not (the multi-GB database dump must never be reachable: this is the old Caddy's allow-list) |

How a served public path is gated, by type, not by prefix (`classify()`):

| Request | Result |
|---|---|
| `*.json` (STAC, `catalog.json`, `layers.json`, `indicators.json`, `latest.json`, `versions.json`), `*.md`, `*.html`, `*.png`, `*.jpg`/`*.jpeg`, `*.txt`, `*.csv`, `*.svg`, `*.atom`/`*.xml` (the indicators Atom feeds, `indicators/feeds/`: `application/atom+xml` as stored, else the extension's type), `credits`, anything under `gazetteer/index/` | keyless. A `?key=` is used only for attribution; a wrong or stale one is ignored, never a 403. Class `stac` for json, else `other` |
| data: `*.parquet`, `*.pmtiles`, `*.tif`/`*.tiff`, `*.duckdb`, `*.zip`, `*.gz`, `*.fgb`, and any extension not in the keyless list, with a valid `?key=` | served; Origin must match the key's allow-list (no Origin header, as from curl/R/QGIS, passes). Class `parquet`, `pmtiles`, `tif`, else `data` |
| same, no key | **anonymous tier**: served, but through the `ANON_LIMITER` rate-limit binding (1,200 requests a minute per client IP, every keyless data request counts, so a map session of several Place page views is never throttled); over the limit is a 429, not a 403 |
| same, no key, un-ranged GET of a parquet over `FULLFILE_BYTES` | also counts against `ANON_FULLFILE_LIMITER`, a separate budget of 60 a minute per client IP; the 61st in a minute is a 429 (same body and `Retry-After: 60`), so a bulk download is throttled while ranged reads are not. Keyed tiers are unchanged |
| same, unknown/malformed/disabled key, or wrong Origin | 403 JSON (`invalid_key`, `origin_not_allowed`) |
| key at or over its monthly byte cap | 429 JSON `{error:"monthly_cap_exceeded", key, cap_bytes, used_bytes}`, `Retry-After` to the start of next UTC month |
| key at or over `soft_pct` (default 80 %) of its cap | served, with `X-OM-Usage: used=...; cap=...; pct=...; state=soft` |
| un-ranged GET of a parquet over `FULLFILE_BYTES` (16 MiB), any prefix | 200 (not blocked), metric class `fullfile`, `X-OM-Warn: full-file-read ...` |
| `/unlisted/gazetteer/<slug>/...` (any file) with a valid `?key=` | served from the `UNLISTED` bucket (`oceanmetrics-io-unlisted-enam`, same `gazetteer/...` key layout) with the same key, Origin, cap, Range/HEAD/ETag/CORS and `Link` rules as the public archives; metric class `unlisted`, object path `unlisted/gazetteer/...` |
| same, no key | **no anonymous tier**: 403 JSON `key_required` (with CORS) |
| same, wrong key or Origin | 403 `invalid_key` / `origin_not_allowed`, as above |
| `/unlisted/gazetteer/index/unlisted.json` (anything under `unlisted/gazetteer/index/`) | keyless, like the public index; metric class `unlisted` |

HTTP details: single `Range` honoured with 206 + `Content-Range`/`Content-Length`/`Accept-Ranges` (R2 range reads;
multi-range and malformed `Range` are ignored per RFC 9110, giving a 200); suffix and open-ended ranges; 416 with
`Content-Range: bytes */size`; HEAD and `HEAD + Range: bytes=0-` answer with headers only (206 for the latter, which is what
duckdb-wasm's reliable-HEAD check needs); `ETag` passthrough, `If-Match` (412) and `If-None-Match` (304). CORS is on every
response including 403/429/404/416: `Access-Control-Allow-Origin` is the request Origin when a valid key's allow-list matches
(with `Vary: Origin`), otherwise `*`; allows `range, if-match, if-none-match`; exposes
`etag, content-range, accept-ranges, content-length, link, retry-after, x-om-usage, x-om-warn, x-om-cache`. Gazetteer responses
(public and unlisted) carry `Link: <https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"` (upload an object at
`gazetteer/credits`); another prefix carries `Link: <.../<prefix>/index/credits>` only when that object exists (looked up
once per isolate per 10 minutes), and the root files none. `Content-Type` is the stored one unless it is missing or generic
(`application/octet-stream`, `binary/octet-stream`), then the extension guess (`.pmtiles` is `application/vnd.pmtiles`,
`.tif` `image/tiff`, `.parquet` `application/vnd.apache.parquet`). `Cache-Control` is the stored one, else 60 s for json
and html and 300 s otherwise; an immutable key (next section) always gets `public, max-age=31536000, immutable`.
`If-Range` (since 2026-10-23): a Range with an `If-Range` that is not the current strong ETag or the exact
`Last-Modified` date is answered with the whole 200.

Keys are low-grade, rotatable attribution keys, not secrets: they sit in URLs, history and logs.

## Edge cache

R2 is in ENAM, so a reader in Europe paid a transatlantic round trip on every request (the atlas Cell pane's one 200 KB
range took 0.19 to 0.85 s from Italy). Objects whose key names their content are now kept at the Cloudflare data center
that served them (`src/edge.ts`, the Cache API `caches.default`).

Which keys: `isImmutable(key, store)` in `src/paths.ts`, a pure function with a table of cases in `test/edge.test.ts`.
Only public data files (`.parquet`, `.pmtiles`, `.tif`/`.tiff`, `.fgb`), and only these layouts (read from the bucket
on 2026-10-23):

| immutable | why |
|---|---|
| `obis-h3/v<digits>/**` | a release folder (`v20261012/species_flat/res=3/p=<cell>.parquet`, `files.parquet`) |
| `marine-atlas/**/<hash>.tif\|.pmtiles`, `marine-atlas/**/<hash>_3857.tif` | content-addressed (`cog/`, `native/`, `cog_3857/`, `v7/cog_3857/`; the marine-atlas README) |
| `atlas/<collection>/**/v<digits>/**` | a versioned folder below the collection (`aquamaps_native/registry/v2/registry.parquet`) |
| `basemap/<set>/**/v<digits>/**` | a versioned folder; **none exists yet** |

Never: any JSON or other metadata type (`latest.json`, `collection.json`, `release.json`, `catalog.json`, `layers.json`,
`indicators.json`, `changes/latest.json`, the `feeds/` Atom files), `_history/`, `gazetteer/` (`<slug>/places.parquet` is
replaced per version; there is no `<slug>/<semver>/` folder), `basemap/gebco/*.pmtiles` and `basemap/osm/land.pmtiles`
(`build_gebco.sh` rebuilds them in place under the same names), `indicators/`, `issues/`, the root files,
`atlas-restricted/` and the whole unlisted bucket. These keep their headers above.

**The contract for publishers**: a key that matches is never rewritten with other bytes. An amendment adds files or
starts a new version folder (`obis-h3/v<next>/`). The release `v20261012` was amended in place twice on 2026-10-23
(obisindicators 0.11 and 0.12) before this cache existed; after it, a browser keeps such a file for a year. A mistake at
the edge is fixable (Cloudflare dashboard, Caching > Purge, by URL: the cache key is the public URL without the query,
`https://storage.oceanmetrics.io/<key>`, or Purge Everything); a browser's copy is not.

How (for an immutable key, after the key, Origin, limit and cap checks, which are unchanged; so a copy is only ever
served to a request that passed them, and every hit writes its Analytics Engine row like any other response):

- The response carries `Cache-Control: public, max-age=31536000, immutable` and `X-OM-Cache: hit | miss | pass`
  (exposed to CORS). `cf-cache-status` is not set: Cloudflare does not cache a Worker's own responses.
- Lookup of the whole object under its public URL. A hit answers GET and HEAD from the copy: `If-None-Match`/`If-Match`
  and the date preconditions, `If-Range`, single ranges (open-ended, suffix, 416) sliced from the copy, the same
  headers as from R2, CORS applied after (so the echoed Origin of a key is never stored).
- A miss answers from R2 as before. When the object is at most `EDGE_CACHE_MAX_BYTES` (8 MiB) the whole object is
  stored after the response (`ctx.waitUntil`): an un-ranged GET tees its body into the cache, a ranged GET or a HEAD
  fetches the whole object from R2 in the background (skipped if its ETag changed; one fill per key per isolate).
- Over the cap: ranges pass through to R2 every time (`X-OM-Cache: pass`), with the immutable header, so only the
  browser keeps them.
- Off on the workers.dev preview (its Cache API stores nothing, so a fill would only add R2 reads): the preview sends
  the immutable header and `X-OM-Cache: pass`, and its timings are the R2 baseline.

The cache is per data center and Cloudflare evicts what is not read, so the first reader of a file at a data center
pays the R2 round trip and the next ones do not.

## Metering

One Analytics Engine data point per request (every response, errors included):

| field | content |
|---|---|
| `index1` | key id, or `anon` |
| `blob1`..`blob7` | key id (`''` if keyless), app, class (`stac`/`parquet`/`pmtiles`/`tif`/`data`/`other`/`fullfile`/`unlisted`), Origin, tier (`anonymous`, `open` for keyless content, else the key's tier), method, object path (prefixed `unlisted/` for the unlisted bucket) |
| `blob8` | prefix, so usage reads per catalog: the first segment of the object path (`gazetteer`, `indicators`, `atlas`, `obis-h3`, `basemap`, `marine-atlas`, `issues`, `atlas-restricted`, `unlisted`), `root` for the root files, or the request path's first segment when the path is not served (`backups` shows probing) |
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
npm test            # vitest + @cloudflare/vitest-plugin (workerd via miniflare), 221 tests
npm run typecheck
```

Tests use the real local R2 and KV from `wrangler.toml` with fake Analytics Engine and rate-limit bindings.
`test/prefixes.test.ts` is the table per prefix and type (keyless metadata, public data keyed and anonymous, restricted
keyed, `backups/` 404, the root files, the folder index rewrite). In a sandbox
where the default temp dir is read-only, run with `TMPDIR=<writable dir> npm test`. The tests need no Cloudflare login.
(`@cloudflare/vitest-pool-workers` is deprecated and renamed `@cloudflare/vitest-plugin`; this uses the new one.)

## Deploy runbook

1. **BEN-DOES** Create/choose the Cloudflare account; add `oceanmetrics.io` as a zone (import DNS records, then switch
   nameservers at the registrar). Diff the Caddyfile before cutover (plan section 9, Migration).
2. **BEN-DOES** `npx wrangler login` (inside `worker/`).
3. **BEN-DOES** R2 bucket: `npx wrangler r2 bucket create oceanmetrics-io-public-enam --location enam` (R2 names cannot
   contain dots, hence `-io-`; the US buckets `-enam` are the default since 2026-10-23, Ben; the first EEUR buckets
   `oceanmetrics-io-public` and `oceanmetrics-io-unlisted` are no longer bound and are kept until Ben deletes them). Then `rclone sync` the S3 bucket's `gazetteer/` prefix into it, keeping the `gazetteer/` key prefix. Set the
   object `Content-Type` as you copy (`.parquet`, `.pmtiles`, `.json`); the Worker falls back to an extension guess. Upload
   `gazetteer/credits` (the licence/credits page the Link header points to). Do not add public access or CORS rules to the
   bucket: the Worker is the only reader.
   Second bucket `oceanmetrics-io-unlisted-enam` (binding `UNLISTED`; the EEUR original was created 2026-10-22): the unlisted Marine Regions copies
   (`gazetteer/<slug>/places.parquet`, `places.pmtiles`, `provenance.json`, `README.md`, and `gazetteer/index/unlisted.json`),
   uploaded per release with rclone as in `catalog/staging/RUNBOOK_PUBLISH.md` "Unlisted copies" (parquet with
   `--header-upload 'Content-Type: application/vnd.apache.parquet'`). Same rule: no public access, the Worker is the only reader.
4. **BEN-DOES** KV: `npx wrangler kv namespace create KEYS`, paste the printed id over `REPLACE_WITH_KV_NAMESPACE_ID` in
   `wrangler.toml`.
5. **BEN-DOES** Analytics Engine: enable it for the account (dashboard, Workers > Analytics Engine); the dataset
   `om_gazetteer` is created on first write.
6. **BEN-DOES** Rate-limit bindings: nothing to create, they are declared in `wrangler.toml` (`ANON_LIMITER` 1200 requests per
   60 s per IP; `ANON_FULLFILE_LIMITER` 60 full-file reads per 60 s per IP; `KEY_LIMITER` 1200 per 60 s per key).
   `namespace_id` values are arbitrary numbers unique in the account. The anonymous numbers are sized from a measured
   Place page load (about 108 requests: gazetteer, layer tiles, GEBCO basemap ranges, values; one DuckDB query on an
   archive is 5 to 30+ requests, see the spike), so tune them from `blob5 = 'anonymous'` rows.
7. **BEN-DOES** Rollup (optional until you want caps): `npx wrangler secret put CF_API_TOKEN` (token with Account >
   Account Analytics > Read) and uncomment/set `CF_ACCOUNT_ID` in `[vars]`.
8. **BEN-DOES** `npx wrangler deploy` (stages on the `*.workers.dev` URL; check `curl -I <url>/gazetteer/catalog.json`).
   Stage on `storage-next.oceanmetrics.io` first as the plan says, by temporarily setting the route pattern to it.
9. **BEN-DOES** Production route once DNS is in Cloudflare: uncomment `routes` in `wrangler.toml`
   (`storage.oceanmetrics.io/*`), deploy, then retire the Caddy VM after a week.
10. Smoke test (replace the key): `curl -sI -H 'Range: bytes=0-' 'https://storage.oceanmetrics.io/gazetteer/<collection>/places.parquet?key=<id>'`
    should be `206` with `Content-Range`. Unlisted: `curl -sI -H 'Range: bytes=0-1023' '<url>/unlisted/gazetteer/mr_eez/places.parquet?key=<id>'`
    is `206`, and `403` (`key_required`) without the key. Other prefixes:
    `curl -sI -H 'Range: bytes=0-16383' <url>/basemap/gebco/far.pmtiles` is `206` `application/vnd.pmtiles`;
    `<url>/atlas/aquamaps_eov/collection.json` and `<url>/obis-h3/latest.json` `200`; `<url>/marine-atlas/` `200` html;
    `<url>/atlas-restricted/x` `403` `key_required`; `<url>/backups/` and `<url>/backups/anything` `404`. Client reminder from the spike: duckdb-wasm >= 1.30 must open with
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
