import { describe, expect, it } from 'vitest'
import { parquetWriteBuffer } from 'hyparquet-writer'
import { countBytes, readPlaceSpeciesRows } from './speciesRead'
import { placeSpecies, speciesCheck, speciesCounts, obisSummary, type ObisRow } from './species'

// a tiny species.parquet as the release writes it (sorted by place_id), three row groups of 4 rows: SYN:B spans groups 0 and 1
const R = (place_id: string, aphiaid: number, name_key: number, n: number, year_min: number, year_max: number) => ({ place_id, aphiaid, name_key, n, year_min, year_max })
const ROWS = [
  R('SYN:A', 1, 1, 10, 2001, 2022), R('SYN:A', 2, 2, 5, 1999, 2003), R('SYN:B', 1, 1, 2, 2010, 2011), R('SYN:B', 3, 3, 4, 2021, 2023),
  R('SYN:B', 4, 4, 8, 1980, 1981), R('SYN:C', 1, 1, 1, 2000, 2000), R('SYN:C', 5, 5, 9, 2020, 2020), R('SYN:C', 6, 6, 3, 2024, 2024),
  R('SYN:D', 2, 2, 3, 2002, 2002), R('SYN:D', 7, 7, 7, 2019, 2025), R('SYN:D', 8, 8, 1, 1990, 1990), R('SYN:E', 9, 9, 4, 2015, 2016),
]
const column = (name: string, type: 'STRING' | 'INT32' | 'INT64') => ({ name, type, data: ROWS.map((r) => (r as Record<string, unknown>)[name]).map((v) => (type === 'INT64' ? BigInt(v as number) : v)) })
const file = parquetWriteBuffer({
  columnData: [column('place_id', 'STRING'), column('aphiaid', 'INT64'), column('name_key', 'INT32'), column('n', 'INT64'), column('year_min', 'INT32'), column('year_max', 'INT32')],
  rowGroupSize: 4, codec: 'UNCOMPRESSED',
})
const buf = { byteLength: file.byteLength, slice: (a: number, b?: number) => file.slice(a, b) }

describe('reading one place from a species.parquet of a collection', () => {
  it('returns the place\'s rows and reads only the row groups whose place_id range holds it', async () => {
    const d = await readPlaceSpeciesRows(buf, 'SYN:D')
    expect(d.rows.map((r) => Number(r.aphiaid))).toEqual([2, 7, 8])
    expect([d.groups, d.groupsRead]).toEqual([3, 1])
  })

  it('reads a fraction of a larger file: 8 places of 1,500 species in 4 row groups of 3,000 rows, one place is one group', async () => {
    const places = Array.from({ length: 8 }, (_, i) => `SYN:${i}`)
    const rows = places.flatMap((p) => Array.from({ length: 1500 }, (_, k) => ({ p, a: k * 7 + 100, k, n: (k * 31) % 997 + 1 })))
    const big = parquetWriteBuffer({
      columnData: [
        { name: 'place_id', type: 'STRING', data: rows.map((r) => r.p) }, { name: 'aphiaid', type: 'INT64', data: rows.map((r) => BigInt(r.a)) },
        { name: 'name_key', type: 'INT32', data: rows.map((r) => r.k) }, { name: 'n', type: 'INT64', data: rows.map((r) => BigInt(r.n)) },
        { name: 'year_min', type: 'INT32', data: rows.map((r) => 1900 + (r.k % 120)) }, { name: 'year_max', type: 'INT32', data: rows.map((r) => 1950 + (r.k % 76)) },
      ],
      rowGroupSize: 3000, codec: 'UNCOMPRESSED',
    })
    const f = { byteLength: big.byteLength, slice: (a: number, b?: number) => big.slice(a, b) }
    const d = await readPlaceSpeciesRows(f, 'SYN:5', 0)
    expect([d.rows.length, d.groups, d.groupsRead]).toEqual([1500, 4, 1])
    expect(d.bytes).toBeLessThan(big.byteLength * 0.6)   // one group of four, and the 64 kB footer
    const whole = await readPlaceSpeciesRows(f, 'SYN:5', 1 << 30)
    expect(whole.rows).toEqual(d.rows)
    expect(whole.bytes).toBe(big.byteLength)
  })

  it('fetches a small file once, whole', async () => {
    const d = await readPlaceSpeciesRows(buf, 'SYN:D')
    expect([d.bytes, d.requests]).toEqual([file.byteLength, 1])
  })

  it('finds a place that spans two groups in both, and not the neighbours\' rows', async () => {
    const d = await readPlaceSpeciesRows(buf, 'SYN:B')
    expect(d.rows.map((r) => Number(r.aphiaid))).toEqual([1, 3, 4])
    expect(d.groupsRead).toBe(2)
  })

  it('returns nothing for a place the file lacks', async () => {
    const d = await readPlaceSpeciesRows(buf, 'SYN:Z')
    expect(d.rows).toEqual([])
    expect(d.groupsRead).toBe(0)
  })

  it('counts the bytes the slices return', async () => {
    const c = countBytes(buf)
    await c.slice(0, 10)
    await c.slice(10, 15)
    expect([c.bytes(), c.requests()]).toEqual([15, 2])
  })

  it('gives, with the lookup, the count that equals the indicators row of the same synthetic place', async () => {
    const d = await readPlaceSpeciesRows(buf, 'SYN:B')
    const list = placeSpecies(d.rows, 'SYN:B', [{ aphiaid: 1, species: 'a' }, { aphiaid: 3, species: 'c' }, { aphiaid: 4, species: 'd' }])
    const ind: ObisRow[] = [
      { place_id: 'SYN:B', eov: 'all', decade: null, n: 14, sp: 3, es: null },
      { place_id: 'SYN:B', eov: 'all', decade: 2020, n: 4, sp: 1, es: null },
    ]
    const sum = obisSummary(ind, 'SYN:B')!
    const c = speciesCounts(list, sum.latest!.decade)
    expect([c.all, c.latest!.n]).toEqual([3, 1])
    expect(speciesCheck(c, sum)).toBeNull()
  })
})
