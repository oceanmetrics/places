<script lang="ts">
  import { onMount } from 'svelte'
  import Credit from '../lib/Credit.svelte'
  import { BASE, loadManifest, manifest } from '../lib/data.svelte'
  import { calcofiLink, collectionUrl, fmtDate, fmtN, parquetUrl, readmeUrl, withBase } from '../lib/helpers'

  let { slug }: { slug: string } = $props()
  onMount(() => { loadManifest() })

  const layer = $derived(manifest.layers.find((l) => l.slug === slug))
</script>

<main class="page">
  <p class="muted"><a href={withBase('/', BASE)}>Map</a> / layer</p>
  {#if manifest.status === 'loading'}
    <h1>{slug}</h1>
    <p class="muted">Loading…</p>
  {:else if layer}
    <h1>{layer.title}</h1>
    <p class="muted"><code>{layer.slug}</code>{#if layer.authority} · {layer.authority}{/if}{#if layer.place_type} · {layer.place_type}{/if}</p>
    <div class="row">
      <a class="btn" href={withBase(`/?layers=${encodeURIComponent(layer.slug)}`, BASE)}>Add to map</a>
      <a class="btn secondary" href={calcofiLink(layer.slug)} target="_blank" rel="noopener noreferrer">Use in CalCOFI explore</a>
    </div>

    <h2>About</h2>
    <table class="kv">
      <tbody>
        <tr><th>Features (n)</th><td>{fmtN(layer.n)}</td></tr>
        <tr><th>Geometry</th><td>{layer.geom_type}</td></tr>
        <tr><th>Version</th><td>{layer.version ?? '–'}</td></tr>
        <tr><th>Updated</th><td>{fmtDate(layer.updated)}</td></tr>
        <tr><th>README</th><td><a href={readmeUrl(BASE, layer.collection)} target="_blank" rel="noopener noreferrer">collection README</a></td></tr>
        <tr><th>Files</th><td>
          <a href={parquetUrl(BASE, layer.collection)}>places.parquet</a> ·
          <a href={layer.pmtiles}>places.pmtiles</a> ·
          <a href={collectionUrl(BASE, layer.collection)}>collection.json</a>
        </td></tr>
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
      <a class="btn secondary" href={readmeUrl(BASE, slug)} target="_blank" rel="noopener noreferrer">Try the collection README</a>
    </div>
  {/if}
</main>
