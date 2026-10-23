<script lang="ts">
  import { getPlace, layerLabel, samePlace, search, type IndexPlace, type PlaceFeature } from '@oceanmetrics/places'
  import { onMount } from 'svelte'
  import Credit from '../lib/Credit.svelte'
  import CopyButton from '../lib/CopyButton.svelte'
  import Indicators from '../lib/Indicators.svelte'
  import LayerUnder from '../lib/LayerUnder.svelte'
  import Layers from '../lib/Layers.svelte'
  import Reports from '../lib/Reports.svelte'
  import Species from '../lib/Species.svelte'
  import ValuesDownload from '../lib/ValuesDownload.svelte'
  import { obisColls } from '../lib/species'
  import type { Box } from '../lib/layers'
  import type { LegendSpec } from '@oceanmetrics/map'
  import { loadErddapLayers } from '../lib/map/gridKind'
  import type { ErddapLayer } from '../lib/map/gridLayer'
  import { parseView } from '../lib/grammar'
  import { loc } from '../lib/router.svelte'
  import { BASE, manifest, loadManifest } from '../lib/data.svelte'
  import {
    calcofiLink, derivedLine, erddapLink, fmtValue, geojsonSql, keepsGeometry, layerForPlace, layerPath, parquetUrl, placePath, sanitizeHtml, viaTitle, withBase,
  } from '../lib/helpers'

  let { id }: { id: string } = $props()

  let feature = $state<PlaceFeature | null>(null)
  let status = $state<'loading' | 'ok' | 'missing' | 'error'>('loading')
  let message = $state('')
  let copies = $state<IndexPlace[]>([])   // the same place in other layers (index group_id)
  let copiesRead = $state(false)
  let row = $state<IndexPlace | null>(null) // the index row: link back to the source, and all a reference place without per-place geometry has

  // the layer under the map and its period, from the query (grammar.ts); the ERDDAP collections of the gazetteer for the picker
  const view = $derived(parseView(loc.search))
  let erddap = $state<ErddapLayer[]>([])
  let legend = $state<LegendSpec | null>(null)

  onMount(async () => {
    loadErddapLayers().then((ls) => { erddap = ls }).catch(() => { erddap = [] })
    await loadManifest()
    try {
      const [f, hits] = await Promise.all([getPlace(id, { unwrap: true }), search(id, { limit: 20 }).catch(() => [])])
      row = (f ? hits.find((h) => h.place_id === id && h.collection === f.collection) : hits.find((h) => h.place_id === id)) ?? null
      const refOnly = !f && row && manifest.layers.some((l) => l.slug === row!.collection && keepsGeometry(l))
      if (f || refOnly) {
        feature = f; status = 'ok'
        samePlace(id, { slug: f?.collection ?? row!.collection }).then((c) => { copies = c }).catch(() => { copies = [] }).finally(() => { copiesRead = true })
      } else status = 'missing'
    } catch (e) {
      status = 'error'
      message = String((e as Error).message ?? e)
    }
  })

  const attrs = $derived((feature?.properties ?? (row ? { ...row, bbox: undefined, centroid: undefined, also: undefined } : {})) as Record<string, unknown>)
  const layer = $derived(feature || row || manifest.status === 'ok' ? layerForPlace(manifest.layers, id, attrs, feature?.collection ?? row?.collection) : undefined)
  const isRef = $derived(keepsGeometry(layer))
  const url = $derived(layer && !isRef ? parquetUrl(BASE, layer.collection) : '')
  const sourceUrl = $derived(String(row?.url ?? attrs.url ?? '') || '')
  const servedBy = $derived(feature?.served_by ? new URL(feature.served_by).host : '')
  const sel = $derived(isRef && layer ? [{ slug: layer.slug, colour: null, opacity: null, width: null }] : [])
  const name = $derived(String(attrs.name ?? id))
  const rows = $derived(Object.entries(attrs).filter(([k, v]) => k !== 'name' && k !== 'place_id' && v !== undefined))
  const sql = $derived(url ? geojsonSql(url, id) : '')
  const geojsonHref = $derived(feature && !isRef ? URL.createObjectURL(new Blob([JSON.stringify(feature)], { type: 'application/geo+json' })) : '')
  const fileName = $derived(id.replace(/[^\w.-]+/g, '_') + '.geojson')
  const ownColl = $derived(feature?.collection ?? row?.collection ?? layer?.collection ?? null)
  // the gazetteer collections that hold the place (its own, then its copies'): the OBIS files and the report sets are by collection
  const placeColls = $derived(obisColls(ownColl, copies))
  const bbox = $derived(((feature?.bbox ?? row?.bbox) as Box | undefined) ?? null)
</script>

<main class="page">
  <p class="muted"><a href={withBase('/', BASE)}>Map</a> / place</p>
  <h1>{status === 'ok' ? name : id}</h1>
  <p class="muted">{id}{#if layer}{' '}· layer <a href={withBase(layerPath(layer.slug), BASE)}>{layerLabel(layer)}</a>{/if}</p>

  {#if status === 'loading'}
    <p class="muted">Loading…</p>
  {:else if status === 'missing'}
    <p class="notice">No published collection contains the place <code>{id}</code>. The collection may not be published yet, or the id is wrong.</p>
  {:else if status === 'error'}
    <p class="notice">The place could not be read: {message}</p>
  {/if}

  {#if status === 'ok'}
    {#if sourceUrl || layer?.source_link?.href}
      <p class="source">
        {#if sourceUrl}<a class="btn secondary small" href={sourceUrl} target="_blank" rel="noopener noreferrer">View at {layer?.source_link?.title ?? 'the source'} ↗</a>{/if}
        {#if layer?.source_link?.href}<span class="muted">Source: <a href={layer.source_link.href} target="_blank" rel="noopener noreferrer">{layer.source_link.title}</a>{#if servedBy}{' · boundary served by '}<code>{servedBy}</code>{/if}{#if layer?.kind === 'raster' && !feature}{" · shown from the source's map tiles"}{/if}</span>{/if}
      </p>
    {/if}
    {#if layer?.kind === 'derived'}<p class="muted">{derivedLine(layer, manifest.layers)}</p>{/if}
    <div class="mapbox">
      {#await import('../lib/PlacesMap.svelte')}
        <p class="muted">Loading the map…</p>
      {:then m}
        <m.default highlight={feature} popups={false} selected={sel} layers={manifest.layers} fit={!feature && row ? row.bbox : null}
          layerKey={feature ? view.layer : null} t={view.t} slicePlace={feature ? id : null} onlegend={(l) => { legend = l }} />
      {/await}
    </div>
    {#if feature && /Polygon$/.test(feature.geometry?.type ?? '')}
      <LayerUnder layers={erddap} layerKey={view.layer} t={view.t} {legend} />
    {/if}

    <Indicators placeId={id} {layer} />

    {#if copiesRead}
      <Species placeId={id} {name} geometry={feature && /Polygon$/.test(feature.geometry?.type ?? '') ? feature.geometry as never : null} {bbox} colls={placeColls} />
    {/if}

    <Layers placeId={id} {name} {bbox} {erddap} />

    {#if copiesRead}<Reports placeId={id} {name} {placeColls} />{/if}

    {#if copies.length}
      <h2>Same place in other layers</h2>
      <p class="muted">Each layer keeps its own boundary, version and licence.</p>
      <ul class="copies">
        {#each copies as c (c.collection + '/' + c.place_id)}
          {@const cl = manifest.layers.find((l) => l.collection === c.collection)}
          <li><a href={withBase(placePath(c.place_id), BASE)}>{cl ? layerLabel(cl) : c.collection}</a> <span class="muted">· {c.place_id}{c.version ? ` · v${c.version}` : ''}</span></li>
        {/each}
      </ul>
    {/if}

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
      <p class="notice">
        {#if manifest.status === 'error'}The layers manifest could not be loaded, so the full citation cannot be shown.
        {:else}No layer in the manifest covers this place's collection, so the full citation cannot be shown.{/if}
      </p>
    {/if}

    <h2>Use in</h2>
    <div class="row">
      {#if layer}<a class="btn secondary" href={calcofiLink(layer.slug)} target="_blank" rel="noopener noreferrer">CalCOFI explore</a>{/if}
      <a class="btn secondary" href={erddapLink(id)} target="_blank" rel="noopener noreferrer">erddap-places</a>
      <a class="btn secondary" href={withBase(`/?${layer ? `layers=${layer.slug}&` : ''}place=${id}`, BASE)}>This map</a>
    </div>

    <h2>Downloads</h2>
    <ValuesDownload placeId={id} />
    <h3>The boundary</h3>
    {#if layer?.kind === 'derived'}
      <p>These places are computed by Ocean Metrics from {viaTitle(layer, manifest.layers)}; their geometry stays internal, so there is no download.</p>
    {:else if isRef}
      <p>The source asked that its data not be republished, so there is no copy here:
        {#if layer?.raster?.link}<a href={layer.raster.link} target="_blank" rel="noopener noreferrer">get it from {layer.source_link?.title ?? 'the source'}</a>{:else}get it from the source{/if}.</p>
    {:else}
      <div class="row">
        {#if url}<a class="btn secondary" href={url}>Collection GeoParquet</a>{/if}
        <a class="btn secondary" href={geojsonHref} download={fileName}>GeoJSON (this place)</a>
      </div>
      {#if sql}
        <h4>Or copy this DuckDB SQL to write GeoJSON from the parquet</h4>
        <pre>{sql}</pre>
        <CopyButton text={sql} label="Copy SQL" />
      {/if}
    {/if}
  {/if}
</main>

<style>
  .copies { margin: 0 0 8px; padding-left: 1.2rem; }
  .source { display: flex; flex-wrap: wrap; gap: 8px 12px; align-items: center; margin: 4px 0 0; }
  .mapbox { position: relative; height: 22rem; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; margin: 12px 0; }
  @media (max-width: 600px) { .mapbox { height: 16rem; } }
</style>
