import { afterEach, describe, expect, it, vi } from 'vitest'
import { parquetWriteBuffer } from 'hyparquet-writer'
import { countBytes, readLineage, readObisLookup, readPlaceSpeciesRows, readWormsTaxon } from './speciesRead'
import { eovChips, filterEov, filterTaxon, placeSpecies, speciesCheck, speciesCounts, obisSummary, type ObisRow } from './species'

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

// ---- the lookup and the lineage file, read by row group over a stubbed fetch ----

/** serves `files` by url with HEAD and Range, counting the bytes of the bodies */
function serve(files: Record<string, ArrayBuffer>) {
  const served = { bytes: 0, requests: 0 }
  vi.stubGlobal('fetch', async (url: string, init?: { method?: string; headers?: Headers }) => {
    const f = files[url]
    if (!f) return new Response(null, { status: 404 })
    if (init?.method === 'HEAD') return new Response(null, { status: 200, headers: { 'content-length': String(f.byteLength) } })
    const m = /bytes=(\d+)-(\d*)/.exec(new Headers(init?.headers).get('Range') ?? '')
    const body = m ? f.slice(Number(m[1]), m[2] ? Number(m[2]) + 1 : undefined) : f
    served.bytes += body.byteLength
    served.requests++
    return new Response(body, { status: m ? 206 : 200 })
  })
  return served
}
afterEach(() => { vi.unstubAllGlobals() })

// 40,000 species in 4 row groups of 10,000, aphiaid = 1000 + 3 i (sorted); the lineage is the aphiaid, then the ancestors 5 (its family, 20 per family), 4, 3, 2, 1
const N = 40_000
const ids = Array.from({ length: N }, (_, i) => 1000 + 3 * i)
const lineageOf = (a: number) => [BigInt(a), BigInt(100_000 + Math.floor((a - 1000) / 60)), 4n, 3n, 2n, 1n]
const lineageFile = parquetWriteBuffer({
  columnData: [{ name: 'aphiaid', type: 'INT64', data: ids.map(BigInt) }, { name: 'name_key', type: 'INT32', data: ids.map((_, i) => i) }, { name: 'lineage', data: ids.map(lineageOf) }],
  rowGroupSize: 10_000, codec: 'UNCOMPRESSED',
})
const lookupFile = parquetWriteBuffer({
  columnData: [
    { name: 'aphiaid', type: 'INT64', data: ids.map(BigInt) }, { name: 'name_key', type: 'INT32', data: ids.map((_, i) => i) },
    { name: 'species', type: 'STRING', data: ids.map((a) => `Synthetica sp${a}`) }, { name: 'genus', type: 'STRING', data: ids.map((a) => `Genus${a % 97}`) },
    { name: 'class', type: 'STRING', data: ids.map((a) => (a % 2 ? 'Teleostei' : 'Aves')) }, { name: 'eov', type: 'STRING', data: ids.map((a) => (a % 3000 === 1 ? 'fish' : null)) },
    { name: 'lineage', data: ids.map(lineageOf) }, { name: 'records', type: 'INT64', data: ids.map((a) => BigInt(a)) },
  ],
  rowGroupSize: 10_000, codec: 'UNCOMPRESSED',
})

describe('the lineage file, read lazily by row group', () => {
  it('reads only the row groups whose aphiaid range holds the place\'s, and returns their lineages (self first)', async () => {
    const served = serve({ 'https://t/lin1.parquet': lineageFile })
    const mine = [ids[10_500], ids[10_700], ids[19_999]]   // all in the second group
    const r = await readLineage('https://t/lin1.parquet', mine)
    expect([r.groups, r.groupsRead]).toEqual([4, 1])
    expect([...r.lineages.keys()].sort((a, b) => a - b)).toEqual(mine)
    expect(r.lineages.get(mine[0])).toEqual(lineageOf(mine[0]).map(Number))
    expect(r.lineages.get(mine[0])![0]).toBe(mine[0])
    expect(r.bytes).toBe(served.bytes)
    expect(r.bytes).toBeLessThan(lineageFile.byteLength * 0.5)   // one group of four plus the footer, and no name_key column
  })

  it('reads the groups of ids that span the file, and not a group twice', async () => {
    const served = serve({ 'https://t/lin2.parquet': lineageFile })
    const mine = [ids[5], ids[12_000], ids[39_000]]
    const a = await readLineage('https://t/lin2.parquet', mine)
    expect(a.groupsRead).toBe(3)
    const bytes = served.bytes
    const b = await readLineage('https://t/lin2.parquet', [ids[6], ids[7]])   // group 0 again
    expect(b.lineages.size).toBe(2)
    expect(served.bytes).toBe(bytes)
  })

  it('narrows a list to a taxon with the lineages it read: 20 species of one family', async () => {
    serve({ 'https://t/lin3.parquet': lineageFile })
    const mine = ids.slice(100, 400)   // 300 species, 15 families of 20
    const r = await readLineage('https://t/lin3.parquet', mine)
    const names = mine.map((a) => ({ aphiaIds: [a] }))
    const family = Number([...r.lineages.get(mine[45])!][1])
    expect(filterTaxon(names, r.lineages, family).length).toBe(20)
    expect(filterTaxon(names, r.lineages, 4).length).toBe(300)   // an ancestor of all
    expect(filterTaxon(names, r.lineages, mine[45]).length).toBe(1)   // the species itself
  })

  it('has no lineage for an aphiaid the file lacks', async () => {
    serve({ 'https://t/lin4.parquet': lineageFile })
    const r = await readLineage('https://t/lin4.parquet', [2, 1001])
    expect(r.lineages.size).toBe(0)
  })
})

describe('the species lookup, read for the place\'s aphiaids', () => {
  it('returns only the name columns (no lineage, no genus) of the groups that hold them', async () => {
    const served = serve({ 'https://t/lk1.parquet': lookupFile })
    const mine = [ids[30_100], ids[30_101]]
    const r = await readObisLookup('https://t/lk1.parquet', mine)
    expect([r.groups, r.groupsRead]).toEqual([4, 1])
    expect(Object.keys(r.rows[0]).sort()).toEqual(['aphiaid', 'class', 'eov', 'species'])
    expect(r.rows.find((x) => Number(x.aphiaid) === mine[0])).toMatchObject({ species: `Synthetica sp${mine[0]}` })
    expect(r.bytes).toBe(served.bytes)
    expect(r.bytes).toBeLessThan(lookupFile.byteLength * 0.3)
  })

  it('joins to the place\'s rows: the EOV chips count the names, the filter keeps them', async () => {
    serve({ 'https://t/lk2.parquet': lookupFile })
    const fish = ids.filter((a) => a % 3000 === 1)
    const rows = [...fish.slice(0, 5), ids[7], ids[8]].map((a, i) => ({ place_id: 'P', aphiaid: a, name_key: i, n: 10 - i, year_min: 2000, year_max: 2001 }))
    const lk = await readObisLookup('https://t/lk2.parquet', rows.map((r) => r.aphiaid))
    const list = placeSpecies(rows, 'P', lk.rows)
    expect(eovChips(list).map((c) => [c.key, c.n])).toEqual([['all', 7], ['fish', 5]])
    expect(filterEov(list, 'fish').map((s) => s.aphiaId)).toEqual(fish.slice(0, 5))
  })
})

describe('a typed name resolved by WoRMS', () => {
  it('reads the record of the exact name, once per text, and says null for 204', async () => {
    const calls: string[] = []
    const f = (async (u: string) => {
      calls.push(u)
      if (u.includes('Nonexistus')) return new Response(null, { status: 204 })
      return new Response(JSON.stringify([{ AphiaID: 148723, scientificname: 'Cetacea', rank: 'Infraorder', status: 'accepted', valid_AphiaID: 148723, valid_name: 'Cetacea' }]), { status: 200 })
    }) as unknown as typeof fetch
    expect(await readWormsTaxon('Cetacea', f)).toMatchObject({ id: 148723, rank: 'infraorder' })
    expect(await readWormsTaxon('cetacea', f)).toMatchObject({ id: 148723 })
    expect(calls.length).toBe(1)
    expect(await readWormsTaxon('Nonexistus', f)).toBeNull()
  })

  it('throws on a server error and asks again next time', async () => {
    let n = 0
    const f = (async () => (++n === 1 ? new Response('x', { status: 503 }) : new Response('[]', { status: 200 }))) as unknown as typeof fetch
    await expect(readWormsTaxon('Flakeus', f)).rejects.toThrow('HTTP 503')
    expect(await readWormsTaxon('Flakeus', f)).toBeNull()
  })
})
