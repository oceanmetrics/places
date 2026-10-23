// the `grid` slot's data: a `SliceSource` (`@oceanmetrics/engine` `sliceSource`) over the polygon of the place the page
// shows. this module is the lazy engine chunk: gridKind.ts `import()`s it the first time the slot asks for a slice, so
// DuckDB-WASM, Apache Arrow and the mask (turf) never reach the entry or the map chunk. DuckDB runs in its own Web Worker
// on self-hosted bundles (`?url`: the mvp and eh wasm and worker files from this origin, no CDN, never a blob worker),
// booted once a page, on the first slice. the polygon comes from the gazetteer client as published (split at ±180, which
// `placeLobes` expects; the page's own copy is unwrapped for the map).
import * as duckdb from '@duckdb/duckdb-wasm'
import ehWasm from '@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url'
import ehWorker from '@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url'
import mvpWasm from '@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url'
import mvpWorker from '@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url'
import { Engine, connectBrowser, fetchTimeExtent, lobeAxes, lobeMasks, patientFetch, placeLobes, sliceSource, toDataset } from '@oceanmetrics/engine'
import type { SliceSource } from '@oceanmetrics/engine'
import { getPlace } from '@oceanmetrics/places'
import { axisSteps, overBudget } from './gridLayer'

// every ERDDAP request of the slice asks again when the mirror drops it (@oceanmetrics/engine `patientFetch`:
// a network error, a 404 "unknown datasetID", a 429 or a 5xx is asked again, six tries). the engine's requests pass a url string
const erddapFetch = ((input, init) => patientFetch(String(input), init)) as typeof fetch

let engine: Engine | null = null
const theEngine = () => (engine ??= new Engine(() => connectBrowser(duckdb, {
  mvp: { mainModule: mvpWasm, mainWorker: mvpWorker },
  eh: { mainModule: ehWasm, mainWorker: ehWorker },
})))

export interface GridSource {
  source: SliceSource
  /** cells per step the slice holds, and how many lobes ask ERDDAP for them */
  cells: number
  lobes: number
}

/** the slice over the place: its lobes (one each side of ±180 where it spans it), each lobe's axes, its mask, and the live time extent */
export async function prepareGridSource(collection: unknown, variableName: string, placeId: string): Promise<GridSource> {
  const ds = toDataset(collection)
  const variable = ds.variables.find((v) => v.name === variableName)
  if (!variable) throw new Error(`${ds.id} has no variable ${variableName}`)
  const f = await getPlace(placeId)
  if (!f?.geometry || !/Polygon$/.test(f.geometry.type)) throw new Error('the place has no polygon to mask the grid with')
  const lobes = placeLobes({ place_id: placeId, geometry: f.geometry })
  const over = overBudget(lobes, axisSteps(collection as Parameters<typeof axisSteps>[0]))
  if (over) throw new Error(over)
  const [axes, extent] = await Promise.all([lobeAxes(ds, lobes, { fetch: erddapFetch }), fetchTimeExtent(ds.baseUrl, ds.datasetId, undefined, { fetchFn: erddapFetch }).catch(() => null)])
  const { cells } = lobeMasks(ds, lobes, axes)
  return { source: sliceSource({ dataset: ds, variable, axes, mask: cells, engine: theEngine(), extent, fetch: erddapFetch }), cells: cells.length, lobes: lobes.length }
}
