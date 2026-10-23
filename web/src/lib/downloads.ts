// the values download of the place page: every values file the place's indicators list is read whole (one fetch each,
// in parallel), its rows for the place kept, and the rows of all files written as one CSV or one Parquet file in the
// browser. a lazy chunk (hyparquet, its codecs and hyparquet-writer load on the first click). tested on fixtures.
import { parquetReadObjects } from 'hyparquet'
import { compressors } from 'hyparquet-compressors'
import { parquetWriteBuffer } from 'hyparquet-writer'
import type { ValuesFile } from './reports'

/** the columns of a values file (contract 1.2), in order; a 1.1 file without `sd` or `class` gives nulls there */
export const VALUES_COLUMNS = ['place_id', 'coll', 'indicator', 'time_grain', 'time', 'class', 'value', 'n', 'sd', 'unit'] as const
export type ValuesRow = Record<(typeof VALUES_COLUMNS)[number], string | number | null> & { source: string }

const day = (v: unknown): string | null => {
  if (v == null) return null
  if (v instanceof Date) return v.toISOString().slice(0, 10)
  if (typeof v === 'number' || typeof v === 'bigint') return new Date(Number(v) * (Number(v) < 1e6 ? 86_400_000 : 1)).toISOString().slice(0, 10)
  return String(v).slice(0, 10)
}
const val = (v: unknown): string | number | null => (v == null ? null : typeof v === 'bigint' ? Number(v) : typeof v === 'number' || typeof v === 'string' ? v : String(v))

/** the place's rows of one values file, in the fixed column order, with the file's url as `source` */
export function placeRows(rows: readonly Record<string, unknown>[], placeId: string, source: string): ValuesRow[] {
  return rows.filter((r) => r.place_id === placeId).map((r) => {
    const o = { source } as ValuesRow
    for (const c of VALUES_COLUMNS) o[c] = c === 'time' ? day(r.time) : val(r[c])
    return o
  })
}

export interface Download { rows: ValuesRow[]; failed: { url: string; why: string }[] }

/** every file read whole, the place's rows kept and concatenated in file order; a file that fails is named, the rest still count */
export async function downloadValues(placeId: string, files: readonly ValuesFile[], fetchFn: typeof fetch = fetch): Promise<Download> {
  const got = await Promise.all(files.map(async (f) => {
    try {
      const r = await fetchFn(f.url)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const rows = await parquetReadObjects({ file: await r.arrayBuffer(), compressors })
      return { rows: placeRows(rows, placeId, f.url) }
    } catch (e) {
      return { rows: [] as ValuesRow[], failed: { url: f.url, why: String((e as Error)?.message ?? e) } }
    }
  }))
  return { rows: got.flatMap((g) => g.rows), failed: got.flatMap((g) => (g.failed ? [g.failed] : [])) }
}

const csvCell = (v: unknown) => {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** the rows as CSV, the values columns then `source` (the values file each row came from) */
export function valuesCsv(rows: readonly ValuesRow[]): string {
  const head = [...VALUES_COLUMNS, 'source']
  return [head.join(','), ...rows.map((r) => head.map((c) => csvCell(r[c as keyof ValuesRow])).join(','))].join('\n') + '\n'
}

/** the rows as one Parquet file (`time` as an ISO date string, the numbers as doubles) */
export function valuesParquet(rows: readonly ValuesRow[]): ArrayBuffer {
  const num = new Set(['value', 'n', 'sd'])
  const columnData = [...VALUES_COLUMNS, 'source'].map((c) => ({
    name: c,
    data: rows.map((r) => {
      const v = r[c as keyof ValuesRow]
      return v == null ? null : num.has(c) ? Number(v) : String(v)
    }),
    type: (num.has(c) ? 'DOUBLE' : 'STRING') as 'DOUBLE' | 'STRING',
    nullable: true,
  }))
  return parquetWriteBuffer({ columnData })
}
