<script lang="ts">
  import { BASE } from '../lib/data.svelte'
  import { layersJsonUrl, recipes, REPO_URL, stacRoot, withBase } from '../lib/helpers'

  const r = recipes(`${BASE}boem_wind_leases/places.parquet`)
  const manifestFields = 'slug, title, collection, pmtiles, source_layer, geom_type, n, updated, version, paint, authority, place_type, bbox, attribution, attribution_html, license, license_url, citation'
</script>

<main class="page">
  <h1>Docs</h1>
  <p class="muted">The gazetteer is a set of static files: no server and no API key. Read them from the web, a notebook or an app.</p>

  <h2>STAC catalog</h2>
  <p>The root is a <a href="https://stacspec.org">STAC</a> 1.1 catalog, one collection per source layer.</p>
  <pre>{stacRoot(BASE)}</pre>
  <p>Each collection folder holds <code>places.parquet</code> (GeoParquet 1.1, WKB geometry, EPSG:4326, <code>bbox</code> struct, split at ±180),
    <code>places.pmtiles</code> (vector tiles, layer name = collection slug), <code>style.json</code>, <code>README.md</code>, <code>AGENTS.md</code> and <code>provenance.json</code>.</p>

  <h2>layers.json</h2>
  <p>The manifest apps read: one row per map layer.</p>
  <pre>{layersJsonUrl(BASE)}</pre>
  <p>Fields: <code>{manifestFields}</code>. It is the contract between this site, CalCOFI explore, erddap-places and the atlas.
    The places index (search across all layers, no geometry) is <code>{BASE}index/places_index.parquet</code>.</p>

  <h2>URL grammar</h2>
  <p>The map and the apps share one grammar:</p>
  <pre>?layers=slug[:colour][:opacity][:width],…&amp;place=&lt;place_id&gt;</pre>
  <p>Colour is six hex digits without <code>#</code>, opacity 0 to 1, width 0.5 to 4 px; the first layer is drawn on top and <code>layers=off</code> means none.
    Example: <a href={withBase('/?layers=boem_wind_leases:1b7f9e:0.5:2', BASE)}><code>?layers=boem_wind_leases:1b7f9e:0.5:2</code></a>.</p>

  <h2>Read the parquet</h2>
  <p>Filtering on the <code>bbox</code> struct lets DuckDB skip row groups, so only the matching rows cross the network.</p>
  <h3>DuckDB</h3>
  <pre>{r.duckdb}</pre>
  <h3>Python</h3>
  <pre>{r.python}</pre>
  <h3>R</h3>
  <pre>{r.r}</pre>
  <p class="muted">A place that crosses the antimeridian is stored in two parts; query both sides, or use the JavaScript client's <code>getPlace(id, {'{'} unwrap: true {'}'})</code>.</p>

  <h2>JavaScript client</h2>
  <pre>import {'{'} listLayers, addLayer, search, getPlace, creditsFor {'}'} from '@oceanmetrics/places'</pre>
  <p>The client lists layers, draws them on a MapLibre map, searches the index, fetches one place and builds the credit line. See the
    <a href="{REPO_URL}/tree/main/client">client README</a>.</p>

  <h2>Source and rules</h2>
  <p>Code, sources and the licence tiers are in the repository: <a href={REPO_URL}>{REPO_URL}</a>.</p>
</main>
