# web/

The website at places.oceanmetrics.io: search the places index, browse layers on a map, and read the licence and
citation of everything on screen; each place's page is the Place page of the Ocean Metrics vision (one URL per
gazetteer id). Svelte 5 + Vite + TypeScript + MapLibre GL 6 through `@oceanmetrics/map`, a static SPA with
client-side routing. Data comes from the `@oceanmetrics/places` client (since 2026-10-22 in
[oceanmetrics/platform `packages/places`](https://github.com/oceanmetrics/platform/tree/main/packages/places), installed from npm;
a client change is made and released there, then the range in `package.json` is bumped here), which reads `layers.json`, the places index, GeoParquet and PMTiles straight from object storage.

The top bar is the shared Ocean Metrics bar, `<om-nav current="places">` from `@oceanmetrics/nav` (`src/App.svelte`: the doors Places / Indicators /
Atlas, the place search, What changed, Docs; it collapses to the mark and a menu button below 860 px). The site's own links (Map, Credits, Data) and the
theme toggle sit in its slot, styled in `src/app.css` (`.app-nav`, `.theme-toggle`); the bar follows `<html data-theme>` itself. Its search is
cancelled in `App.svelte` (`navSearchTarget`, `helpers.ts`) and routed in-app to `/?q=<text>`, which the home page's search field starts from
(`queryOf`); `changes-href` points at oceanmetrics.io/docs/ until the change feed page exists.

| route | page |
|---|---|
| `/` | search + browse map with layer toggles; reads and writes `?layers=slug[:colour][:opacity][:width],…&place=<place_id>` |
| `/p/<place_id>` | the Place page: map with the layer under it, indicators, species, layers, reports, same place in other layers, metadata, licence, "use in", downloads; reads `?layer=<kind>:<id>[:<variable>]&t=<period>` |
| `/l/<slug>` | layer page: n, version, updated, licence, attribution, citation, README, "Add to map" |
| `/credits` | every layer's attribution and citation, grouped by authority |
| `/docs` | STAC root, the `layers.json` contract, DuckDB / Python / R recipes |

## Develop

```sh
cd web
npm install          # @oceanmetrics/places and @oceanmetrics/catalog from npm (their built dist/); no sibling checkout
npm run dev          # http://localhost:5180
npm test             # vitest: URL grammar, helpers, the indicators slot, the map rules, layers, species, reports, downloads (synthetic fixtures, no network)
npm run check        # svelte-check
npm run build        # dist/
npm run size         # the size budget over dist/ (below); pages.yml runs it after the build
node scripts/shoot.mjs [--url http://localhost:5180/] [--only NMS:CINMS | home]   # home and place page screenshots -> docs/shots/; look at them
```

`scripts/shoot.mjs` (Playwright, headless Google Chrome through `channel: "chrome"`, else Playwright's chromium after
`npx playwright install chromium`) serves `dist/` with `vite preview` unless `--url` names a running server, opens the CPO
task force's two sanctuaries, `/p/NMS:CINMS?layer=grid:jplMURSST41mday:sst&t=2024-07` (with the MUR SST slice of July
2024 under the map) and `/p/NMS:FGBNMS`, at 390 px and 1280 px in light and dark (the theme is set as `localStorage`
`om-theme` before load), waits until no section is loading and the slice is in, and saves two parts (the home page too: `docs/shots/home_<width>_<theme>.png`, and at 390 px `..._menu.png` with the bar's menu open):
`docs/shots/place_<id>_<width>_<theme>.png` (the top: title, map, layer, the first indicator cards) and
`..._sections.png` (Species, Layers, Reports). It reads the live catalogs and warns when a page is wider than the window.
The committed shots were made small with a palette (sharp `png({ palette: true, quality: 80 })`, run from a scratch
folder, about a quarter of the size).

If vitest cannot create its temp dir in a sandbox, set `TMPDIR` to a writable directory.

Data base URL: `https://storage.oceanmetrics.io/gazetteer/` by default; override at build time with
`VITE_PLACES_BASE=https://…/` or at run time with `?base=https://…/` (internal links keep it). To develop offline, serve
the client repo's `packages/places/test/fixtures/` (oceanmetrics/platform) with CORS and Range support and use `?base=http://127.0.0.1:<port>/`.

## The Place page

`/p/<place_id>` (`src/pages/Place.svelte`) is the front door of the vision ("The Place page as the front door"): one URL
per gazetteer id, the sections in this order, each a component that only draws, with its rules in a plain tested `.ts`:

1. **Title** and the source link.
2. **The map** (`src/lib/PlacesMap.svelte`, shared with the home and layer pages): MapLibre 6 through `@oceanmetrics/map`
   `setupMapLibre`, once a page (`src/lib/map/setup.ts`; the worker chunk is `.mjs`, `vite.config.ts` `worker`), the style
   `composeStyle` builds (`src/lib/map/basemap.ts`): CARTO's positron or dark-matter with the GEBCO 2025 sea floor,
   isobaths, the OSM land mask and the GEBCO undersea names, both themes. It boots on CARTO's own style and turns the
   tiers on at `load`; the tiers are read from the bucket's path-style url `BASEMAP_BUCKET`
   (`https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/basemap/`) because `storage.oceanmetrics.io/basemap/`
   answers 404 until the DNS cutover: set `BASEMAP_BUCKET` to the package's `BASEMAP_URL` then. A theme flip is
   `setStyle(..., { diff: true, transformStyle: carryLayers(id => !basemap.has(id)) })` with `basemapLayerIds` of the style
   set; the place layers go back under the names (`placesBeforeId`), the highlight is redrawn, and the layer under the map
   stays under the land mask (`seaSurfaceId`).
   **The layer under the map**: `?layer=grid:<dataset>:<variable>&t=<period>` (`src/lib/grammar.ts`; `t` is a year, month
   or day, absent = the latest; both are carried from page to page like `proj`). The "Layer under the map" select lists
   every variable of the gridded ERDDAP collections of the gazetteer's STAC catalog (`erddap/<id>/collection.json`,
   `src/lib/map/gridLayer.ts` `layerChoices`; masks, counts and error bands left out), with a month and the legend line
   (`legendLine`: title, period, how it is drawn, the range). The slot is `@oceanmetrics/map` `gridSlot` over
   `@oceanmetrics/engine` `sliceSource` of the place's own lobes (`placeLobes` on the polygon as published, split at ±180;
   `lobeAxes`, `lobeMasks`, `fetchTimeExtent`), registered with `registerSlotKind('grid', gridKind(placeId))`
   (`src/lib/map/gridKind.ts`). The engine and DuckDB-WASM 1.32 (self-hosted mvp and eh bundles, `?url`) are the lazy
   chunk `src/lib/map/gridSource.ts`, loaded on the first slice. A place over the cell budget (250,000 cells a request,
   600,000 a step) says so. The ERDDAP mirror at erddap.oceanmetrics.io answered the same url 404 and 200 by turns on
   2026-10-23, so every slice request goes through `patientFetch` (asks again after a 404 or a 5xx, six tries).
3. **Indicators** (below): led by the roll-up line (`src/lib/reports.ts` `summaryLine` over `@oceanmetrics/catalog`
   `rollups`): "N indicators with a value: a above, w within, b below the place's own record, n without a status; latest
   <period>".
4. **Species** (`src/lib/species.ts`, the reads in the lazy `speciesRead.ts`):
   - *OBIS records in the place*: the obis-h3 release (`obis-h3/latest.json` -> `place_exact/coll=<coll>/indicators.parquet`,
     the place's own collection first, then its copies'), the `eov='all'` rows: records `n`, species `sp` and ES(50) `es`
     for every year and by decade, the latest decade in the line, species by EOV group, with Reproduce (the file and a
     DuckDB query). They are counted point-in-polygon on the place itself.
     **Species with records in the place** (since 2026-10-23): the same folder's `species.parquet` (`place_id, aphiaid,
     name_key, n, year_min, year_max`, the exact per-place species of the same pass, all places of the collection in one
     file sorted by `place_id`). `readPlaceSpeciesRows` reads the footer (the last 64 kB), then only the row groups whose
     `place_id` min/max statistics can hold the place (`groupsHoldingText`; a place may span two), filtered by `place_id`;
     a file under 1 MB is fetched once whole. Measured 2026-10-23 (release v20261012): the sanctuaries' file
     (`coll=places`, 202 kB) is one row group, so the whole file, 202 kB a page (the same as no pruning); `coll=mr_eez`
     (4.97 MB, 6 row groups of 122,880 rows) is 0.94 MB for a place in one group and 1.83 MB for one that spans two, against
     4.97 MB whole; `coll=fao_high_seas` 510 kB (one group). The names come from the release's `species/species.parquet`
     (one row per `aphiaid`; columns `aphiaid, species, class` read, 1.68 MB for a page, once per page load: two row groups,
     so no pruning is possible). `placeSpecies` merges the rows of one `name_key` (richness counts names, not aphiaids: CINMS
     has 2,266 aphiaids of 2,258 names), sums the records, spans first and last year, and ranks by records then name.
     The table shows the first 20 ("Show all N"), species with a WoRMS link, the group (the EOV group when the lookup has
     an `eov` column, else the OBIS class: the release's lookup has no `eov` or `redlist_code` column yet, so today it is the
     class), records and first-last year; a CSV (`placeSpeciesCsv`); "Explore in OBIS" (the OBIS mapper) and the OBIS
     checklist (JSON) for the place's box (`bboxWkt`, two boxes across +-180), which is a box, not the boundary.
     **The count line** "N species with records in the place (exact), M in the latest decade (the 2020s)" is the list's own
     count (`speciesCounts`: N names; M names whose last year is in or after the latest decade of the indicators), and it
     must equal `sp` of the `indicators.parquet` row (`eov='all'`, decade null; the latest decade). `speciesCheck` writes
     the warning line the page shows when they differ (two files of different releases). The rule held for all 318 places
     of the four collections on 2026-10-23, checked with DuckDB, and is asserted on a synthetic fixture in
     `species.test.ts` and `speciesRead.test.ts` (a tiny species.parquet written in the test with hyparquet-writer).
     CINMS: 2,258 species, 668 in the 2020s; FGBNMS: 469, 160 (both equal `sp`).
   - *Species on the map* (since 2026-10-23, `src/lib/obisLink.ts` `placeObisUrl`): under the OBIS heading, "Species on the map
     (Ocean Metrics Atlas, OBIS H3 layer)" opens `https://oceanmetrics.io/atlas/?c=obis_h3&i=all&dim.indicator=es&dim.period=all&res=auto&map=<lon,lat,zoom>&collection=<OBIS_COLLECTION_HREF>#pl=<p. token>`
     with the place selected and the camera on its box (zoom `log2(600/span)`, clamped 1..10). The rule is the atlas's own
     (oceanmetrics/atlas `src/lib/state/obisPlace.ts`, `docs/obis-layer.md`), ported with its test cases in `obisLink.test.ts` (the CINMS
     url byte for byte, a box across 180, the zoom clamps). `OBIS_COLLECTION_HREF` (the bucket's `obis-h3/collection.json`) rides along as
     `&collection=` so the link works before `atlas/catalog.json` lists obis_h3: drop it then (one constant and its test). The per-species WoRMS links stay.
   - *Species from AquaMaps*: the atlas collection `aquamaps_eov` declares `atlas:cell_species`, a cell -> species table in
     5° tiles of the 0.05° grid (not H3). The place's cells are the cells whose centre falls in its polygon (exact on the
     native grid; a part too small for a centre keeps the cell under it: `placeCells`), only the tiles' row groups whose
     `cell_id` range holds one are read (`groupsHolding`), joined with `species.parquet` (`sdmSpecies`: most cells first,
     then the mean suitability). CINMS: 152 cells in 2 tiles, 920 species; FGBNMS: 26 cells, 1,320 species (2026-10-23). A
     table of the first 20, "Show all", a CSV (`sdmCsv`) and the atlas link; the AquaMaps EOV citation and its licence (CC
     BY-NC 3.0). The place's H3 membership is not a step here: the tiles are keyed on the 0.05° grid, so the exact mask is
     both simpler and the record.
5. **Layers that cover this place** (`src/lib/layers.ts` `layersCovering`): the atlas collections
   (`atlas/catalog.json`, its MarineSensitivity children by reference) and the gazetteer's ERDDAP layers whose extent meets
   the place's box (either may cross ±180 or be unwrapped), regional ones listed, the global ones folded with the line
   saying how many are global, since a box says little about where a global layer has data; a check by data cell waits
   on the atlas collections' H3 cells. Atlas links open the collection with the place by reference:
   `https://oceanmetrics.io/atlas/?c=<collection>#pl=<p. token>` (`placeToken`, the `g1` encoding of atlas
   `docs/gazetteer-places.md`, escaped once more for the atlas's `URLSearchParams`); gridded ERDDAP layers open under this
   page's map.
6. **Reports** (`src/lib/reports.ts`): the indicators app's Report view (`#view=report&pi=<id>`) for the place alone, the
   default selection (`coll:places`, the sanctuaries) when the place's values are there, each manifest `place_sets` entry
   whose groups hold one of the place's collections (`set:political` for an EEZ or a high-seas area), and for an `NMS:*`
   place the SanctuaryWatch bundle, which the Report view builds (Export, "SanctuaryWatch bundle (zip)").
7. **Same place in other layers**, **Metadata**, **Licence, attribution and citation**, **Use in**.
8. **Downloads**: *Values of this place's indicators* as CSV or Parquet (`src/lib/downloads.ts` `downloadValues`, a lazy
   chunk: every values file the place's coverage rows list, read whole with one fetch each, filtered to the place,
   concatenated with a `source` column; Parquet by hyparquet-writer with `time` as an ISO date string; FGBNMS: 13,458 values
   from 80 files), then the boundary as before (the collection's GeoParquet, the place's GeoJSON, the DuckDB SQL).

## Indicators on the place page

The place page shows the place's indicators right after the map (`src/lib/Indicators.svelte`). The rules are
`@oceanmetrics/catalog/indicators` (oceanmetrics/platform `packages/catalog`, 0.3.0: the one implementation of the cards,
shared with the indicators viewer, and tested there); `src/lib/indicators.ts` only wires them to this site (the catalog
base, the dated "not computed yet" sentence), checked in `indicators.test.ts` with `src/lib/fixtures/` (a copy of the
package's fixtures: `indicators.json`, and `coverage.parquet` made by `make_coverage.sql`). It reads the Ocean Metrics indicators catalog
(oceanmetrics/indicators): `indicators.json` (the manifest: titles, units, series, leads, status method, dataset citation)
and `coverage.parquet` (one row per place × indicator × grain with the last value, status, trend and the method's
sentence, all computed there with `@oceanmetrics/status`; nothing here computes a status). Each card has the title, the
last value with its unit, the period (by grain: `2025`, `2025-07`, `the 2020s`), the status glyph and caption (shapes
from the indicators viewer: a ring with a plus, a filled centre, a minus, a dashed ring for none; captions say "its own
record"), the sentence, method (label and note) and the citation with the place in its "Values:" clause under a
disclosure, a "Reproduce" disclosure (the values parquet url, a DuckDB query for the place's rows, the config lines and
their hash), and "Open in Indicators ↗", the indicators app's Place
view (`https://oceanmetrics.io/indicators/#view=place&place=<id>&coll=<coll>&ind=<indicator>`). Leads show first, then
"Show all"; the OBIS series that are not leads fold into one "no status rule" line with a count. With no cards the
section says which absence applies: **no data here** (the catalog covers the place's layer but has no value for it) or
**not computed yet** (nobody computed the place, whatever its layer: indicators for every gazetteer place arrive in
build week 3, 2026-11-13 to 11-19, a sentence this site passes to the package; until then the link goes to ERDDAP
Places). `readCatalog()` (`src/lib/indicators.ts`) reads the two files once a page for every section that needs them
(Indicators, Reports, Downloads).

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

## Deep links and link previews

GitHub Pages answers a path it has no file for with `404.html` (`pages.yml` copies `index.html` there), so a deep link that only
exists in the router has the status 404, one shared `<title>`, and nothing for a crawler or a chat link preview to read.
`npm run build` therefore ends with `scripts/prerender-shells.mjs` (npm's `postbuild`, so `npm run build -- --base=/places/` in
`pages.yml` runs it too): it writes `dist/<route>/index.html` for a chosen set of pages, each the built `index.html` with the
page's own head, and the app mounts over it as usual. A folder with an `index.html` answers 200 (Pages redirects `/p/NMS:CINMS` to
`/p/NMS:CINMS/`; `matchRoute` takes the trailing slash, and the built asset urls are absolute under the base, so they resolve from
the deeper path). Every other place still goes through `404.html`.

Each shell has `<title>` ("<name> · Places · Ocean Metrics"), `<meta name="description">`, `<link rel="canonical">`, Open Graph
(`og:title`, `og:description`, `og:url`, `og:type` website, `og:image`, `og:site_name`), the Twitter card and a JSON-LD
schema.org `Place` (`name`, `identifier`, `url`, `geo` as a `GeoShape` box from the index bbox, south west north east). The
description is the place's layer title, its authority and what it is (`placeDescription`). `og:image` is `favicon.svg`, the only
image in `public/`; most chat apps do not draw an SVG preview image, so a 1200x630 PNG in `public/` and the `image` constant in
the script is the next step. The app sets the same title once it has mounted (`Place.svelte`, `LayerPage.svelte`).

| shell | pages | from |
|---|---|---|
| `/p/<id>/` | the 18 `NMS:*` sanctuaries (`NMSAS`, `HIHWNMS`, `FGBNMS`, `OCNMS`, `MBNMS`, `CBNMS`, `GFNMS`, `CHNMS`, `CINMS`, `MNMS`, `MBPR`, `SBNMS`, `LONMS`, `WSCNMS`, `TBNMS`, `PMNM`, `GRNMS`, `FKNMS`), plus any you add | the published index (`places_index.parquet`) read with the `@oceanmetrics/places` client |
| `/l/<slug>/` | every public layer (52 on 2026-10-23); JSON-LD `Dataset` | `layers.json` |
| `/credits/`, `/docs/` | the two static pages | the script |

The home page is `index.html` itself. The pure parts (titles, descriptions, escaping, JSON-LD, the head rewrite) are
`scripts/shell-lib.mjs`, tested in `src/lib/shells.test.ts`.

To add places: `PRERENDER_IDS="MPAINV:NMS9 <more ids>" npm run build`, or `node scripts/prerender-shells.mjs --ids=MPAINV:NMS9,<more ids>`
on a built `dist/`; for a standing addition put the id in the `pages.yml` build step's `env: PRERENDER_IDS`. An id that is not
in the index is skipped with a warning; the build fails if the set is over `--limit` (default 100, raise it on purpose) or the
index has no `NMS:` place. Other flags and env: `--data` / `PRERENDER_BASE` (the gazetteer url; default the S3 path-style url, as the
Place page's basemap), `--origin` / `PRERENDER_ORIGIN` (default `https://oceanmetrics.io`), `--dist`, `PRERENDER_SKIP=1` to build
offline with no shells. The shells are written at build time, so a renamed place shows its old name until the next deploy.

## Size budget

`scripts/size-budget.mjs` (`npm run size`, in `pages.yml` after the build) sums the gzip (level 9) of the built JS and CSS
by when they load, told apart by Vite's manifest; a line over its budget fails the job. Raise a line only with the reason
written here. Set on 2026-10-23 from a measurement, with about 10 % headroom:

| line | what | measured | budget |
|---|---|--:|--:|
| entry JS | what `index.html` loads up front: router, pages, the places client with hyparquet and its codecs, the indicator cards | 161.2 kB (2026-10-23, with the shared bar `@oceanmetrics/nav`, about +3 kB) | 172 kB |
| map JS | `PlacesMap.svelte`'s chunk: MapLibre 6, `@oceanmetrics/map`, the basemap and the slot | 299.3 kB | 330 kB |
| engine JS | `map/gridSource.ts`: `@oceanmetrics/engine`, Apache Arrow, the mask, DuckDB-WASM's JS API (on the first slice) | 63.2 kB | 70 kB |
| rest JS | the other lazy chunks: the species reader, the values download (hyparquet-writer) | 17.8 kB | 24 kB |
| CSS | the site's styles | 3.5 kB | 5 kB |
| map CSS | MapLibre's stylesheet and the map's | 10.4 kB | 12 kB |

Not budgeted, and printed: DuckDB-WASM's worker scripts (381 kB) and wasm (eh 7.6 MB, mvp 8.7 MB gzip, fetched by the
engine's worker on the first slice), MapLibre's worker module (147 kB), and geotiff's decoders that the map package's COG
protocol would import (never requested: no `cog` slot here).

## Analytics

Off unless the repository variable **`VITE_GA_ID`** (Settings -> Secrets and variables -> Actions -> Variables) holds a
GA4 measurement id. `pages.yml` passes it to `vite build`; `src/lib/ga.ts` `gaId()` keeps it only when it matches
`^G-[A-Z0-9]{4,16}$`, and `App.svelte` sets it on the bar as `<om-nav data-ga>`. The bar (`@oceanmetrics/nav` >= 0.2.0,
README "Analytics") loads gtag.js once, with `anonymize_ip`, no Google signals and no ad personalization, and sends a
page_view on load and on each route change (pushState, popstate) with a rebuilt `page_location`: origin + path, never
the query (`?q=`, `layers=`, `place=`) or a fragment. No id is written in the repo.

- `npm test`: `src/lib/ga.test.ts` (the id rule, and `scripts/check-ga.mjs` on small dists).
- `npm run check:ga` (after a build; `pages.yml` runs it with `--id "$VITE_GA_ID"`): no page carries a gtag.js script
  tag, and a measurement id is in the bundle exactly when one was given.
- `npm run e2e:ga [-- --id G-TEST000000]` (after a build with or without `VITE_GA_ID=G-TEST000000`): the built site in
  headless Chrome, every request off its origin aborted, opened with a polygon, a title and a search in its url and
  moved by pushState, replaceState and the hash. Unset: no script tag, no dataLayer. Set: one script tag,
  `anonymize_ip: true`, `send_page_view: false`, and no gtag() call or request carries the query or the fragment.

The GA4 stream's enhanced measurement "Page changes based on browser history events" must be off (the nav README says why).

## Deploy

**Live now at <https://oceanmetrics.io/places/>** via GitHub Pages (`.github/workflows/pages.yml`: on push to `main`
touching `web/`, it runs `npm ci`, checks, tests, builds with `--base=/places/` and deploys; `404.html` is a copy of
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
