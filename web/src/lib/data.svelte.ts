// the gazetteer connection: base url, the layers manifest and the places index, each with a status the pages can show
import { configure, listLayers, search, type IndexPlace, type Layer } from '@oceanmetrics/places'
import { DEFAULT_BASE, slash } from './helpers'

function resolveBase(): string {
  const q = new URLSearchParams(location.search).get('base')
  return slash(q || (import.meta.env.VITE_PLACES_BASE as string | undefined) || DEFAULT_BASE)
}

/** the data root: `?base=` > VITE_PLACES_BASE > https://storage.oceanmetrics.io/gazetteer/ */
export const BASE = resolveBase()
configure({ base: BASE })

export const manifest = $state<{ status: 'loading' | 'ok' | 'error'; layers: Layer[]; error: string }>({ status: 'loading', layers: [], error: '' })
export const index = $state<{ status: 'idle' | 'ok' | 'error'; error: string }>({ status: 'idle', error: '' })

let started: Promise<void> | null = null

/** load layers.json once; a failure leaves an empty list and a message (the pages render regardless). */
export function loadManifest(): Promise<void> {
  started ??= listLayers()
    .then((ls) => { manifest.layers = ls; manifest.status = 'ok' })
    .catch((e: unknown) => { manifest.status = 'error'; manifest.error = String((e as Error)?.message ?? e) })
  return started
}

/** search the places index; on failure (e.g. the index is not published yet) mark it and return []. */
export async function searchPlaces(q: string, limit = 12): Promise<IndexPlace[]> {
  try {
    const r = await search(q, { limit })
    index.status = 'ok'
    return r
  } catch (e) {
    index.status = 'error'
    index.error = String((e as Error)?.message ?? e)
    return []
  }
}
