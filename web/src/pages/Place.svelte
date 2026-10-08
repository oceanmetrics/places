<script lang="ts">
  import { getPlace, type PlaceFeature } from '@oceanmetrics/places'
  import { onMount } from 'svelte'
  import Credit from '../lib/Credit.svelte'
  import CopyButton from '../lib/CopyButton.svelte'
  import { BASE, manifest, loadManifest } from '../lib/data.svelte'
  import {
    calcofiLink, erddapLink, fmtValue, geojsonSql, layerForPlace, layerPath, parquetUrl, sanitizeHtml, withBase,
  } from '../lib/helpers'

  let { id }: { id: string } = $props()

  let feature = $state<PlaceFeature | null>(null)
  let status = $state<'loading' | 'ok' | 'missing' | 'error'>('loading')
  let message = $state('')

  onMount(async () => {
    await loadManifest()
    try {
      const f = await getPlace(id, { unwrap: true })
      if (f) { feature = f; status = 'ok' } else status = 'missing'
    } catch (e) {
      status = 'error'
      message = String((e as Error).message ?? e)
    }
  })

  const attrs = $derived((feature?.properties ?? {}) as Record<string, unknown>)
  const layer = $derived(feature || manifest.status === 'ok' ? layerForPlace(manifest.layers, id, attrs) : undefined)
  const url = $derived(layer ? parquetUrl(BASE, layer.collection) : '')
  const name = $derived(String(attrs.name ?? id))
  const rows = $derived(Object.entries(attrs).filter(([k]) => k !== 'name' && k !== 'place_id'))
  const sql = $derived(url ? geojsonSql(url, id) : '')
  const geojsonHref = $derived(feature ? URL.createObjectURL(new Blob([JSON.stringify(feature)], { type: 'application/geo+json' })) : '')
  const fileName = $derived(id.replace(/[^\w.-]+/g, '_') + '.geojson')
</script>

<main class="page">
  <p class="muted"><a href={withBase('/', BASE)}>Map</a> / place</p>
  <h1>{status === 'ok' ? name : id}</h1>
  <p class="muted">{id}{#if layer}{' '}· layer <a href={withBase(layerPath(layer.slug), BASE)}>{layer.title}</a>{/if}</p>

  {#if status === 'loading'}
    <p class="muted">Loading from the collection parquet…</p>
  {:else if status === 'missing'}
    <p class="notice">No published collection contains the place <code>{id}</code>. The collection may not be published yet, or the id is wrong.</p>
  {:else if status === 'error'}
    <p class="notice">The place could not be read: {message}</p>
  {/if}

  {#if status === 'ok'}
    <div class="mapbox">
      {#await import('../lib/PlacesMap.svelte')}
        <p class="muted">Loading the map…</p>
      {:then m}
        <m.default highlight={feature} popups={false} />
      {/await}
    </div>

    <h2>Metadata</h2>
    <table class="kv">
      <tbody>
        <tr><th>place_id</th><td>{id}</td></tr>
        {#each rows as [k, v] (k)}
          <tr><th>{k}</th><td>{fmtValue(v)}</td></tr>
        {/each}
      </tbody>
    </table>

    <h2>Licence, attribution and citation</h2>
    {#if layer}
      <Credit {layer} />
    {:else}
      <table class="kv"><tbody>
        <tr><th>Licence</th><td>{fmtValue(attrs.license)}</td></tr>
        <tr><th>Attribution</th><td>{@html sanitizeHtml(String(attrs.attribution ?? '–'))}</td></tr>
      </tbody></table>
      <p class="notice">The layers manifest is not available, so the full citation cannot be shown.</p>
    {/if}

    <h2>Use in</h2>
    <div class="row">
      {#if layer}<a class="btn secondary" href={calcofiLink(layer.slug)} target="_blank" rel="noopener noreferrer">CalCOFI explore</a>{/if}
      <a class="btn secondary" href={erddapLink(id)} target="_blank" rel="noopener noreferrer">erddap-places</a>
      <a class="btn secondary" href={withBase(`/?${layer ? `layers=${layer.slug}&` : ''}place=${id}`, BASE)}>This map</a>
    </div>

    <h2>Download</h2>
    <div class="row">
      {#if url}<a class="btn secondary" href={url}>Collection GeoParquet</a>{/if}
      <a class="btn secondary" href={geojsonHref} download={fileName}>GeoJSON (this place)</a>
    </div>
    {#if sql}
      <h3>Or copy this DuckDB SQL to write GeoJSON from the parquet</h3>
      <pre>{sql}</pre>
      <CopyButton text={sql} label="Copy SQL" />
    {/if}
  {/if}
</main>

<style>
  .mapbox { position: relative; height: 22rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 12px 0; }
  @media (max-width: 600px) { .mapbox { height: 16rem; } }
</style>
