// the `grid` kind of the layer slot on the place page: `@oceanmetrics/map`'s `gridSlot` (one square per cell of the
// dataset's own lattice, a ramp fill, holes where the step has no data) over a slice the engine computes in the browser
// for the place's own lobes. the factory reads the gazetteer's `erddap/<id>/collection.json` (small, here); the engine,
// DuckDB-WASM and the place polygon arrive with the first slice (gridSource.ts, a lazy chunk). the rules (the choices, the
// budget, the title, the legend line, the credit) are gridLayer.ts.
import { defaultRampFor, gridSlot } from '@oceanmetrics/map'
import type { LayerSlot, LayerSpec, SlotOptions } from '@oceanmetrics/map'
import { GAZETTEER_STAC, erddapCollectionUrl, erddapEntries, gridCredit, gridTitle, gridVia, problemText, toErddapLayer, unitLabel, withRetries, type ErddapLayer } from './gridLayer'
import type { GridSource } from './gridSource'

const collections = new Map<string, Promise<ErddapLayer>>()

/** an ERDDAP collection of the gazetteer, read once a page */
export function loadErddapLayer(id: string, fetchFn: typeof fetch = fetch): Promise<ErddapLayer> {
  let p = collections.get(id)
  if (!p) {
    p = (async () => {
      const r = await fetchFn(erddapCollectionUrl(id))
      if (!r.ok) throw new Error(`erddap/${id}: HTTP ${r.status}`)
      return toErddapLayer(id, await r.json())
    })()
    collections.set(id, p)
    p.catch(() => collections.delete(id))
  }
  return p
}

/** the pause before a dropped request is asked again (grows with each try: gridLayer.ts `withRetries`) */
export const RETRY_MS = 1500

/** the slot factory of the `grid` kind over one place (its id, read with its antimeridian split as the engine expects) */
export function gridKind(placeId: string) {
  return async (spec: LayerSpec, opts: SlotOptions): Promise<LayerSlot> => {
    const layer = await loadErddapLayer(spec.id, opts.fetch ?? fetch)
    if (layer.protocol !== 'griddap') throw new Error(`erddap/${spec.id} is not a grid (${layer.protocol})`)
    const name = spec.variable ?? layer.variables[0]?.name
    const v = layer.variables.find((x) => x.name === name)
    if (!name || !v) throw new Error(`erddap/${spec.id} has no variable ${spec.variable ?? 'to draw'}`)
    let prepared: Promise<GridSource> | null = null
    const prepare = () => {
      prepared ??= import('./gridSource').then((m) => m.prepareGridSource(layer.raw, name, placeId))
      prepared.catch(() => { prepared = null })
      return prepared
    }
    const source = () => withRetries(prepare, 4, RETRY_MS)
    const title = gridTitle(layer.title, v)
    return gridSlot({ ...spec, variable: name }, {
      async slice(t, signal) {
        let g: GridSource
        try { g = await source() } catch (e) { throw new Error(problemText(e)) }
        const s0 = performance.now()
        const rows = await withRetries(() => g.source.slice(t, signal), 3, RETRY_MS, signal).catch((e) => { throw signal?.aborted ? e : new Error(problemText(e)) })
        console.info(`[om] grid slice ${spec.id}:${name} at ${t ?? 'latest'}: ${rows.length} cells, ${g.lobes} lobes, ${Math.round(performance.now() - s0)} ms`)
        return rows
      },
    }, {
      title, credit: gridCredit(title, layer.producers, layer.host), units: unitLabel(v.unit), via: gridVia(layer.host), opacity: 0.9,
      ramp: defaultRampFor(name, { units: v.unit ?? undefined }), onchange: opts.onchange,
    })
  }
}

let catalog: Promise<ErddapLayer[]> | null = null

/** every ERDDAP collection the gazetteer's STAC catalog lists, read once a page (one that does not answer is left out) */
export function loadErddapLayers(fetchFn: typeof fetch = fetch): Promise<ErddapLayer[]> {
  catalog ??= (async () => {
    const r = await fetchFn(`${GAZETTEER_STAC}catalog.json`)
    if (!r.ok) throw new Error(`gazetteer catalog.json: HTTP ${r.status}`)
    const got = await Promise.all(erddapEntries(await r.json()).map((e) => loadErddapLayer(e.id, fetchFn).catch(() => null)))
    return got.filter((l): l is ErddapLayer => !!l)
  })()
  catalog.catch(() => { catalog = null })
  return catalog
}
