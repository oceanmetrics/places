<script lang="ts">
  // the Reports section: the indicators app's report presets that include the place, and a sanctuary's SanctuaryWatch
  // bundle (the Report view builds it). the rules are reports.ts (tested); this only draws.
  import { readCatalog } from './indicators'
  import { reportPresets, swBundleHref, type ReportPreset } from './reports'

  let { placeId, name, placeColls }: { placeId: string; name: string; placeColls: string[] } = $props()

  let presets = $state<ReportPreset[] | null>(null)
  let failed = $state(false)
  $effect(() => {
    const id = placeId, n = name, cs = placeColls
    readCatalog().then(([m, rows]) => { presets = reportPresets(id, n, rows, m, cs) }).catch(() => { failed = true })
  })
  const sw = $derived(swBundleHref(placeId))
</script>

<section aria-labelledby="reports-h">
  <h2 id="reports-h">Reports</h2>
  {#if failed}
    <p class="notice">The indicators catalog could not be read, so the reports that include this place cannot be listed.</p>
  {:else if presets === null}
    <p class="muted" aria-live="polite">Reading the report presets…</p>
  {:else if !presets.length}
    <p class="muted">No report of the indicators app includes this place yet: nobody has computed its indicators.</p>
  {:else}
    <ul class="presets">
      {#each presets as p (p.href)}
        <li><a href={p.href} target="_blank" rel="noopener noreferrer">{p.title} ↗</a> <span class="muted">· {p.note}</span></li>
      {/each}
    </ul>
    {#if sw}
      <p><a class="btn secondary small" href={sw} target="_blank" rel="noopener noreferrer">SanctuaryWatch bundle ↗</a>
        <span class="muted">The Report view of this sanctuary builds it: Export, then "SanctuaryWatch bundle (zip)" (each indicator's job files with its figure, in one ZIP).</span></p>
    {/if}
  {/if}
</section>

<style>
  .presets { margin: 4px 0 8px; padding-left: 1.2rem; }
  .presets li { margin: 3px 0; overflow-wrap: anywhere; }
</style>
