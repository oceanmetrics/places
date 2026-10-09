# web/

The website at places.oceanmetrics.io: search the places index, browse layers on a map, and read the licence and
citation of everything on screen. Svelte 5 + Vite + TypeScript + MapLibre GL + pmtiles, a static SPA with
client-side routing. Data comes from the sibling [`client/`](../client/README.md) package (`@oceanmetrics/places`),
which reads `layers.json`, the places index, GeoParquet and PMTiles straight from object storage.

| route | page |
|---|---|
| `/` | search + browse map with layer toggles; reads and writes `?layers=slug[:colour][:opacity][:width],…&place=<place_id>` |
| `/p/<place_id>` | place page: geometry, metadata, licence + attribution + citation, "use in" links, downloads |
| `/l/<slug>` | layer page: n, version, updated, licence, attribution, citation, README, "Add to map" |
| `/credits` | every layer's attribution and citation, grouped by authority |
| `/docs` | STAC root, the `layers.json` contract, DuckDB / Python / R recipes |

## Develop

```sh
cd web
npm install          # links ../client as @oceanmetrics/places (used from its TypeScript source, no client build needed)
npm run dev          # http://localhost:5180
npm test             # vitest: URL grammar codec (round trips) and pure helpers
npm run check        # svelte-check
npm run build        # dist/
```

If vitest cannot create its temp dir in a sandbox, set `TMPDIR` to a writable directory.

Data base URL: `https://storage.oceanmetrics.io/gazetteer/` by default; override at build time with
`VITE_PLACES_BASE=https://…/` or at run time with `?base=https://…/` (internal links keep it). To develop offline, serve
`client/test/fixtures/` with CORS and Range support and use `?base=http://127.0.0.1:<port>/`.

Everything degrades: when `index/layers.json` or the places index is not published the page shows a notice and still
renders (search falls back to filtering the layer list; a layer whose tiles are missing is flagged, not fatal).
`attribution_html` is sanitised (inline tags and http(s) links only) because the base URL can be overridden.

## Deploy

**Live now at <https://oceanmetrics.io/places/>** via GitHub Pages (`.github/workflows/pages.yml`: on push to `main`
touching `web/` or `client/`, it checks, tests, builds with `--base=/places/` and deploys; `404.html` is a copy of
`index.html`, the SPA fallback). The app base is `import.meta.env.BASE_URL` (`APP_BASE` in `lib/helpers.ts`): routes
are matched and internal links written under it, so the same build runs at `/` (dev, Workers) and `/places/` (Pages).

## BEN-DOES: deploy to places.oceanmetrics.io (not done)

Hosting there is Cloudflare Workers static assets (decision D11). `wrangler.jsonc` is ready (assets from `dist/`, SPA fallback so
`/p/…` and `/l/…` resolve to `index.html`). After the `oceanmetrics.io` DNS move to Cloudflare:

1. `cd web && npm ci && npm run build`
2. `npx wrangler deploy` (log in first with `npx wrangler login`)
3. In the Cloudflare dashboard add the route / custom domain `places.oceanmetrics.io` to the `places-web` Worker.
4. Confirm CORS and Range work from the new origin against `storage.oceanmetrics.io` (S3 supplies the CORS headers) and
   that `index/layers.json` is publicly readable (it returned 403 on 2026-10-08, before the first publish).
