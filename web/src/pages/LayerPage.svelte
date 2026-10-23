<script lang="ts">
  import { onMount } from 'svelte'
  import Credit from '../lib/Credit.svelte'
  import { BASE, loadManifest, manifest } from '../lib/data.svelte'
  import { layerLabel } from '@oceanmetrics/places'
  import { layerPageTitle } from '../../scripts/shell-lib.mjs'
  import { calcofiLink, collectionDir, collectionUrl, derivedLine, drawable, fmtDate, fmtN, layerPath, parquetUrl, viaTitle, withBase } from '../lib/helpers'

  let { slug }: { slug: string } = $props()
  onMount(() => { loadManifest() })

  const layer = $derived(manifest.layers.find((l) => l.slug === slug))
  $effect(() => { document.title = layerPageTitle(layer ? layer.title : slug) })
  const sel = $derived([{ slug, colour: null, opacity: null, width: null }])
  const tileHost = (u: string | undefined) => { try { return u ? new URL(u.replace(/[{}]/g, '')).host : '–' } catch { return '–' } }
</script>

<main class="page">
  <p class="muted"><a href={withBase('/', BASE)}>Map</a> / layer</p>
  {#if manifest.status === 'loading'}
    <h1>{slug}</h1>
    <p class="muted">Loading…</p>
  {:else if layer}
    <h1>{layerLabel(layer)}</h1>
    <p class="muted"><code>{layer.slug}</code>{#if layer.authority} · {layer.authority}{/if}{#if layer.place_type} · {layer.place_type}{/if}</p>
    <div class="row">
      <a class="btn" href={withBase(`/?layers=${encodeURIComponent(layer.slug)}`, BASE)}>Add to map</a>
      <a class="btn secondary" href={calcofiLink(layer.slug)} target="_blank" rel="noopener noreferrer">Use in CalCOFI explore</a>
    </div>

    {#if layer.kind === 'derived'}
      <p class={drawable(layer, manifest.layers) ? 'muted' : 'notice'}>{derivedLine(layer, manifest.layers)}</p>
    {/if}
    <div class="mapbox">
      {#await import('../lib/PlacesMap.svelte')}
        <p class="muted">Loading the map…</p>
      {:then m}
        <m.default selected={sel} layers={manifest.layers} fit={layer.bbox} />
      {/await}
    </div>

    <h2>About</h2>
    <table class="kv">
      <tbody>
        <tr><th>Features (n)</th><td>{fmtN(layer.n)}</td></tr>
        <tr><th>Geometry</th><td>{layer.geom_type}</td></tr>
        <tr><th>Version</th><td>{layer.version ?? '–'}</td></tr>
        <tr><th>Updated</th><td>{fmtDate(layer.updated)}</td></tr>
        <tr><th>README</th><td><a href={collectionDir(BASE, layer.collection)} target="_blank" rel="noopener noreferrer">collection README</a></td></tr>
        {#if layer.kind === 'raster'}
          <tr><th>Map tiles</th><td>served by <code>{tileHost(layer.raster?.tiles?.[0])}</code> (the publisher's own tile service)</td></tr>
          <tr><th>Data</th><td>
            {#if layer.raster?.link}<a href={layer.raster.link} target="_blank" rel="noopener noreferrer">at the publisher</a> · {/if}
            <a href={collectionUrl(BASE, layer.collection)}>collection.json</a> (metadata only: no copy of the data here)
          </td></tr>
        {:else if layer.kind === 'derived'}
          <tr><th>Drawn by</th><td>
            <a href={withBase(layerPath(layer.display?.via ?? ''), BASE)}>{viaTitle(layer, manifest.layers)}</a>
            (each place is shown as its feature there, matched on <code>{layer.display?.id_from}</code>)
          </td></tr>
          <tr><th>Data</th><td>
            <a href={collectionUrl(BASE, layer.collection)}>collection.json</a> (metadata only: the geometry of these places stays internal, so there is no parquet or PMTiles)
          </td></tr>
        {:else}
          <tr><th>Files</th><td>
            <a href={parquetUrl(BASE, layer.collection)}>places.parquet</a> ·
            <a href={layer.pmtiles}>places.pmtiles</a> ·
            <a href={collectionUrl(BASE, layer.collection)}>collection.json</a>
          </td></tr>
        {/if}
      </tbody>
    </table>

    <h2>Licence, attribution and citation</h2>
    <Credit {layer} />
  {:else}
    <h1>{slug}</h1>
    <p class="notice">
      {#if manifest.status === 'error'}
        The layers manifest could not be read from <code>{BASE}index/layers.json</code>, so this layer's details are not available. {manifest.error}
      {:else}
        There is no layer <code>{slug}</code> in the manifest. It may not be published yet.
      {/if}
    </p>
    <div class="row">
      <a class="btn secondary" href={collectionDir(BASE, slug)} target="_blank" rel="noopener noreferrer">Try the collection README</a>
    </div>
  {/if}
</main>

<style>
  .mapbox { position: relative; height: 22rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 12px 0; }
  @media (max-width: 600px) { .mapbox { height: 16rem; } }
</style>
