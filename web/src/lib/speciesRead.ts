// the Species section's reads (a lazy chunk: hyparquet with its ZSTD codec only when the section loads). the rules are
// species.ts; this fetches and hands rows over.
import { asyncBufferFromUrl, parquetMetadataAsync, parquetReadObjects } from 'hyparquet'
import { compressors } from 'hyparquet-compressors'
import {
  groupsHolding, obisSummary, OBIS_LATEST, parseCellSpecies, placeCells, placeExactUrl, sdmSpecies, tilesOf,
  type CellSpeciesHook, type MetaLike, type ObisRelease, type ObisRow, type ObisSummary, type SdmSpecies, type SpeciesLookupRow,
} from './species'

/** the AquaMaps EOV collection of the atlas (the bucket's path-style url) */
export const AQUAMAPS_EOV = 'https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/atlas/aquamaps_eov/collection.json'

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
