<script lang="ts">
  // the "Layer under the map" control of the place page: the select (none, then each variable of the gazetteer's gridded
  // ERDDAP collections, map/gridLayer.ts `layerChoices`), the period, and the legend line with the ramp. it writes
  // `layer=` and `t=` into the query (grammar.ts); the map reads them back. no rules here.
  import type { LegendSpec } from '@oceanmetrics/map'
  import { buildSearch } from './grammar'
  import { layerChoices, legendLine, type ErddapLayer } from './map/gridLayer'
  import { loc, navigate } from './router.svelte'

  let { layers, layerKey, t, legend }: { layers: ErddapLayer[]; layerKey: string | null; t: string | null; legend: LegendSpec | null } = $props()

  const choices = $derived(layerChoices(layers, layerKey))
  const groups = $derived([...new Set(choices.slice(1).map((c) => c.group ?? ''))])
  const current = $derived(layers.find((l) => layerKey?.startsWith(`grid:${l.id}:`) || layerKey === `grid:${l.id}`) ?? null)
  const month = $derived(!t ? '' : t.length >= 7 ? t.slice(0, 7) : `${t}-01`)
  const bounds = $derived(current ? [current.time[0]?.slice(0, 7) ?? '', current.time[1]?.slice(0, 7) ?? ''] : ['', ''])
  const set = (v: { layer?: string | null; t?: string | null }) => navigate(loc.path + buildSearch(v, loc.search), { replace: true })
  const gradient = $derived(legend?.ramp ? `linear-gradient(to right, ${legend.ramp.colors.join(', ')})` : '')
</script>

<div class="under">
  <label>
    <span>Layer under the map</span>
    <select value={layerKey ?? ''} onchange={(e) => set({ layer: (e.currentTarget as HTMLSelectElement).value || null })}>
      <option value="">None</option>
      {#each groups as g (g)}
        <optgroup label={g}>
          {#each choices.filter((c) => c.group === g) as c (c.value)}<option value={c.value}>{c.label}</option>{/each}
        </optgroup>
      {/each}
    </select>
  </label>
  {#if layerKey}
    <label>
      <span>Month</span>
      <input type="month" value={month} min={bounds[0] || undefined} max={bounds[1] || undefined}
        onchange={(e) => set({ t: (e.currentTarget as HTMLInputElement).value || null })} />
    </label>
    {#if t}<button class="btn secondary small" type="button" onclick={() => set({ t: null })}>Latest</button>{/if}
  {/if}
</div>
{#if legend}
  <p class="legend muted" aria-live="polite">
    {#if gradient}<span class="ramp" style:background={gradient} aria-hidden="true"></span>{/if}
    <span>{legendLine(legend)}</span>
  </p>
{/if}

<style>
  .under { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: flex-end; margin: 4px 0 0; }
  .under label { display: flex; flex-direction: column; gap: 2px; font-size: 13px; color: var(--text-muted); min-width: 0; max-width: 100%; }
  .under select, .under input { max-width: min(100%, 28rem); padding: 6px 8px; background: var(--bg-card); border: 1px solid var(--border); border-radius: 6px; color: var(--text); }
  .legend { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; font-size: 12.5px; margin: 6px 0 0; overflow-wrap: anywhere; }
  .ramp { display: inline-block; width: 7rem; height: 10px; border-radius: 2px; box-shadow: 0 0 0 1px var(--border); flex: none; }
</style>
