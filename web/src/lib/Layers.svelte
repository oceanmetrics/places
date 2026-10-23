<script lang="ts">
  // "Layers that cover this place": the atlas collections and the gazetteer's ERDDAP layers whose extent meets the place's
  // box (layers.ts `layersCovering`, tested), each with its way in: the atlas opened on the collection with the place, or
  // this page's map with the layer under it. no rules here.
  import { atlasHref, coverLine, erddapLayer, layersCovering, loadAtlasCollections, type Box, type CoverLayer, type Covering } from './layers'
  import type { ErddapLayer } from './map/gridLayer'
  import { buildSearch } from './grammar'
  import { loc } from './router.svelte'

  let { placeId, name, bbox, erddap }: { placeId: string; name: string; bbox: Box | null; erddap: ErddapLayer[] } = $props()

  let atlas = $state<CoverLayer[]>([])
  let phase = $state<'loading' | 'ok' | 'error'>('loading')
  $effect(() => {
    loadAtlasCollections().then((a) => { atlas = a; phase = 'ok' }).catch(() => { atlas = []; phase = 'error' })
  })
  const hits = $derived(layersCovering({ bbox }, [...atlas, ...erddap.map(erddapLayer)]))
  const regional = $derived(hits.filter((h) => !h.global))
  const global = $derived(hits.filter((h) => h.global))
  const underHref = (key: string) => loc.path + buildSearch({ layer: key }, loc.search)
</script>

<section aria-labelledby="layers-h">
  <h2 id="layers-h">Layers that cover this place</h2>
  {#if phase === 'loading'}
    <p class="muted loading" aria-live="polite">Reading the atlas and ERDDAP catalogs…</p>
  {:else}
    {#if phase === 'error'}<p class="notice">The atlas catalog could not be read; the ERDDAP layers follow.</p>{/if}
    <p class="muted">{coverLine(hits)}</p>
    {#snippet list(xs: Covering[])}
      <ul class="cover">
        {#each xs as h (h.source + ':' + h.id)}
        <li>
          <span class="t">{h.title}</span>
          <span class="muted">{' · '}{h.source === 'atlas' ? 'atlas' : 'ERDDAP'}{h.note ? ` · ${h.note}` : ''}</span>
          {#if h.source === 'atlas'}
            <a href={atlasHref(h.id, placeId, name)} target="_blank" rel="noopener noreferrer">Open in the atlas with this place ↗</a>
          {:else if h.layerKey}
            <a href={underHref(h.layerKey)}>Under the map</a>
          {/if}
        </li>
        {/each}
      </ul>
    {/snippet}
    {#if regional.length}{@render list(regional)}{/if}
    {#if global.length}
      <details open={!regional.length}>
        <summary>{global.length} global {global.length === 1 ? 'layer' : 'layers'} ({global.filter((g) => g.source === 'atlas').length} atlas, {global.filter((g) => g.source === 'erddap').length} ERDDAP)</summary>
        {@render list(global)}
      </details>
    {/if}
  {/if}
</section>

<style>
  .cover { margin: 4px 0 8px; padding-left: 1.2rem; }
  .cover li { margin: 3px 0; overflow-wrap: anywhere; }
  .cover a { margin-left: 6px; white-space: nowrap; }
  .t { color: var(--text); }
  details summary { cursor: pointer; color: var(--link); margin: 4px 0; }
</style>
