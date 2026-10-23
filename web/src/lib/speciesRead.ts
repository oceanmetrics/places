// the Species section's reads (a lazy chunk: hyparquet with its ZSTD codec only when the section loads). the rules are
// species.ts; this fetches and hands rows over.
import { asyncBufferFromUrl, cachedAsyncBuffer, parquetMetadataAsync, parquetReadObjects, type AsyncBuffer, type FileMetaData } from 'hyparquet'
import { compressors } from 'hyparquet-compressors'
import { store } from './storage'
import {
  groupIndexes, groupsHolding, groupsHoldingText, obisSummary, pickWormsTaxon, wormsNameUrl, OBIS_LATEST, parseCellSpecies, placeCells, placeExactUrl, placeSpecies, placeSpeciesUrl, sdmSpecies,
  speciesLookupUrl, tilesOf,
  type CellSpeciesHook, type MetaLike, type ObisLookupRow, type ObisRelease, type ObisRow, type ObisSpecies, type ObisSummary, type PlaceSpeciesRow,
  type SdmSpecies, type SpeciesLookupRow, type WormsTaxon,
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
  return { rows, groups: meta.row_groups.length, groupsRead: groupIndexes(meta, ranges).length, bytes: counted.bytes(), requests: counted.requests(), fileBytes: file.byteLength }
}

/** a parquet file read by row group: the footer once, each group's columns once (the groups a call needs, none twice) */
interface GroupedFile {
  buf: AsyncBuffer
  metadata: FileMetaData
  columns: string[]
  groups: Map<number, Promise<Record<string, unknown>[]>>
  bytes: () => number
  requests: () => number
}

const files = new Map<string, Promise<GroupedFile>>()

/** the file at `url` opened for `wanted` columns (those the file has); the open files are kept for the page load */
function openGrouped(url: string, wanted: readonly string[]): Promise<GroupedFile> {
  const key = `${url}\n${wanted.join(',')}`
  const hit = files.get(key)
  if (hit) return hit
  const p = (async (): Promise<GroupedFile> => {
    const counted = countBytes(await asyncBufferFromUrl({ url }))
    const buf = cachedAsyncBuffer(counted, { minSize: 1 << 20 })
    const metadata = await parquetMetadataAsync(buf, { initialFetchSize: FOOTER })
    const have = new Set(metadata.schema.map((e) => e.name))
    return { buf, metadata, columns: wanted.filter((c) => have.has(c)), groups: new Map(), bytes: counted.bytes, requests: counted.requests }
  })()
  files.set(key, p)
  p.catch(() => files.delete(key))
  return p
}

/** the rows of the row groups whose `key` range can hold one of the (sorted) ids; a group read before is not read again */
async function readGroupsHolding(f: GroupedFile, key: string, ids: readonly number[]): Promise<{ rows: Record<string, unknown>[]; groups: number; groupsRead: number }> {
  const meta = f.metadata as unknown as MetaLike
  const idx = groupIndexes(meta, groupsHolding(meta, key, ids))
  const parts = await Promise.all(idx.map(({ index, rowStart, rowEnd }) => {
    const hit = f.groups.get(index)
    if (hit) return hit
    const p = parquetReadObjects({ file: f.buf, metadata: f.metadata, compressors, columns: f.columns, rowStart, rowEnd })
    f.groups.set(index, p)
    p.catch(() => f.groups.delete(index))
    return p
  }))
  return { rows: parts.flat(), groups: meta.row_groups.length, groupsRead: idx.length }
}

const sortedIds = (ids: Iterable<number>) => [...new Set(ids)].sort((a, b) => a - b)

export interface LookupRead { rows: ObisLookupRow[]; bytes: number; groups: number; groupsRead: number }

/**
 * the release's species lookup for the aphiaids of the place: the name columns only (aphiaid, species, class, and eov /
 * redlist_code when the file has them), and only the row groups (sorted by aphiaid) whose range holds one of the ids; `bytes`
 * is what the page has read of the file so far
 */
export async function readObisLookup(url: string, aphiaIds: Iterable<number>): Promise<LookupRead> {
  const f = await openGrouped(url, ['aphiaid', 'species', 'scientific_name', 'class', 'eov', 'redlist_code'])
  const g = await readGroupsHolding(f, 'aphiaid', sortedIds(aphiaIds))
  return { rows: g.rows as unknown as ObisLookupRow[], bytes: f.bytes(), groups: g.groups, groupsRead: g.groupsRead }
}

export interface LineageRead { lineages: Map<number, number[]>; bytes: number; groups: number; groupsRead: number }

/**
 * the lineages (aphiaid -> itself, then its ancestors) of the place's aphiaids from the release's `species/lineage.parquet`
 * (aphiaid, name_key, lineage; sorted by aphiaid): the aphiaid and lineage columns of the row groups whose range holds one of
 * them, read on the first taxon filter and kept; `bytes` is what the page has read of the file so far
 */
export async function readLineage(url: string, aphiaIds: Iterable<number>): Promise<LineageRead> {
  const ids = sortedIds(aphiaIds), want = new Set(ids)
  const f = await openGrouped(url, ['aphiaid', 'lineage'])
  const g = await readGroupsHolding(f, 'aphiaid', ids)
  const lineages = new Map<number, number[]>()
  for (const r of g.rows) {
    const id = Number(r.aphiaid)
    if (want.has(id) && Array.isArray(r.lineage)) lineages.set(id, (r.lineage as (number | bigint)[]).map(Number))
  }
  return { lineages, bytes: f.bytes(), groups: g.groups, groupsRead: g.groupsRead }
}

const wormsNames = new Map<string, Promise<WormsTaxon | null>>()

/** a typed name resolved by WoRMS's REST API (CORS-open), once a page load per text; null when WoRMS has no such name */
export function readWormsTaxon(typed: string, fetchFn: typeof fetch = fetch): Promise<WormsTaxon | null> {
  const key = typed.trim().toLowerCase()
  const hit = wormsNames.get(key)
  if (hit) return hit
  const p = (async () => {
    const r = await fetchFn(wormsNameUrl(typed))
    if (r.status === 204 || r.status === 404) return null   // WoRMS answers 204 for no match
    if (!r.ok) throw new Error(`WoRMS answered HTTP ${r.status}`)
    return pickWormsTaxon(await r.json(), typed)
  })()
  wormsNames.set(key, p)
  p.catch(() => wormsNames.delete(key))
  return p
}

export interface ObisSpeciesResult {
  url: string; list: ObisSpecies[]; rowBytes: number; lookupBytes: number; groups: number; groupsRead: number; fileBytes: number
  /** the release's lookup and lineage files, for the taxon filter's read and the Reproduce block */
  lookupGroups: number; lookupGroupsRead: number
}

/** the place's species list of the release; null when the collection has no species.parquet (404, 403) */
export async function readObisSpecies(release: ObisRelease, coll: string, placeId: string): Promise<ObisSpeciesResult | null> {
  const url = placeSpeciesUrl(release, coll)
  let rd: PlaceSpeciesRead
  try { rd = await readPlaceSpeciesRows(await asyncBufferFromUrl({ url }), placeId) } catch (e) { if (/\b(404|403)\b/.test(String(e))) return null; throw e }
  const lk = await readObisLookup(speciesLookupUrl(release), rd.rows.map((r) => Number(r.aphiaid)))
  return {
    url, list: placeSpecies(rd.rows, placeId, lk.rows), rowBytes: rd.bytes, lookupBytes: lk.bytes, groups: rd.groups, groupsRead: rd.groupsRead, fileBytes: rd.fileBytes,
    lookupGroups: lk.groups, lookupGroupsRead: lk.groupsRead,
  }
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
