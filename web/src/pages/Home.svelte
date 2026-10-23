<script lang="ts">
  import { getPlace, layerLabel, type IndexPlace, type PlaceFeature } from '@oceanmetrics/places'
  import { BASE, index, manifest, searchPlaces } from '../lib/data.svelte'
  import { buildSearch, parseView, type LayerSel } from '../lib/grammar'
  import { collectionDir, defaultColour, derivedLine, drawable, fmtDate, fmtLonLat, fmtN, groupByAuthority, layerPath, placePath, queryOf, sanitizeHtml, withBase } from '../lib/helpers'
  import { loc, navigate } from '../lib/router.svelte'
  import TryThese from '../lib/TryThese.svelte'

  // the URL is the state: layers=… and place=… are read here and written back with replaceState ----
  const view = $derived(parseView(loc.search))
  const selected = $derived<LayerSel[]>(view.layers ?? [])
  const known = $derived(new Set(manifest.layers.map((l) => l.slug)))
  const unknown = $derived(selected.filter((s) => manifest.status === 'ok' && !known.has(s.slug)).map((s) => s.slug))

  const write = (v: Parameters<typeof buildSearch>[0]) => navigate(loc.path + buildSearch(v, loc.search), { replace: true })
  const setLayers = (ls: LayerSel[]) => write({ layers: ls.length ? ls : null })
  const isOn = (slug: string) => selected.some((s) => s.slug === slug)
  const toggle = (slug: string) =>
    setLayers(isOn(slug) ? selected.filter((s) => s.slug !== slug) : [{ slug, colour: null, opacity: null, width: null }, ...selected])
  const patch = (slug: string, p: Partial<LayerSel>) => setLayers(selected.map((s) => (s.slug === slug ? { ...s, ...p } : s)))
  const move = (i: number, d: number) => {
    const j = i + d
    if (j < 0 || j >= selected.length) return
    const ls = selected.slice()
    ;[ls[i], ls[j]] = [ls[j], ls[i]]
    setLayers(ls)
  }

  // search: the places index when it is published, else the layer list is filtered by the same text ----
  // scope: '' = all layers, ON_MAP = the layers on the map, else one layer's slug
  const ON_MAP = '@map'
  // the bar's place search arrives as ?q=<text>: it starts the field, and a new ?q= (the bar used again on this page) sets it
  let q = $state(queryOf(loc.search))
  let lastQ = queryOf(loc.search)
  $effect(() => {
    const next = queryOf(loc.search)
    if (next !== lastQ) { lastQ = next; if (next) q = next }
  })
  let scope = $state('')
  const scopeSlugs = $derived.by(() => {
    if (!scope) return undefined
    const slugs = scope === ON_MAP ? selected.map((s) => s.slug) : [scope]
    return slugs.map((s) => manifest.layers.find((l) => l.slug === s)?.collection ?? s)
  })
  // the scope falls back to all layers when its layers leave the map or the manifest
  $effect(() => {
    if (scope === ON_MAP && !selected.length) scope = ''
    else if (scope && scope !== ON_MAP && manifest.status === 'ok' && !known.has(scope)) scope = ''
  })
  let hits = $state<IndexPlace[]>([])
  let searching = $state(false)
  let timer: ReturnType<typeof setTimeout> | undefined
  let token = 0
  $effect(() => {
    const text = q.trim(), within = scopeSlugs
    clearTimeout(timer)
    if (!text) { hits = []; searching = false; return }
    searching = true
    const my = ++token
    timer = setTimeout(async () => {
      const r = await searchPlaces(text, 12, within)
      if (my === token) { hits = r; searching = false }
    }, 200)
  })

  const filteredLayers = $derived.by(() => {
    const t = q.trim().toLowerCase()
    return t ? manifest.layers.filter((l) => `${layerLabel(l)} ${l.slug} ${l.authority ?? ''} ${l.place_type ?? ''}`.toLowerCase().includes(t)) : manifest.layers
  })
  const groups = $derived(groupByAuthority(filteredLayers))

  // the chosen place: drawn on the map from the collection parquet ----
  let place = $state<PlaceFeature | null>(null)
  let placeError = $state('')
  let placeNote = $state('')
  let placeLabel = $state('')   // the name of a place that has no feature to take it from (a derived one)
  let pt = 0
  $effect(() => {
    const id = view.place
    const my = ++pt
    place = null
    placeError = ''
    placeNote = ''
    placeLabel = ''
    if (!id) return
    getPlace(id, { unwrap: true })
      .then(async (f) => {
        if (my !== pt) return
        if (f) { place = f; return }
        // a place of a derived layer has no geometry of ours to draw: say what draws it and go to it
        const row = (await searchPlaces(id, 20)).find((h) => h.place_id === id)
        const dl = row && manifest.layers.find((l) => l.slug === row.collection && l.kind === 'derived')
        if (my !== pt) return
        if (dl && row) { placeNote = derivedLine(dl, manifest.layers); placeLabel = row.name; mapRef?.fitTo(row.bbox) }
        else placeError = `Place ${id} was not found in any published collection.`
      })
      .catch((e: unknown) => { if (my === pt) placeError = `Place ${id} could not be read: ${(e as Error).message}` })
  })
  const pickHit = (h: IndexPlace) => write({ place: h.place_id })
  // a hit's second line: its layer, type, area, and its position when another hit has the same name (homonyms,
  // zones split into parts); copies of the same place in other layers are grouped under the hit (`also`) ----
  const layerOf = (h: IndexPlace) => { const l = manifest.layers.find((x) => x.collection === h.collection); return l ? layerLabel(l) : h.collection }
  const repeated = $derived.by(() => {
    const n = new Map<string, number>()
    for (const h of hits) { const k = h.name.trim().toLowerCase(); n.set(k, (n.get(k) ?? 0) + 1) }
    return new Set([...n].filter(([, c]) => c > 1).map(([k]) => k))
  })
  const hitLine = (h: IndexPlace) =>
    [layerOf(h), h.place_type, h.area_km2 ? `${fmtN(Math.round(h.area_km2))} km²` : '',
     repeated.has(h.name.trim().toLowerCase()) ? fmtLonLat(h.centroid) : ''].filter(Boolean).join(' · ')
  const hitKey = (h: IndexPlace) => `${h.collection}/${h.place_id}`
  let openCopies = $state<string | null>(null)

  // the one open layer-info card in the list (a second click, another row, or Esc closes it) ----
  let info = $state<string | null>(null)

  // zoom to a layer's manifest bbox (unwrapped: east may exceed 180 for antimeridian-cut collections) ----
  let mapRef = $state<{ fitTo(b: [number, number, number, number]) : void } | null>(null)
  const zoomTo = (slug: string) => {
    const b = manifest.layers.find((l) => l.slug === slug)?.bbox
    if (b) mapRef?.fitTo(b as [number, number, number, number])
  }

  // tile sources that fail (collection not published yet) ----
  let badLayers = $state<string[]>([])
  const onlayererror = (slug: string) => { if (!badLayers.includes(slug)) badLayers = [...badLayers, slug] }
  const titleOf = (slug: string) => { const l = manifest.layers.find((l) => l.slug === slug); return l ? layerLabel(l) : slug }
  const placeName = $derived(String(place?.properties?.name ?? (placeLabel || view.place) ?? ''))
</script>

<div class="home">
  <aside class="panel" aria-label="Search and layers">
    <label class="sr" for="q">Search places</label>
    <input id="q" type="search" placeholder="Search places or filter layers…" bind:value={q} autocomplete="off" />
    {#if manifest.status === 'ok' && manifest.layers.length}
      <label class="scope">
        <span class="muted">Search in</span>
        <select bind:value={scope}>
          <option value="">All layers</option>
          {#if selected.length}<option value={ON_MAP}>Layers on the map ({selected.length})</option>{/if}
          {#each groupByAuthority(manifest.layers) as g (g.authority)}
            <optgroup label={g.authority}>
              {#each g.layers as l (l.slug)}<option value={l.slug}>{layerLabel(l)}</option>{/each}
            </optgroup>
          {/each}
        </select>
      </label>
    {/if}

    {#if !q.trim() && !view.place}<TryThese />{/if}

    {#if index.status === 'error' && q.trim()}
      <p class="notice">The places index is not available yet, so name search is off. Layers are filtered by that text instead.</p>
    {/if}

    {#if q.trim() && index.status !== 'error'}
      <section aria-live="polite">
        <h2>Places {searching ? '…' : `(${hits.length})`}</h2>
        <ul class="hits">
          {#each hits as h (hitKey(h))}
            <li>
              <button type="button" onclick={() => pickHit(h)}>
                <strong>{h.name}</strong>
                <span class="muted">{hitLine(h)}</span>
              </button>
              {#if h.also?.length}
                <button type="button" class="copies" aria-expanded={openCopies === hitKey(h)}
                  onclick={() => (openCopies = openCopies === hitKey(h) ? null : hitKey(h))}>
                  {openCopies === hitKey(h) ? '▾' : '▸'} also in {h.also.length} other layer{h.also.length > 1 ? 's' : ''}
                </button>
                {#if openCopies === hitKey(h)}
                  <ul class="also">
                    {#each h.also as a (hitKey(a))}
                      <li><button type="button" onclick={() => pickHit(a)}>{layerOf(a)} <span class="muted">· {a.place_id}</span></button></li>
                    {/each}
                  </ul>
                {/if}
              {/if}
            </li>
          {:else}
            {#if !searching}<li class="muted">No places match.</li>{/if}
          {/each}
        </ul>
      </section>
    {/if}

    {#if view.place}
      <section class="card placecard">
        <div class="row"><strong>{placeName}</strong><button class="btn secondary small" type="button" onclick={() => write({ place: null })}>Clear</button></div>
        <div class="muted">{view.place}</div>
        {#if placeError}<div class="notice">{placeError}</div>{/if}
        {#if placeNote}<div class="muted">{placeNote}</div>{/if}
        <div class="row"><a class="btn small" href={withBase(placePath(view.place), BASE)}>Place page</a></div>
      </section>
    {/if}

    <h2>Layers</h2>
    {#if manifest.status === 'loading'}
      <p class="muted">Loading layers…</p>
    {:else if manifest.status === 'error'}
      <p class="notice">
        The layers manifest could not be read from <code>{BASE}index/layers.json</code>. The gazetteer may not be published at this address yet
        (use <code>?base=</code> to point at another one). {manifest.error}
      </p>
    {:else if !manifest.layers.length}
      <p class="muted">No layers are published yet.</p>
    {/if}

    {#if selected.length}
      <h3>On the map <span class="muted">(top first)</span></h3>
      <ul class="onmap">
        {#each selected as s, i (s.slug)}
          {@const l = manifest.layers.find((x) => x.slug === s.slug)}
          <li class="card">
            <div class="row">
              {#if l?.kind === 'raster'}
                <span class="sw raster" title="Map tiles from the publisher (colours are theirs)"></span>
              {:else}
                <input type="color" aria-label="Colour of {l ? layerLabel(l) : s.slug}" value={s.colour ?? defaultColour(l)} oninput={(e) => patch(s.slug, { colour: e.currentTarget.value })} />
              {/if}
              <a href={withBase(layerPath(s.slug), BASE)} class="grow">{l ? layerLabel(l) : s.slug}</a>
              <button class="btn secondary small" type="button" aria-label="Zoom to {l ? layerLabel(l) : s.slug}" title="Zoom to layer" disabled={!l?.bbox} onclick={() => zoomTo(s.slug)}>⌖</button>
              <button class="btn secondary small" type="button" aria-label="Move up" disabled={i === 0} onclick={() => move(i, -1)}>▲</button>
              <button class="btn secondary small" type="button" aria-label="Move down" disabled={i === selected.length - 1} onclick={() => move(i, 1)}>▼</button>
              <button class="btn secondary small" type="button" aria-label="Remove {l ? layerLabel(l) : s.slug} from the map" onclick={() => toggle(s.slug)}>✕</button>
            </div>
            {#if l}
              <div class="sliders">
                <label>Opacity <input type="range" min="0" max="1" step="0.05" value={s.opacity ?? 1} oninput={(e) => patch(s.slug, { opacity: Math.round(+e.currentTarget.value * 100) / 100 })} /></label>
                {#if l.kind !== 'raster'}
                  <label>Width <input type="range" min="0.5" max="4" step="0.5" value={s.width ?? 1} oninput={(e) => patch(s.slug, { width: +e.currentTarget.value })} /></label>
                {/if}
                {#if s.colour || s.opacity != null || s.width != null}
                  <button class="btn secondary small" type="button" onclick={() => patch(s.slug, { colour: null, opacity: null, width: null })}>Reset style</button>
                {/if}
              </div>
            {/if}
            {#if l && !drawable(l, manifest.layers)}<div class="notice">{derivedLine(l, manifest.layers)}</div>
            {:else if badLayers.includes(s.slug)}<div class="notice">Tiles for this layer could not be loaded; it may not be published yet.</div>{/if}
          </li>
        {/each}
      </ul>
    {/if}
    {#if unknown.length}
      <p class="notice">Not in the manifest, so not drawn: {unknown.join(', ')}.</p>
    {/if}

    {#each groups as g (g.authority)}
      <h3>{g.authority}</h3>
      <ul class="layers">
        {#each g.layers as l (l.slug)}
          <li>
            <div class="lrow">
              <label>
                <input type="checkbox" aria-label={layerLabel(l)} checked={isOn(l.slug)} disabled={!drawable(l, manifest.layers) && !isOn(l.slug)} onchange={() => toggle(l.slug)} />
                {#if l.kind === 'raster'}
                  <span class="sw raster" title="Map tiles from the publisher"></span>
                {:else}
                  <span class="sw" style:background={defaultColour(l)}></span>
                {/if}
                <span class="grow">{layerLabel(l)}</span>
                <span class="muted n">{fmtN(l.n)}</span>
              </label>
              <button class="info-btn" type="button" aria-label="About {layerLabel(l)}" aria-expanded={info === l.slug}
                onclick={() => (info = info === l.slug ? null : l.slug)}
                onkeydown={(e) => { if (e.key === 'Escape') info = null }}>
                <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7" fill="none" stroke="currentColor" stroke-width="1.4" /><circle cx="8" cy="4.9" r="1" fill="currentColor" /><path d="M8 7.2v4.2" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" /></svg>
              </button>
            </div>
            {#if !drawable(l, manifest.layers) && !isOn(l.slug)}<div class="muted small-note">{derivedLine(l, manifest.layers)}</div>{/if}
            {#if info === l.slug}
              <div class="card linfo">
                <div class="muted">{fmtN(l.n)} places · {l.geom_type}{l.version ? ` · v${l.version}` : ''}{l.updated ? ` · ${fmtDate(l.updated)}` : ''}</div>
                {#if l.kind === 'derived'}<div class="muted">{derivedLine(l, manifest.layers)}</div>{/if}
                {#if l.license}<div class="muted">Licence: {#if l.license_url}<a href={l.license_url} target="_blank" rel="noopener noreferrer">{l.license}</a>{:else}{l.license}{/if}</div>{/if}
                {#if l.attribution_html || l.attribution}
                  <div class="attr">{@html sanitizeHtml(l.attribution_html || l.attribution)}</div>
                {/if}
                <div class="row">
                  <a class="btn small" href={withBase(layerPath(l.slug), BASE)}>Full layer page</a>
                  <a class="btn secondary small" href={collectionDir(BASE, l.collection)} target="_blank" rel="noopener noreferrer">Collection README</a>
                  <button class="btn secondary small" type="button" disabled={!drawable(l, manifest.layers) && !isOn(l.slug)} onclick={() => toggle(l.slug)}>{isOn(l.slug) ? 'Remove from map' : 'Add to map'}</button>
                  {#if l.bbox}
                    <button class="btn secondary small" type="button" disabled={!drawable(l, manifest.layers) && !isOn(l.slug)} onclick={() => { if (!isOn(l.slug)) toggle(l.slug); zoomTo(l.slug) }}>Zoom to</button>
                  {/if}
                </div>
              </div>
            {/if}
          </li>
        {/each}
      </ul>
    {:else}
      {#if manifest.status === 'ok' && q.trim()}<p class="muted">No layer matches.</p>{/if}
    {/each}
  </aside>

  <div class="stage">
    {#await import('../lib/PlacesMap.svelte')}
      <p class="muted loading">Loading the map…</p>
    {:then m}
      <m.default bind:this={mapRef} {selected} layers={manifest.layers} highlight={place} {onlayererror} onpick={(id: string | null) => id && write({ place: id })} />
    {:catch}
      <p class="notice">The map could not be loaded.</p>
    {/await}
    {#if !selected.length && !view.place}
      <div class="hint">Tick a layer to draw it on the map.</div>
    {/if}
  </div>
</div>

<style>
  /* flex: none so the height holds; with flex: 1 the column grew to the layer list's length and the map's centre fell below the fold */
  .home { flex: none; min-height: 0; display: grid; grid-template-columns: 22rem 1fr; height: calc(100dvh - var(--header-h)); }
  .panel { overflow-y: auto; padding: 12px 14px 24px; background: var(--bg-card); border-right: 1px solid var(--border); }
  .stage { position: relative; min-height: 0; }
  .scope { display: flex; align-items: center; gap: 6px; margin-top: 6px; font-size: 12px; }
  .scope select { flex: 1; min-width: 0; font: inherit; color: var(--text); background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 3px 4px; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
  .panel h2 { margin: 1rem 0 .3rem; }
  .panel h3 { margin: 1rem 0 .2rem; font-size: .8rem; text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); }
  ul { list-style: none; margin: 0; padding: 0; }
  .hits button { all: unset; display: block; width: 100%; box-sizing: border-box; cursor: pointer; padding: 6px 4px; border-bottom: 1px solid var(--border); }
  .hits button:hover, .hits button:focus-visible { background: var(--bg-tint); }
  .hits span { display: block; font-size: 12px; }
  .hits li { border-bottom: 1px solid var(--border); }
  .hits li > button:first-child { border-bottom: 0; }
  .hits .copies { all: unset; cursor: pointer; display: block; padding: 0 4px 6px; font-size: 12px; color: var(--link); }
  .hits .also { margin: 0 0 6px 12px; }
  .hits .also button { all: unset; cursor: pointer; display: block; padding: 3px 4px; font-size: 12px; border: 0; }
  .hits .also button:hover, .hits .copies:hover { text-decoration: underline; }
  .hits .also span { display: inline; }
  .layers label { display: flex; gap: 8px; align-items: center; padding: 4px 0; cursor: pointer; }
  .lrow { display: flex; align-items: center; gap: 4px; }
  .small-note { font-size: 12px; margin: 0 0 4px 24px; }
  .lrow label { flex: 1; min-width: 0; }
  .info-btn { display: inline-flex; align-items: center; justify-content: center; flex: none; width: 22px; height: 22px; padding: 0; border: none; border-radius: 50%; background: transparent; color: var(--text-muted); cursor: pointer; }
  .info-btn:hover, .info-btn[aria-expanded='true'] { color: var(--brand-text); background: var(--bg-tint); }
  .info-btn svg { width: 15px; height: 15px; }
  .linfo { font-size: 13px; margin: 2px 0 8px; display: grid; gap: 6px; }
  .linfo .attr { color: var(--text-muted); }
  .sw { width: 12px; height: 12px; border-radius: 3px; flex: none; border: 1px solid var(--border); }
  .sw.raster { background: repeating-linear-gradient(45deg, var(--text-muted) 0 2px, transparent 2px 4px); }
  .onmap .sw.raster { width: 26px; height: 18px; }
  .grow { flex: 1; min-width: 0; }
  .n { font-size: 12px; font-variant-numeric: tabular-nums; }
  .onmap .card { padding: 8px 10px; margin: 6px 0; }
  .sliders { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 6px; font-size: 12px; color: var(--text-muted); align-items: center; }
  .sliders input[type='range'] { width: 6rem; vertical-align: middle; }
  .placecard { margin-top: 10px; }
  .loading { padding: 16px; }
  .hint { position: absolute; top: 10px; left: 50%; transform: translateX(-50%); background: var(--bg-card); color: var(--text-muted); border: 1px solid var(--border); border-radius: 999px; padding: 4px 12px; font-size: 13px; pointer-events: none; }
  @media (max-width: 800px) {
    .home { display: flex; flex-direction: column; height: auto; flex: none; }
    .stage { order: -1; height: 58dvh; flex: none; }
    .panel { border-right: 0; border-top: 1px solid var(--border); overflow: visible; }
  }
</style>
