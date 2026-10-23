<script lang="ts">
  // the site's map (home, layer and place pages): MapLibre 6 through `@oceanmetrics/map` (`setupMapLibre`, once a page, in
  // map/setup.ts), the basemap `composeStyle` builds (CARTO's style with the GEBCO sea floor, isobaths, land mask and
  // undersea names, both themes: map/basemap.ts), the gazetteer layers through the places client, a highlighted place,
  // popups and identify, and on the place page the layer under the map: a `grid` slot (`@oceanmetrics/map` `gridSlot` over
  // the engine's slice of the place's own lobes at `t`, map/gridKind.ts) mounted under the land mask. what is the
  // basemap's is the layer ids of the style set (`basemapLayerIds`); a theme flip carries every other layer into the next
  // style (`carryLayers`), then the place layers go back under the names.
  import { Map as MlMap, NavigationControl, Popup, ScaleControl } from 'maplibre-gl'
  import type { GeoJSONSource, IControl, MapGeoJSONFeature, Point, LngLat, StyleSpecification } from 'maplibre-gl'
  import 'maplibre-gl/dist/maplibre-gl.css'
  import { basemapLayerIds, carryLayers, isSlotLayer, parseLayerKey, registerSlotKind, seaSurfaceId, slotFor } from '@oceanmetrics/map'
  import type { LayerSlot, LegendSpec } from '@oceanmetrics/map'
  import { addLayer, creditsFor, displaySource, identify, layerLabel, removeLayer, layerId, DRAW_KINDS, type BBox, type DerivedPiece, type Layer, type PlaceFeature } from '@oceanmetrics/places'
  import { onMount, untrack } from 'svelte'
  import { placesBeforeId, styleCredit, styleFor } from './map/basemap'
  import { setupMap } from './map/setup'
  import { gridKind } from './map/gridKind'
  import { stepDate } from './map/gridLayer'
  import { buildSearch, parseView, type LayerSel, type Projection } from './grammar'
  import { drawable, layerPath, pieceProps, sanitizeHtml, withBase, fmtDate, placePath } from './helpers'
  import { BASE } from './data.svelte'
  import { loc, navigate } from './router.svelte'
  import { theme } from './theme.svelte'

  interface Props {
    /** layers on the map, first on top */
    selected?: LayerSel[]
    /** the manifest (to find a layer by slug) */
    layers?: Layer[]
    /** a place drawn on top, with a fit to its bounds when it changes */
    highlight?: PlaceFeature | null
    /** bounds to fit once the map loads (e.g. a layer page), when there is no highlight */
    fit?: BBox | null
    /** click a feature: popup with name/status/attribution (off for the place page) */
    popups?: boolean
    onpick?: (placeId: string | null) => void
    onlayererror?: (slug: string) => void
    /** the layer under the map (`grid:<dataset>:<variable>`), sliced by `slicePlace`'s polygon; null for none */
    layerKey?: string | null
    /** the period the layer is drawn at (`2024-07`); null = the dataset's latest */
    t?: string | null
    /** the place whose polygon masks the layer (its own lobes are sliced) */
    slicePlace?: string | null
    /** the layer's legend, each time it changes (null when there is none) */
    onlegend?: (legend: LegendSpec | null, credit: string | null) => void
  }
  let { selected = [], layers = [], highlight = null, fit = null, popups = true, onpick, onlayererror, layerKey = null, t = null, slicePlace = null, onlegend }: Props = $props()

  let el: HTMLDivElement
  let map: MlMap | undefined
  let ready = $state(false)
  let on = new Set<string>()        // slugs currently on the map
  // derived layers on the map: the piece each drawn `via` feature stands for, by the feature's place_id (= the piece's source_id)
  const pieceOf = new Map<string, Map<string, DerivedPiece>>()
  let queue: Promise<void> = Promise.resolve()
  const failed = new Set<string>()

  const HL = 'place-hl'

  // credit line control: the basemap plus creditsFor() of what is visible ----
  class CreditsControl implements IControl {
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
    layers = ''
    base = ''
    slot = ''
    set(html: string) { this.layers = html; this.draw() }
    setSlot(text: string) { this.slot = text; this.draw() }
    setBase(html: string) { this.base = html; this.draw() }
    draw() {
      this.body.innerHTML = [this.layers, this.slot ? escapeHtml(this.slot) : '', this.base].filter(Boolean).map(sanitizeHtml).join(' · ')
    }
    onAdd() { return this.box }
    onRemove() { this.box.remove() }
  }
  const credits = new CreditsControl()
  const escapeHtml = (t: string) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

  // fit padding that keeps the fitted bounds clear of the zoom/projection buttons (right) and the credits box (bottom) ----
  const fitPadding = () => {
    const h = el?.clientHeight ?? 0
    return { top: 32, left: 32, right: 56, bottom: Math.min(Math.max(32, credits.box.offsetHeight + 16), Math.round(h / 3)) }
  }

  // projection: globe by default, mercator with ?proj=mercator; the button writes the URL, the URL drives the map ----
  const proj = $derived(parseView(loc.search).proj)
  class ProjectionControl implements IControl {
    box = document.createElement('div')
    btn = document.createElement('button')
    constructor() {
      this.box.className = 'maplibregl-ctrl maplibregl-ctrl-group'
      this.btn.type = 'button'
      this.btn.innerHTML = '<span class="maplibregl-ctrl-icon" aria-hidden="true"></span>'
      this.btn.addEventListener('click', () => {
        const next: Projection = proj === 'globe' ? 'mercator' : 'globe'
        navigate(loc.path + buildSearch({ proj: next }, loc.search), { replace: true })
      })
      this.box.append(this.btn)
    }
    set(p: Projection) {
      // maplibre's own globe icons: plain = "switch to globe", -enabled = "switch to flat map"
      this.btn.className = p === 'globe' ? 'maplibregl-ctrl-globe-enabled' : 'maplibregl-ctrl-globe'
      this.btn.title = p === 'globe' ? 'Flat map (Mercator)' : 'Globe'
      this.btn.setAttribute('aria-label', p === 'globe' ? 'Switch to a flat Mercator map' : 'Switch to the globe')
    }
    onAdd() { return this.box }
    onRemove() { this.box.remove() }
  }
  const projCtrl = new ProjectionControl()

  const refreshCredits = async () => {
    const slugs = selected.map((s) => s.slug).filter((s) => layers.some((l) => l.slug === s && drawable(l, layers)))
    try { credits.set(slugs.length ? await creditsFor(slugs, { html: true }) : '') } catch { credits.set('') }
  }

  // sync the selected layers with the map (serialised: addLayer is async) ----
  async function doSync(sel: LayerSel[]) {
    const m = map
    if (!m) return
    // a derived layer whose `via` layer is missing is listed (the layer list says why) but not drawn
    const want = sel.filter((s) => layers.some((l) => l.slug === s.slug && drawable(l, layers)))
    const slugs = new Set(want.map((w) => w.slug))
    for (const s of [...on]) if (!slugs.has(s)) { removeLayer(m, s); on.delete(s); pieceOf.delete(s) }
    for (const w of want) {
      try {
        await addLayer(m, w.slug, { colour: w.colour ?? undefined, opacity: w.opacity ?? undefined, width: w.width ?? undefined, beforeId: below() })
        on.add(w.slug)
        if (layers.find((l) => l.slug === w.slug)?.kind === 'derived' && !pieceOf.has(w.slug)) {
          const d = await displaySource(w.slug)
          if (d) pieceOf.set(w.slug, new Map([...d.pieces].reverse().map((p) => [p.source_id, p])))   // the first piece of a source_id wins
        }
      } catch (e) {
        console.warn(`places: layer ${w.slug} not drawn`, e)
        if (!failed.has(w.slug)) { failed.add(w.slug); onlayererror?.(w.slug) }
      }
    }
    restack(m, want)
  }

  /** draw order: first entry on top; move bottom-up under the names, then the highlight above every place layer */
  function restack(m: MlMap, want: LayerSel[] = selected) {
    const b = below()
    for (const w of [...want].reverse()) for (const k of DRAW_KINDS) if (m.getLayer(layerId(w.slug, k))) m.moveLayer(layerId(w.slug, k), b)
    for (const id of [`${HL}-fill`, `${HL}-line`, `${HL}-point`]) if (m.getLayer(id)) m.moveLayer(id, b)
    // the layer under the map stays under the land mask (it may have been mounted on the boot style, which has none)
    if (sea && m.getLayer(sea)) for (const l of m.getStyle().layers) if (isSlotLayer(l.id)) m.moveLayer(l.id, sea)
  }

  $effect(() => {
    if (!ready) return
    const sel = selected.map((s) => ({ ...s })), _l = layers.length
    void _l
    queue = queue.then(() => doSync(sel)).then(refreshCredits).then(fitOnce)
  })

  // the `fit` bounds, once, after the first credits refresh: the padding needs the credits box at its final height
  let fitPending = true
  function fitOnce() {
    if (!fitPending || !map) return
    fitPending = false
    if (fit && !highlight) map.fitBounds([[fit[0], fit[1]], [fit[2], fit[3]]], { padding: fitPadding(), maxZoom: 10, duration: 0 })
  }

  // the highlighted place ----
  let lastFit = ''
  /** the highlight's data (again after a restyle: the style diff can hand the source back as it was when carried) */
  function drawHighlight(m: MlMap) {
    const src = m.getSource(HL) as GeoJSONSource | undefined
    if (!src) return
    if (!highlight) { src.setData({ type: 'FeatureCollection', features: [] }); lastFit = ''; return }
    src.setData(highlight as any)
    const key = String(highlight.id)
    if (key !== lastFit && highlight.bbox) {
      lastFit = key
      const [w, s, e, n] = highlight.bbox as BBox
      m.fitBounds([[w, s], [e, n]], { padding: fitPadding(), maxZoom: 10, duration: 600 })
    }
  }
  $effect(() => {
    void highlight
    if (ready && map) untrack(() => drawHighlight(map!))
  })

  // popup ----
  function popupContent(f: Pick<MapGeoJSONFeature, 'properties' | 'source'>): HTMLElement {
    const p = f.properties ?? {}
    const slug = String(f.source).replace(/^places:/, '')
    const layer = layers.find((l) => l.slug === slug)
    const root = document.createElement('div')
    root.className = 'popup'
    const h = document.createElement('strong')
    h.textContent = String(p.name ?? p.NAME ?? p.place_id ?? (layer ? layerLabel(layer) : slug))
    root.append(h)
    const line = (label: string, v: unknown) => {
      if (v == null || v === '') return
      const d = document.createElement('div')
      d.className = 'popup-row'
      d.textContent = `${label}: ${v}`
      root.append(d)
    }
    line('Layer', (layer ? layerLabel(layer) : slug))
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
    if (p.url && /^https?:\/\//.test(String(p.url))) {      // the place's own page at its source (e.g. Marine Regions)
      const sa = document.createElement('a')
      sa.href = String(p.url)
      sa.target = '_blank'
      sa.rel = 'noopener'
      sa.textContent = layer?.source_link?.title ? `At ${layer.source_link.title}` : 'At source'
      links.append(' · ', sa)
    }
    root.append(links)
    if (layer?.attribution_html || layer?.attribution) {
      const at = document.createElement('div')
      at.className = 'popup-attr'
      at.innerHTML = sanitizeHtml(layer.attribution_html || layer.attribution)
      root.append(at)
    }
    return root
  }

  // the GetFeatureInfo box: 101 x 101 screen pixels round the click (the point at the centre pixel, so a buffer for
  // lines matches the screen); off the globe's edge, a small box in degrees ----
  function clickBox(m: MlMap, pt: Point, ll: LngLat): BBox {
    const a = m.unproject([pt.x - 50, pt.y + 50]), b = m.unproject([pt.x + 50, pt.y - 50])
    const ok = [a.lng, a.lat, b.lng, b.lat].every(Number.isFinite) && a.lng < b.lng && a.lat < b.lat
    if (ok) return [a.lng, a.lat, b.lng, b.lat]
    const d = 0.01
    return [ll.lng - d, ll.lat - d, ll.lng + d, ll.lat + d]
  }

  // ---- the basemap: the style in force, and what of it is the basemap's ----
  let basemap = new Set<string>()
  let sea: string | null = null
  let before: string | null = null
  const below = () => (before && map?.getLayer(before) ? before : undefined)
  function setBasemap(style: StyleSpecification) {
    basemap = basemapLayerIds(style)
    sea = seaSurfaceId(style)
    before = placesBeforeId(style.layers)
    credits.setBase(styleCredit(style))
  }
  // the tiers on (or a theme flip): the next style, every layer of ours carried over, then the places back under the names
  let restyleSeq = 0
  let styledDark: boolean | null = null
  async function restyle(m: MlMap, d: boolean) {
    const seq = ++restyleSeq
    const next = await styleFor(d, true)
    if (seq !== restyleSeq || map !== m) return
    const old = basemap
    m.setStyle({ ...next, projection: { type: untrack(() => proj) } }, { diff: true, transformStyle: carryLayers((id) => !old.has(id)) })
    setBasemap(next)
    styledDark = d
    const after = () => { restack(m); drawHighlight(m); placeSlot(m) }
    if ((m as unknown as { style?: { _loaded?: boolean } }).style?._loaded !== false) after()
    else m.once('style.load', after)
  }

  onMount(() => {
    let dead = false
    let ro: ResizeObserver | null = null
    let made: MlMap | null = null
    void (async () => {
      await setupMap()
      const d = untrack(() => theme.dark)
      // the boot style is CARTO's own: the first paint never waits on the terrain tiers, which come on at `load`
      const style = await styleFor(d, false)
      if (dead) return
      const m = (made = new MlMap({
        // the whole globe on a first visit; the flat map opens closer, as before
        container: el, style: { ...style, projection: { type: untrack(() => proj) } }, center: [-121, 36], zoom: untrack(() => proj) === 'globe' ? 2 : 3.4,
        attributionControl: false, hash: false, renderWorldCopies: true,
      }))
      map = m
      setBasemap(style)
      styledDark = d
      m.addControl(new NavigationControl({ showCompass: false }), 'top-right')
      m.addControl(projCtrl, 'top-right')
      m.addControl(new ScaleControl({ unit: 'metric' }), 'bottom-left')
      m.addControl(credits, 'bottom-right')
      ro = new ResizeObserver(() => m.resize())
      ro.observe(el)

      m.on('load', () => {
        projCtrl.set(untrack(() => proj))
        m.addSource(HL, { type: 'geojson', data: { type: 'FeatureCollection', features: [] } })
        const acc = '#f5b528'   // the brand's one warm spark (oceanmetrics.io/brand/v1)
        m.addLayer({ id: `${HL}-fill`, type: 'fill', source: HL, filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': acc, 'fill-opacity': 0.25 } }, below())
        m.addLayer({ id: `${HL}-line`, type: 'line', source: HL, paint: { 'line-color': acc, 'line-width': 3 } }, below())
        m.addLayer({ id: `${HL}-point`, type: 'circle', source: HL, filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-color': acc, 'circle-radius': 7, 'circle-stroke-color': '#000', 'circle-stroke-width': 1.5 } }, below())
        ready = true
        void restyle(m, untrack(() => theme.dark))
      })

      // a tile source that fails (a collection not published yet) is reported once, the page keeps working
      m.on('error', (e: any) => {
        const sid = String(e?.sourceId ?? '')
        if (sid.startsWith('places:')) {
          const slug = sid.slice(7)
          if (!failed.has(slug)) { failed.add(slug); onlayererror?.(slug) }
        }
      })

      // a clicked feature of a derived layer is the `via` layer's feature (an FAO area); it stands for the derived place
      const asPlace = (f: MapGeoJSONFeature): Pick<MapGeoJSONFeature, 'properties' | 'source'> => {
        const slug = String(f.source).replace(/^places:/, '')
        const piece = pieceOf.get(slug)?.get(String(f.properties?.place_id))
        const layer = layers.find((l) => l.slug === slug)
        return piece && layer ? { properties: pieceProps(piece, layer), source: f.source } : f
      }
      const interactive = () => m.getStyle().layers.filter((l) => l.id.startsWith('places:') && l.type !== 'raster').map((l) => l.id)
      if (popups) {
        m.on('click', async (e) => {
          const ids = interactive()
          const f = ids.length ? m.queryRenderedFeatures(e.point, { layers: ids })[0] : undefined
          if (f) {
            const p = asPlace(f)
            new Popup({ maxWidth: '320px' }).setLngLat(e.lngLat).setDOMContent(popupContent(p)).addTo(m)
            if (p.properties?.place_id) onpick?.(String(p.properties.place_id))
            return
          }
          // a reference layer is the publisher's PNG tiles: ask its GetFeatureInfo what is under the point (first on top)
          const refs = selected.map((s) => layers.find((l) => l.slug === s.slug)).filter((l): l is Layer => !!l && on.has(l.slug) && l.kind === 'raster' && !!l.raster?.info_url)
          if (!refs.length) { onpick?.(null); return }
          for (const l of refs) {
            let hits: Awaited<ReturnType<typeof identify>> = []
            try { hits = await identify(l.slug, clickBox(m, e.point, e.lngLat)) } catch { continue }
            if (!hits.length) continue
            const h = hits[0]
            new Popup({ maxWidth: '320px' }).setLngLat(e.lngLat)
              .setDOMContent(popupContent({ properties: { name: h.name, place_id: h.place_id, url: h.url }, source: `places:${l.slug}` })).addTo(m)
            onpick?.(h.place_id)
            return
          }
          onpick?.(null)
        })
        m.on('mousemove', (e) => {
          const ids = interactive()
          m.getCanvas().style.cursor = ids.length && m.queryRenderedFeatures(e.point, { layers: ids }).length ? 'pointer' : ''
        })
      }
    })()

    return () => { dead = true; ro?.disconnect(); mounted?.unmount(made!); mounted = null; made?.remove(); map = undefined }
  })

  // ---- the layer under the map ----
  let slot = $state<LayerSlot | null>(null)
  let mounted: LayerSlot | null = null
  let slotSeq = 0
  const legendNow = () => { credits.setSlot(slot?.credit ?? ''); onlegend?.(slot?.legend() ?? null, slot?.credit ?? null) }
  $effect(() => {
    const key = layerKey, place = slicePlace
    const seq = ++slotSeq
    const spec = parseLayerKey(key)
    if (!spec || spec.kind !== 'grid' || !place) { slot = null; untrack(() => onlegend?.(null, null)); return }
    registerSlotKind('grid', gridKind(place))
    slotFor(spec, { onchange: () => { if (seq === slotSeq) legendNow() } })
      .then((s) => { if (seq === slotSeq) { slot = s; legendNow() } })
      .catch((e: unknown) => {
        if (seq !== slotSeq) return
        slot = null
        onlegend?.({ title: spec.id + (spec.variable ? ` (${spec.variable})` : ''), t: stepDate(untrack(() => t)), via: 'grid slice', problem: `not drawn: ${(e as Error)?.message ?? e}` }, null)
      })
  })
  /** the slot under the land mask (its data stays off the land and under the labels), and the highlight's fill cleared over it */
  function placeSlot(m: MlMap) {
    if (mounted !== slot) {
      mounted?.unmount(m)
      mounted = slot
      slot?.mount(m, sea && m.getLayer(sea) ? sea : null, stepDate(untrack(() => t)))
      restack(m)
      legendNow()
    }
    if (m.getLayer(`${HL}-fill`)) m.setPaintProperty(`${HL}-fill`, 'fill-opacity', mounted ? 0 : 0.25)
  }
  $effect(() => {
    void slot
    if (ready && map) untrack(() => placeSlot(map!))
  })
  let lastT: string | null | undefined
  $effect(() => {
    const tt = stepDate(t)
    if (lastT !== undefined && tt !== lastT && mounted) mounted.update(tt)
    lastT = tt
  })

  $effect(() => {
    const p = proj
    if (!map || !ready) return
    if (map.getProjection()?.type !== p) map.setProjection({ type: p })
    projCtrl.set(p)
  })

  // the basemap follows the app theme (header toggle or OS; src/lib/theme.svelte.ts)
  $effect(() => {
    const d = theme.dark
    if (map && ready && styledDark !== null && d !== styledDark) void restyle(map, d)
  })

  /** let a parent move the map. */
  export function fitTo(b: BBox) {
    map?.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: fitPadding(), maxZoom: 10, duration: 600 })
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
