<script lang="ts">
  import maplibregl from 'maplibre-gl'
  import 'maplibre-gl/dist/maplibre-gl.css'
  import * as pmtiles from 'pmtiles'
  import { addLayer, creditsFor, registerPmtiles, removeLayer, layerId, type BBox, type Layer, type PlaceFeature } from '@oceanmetrics/places'
  import { onMount } from 'svelte'
  import { applyTheme, BASEMAP_CREDIT, LABELS_BELOW, style } from './basemap'
  import type { LayerSel } from './grammar'
  import { layerPath, sanitizeHtml, withBase, fmtDate, placePath } from './helpers'
  import { BASE } from './data.svelte'
  import { theme } from './theme.svelte'

  interface Props {
    /** layers on the map, first on top */
    selected?: LayerSel[]
    /** the manifest (to find a layer by slug) */
    layers?: Layer[]
    /** a place drawn on top, with a fit to its bounds when it changes */
    highlight?: PlaceFeature | null
    /** click a feature: popup with name/status/attribution (off for the place page) */
    popups?: boolean
    onpick?: (placeId: string | null) => void
    onlayererror?: (slug: string) => void
  }
  let { selected = [], layers = [], highlight = null, popups = true, onpick, onlayererror }: Props = $props()

  let el: HTMLDivElement
  let map: maplibregl.Map | undefined
  let ready = $state(false)
  let on = new Set<string>()        // slugs currently on the map
  let queue: Promise<void> = Promise.resolve()
  const failed = new Set<string>()

  const HL = 'place-hl'

  // credit line control: the basemap plus creditsFor() of what is visible ----
  class CreditsControl implements maplibregl.IControl {
    box = document.createElement('div')
    body = document.createElement('div')
    btn = document.createElement('button')
    constructor() {
      this.box.className = 'maplibregl-ctrl credits-ctrl'
      this.btn.type = 'button'
      this.btn.className = 'credits-btn'
      this.btn.textContent = 'i'
      this.btn.title = 'Data credits'
      this.btn.setAttribute('aria-label', 'Show or hide data credits')
      this.btn.addEventListener('click', () => this.box.classList.toggle('open'))
      this.body.className = 'credits-body'
      this.box.append(this.body, this.btn)
      this.set('')
    }
    set(html: string) {
      this.body.innerHTML = (html ? sanitizeHtml(html) + ' ' : '') + BASEMAP_CREDIT
    }
    onAdd() { return this.box }
    onRemove() { this.box.remove() }
  }
  const credits = new CreditsControl()

  const refreshCredits = async () => {
    const slugs = selected.map((s) => s.slug).filter((s) => layers.some((l) => l.slug === s))
    try { credits.set(slugs.length ? await creditsFor(slugs, { html: true }) : '') } catch { credits.set('') }
  }

  // sync the selected layers with the map (serialised: addLayer is async) ----
  async function doSync(sel: LayerSel[]) {
    const m = map
    if (!m) return
    const want = sel.filter((s) => layers.some((l) => l.slug === s.slug))
    const slugs = new Set(want.map((w) => w.slug))
    for (const s of [...on]) if (!slugs.has(s)) { removeLayer(m, s); on.delete(s) }
    for (const w of want) {
      try {
        await addLayer(m, w.slug, { colour: w.colour ?? undefined, opacity: w.opacity ?? undefined, width: w.width ?? undefined, beforeId: LABELS_BELOW })
        on.add(w.slug)
      } catch (e) {
        console.warn(`places: layer ${w.slug} not drawn`, e)
        if (!failed.has(w.slug)) { failed.add(w.slug); onlayererror?.(w.slug) }
      }
    }
    // draw order: first entry on top; move bottom-up, then the highlight above everything
    for (const w of [...want].reverse()) for (const k of ['fill', 'line', 'circle'] as const) if (m.getLayer(layerId(w.slug, k))) m.moveLayer(layerId(w.slug, k), LABELS_BELOW)
    for (const id of [`${HL}-fill`, `${HL}-line`, `${HL}-point`]) if (m.getLayer(id)) m.moveLayer(id, LABELS_BELOW)
  }

  $effect(() => {
    if (!ready) return
    const sel = selected.map((s) => ({ ...s })), _l = layers.length
    void _l
    queue = queue.then(() => doSync(sel)).then(refreshCredits)
  })

  // the highlighted place ----
  let lastFit = ''
  $effect(() => {
    if (!ready || !map) return
    const src = map.getSource(HL) as maplibregl.GeoJSONSource | undefined
    if (!src) return
    if (!highlight) { src.setData({ type: 'FeatureCollection', features: [] }); lastFit = ''; return }
    src.setData(highlight as any)
    const key = String(highlight.id)
    if (key !== lastFit && highlight.bbox) {
      lastFit = key
      const [w, s, e, n] = highlight.bbox as BBox
      map.fitBounds([[w, s], [e, n]], { padding: 48, maxZoom: 10, duration: 600 })
    }
  })

  // popup ----
  function popupContent(f: maplibregl.MapGeoJSONFeature): HTMLElement {
    const p = f.properties ?? {}
    const slug = String(f.source).replace(/^places:/, '')
    const layer = layers.find((l) => l.slug === slug)
    const root = document.createElement('div')
    root.className = 'popup'
    const h = document.createElement('strong')
    h.textContent = String(p.name ?? p.NAME ?? p.place_id ?? layer?.title ?? slug)
    root.append(h)
    const line = (label: string, v: unknown) => {
      if (v == null || v === '') return
      const d = document.createElement('div')
      d.className = 'popup-row'
      d.textContent = `${label}: ${v}`
      root.append(d)
    }
    line('Layer', layer?.title ?? slug)
    line('Status', p.status)
    line('Status date', p.status_date ? fmtDate(String(p.status_date)) : null)
    const links = document.createElement('div')
    links.className = 'popup-row'
    if (p.place_id) {
      const a = document.createElement('a')
      a.href = withBase(placePath(String(p.place_id)), BASE)
      a.textContent = 'Place page'
      links.append(a, ' · ')
    }
    const la = document.createElement('a')
    la.href = withBase(layerPath(slug), BASE)
    la.textContent = 'Layer page'
    links.append(la)
    root.append(links)
    if (layer?.attribution_html || layer?.attribution) {
      const at = document.createElement('div')
      at.className = 'popup-attr'
      at.innerHTML = sanitizeHtml(layer.attribution_html || layer.attribution)
      root.append(at)
    }
    return root
  }

  onMount(() => {
    registerPmtiles(maplibregl, pmtiles)
    const m = new maplibregl.Map({
      container: el, style, center: [-121, 36], zoom: 3.4, attributionControl: false, hash: false, renderWorldCopies: true,
    })
    map = m
    m.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right')
    m.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left')
    m.addControl(credits, 'bottom-right')

    m.on('load', () => {
      applyTheme(m, theme.dark)
      m.addSource(HL, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
      const acc = '#f5b528'   // the brand's one warm spark (oceanmetrics.io/brand/v1)
      m.addLayer({ id: `${HL}-fill`, type: 'fill', source: HL, filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': acc, 'fill-opacity': 0.25 } }, LABELS_BELOW)
      m.addLayer({ id: `${HL}-line`, type: 'line', source: HL, paint: { 'line-color': acc, 'line-width': 3 } }, LABELS_BELOW)
      m.addLayer({ id: `${HL}-point`, type: 'circle', source: HL, filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-color': acc, 'circle-radius': 7, 'circle-stroke-color': '#000', 'circle-stroke-width': 1.5 } }, LABELS_BELOW)
      ready = true
    })

    // a tile source that fails (a collection not published yet) is reported once, the page keeps working
    m.on('error', (e: any) => {
      const sid = String(e?.sourceId ?? '')
      if (sid.startsWith('places:')) {
        const slug = sid.slice(7)
        if (!failed.has(slug)) { failed.add(slug); onlayererror?.(slug) }
      }
    })

    const interactive = () => m.getStyle().layers.map((l) => l.id).filter((id) => id.startsWith('places:'))
    if (popups) {
      m.on('click', (e) => {
        const ids = interactive()
        const f = ids.length ? m.queryRenderedFeatures(e.point, { layers: ids })[0] : undefined
        if (!f) { onpick?.(null); return }
        new maplibregl.Popup({ maxWidth: '320px' }).setLngLat(e.lngLat).setDOMContent(popupContent(f)).addTo(m)
        if (f.properties?.place_id) onpick?.(String(f.properties.place_id))
      })
      m.on('mousemove', (e) => {
        const ids = interactive()
        m.getCanvas().style.cursor = ids.length && m.queryRenderedFeatures(e.point, { layers: ids }).length ? 'pointer' : ''
      })
    }

    return () => { m.remove(); map = undefined }
  })

  // the basemap follows the app theme (header toggle or OS; src/lib/theme.svelte.ts)
  $effect(() => {
    const d = theme.dark
    if (map && ready) applyTheme(map, d)
  })

  /** let a parent move the map. */
  export function fitTo(b: BBox) {
    map?.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: 48, maxZoom: 10, duration: 600 })
  }
</script>

<div class="map" bind:this={el}></div>

<style>
  .map { position: absolute; inset: 0; }
  :global(.credits-ctrl) { display: flex; align-items: flex-end; gap: 4px; max-width: min(36rem, 86vw); background: var(--bg-card); color: var(--text); font-size: 11px; line-height: 1.35; border-radius: 4px; box-shadow: 0 0 0 1px var(--border); }
  :global(.credits-ctrl .credits-body) { display: none; padding: 4px 6px; }
  :global(.credits-ctrl.open .credits-body) { display: block; }
  :global(.credits-ctrl .credits-btn) { all: unset; cursor: pointer; width: 24px; height: 24px; text-align: center; font: italic 600 14px/24px Georgia, serif; color: var(--text); }
  :global(.credits-ctrl a) { color: var(--link); }
  @media (min-width: 900px) {
    :global(.credits-ctrl .credits-body) { display: block; }
  }
  :global(.maplibregl-popup-content) { background: var(--bg-card); color: var(--text); border-radius: 6px; padding: 10px 12px; font: 13px/1.4 var(--font); }
  :global(.maplibregl-popup-anchor-top .maplibregl-popup-tip), :global(.maplibregl-popup-anchor-top-left .maplibregl-popup-tip), :global(.maplibregl-popup-anchor-top-right .maplibregl-popup-tip) { border-bottom-color: var(--bg-card); }
  :global(.maplibregl-popup-anchor-bottom .maplibregl-popup-tip), :global(.maplibregl-popup-anchor-bottom-left .maplibregl-popup-tip), :global(.maplibregl-popup-anchor-bottom-right .maplibregl-popup-tip) { border-top-color: var(--bg-card); }
  :global(.maplibregl-popup-close-button) { color: var(--text); }
  :global(.popup .popup-row) { color: var(--text-muted); margin-top: 2px; }
  :global(.popup .popup-attr) { margin-top: 6px; font-size: 11px; color: var(--text-muted); }
  :global(.popup a) { color: var(--link); }
</style>
