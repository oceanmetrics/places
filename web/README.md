# web/

The website at places.oceanmetrics.io: search the places index, browse layers on a map, and read the licence and
citation of everything on screen. Svelte 5 + Vite + TypeScript + MapLibre GL + pmtiles, a static SPA with
client-side routing. Data comes from the `@oceanmetrics/places` client (since 2026-10-22 in
[oceanmetrics/platform `packages/places`](https://github.com/oceanmetrics/platform/tree/main/packages/places), a sibling checkout
linked locally until the npm publish on Day 5, 2026-10-26), which reads `layers.json`, the places index, GeoParquet and PMTiles straight from object storage.

| route | page |
|---|---|
| `/` | search + browse map with layer toggles; reads and writes `?layers=slug[:colour][:opacity][:width],…&place=<place_id>` |
| `/p/<place_id>` | place page: geometry, indicators, metadata, licence + attribution + citation, "use in" links, downloads |
| `/l/<slug>` | layer page: n, version, updated, licence, attribution, citation, README, "Add to map" |
| `/credits` | every layer's attribution and citation, grouped by authority |
| `/docs` | STAC root, the `layers.json` contract, DuckDB / Python / R recipes |

## Develop

```sh
cd web
npm install          # links ../../platform/packages/places as @oceanmetrics/places (its TypeScript source, no client build needed);
                     # needs a checkout of oceanmetrics/platform next to this repo, with `npm install` run at its root
npm run dev          # http://localhost:5180
npm test             # vitest: URL grammar codec (round trips), pure helpers, the indicators slot (synthetic fixtures, no network)
npm run check        # svelte-check
npm run build        # dist/
node scripts/shoot.mjs [--url http://localhost:5180/] [--only NMS:CINMS]   # place page screenshots -> docs/shots/; look at them
```

`scripts/shoot.mjs` (Playwright, headless Google Chrome through `channel: "chrome"`, else Playwright's chromium after
`npx playwright install chromium`) serves `dist/` with `vite preview` unless `--url` names a running server, opens
`/p/NMS:CINMS` (a sanctuary with status cards) and `/p/MRGID:8439` (an EEZ with OBIS series and SDG) at 390 px and 1280 px
in light and dark (the theme is set as `localStorage` `om-theme` before load), and saves the page from the top to the end
of the Indicators section as `docs/shots/place_<id>_<width>_<theme>.png`. It reads the live catalogs and warns when a page
is wider than the window.

If vitest cannot create its temp dir in a sandbox, set `TMPDIR` to a writable directory.

Data base URL: `https://storage.oceanmetrics.io/gazetteer/` by default; override at build time with
`VITE_PLACES_BASE=https://…/` or at run time with `?base=https://…/` (internal links keep it). To develop offline, serve
`platform/packages/places/test/fixtures/` with CORS and Range support and use `?base=http://127.0.0.1:<port>/`.

## Indicators on the place page

The place page shows the place's indicators right after the map (`src/lib/Indicators.svelte`, rules in
`src/lib/indicators.ts`, tested in `indicators.test.ts` with `src/lib/fixtures/` (`indicators.json`, and
`coverage.parquet` made by `make_coverage.sql`)). It reads the Ocean Metrics indicators catalog
(oceanmetrics/indicators): `indicators.json` (the manifest: titles, units, series, leads, status method, dataset citation)
and `coverage.parquet` (one row per place × indicator × grain with the last value, status, trend and the method's
sentence, all computed there with `@oceanmetrics/status`; nothing here computes a status). Each card has the title, the
last value with its unit, the period (by grain: `2025`, `2025-07`, `the 2020s`), the status glyph and caption (shapes
from the indicators viewer: a ring with a plus, a filled centre, a minus, a dashed ring for none; captions say "its own
record"), the sentence, method and citation under a disclosure, and "Open in Indicators ↗", the indicators app's Place
view (`https://oceanmetrics.io/indicators/#view=place&place=<id>&coll=<coll>&ind=<indicator>`). Leads show first, then
"Show all"; the OBIS series that are not leads fold into one "no status rule" line with a count. With no cards the
section says which absence applies: **no data here** (the catalog covers the place's layer but has no value for it) or
**not computed yet** (it does not cover the layer: indicators for every gazetteer place arrive in build week 3,
2026-11-13 to 11-19; until then the link goes to ERDDAP Places). The full Place page is build week 3.

Catalog base: `https://storage.oceanmetrics.io/indicators/` by default; override at build time with
`VITE_INDICATORS_BASE=https://…/` or at run time with `?indicators=https://…/` (for example a local `catalog/` of the
indicators repo served with CORS). Both files are read whole, once per page load, and shared by every place page
visited: on 2026-10-22 `coverage.parquet` was 1.9 MB (1,898,582 bytes, 52,660 rows, 319 places; 63% of it is the
`spark` column, which is not decoded: the read projects to the 13 columns the cards need) and `indicators.json` 433 kB;
fetching coverage took 0.46 to 1.45 s and decoding it 22 to 48 ms (Node, from this machine). Range reads of only the
needed column chunks (hyparquet `asyncBufferFromUrl`) would fetch about a third of it, if the size starts to matter.

Everything degrades: when `index/layers.json` or the places index is not published the page shows a notice and still
renders (search falls back to filtering the layer list; a layer whose tiles are missing is flagged, not fatal; an
unreadable indicators catalog is a notice in the Indicators section).
`attribution_html` is sanitised (inline tags and http(s) links only) because the base URL can be overridden.

## Deploy

**Live now at <https://oceanmetrics.io/places/>** via GitHub Pages (`.github/workflows/pages.yml`: on push to `main`
touching `web/`, it checks out oceanmetrics/platform next to this repo, checks, tests, builds with `--base=/places/` and deploys; `404.html` is a copy of
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
