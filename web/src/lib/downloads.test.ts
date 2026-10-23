import { parquetReadObjects } from 'hyparquet'
import { parquetWriteBuffer } from 'hyparquet-writer'
import { describe, expect, it } from 'vitest'
import { downloadValues, placeRows, valuesCsv, valuesParquet, VALUES_COLUMNS } from './downloads'

// two synthetic values files: contract 1.2 (with sd and class) and an older one without them
const col = (name: string, data: unknown[], type: 'STRING' | 'DOUBLE' | 'TIMESTAMP') => ({ name, data: data as never, type, nullable: true })
const SST = parquetWriteBuffer({ columnData: [
  col('place_id', ['NMS:A', 'NMS:A', 'NMS:B'], 'STRING'), col('coll', ['places', 'places', 'places'], 'STRING'),
  col('indicator', ['erddap:sst', 'erddap:sst', 'erddap:sst'], 'STRING'), col('time_grain', ['year', 'year', 'year'], 'STRING'),
  col('time', [new Date('2024-01-01'), new Date('2025-01-01'), new Date('2025-01-01')], 'TIMESTAMP'), col('class', [null, null, null], 'STRING'),
  col('value', [15.5, 16.25, 20], 'DOUBLE'), col('n', [12, 12, 12], 'DOUBLE'), col('sd', [0.5, null, 1], 'DOUBLE'), col('unit', ['°C', '°C', '°C'], 'STRING'),
] })
const OLD = parquetWriteBuffer({ columnData: [
  col('place_id', ['NMS:A'], 'STRING'), col('coll', ['places'], 'STRING'), col('indicator', ['cmems:chl'], 'STRING'),
  col('time_grain', ['month'], 'STRING'), col('time', [new Date('2025-07-01')], 'TIMESTAMP'), col('value', [1.25], 'DOUBLE'), col('n', [1], 'DOUBLE'), col('unit', ['mg m-3, total'], 'STRING'),
] })
const FILES = [
  { indicator: 'erddap:sst', coll: 'places', url: 'https://x/sst.parquet' },
  { indicator: 'cmems:chl', coll: 'places', url: 'https://x/chl.parquet' },
  { indicator: 'gone', coll: 'places', url: 'https://x/gone.parquet' },
]
const f = (async (u: RequestInfo | URL) => {
  const url = String(u)
  if (url.endsWith('sst.parquet')) return new Response(new Uint8Array(SST))
  if (url.endsWith('chl.parquet')) return new Response(new Uint8Array(OLD))
  return new Response('', { status: 404 })
}) as typeof fetch

describe('the values of the place', () => {
  it('reads each file whole, keeps the place\'s rows, concatenates in file order and names a file that failed', async () => {
    const d = await downloadValues('NMS:A', FILES, f)
    expect(d.rows.map((r) => [r.indicator, r.time, r.value, r.sd, r.class])).toEqual([
      ['erddap:sst', '2024-01-01', 15.5, 0.5, null], ['erddap:sst', '2025-01-01', 16.25, null, null], ['cmems:chl', '2025-07-01', 1.25, null, null]])
    expect(d.rows[2].source).toBe('https://x/chl.parquet')
    expect(d.failed).toEqual([{ url: 'https://x/gone.parquet', why: 'HTTP 404' }])
  })

  it('puts every row in the fixed column order, nulls for a column the file lacks', () => {
    expect(Object.keys(placeRows([{ value: 1n, place_id: 'P', extra: 2 }], 'P', 's')[0])).toEqual(['source', ...VALUES_COLUMNS])
    const [r] = placeRows([{ place_id: 'P', value: 1n, time: '2020-01-01T00:00:00Z' }], 'P', 's')
    expect([r.value, r.time, r.sd]).toEqual([1, '2020-01-01', null])
    expect(placeRows([{ place_id: 'Q' }], 'P', 's')).toEqual([])
  })

  it('writes CSV with the source column, quoting a comma', async () => {
    const csv = valuesCsv((await downloadValues('NMS:A', FILES, f)).rows)
    const lines = csv.trim().split('\n')
    expect(lines[0]).toBe([...VALUES_COLUMNS, 'source'].join(','))
    expect(lines[1]).toBe('NMS:A,places,erddap:sst,year,2024-01-01,,15.5,12,0.5,°C,https://x/sst.parquet')
    expect(lines[3]).toBe('NMS:A,places,cmems:chl,month,2025-07-01,,1.25,1,,"mg m-3, total",https://x/chl.parquet')
  })

  it('writes Parquet that reads back the same rows', async () => {
    const rows = (await downloadValues('NMS:A', FILES, f)).rows
    const back = await parquetReadObjects({ file: valuesParquet(rows) })
    expect(back.map((r) => [r.indicator, r.time, r.value, r.sd, r.source])).toEqual(rows.map((r) => [r.indicator, r.time, r.value, r.sd, r.source]))
  })
})
