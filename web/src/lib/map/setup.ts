// the MapLibre setup, once a page, shared by every map of the site (home, layer and place pages): MapLibre 6's worker
// module and the pmtiles:// protocol through `@oceanmetrics/map` `setupMapLibre`. it is given the same object each time
// (setupMapLibre refuses a second maplibre-gl module), and the three functions, not the namespace, which would keep every
// export of maplibre-gl in the bundle.
import { addProtocol, importScriptInWorkers, setWorkerUrl } from 'maplibre-gl'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url'
import { setupMapLibre } from '@oceanmetrics/map'

const MAPLIBRE = { addProtocol, importScriptInWorkers, setWorkerUrl }
let done: Promise<void> | null = null

export function setupMap(): Promise<void> {
  done ??= setupMapLibre({ maplibre: MAPLIBRE, workerUrl, protocols: ['pmtiles'] })
  done.catch(() => { done = null })
  return done
}
