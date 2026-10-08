<script lang="ts">
  import { onMount } from 'svelte'
  import Credit from '../lib/Credit.svelte'
  import { BASE, loadManifest, manifest } from '../lib/data.svelte'
  import { groupByAuthority, layerPath, withBase } from '../lib/helpers'

  onMount(() => { loadManifest() })
  const groups = $derived(groupByAuthority(manifest.layers))
</script>

<main class="page">
  <h1>Credits</h1>
  <p class="muted">
    Every layer keeps the licence and attribution of its source. Please cite the layers you use. All data are processed by Ocean Metrics.
  </p>

  {#if manifest.status === 'loading'}
    <p class="muted">Loading…</p>
  {:else if manifest.status === 'error'}
    <p class="notice">The layers manifest could not be read from <code>{BASE}index/layers.json</code>, so the credits cannot be listed yet. {manifest.error}</p>
  {:else if !groups.length}
    <p class="muted">No layers are published yet.</p>
  {/if}

  {#each groups as g (g.authority)}
    <h2 id={g.authority}>{g.authority}</h2>
    {#each g.layers as l (l.slug)}
      <section class="card">
        <h3><a href={withBase(layerPath(l.slug), BASE)}>{l.title}</a> <span class="chip">{l.version ?? 'no version'}</span></h3>
        <Credit layer={l} />
      </section>
    {/each}
  {/each}
</main>
