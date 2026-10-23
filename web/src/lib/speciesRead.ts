// the Species section's reads (a lazy chunk: hyparquet with its ZSTD codec only when the section loads). the rules are
// species.ts; this fetches and hands rows over.
import { asyncBufferFromUrl, cachedAsyncBuffer, parquetMetadataAsync, parquetReadObjects, type AsyncBuffer } from 'hyparquet'
import { compressors } from 'hyparquet-compressors'
import { store } from './storage'
import {
  groupsHolding, groupsHoldingText, obisSummary, OBIS_LATEST, parseCellSpecies, placeCells, placeExactUrl, placeSpecies, placeSpeciesUrl, sdmSpecies,
  speciesLookupUrl, tilesOf,
  type CellSpeciesHook, type MetaLike, type ObisLookupRow, type ObisRelease, type ObisRow, type ObisSpecies, type ObisSummary, type PlaceSpeciesRow,
  type SdmSpecies, type SpeciesLookupRow,
} from './species'

/** the AquaMaps EOV collection of the atlas */
export const AQUAMAPS_EOV = store('atlas/aquamaps_eov/collection.json')

async function readWhole(url: string, columns: string[]): Promise<Record<string, unknown>[]> {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`HTTP ${r.status}`)
  const file = await r.arrayBuffer()
  return parquetReadObjects({ file, columns, compressors })
}

export interface ObisResult { release: ObisRelease; coll: string; url: string; summary: ObisSummary }

/** the place's OBIS rows from the first collection file that has them; null when none does */
export async function readObis(placeId: string, colls: readonly string[]): Promise<ObisResult | null> {
  const r = await fetch(OBIS_LATEST)
  if (!r.ok) throw new Error(`obis-h3 latest.json: HTTP ${r.status}`)
  const release = (await r.json()) as ObisRelease
  for (const coll of colls) {
    const url = placeExactUrl(release, coll)
    let rows: Record<string, unknown>[]
    try { rows = await readWhole(url, ['place_id', 'eov', 'decade', 'n', 'sp', 'es']) } catch { continue }
    const summary = obisSummary(rows as unknown as ObisRow[], placeId)
    if (summary) return { release, coll, url, summary }
  }
  return null
}

// ---- OBIS, exact: the species of the place ----

/** an AsyncBuffer that counts the bytes its slices return, for the "bytes read" line and the measurements */
export function countBytes(b: AsyncBuffer): AsyncBuffer & { bytes: () => number; requests: () => number } {
  let bytes = 0, requests = 0
  return {
    byteLength: b.byteLength,
    slice: (start, end) => {
      requests++
      return Promise.resolve(b.slice(start, end)).then((ab) => { bytes += ab.byteLength; return ab })
    },
    bytes: () => bytes,
    requests: () => requests,
  }
}

/** the footer is a few kB: ask for the last 64 kB, not hyparquet's 512 kB, so a small file is not read whole for its footer */
const FOOTER = 64 * 1024

const groupsIn = (meta: MetaLike, ranges: { rowStart: number; rowEnd: number }[]) => {
  let start = 0, n = 0
  for (const rg of meta.row_groups) { const end = start + Number(rg.num_rows); if (ranges.some((r) => r.rowStart <= start && end <= r.rowEnd)) n++; start = end }
  return n
}

export interface PlaceSpeciesRead { rows: PlaceSpeciesRow[]; groups: number; groupsRead: number; bytes: number; requests: number; fileBytes: number }

/**
 * the rows of one place from a species.parquet that holds a whole collection, sorted by place_id: only the row groups whose
 * place_id statistics can hold the place are read (columns place_id, aphiaid, name_key, n, year_min, year_max), then filtered
 */
export async function readPlaceSpeciesRows(file: AsyncBuffer, placeId: string, wholeUnder = 1 << 20): Promise<PlaceSpeciesRead> {
  const counted = countBytes(file)
  // a file under `wholeUnder` (1 MB) is fetched once whole: the footer and the groups come from that one request
  const buf = cachedAsyncBuffer(counted, { minSize: wholeUnder })
  const metadata = await parquetMetadataAsync(buf, { initialFetchSize: FOOTER })
  const meta = metadata as unknown as MetaLike
  const ranges = groupsHoldingText(meta, 'place_id', placeId)
  const rows: PlaceSpeciesRow[] = []
  for (const g of ranges) {
    const got = await parquetReadObjects({ file: buf, metadata, compressors, columns: ['place_id', 'aphiaid', 'name_key', 'n', 'year_min', 'year_max'], rowStart: g.rowStart, rowEnd: g.rowEnd })
    for (const x of got) if (x.place_id === placeId) rows.push(x as unknown as PlaceSpeciesRow)
  }
  return { rows, groups: meta.row_groups.length, groupsRead: groupsIn(meta, ranges), bytes: counted.bytes(), requests: counted.requests(), fileBytes: file.byteLength }
}

const lookups = new Map<string, Promise<{ rows: ObisLookupRow[]; bytes: number }>>()

/** the release's species lookup, the name columns only (aphiaid, species, class, and eov / redlist_code when the file has them), once a page load */
export function readObisLookup(url: string): Promise<{ rows: ObisLookupRow[]; bytes: number }> {
  const hit = lookups.get(url)
  if (hit) return hit
  const p = (async () => {
    const counted = countBytes(await asyncBufferFromUrl({ url }))
    const buf = cachedAsyncBuffer(counted, { minSize: 1 << 20 })
    const metadata = await parquetMetadataAsync(buf, { initialFetchSize: FOOTER })
    const have = new Set(metadata.schema.map((e) => e.name))
    const columns = ['aphiaid', 'species', 'scientific_name', 'class', 'eov', 'redlist_code'].filter((c) => have.has(c))
    const rows = (await parquetReadObjects({ file: buf, metadata, compressors, columns })) as unknown as ObisLookupRow[]
    return { rows, bytes: counted.bytes() }
  })()
  lookups.set(url, p)
  p.catch(() => lookups.delete(url))
  return p
}

export interface ObisSpeciesResult { url: string; list: ObisSpecies[]; rowBytes: number; lookupBytes: number; groups: number; groupsRead: number; fileBytes: number }

/** the place's species list of the release; null when the collection has no species.parquet (404, 403) */
export async function readObisSpecies(release: ObisRelease, coll: string, placeId: string): Promise<ObisSpeciesResult | null> {
  const url = placeSpeciesUrl(release, coll)
  let rd: PlaceSpeciesRead
  try { rd = await readPlaceSpeciesRows(await asyncBufferFromUrl({ url }), placeId) } catch (e) { if (/\b(404|403)\b/.test(String(e))) return null; throw e }
  const lk = await readObisLookup(speciesLookupUrl(release))
  return { url, list: placeSpecies(rd.rows, placeId, lk.rows), rowBytes: rd.bytes, lookupBytes: lk.bytes, groups: rd.groups, groupsRead: rd.groupsRead, fileBytes: rd.fileBytes }
}

export interface SdmResult { hook: CellSpeciesHook; cells: number; tiles: number; species: SdmSpecies[]; citation: string | null; license: string | null }

/** the AquaMaps species suitable in the place's cells; null when the place is too large to list */
export async function readSdm(geometry: { type: string; coordinates: unknown } | null | undefined): Promise<SdmResult | null> {
  const r = await fetch(AQUAMAPS_EOV)
  if (!r.ok) throw new Error(`aquamaps_eov collection.json: HTTP ${r.status}`)
  const coll = await r.json()
  const hook = parseCellSpecies(coll, AQUAMAPS_EOV)
  if (!hook) throw new Error('aquamaps_eov declares no usable atlas:cell_species')
  const cells = placeCells(geometry as never, hook.grid, hook.tileDeg)
  if (!cells) return null
  const rows: { cell: number; species: number; suit: number }[] = []
  const tiles = tilesOf(cells)
  await Promise.all(tiles.map(async ({ tile, ids }) => {
    const file = await asyncBufferFromUrl({ url: hook.tileTemplate.replace('{tile}', String(tile)) })
    const metadata = await parquetMetadataAsync(file)
    for (const g of groupsHolding(metadata as unknown as MetaLike, hook.keyColumn, ids)) {
      const got = await parquetReadObjects({ file, metadata, compressors, columns: [hook.keyColumn, hook.speciesColumn, hook.valueColumn], rowStart: g.rowStart, rowEnd: g.rowEnd })
      for (const x of got) rows.push({ cell: Number(x[hook.keyColumn]), species: Number(x[hook.speciesColumn]), suit: Number(x[hook.valueColumn]) })
    }
  }).map((p) => p.catch((e) => { if (!/HTTP 404|403/.test(String(e))) throw e })))   // a tile with no ocean is not published
  const lookup = await readWhole(hook.lookupUrl, ['aphia_id', 'scientific_name', 'common_name', 'eov', 'redlist_code', 'worms_url', 'aquamaps_url'])
  return { hook, cells: cells.size, tiles: tiles.length, species: sdmSpecies(rows, cells, lookup as unknown as SpeciesLookupRow[]), citation: coll['sci:citation'] ?? null, license: coll.license ?? null }
}
