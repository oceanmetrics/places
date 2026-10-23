<script lang="ts">
  // the Species section: OBIS records counted on the place's own polygon (the obis-h3 release's place_exact), and the
  // AquaMaps species suitable in the place's 0.05 degree cells (the atlas's `atlas:cell_species` tiles). the rules are
  // species.ts (tested); the reads are speciesRead.ts, a lazy chunk. this only draws.
  import CopyButton from './CopyButton.svelte'
  import { atlasHref } from './layers'
  import { eovLabel, obisLine, obisLinks, sdmCsv, sdmLine } from './species'
  import type { ObisResult, SdmResult } from './speciesRead'

  let { placeId, name, geometry, bbox, colls }: {
    placeId: string; name: string; geometry: { type: string; coordinates: unknown } | null; bbox: number[] | null; colls: string[]
  } = $props()

  let obis = $state<{ phase: 'loading' | 'ok' | 'none' | 'error'; r: ObisResult | null; msg: string }>({ phase: 'loading', r: null, msg: '' })
  let sdm = $state<{ phase: 'loading' | 'ok' | 'large' | 'error'; r: SdmResult | null; msg: string }>({ phase: 'loading', r: null, msg: '' })
  let all = $state(false)
  const SHOWN = 20

  $effect(() => {
    const id = placeId, cs = colls, g = geometry
    void import('./speciesRead').then((m) => {
      m.readObis(id, cs).then((r) => { obis = { phase: r ? 'ok' : 'none', r, msg: '' } }).catch((e) => { obis = { phase: 'error', r: null, msg: String(e?.message ?? e) } })
      if (!g) { sdm = { phase: 'large', r: null, msg: '' }; return }
      m.readSdm(g).then((r) => { sdm = r ? { phase: 'ok', r, msg: '' } : { phase: 'large', r: null, msg: '' } }).catch((e) => { sdm = { phase: 'error', r: null, msg: String(e?.message ?? e) } })
    })
  })

  const links = $derived(bbox ? obisLinks(bbox) : null)
  const sql = $derived(obis.r ? `SELECT * FROM '${obis.r.url}'\nWHERE place_id = '${placeId.replaceAll("'", "''")}' ORDER BY eov, decade NULLS FIRST;` : '')
  const csvHref = $derived(sdm.r ? URL.createObjectURL(new Blob([sdmCsv(placeId, sdm.r.species)], { type: 'text/csv' })) : '')
  const csvName = $derived(`aquamaps_species_${placeId.replace(/[^\w.-]+/g, '_')}.csv`)
  const shown = $derived(sdm.r ? (all ? sdm.r.species : sdm.r.species.slice(0, SHOWN)) : [])
  const int = (n: number) => n.toLocaleString('en-US')
</script>

<section aria-labelledby="species-h">
  <h2 id="species-h">Species</h2>

  <h3>OBIS records in the place</h3>
  {#if obis.phase === 'loading'}
    <p class="muted loading" aria-live="polite">Reading the OBIS counts…</p>
  {:else if obis.phase === 'error'}
    <p class="notice">The OBIS release could not be read: {obis.msg}</p>
  {:else if obis.phase === 'none' || !obis.r}
    <p class="notice">The obis-h3 release has no exact counts for this place yet: they are computed for the sanctuaries, the EEZs and the high seas so far.</p>
  {:else}
    {@const s = obis.r.summary}
    <p>{obisLine(s)}</p>
    {#if s.decades.length}
      <div class="scroll">
        <table class="kv dec">
          <thead><tr><th>Decade</th><th>Records</th><th>Species</th><th>ES(50)</th></tr></thead>
          <tbody>
            {#each s.decades as d (d.decade)}<tr><td>{d.decade}s</td><td>{int(d.n)}</td><td>{int(d.sp)}</td><td>{d.es == null ? '–' : d.es.toFixed(1)}</td></tr>{/each}
          </tbody>
        </table>
      </div>
    {/if}
    {#if s.byEov.length}<p class="muted">By EOV group, every year: {s.byEov.map((e) => `${eovLabel(e.eov)} ${int(e.sp)} species`).join(', ')}.</p>{/if}
    <p class="muted">Counted point-in-polygon on this place's own boundary (exact, not by hexagon) from obis-h3 release {obis.r.release.release}
      (OBIS snapshot {obis.r.release.obis_snapshot ?? '–'}, WoRMS {obis.r.release.worms_version ?? '–'}). The list of species by name is not in the release:
      {#if links}<a href={links.mapper} target="_blank" rel="noopener noreferrer">the OBIS mapper for the place's box ↗</a> ·
        <a href={links.checklist} target="_blank" rel="noopener noreferrer">the OBIS checklist for the box (JSON) ↗</a>{/if}</p>
    <details class="repro">
      <summary>Reproduce</summary>
      <p><span class="muted">Values:</span> <a href={obis.r.url}>{obis.r.url}</a></p>
      <pre><code>{sql}</code></pre>
      <p><CopyButton text={sql} label="Copy DuckDB SQL" /></p>
    </details>
  {/if}

  <h3>Species from AquaMaps (habitat suitability models)</h3>
  {#if sdm.phase === 'loading'}
    <p class="muted loading" aria-live="polite">Reading the AquaMaps cells of the place…</p>
  {:else if sdm.phase === 'error'}
    <p class="notice">The AquaMaps species could not be read: {sdm.msg}</p>
  {:else if sdm.phase === 'large' || !sdm.r}
    <p class="notice">This place is too large to list its AquaMaps species cell by cell here (more than 200,000 cells of 0.05°): <a href={atlasHref('aquamaps_eov', placeId, name)} target="_blank" rel="noopener noreferrer">open it in the atlas ↗</a>.</p>
  {:else}
    <p>{sdmLine(sdm.r.species, sdm.r.cells, sdm.r.hook.grid.res)}</p>
    {#if shown.length}
      <div class="scroll">
        <table class="kv sp">
          <thead><tr><th>Species</th><th>Group</th><th>Cells</th><th>Suitability, mean (best)</th></tr></thead>
          <tbody>
            {#each shown as s (s.aphiaId)}
              <tr>
                <td>{#if s.worms}<a href={s.worms} target="_blank" rel="noopener noreferrer"><i>{s.name}</i></a>{:else}<i>{s.name}</i>{/if}{#if s.common}<span class="muted">{' · '}{s.common}</span>{/if}{#if s.redlist}<span class="muted">{' · '}IUCN {s.redlist}</span>{/if}</td>
                <td>{eovLabel(s.group ?? 'other')}</td>
                <td class="n">{int(s.cells)}</td>
                <td class="n">{Math.round(s.meanSuit)}% <span class="muted">({s.maxSuit}%)</span></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
    <div class="row">
      {#if sdm.r.species.length > SHOWN}<button class="btn secondary small" type="button" aria-expanded={all} onclick={() => (all = !all)}>{all ? `Show the first ${SHOWN}` : `Show all ${int(sdm.r.species.length)}`}</button>{/if}
      <a class="btn secondary small" href={csvHref} download={csvName}>Species list (CSV)</a>
      <a class="btn secondary small" href={atlasHref('aquamaps_eov', placeId, name)} target="_blank" rel="noopener noreferrer">Open in the atlas ↗</a>
    </div>
    <p class="muted">The cells are those of the 0.05° grid whose centre falls inside the place (a part too small for one counts the cell under it), read from the atlas's
      AquaMaps EOV share ({sdm.r.tiles} {sdm.r.tiles === 1 ? 'tile' : 'tiles'} of 5°); a species is listed when its modelled suitability is at least 1% in one of them. {#if sdm.r.license}Licence {sdm.r.license}.{/if}</p>
    {#if sdm.r.citation}<p class="muted cite">{sdm.r.citation}</p>{/if}
  {/if}
</section>

<style>
  h3 { margin: 12px 0 4px; font-size: 1rem; }
  .scroll { overflow-x: auto; max-width: 100%; }
  .dec, .sp { font-size: 13px; }
  .dec { width: auto; }
  .dec th, .sp th { width: auto; padding-right: 16px; }
  .dec td, .sp td { overflow-wrap: anywhere; }
  .sp { width: 100%; }
  .sp .n { white-space: nowrap; }
  .repro { font-size: 12.5px; }
  .repro summary { cursor: pointer; color: var(--link); }
  .repro pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  .cite { font-size: 12.5px; }
</style>
