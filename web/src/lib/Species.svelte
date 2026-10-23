<script lang="ts">
  // the Species section: OBIS records and species counted on the place's own polygon (the obis-h3 release's place_exact:
  // indicators.parquet and the per-species species.parquet), and the AquaMaps species suitable in the place's 0.05 degree cells (the atlas's `atlas:cell_species` tiles). the rules are
  // species.ts (tested); the reads are speciesRead.ts, a lazy chunk. this only draws.
  import CopyButton from './CopyButton.svelte'
  import { atlasHref } from './layers'
  import { placeObisUrl } from './obisLink'
  import { DEFAULT_SPECIES_SORT, eovLabel, filterSpecies, groupOf, nextSort, obisLine, obisLinks, obisSpeciesSql, obisValuesSql, placeSpeciesCsv, sdmCsv, sdmLine, sortSpecies, speciesCheck, speciesCountLine, speciesCounts, speciesLookupUrl } from './species'
  import type { SpeciesSort } from './species'
  import type { ObisResult, ObisSpeciesResult, SdmResult } from './speciesRead'

  let { placeId, name, geometry, bbox, colls }: {
    placeId: string; name: string; geometry: { type: string; coordinates: unknown } | null; bbox: number[] | null; colls: string[]
  } = $props()

  let obis = $state<{ phase: 'loading' | 'ok' | 'none' | 'error'; r: ObisResult | null; msg: string }>({ phase: 'loading', r: null, msg: '' })
  let osp = $state<{ phase: 'loading' | 'ok' | 'none' | 'error'; r: ObisSpeciesResult | null; msg: string }>({ phase: 'loading', r: null, msg: '' })
  let sdm = $state<{ phase: 'loading' | 'ok' | 'large' | 'error'; r: SdmResult | null; msg: string }>({ phase: 'loading', r: null, msg: '' })
  let all = $state(false)
  let allObis = $state(false)
  let query = $state('')
  let sort = $state<SpeciesSort>(DEFAULT_SPECIES_SORT)
  const SHOWN = 20

  $effect(() => {
    const id = placeId, cs = colls, g = geometry
    void import('./speciesRead').then((m) => {
      osp = { phase: 'loading', r: null, msg: '' }
      m.readObis(id, cs).then((r) => {
        obis = { phase: r ? 'ok' : 'none', r, msg: '' }
        if (!r) return
        // the exact list of the same release and collection as the counts above
        m.readObisSpecies(r.release, r.coll, id)
          .then((l) => { osp = { phase: l ? 'ok' : 'none', r: l, msg: '' } })
          .catch((e) => { osp = { phase: 'error', r: null, msg: String(e?.message ?? e) } })
      }).catch((e) => { obis = { phase: 'error', r: null, msg: String(e?.message ?? e) } })
      if (!g) { sdm = { phase: 'large', r: null, msg: '' }; return }
      m.readSdm(g).then((r) => { sdm = r ? { phase: 'ok', r, msg: '' } : { phase: 'large', r: null, msg: '' } }).catch((e) => { sdm = { phase: 'error', r: null, msg: String(e?.message ?? e) } })
    })
  })

  const links = $derived(bbox ? obisLinks(bbox) : null)
  const mapHref = $derived(placeObisUrl({ placeId, name, bbox }))
  const sql = $derived(obis.r ? obisValuesSql(obis.r.url, placeId) : '')
  const spSql = $derived(obis.r && osp.r ? obisSpeciesSql(osp.r.url, speciesLookupUrl(obis.r.release), placeId) : '')
  const counts = $derived(obis.r && osp.r ? speciesCounts(osp.r.list, obis.r.summary.latest?.decade ?? null) : null)
  const warn = $derived(obis.r && counts ? speciesCheck(counts, obis.r.summary) : null)
  // the filter and the sort act on the whole list; the first SHOWN of what is left are drawn until "Show all"
  const matched = $derived(osp.r ? sortSpecies(filterSpecies(osp.r.list, query), sort) : [])
  const obisShown = $derived(allObis ? matched : matched.slice(0, SHOWN))
  const arrow = (k: SpeciesSort['key']) => (sort.key === k ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : '')
  const ariaSort = (k: SpeciesSort['key']) => (sort.key === k ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none')
  const obisCsvHref = $derived(osp.r ? URL.createObjectURL(new Blob([placeSpeciesCsv(placeId, osp.r.list)], { type: 'text/csv' })) : '')
  const obisCsvName = $derived(`obis_species_${placeId.replace(/[^\w.-]+/g, '_')}.csv`)
  const kb = (b: number) => (b >= 1e6 ? `${(b / 1e6).toFixed(1)} MB` : `${Math.round(b / 1e3)} kB`)
  const csvHref = $derived(sdm.r ? URL.createObjectURL(new Blob([sdmCsv(placeId, sdm.r.species)], { type: 'text/csv' })) : '')
  const csvName = $derived(`aquamaps_species_${placeId.replace(/[^\w.-]+/g, '_')}.csv`)
  const shown = $derived(sdm.r ? (all ? sdm.r.species : sdm.r.species.slice(0, SHOWN)) : [])
  const int = (n: number) => n.toLocaleString('en-US')
</script>

<section aria-labelledby="species-h">
  <h2 id="species-h">Species</h2>

  <h3>OBIS records in the place</h3>
  <p class="maplink"><a href={mapHref} target="_blank" rel="noopener noreferrer">Species on the map (Ocean Metrics Atlas, OBIS H3 layer) ↗</a></p>
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
      (OBIS snapshot {obis.r.release.obis_snapshot ?? '–'}, WoRMS {obis.r.release.worms_version ?? '–'}).</p>

    <h4>Species with records in the place</h4>
    {#if osp.phase === 'loading'}
      <p class="muted loading" aria-live="polite">Reading the species list…</p>
    {:else if osp.phase === 'error'}
      <p class="notice">The species list of the release could not be read: {osp.msg}</p>
    {:else if osp.phase === 'none' || !osp.r || !counts}
      <p class="notice">The release has no species file for this collection yet ({obis.r.coll}).</p>
    {:else}
      <p>{speciesCountLine(counts)}</p>
      {#if warn}<p class="notice" role="status">{warn}</p>{/if}
      {#if osp.r.list.length > 1}
        <p class="filter"><label>Filter <input type="search" bind:value={query} placeholder="name, group or IUCN code" aria-controls="obis-species" /></label>
          {#if query.trim()}<span class="muted" role="status">{int(matched.length)} of {int(osp.r.list.length)}</span>{/if}</p>
      {/if}
      {#if obisShown.length}
        <div class="scroll">
          <table class="kv sp osp" id="obis-species">
            <thead><tr>
              <th aria-sort={ariaSort('name')}><button class="sortb" type="button" onclick={() => (sort = nextSort(sort, 'name'))}>Species{arrow('name')}</button></th>
              <th aria-sort={ariaSort('records')}><button class="sortb" type="button" onclick={() => (sort = nextSort(sort, 'records'))}>Records{arrow('records')}</button></th>
              <th aria-sort={ariaSort('last')}><button class="sortb" type="button" onclick={() => (sort = nextSort(sort, 'last'))}>First–last year{arrow('last')}</button></th>
            </tr></thead>
            <tbody>
              {#each obisShown as s (s.nameKey)}
                <tr>
                  <td><a href={s.worms} target="_blank" rel="noopener noreferrer"><i>{s.name}</i></a><span class="muted grp">{groupOf(s)}{#if s.redlist}{' · '}IUCN {s.redlist}{/if}</span></td>
                  <td class="n">{int(s.n)}</td>
                  <td class="n">{s.yearMin == null ? '–' : s.yearMin === s.yearMax ? s.yearMin : `${s.yearMin}–${s.yearMax ?? ''}`}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else if query.trim()}
        <p class="muted">No species match “{query.trim()}”.</p>
      {/if}
      <div class="row">
        {#if matched.length > SHOWN}<button class="btn secondary small" type="button" aria-expanded={allObis} onclick={() => (allObis = !allObis)}>{allObis ? `Show the first ${SHOWN}` : `Show all ${int(matched.length)}`}</button>{/if}
        <a class="btn secondary small" href={obisCsvHref} download={obisCsvName}>Species list (CSV)</a>
        {#if links}<a class="btn secondary small" href={links.mapper} target="_blank" rel="noopener noreferrer">Explore in OBIS ↗</a>
          <a class="btn secondary small" href={links.checklist} target="_blank" rel="noopener noreferrer">OBIS checklist for the box (JSON) ↗</a>{/if}
      </div>
      <p class="muted">Ranked by records; a name that carries several AphiaIDs is one species, as in the counts above. The group is the OBIS class (the release's species table has no EOV group or red list code yet).
        Read {kb(osp.r.rowBytes)} of the {obis.r.coll} species file ({osp.r.groupsRead} of {osp.r.groups} row {osp.r.groups === 1 ? 'group' : 'groups'}) and {kb(osp.r.lookupBytes)} of the species names.
        The OBIS mapper and checklist are for the place's box, not its boundary.</p>
    {/if}
    <details class="repro">
      <summary>Reproduce</summary>
      <p><span class="muted">Values:</span> <a href={obis.r.url}>{obis.r.url}</a></p>
      <pre><code>{sql}</code></pre>
      <p><CopyButton text={sql} label="Copy DuckDB SQL" /></p>
      {#if spSql}
        <p><span class="muted">Species:</span> <a href={osp.r?.url}>{osp.r?.url}</a></p>
        <pre><code>{spSql}</code></pre>
        <p><CopyButton text={spSql} label="Copy species SQL" /></p>
      {/if}
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
  h4 { margin: 12px 0 4px; font-size: .95rem; }
  .scroll { overflow-x: auto; max-width: 100%; }
  .dec, .sp { font-size: 13px; }
  .dec { width: auto; }
  .dec th, .sp th { width: auto; padding-right: 16px; }
  .dec td, .sp td { overflow-wrap: anywhere; }
  .sp { width: 100%; }
  .sp .n { white-space: nowrap; }
  .osp .grp { display: block; }
  .filter { margin: 4px 0; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .filter label { display: flex; gap: 8px; align-items: center; flex: 1 1 260px; max-width: 420px; }
  .sortb { all: unset; cursor: pointer; font-weight: inherit; color: var(--link); }
  .sortb:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  .maplink { margin: 4px 0 8px; }
  .repro { font-size: 12.5px; }
  .repro summary { cursor: pointer; color: var(--link); }
  .repro pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  .cite { font-size: 12.5px; }
</style>
