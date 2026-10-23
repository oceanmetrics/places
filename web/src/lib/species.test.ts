import { describe, expect, it } from 'vitest'
import {
  bboxWkt, byGroup, cellAt, groupsHolding, inRings, obisColls, obisLine, obisLinks, obisSummary, parseCellSpecies, placeCells,
  placeExactUrl, sdmCsv, sdmLine, sdmSpecies, tilesOf, type CellGrid, type MetaLike, type ObisRow,
} from './species'

// ---- OBIS ----

const rows: ObisRow[] = [
  { place_id: 'NMS:CINMS', eov: 'all', decade: null, n: 5650862, sp: 2258, es: 39.138 },
  { place_id: 'NMS:CINMS', eov: 'all', decade: 2010, n: 1457938, sp: 694, es: 40.53 },
  { place_id: 'NMS:CINMS', eov: 'all', decade: 2020, n: 2433277, sp: 668, es: 30.278 },
  { place_id: 'NMS:CINMS', eov: 'all', decade: 1960, n: 974, sp: 144, es: 28.46 },
  { place_id: 'NMS:CINMS', eov: 'fish', decade: null, n: 900, sp: 400, es: null },
  { place_id: 'NMS:CINMS', eov: 'seabirds', decade: null, n: 50, sp: 60, es: null },
  { place_id: 'NMS:CINMS', eov: 'mangroves', decade: null, n: 0, sp: 0, es: null },
  { place_id: 'NMS:FGBNMS', eov: 'all', decade: null, n: 7716, sp: 469, es: 26.77 },
]

describe('OBIS exact', () => {
  it('summarises every year, the decades oldest first, the latest, and the EOV groups with species', () => {
    const s = obisSummary(rows, 'NMS:CINMS')!
    expect(s.all).toEqual({ n: 5650862, sp: 2258, es: 39.138 })
    expect(s.decades.map((d) => d.decade)).toEqual([1960, 2010, 2020])
    expect(s.latest?.decade).toBe(2020)
    expect(s.byEov).toEqual([{ eov: 'fish', sp: 400, n: 900 }, { eov: 'seabirds', sp: 60, n: 50 }])
  })

  it('says it in one line, and says when ES(50) is not defined', () => {
    expect(obisLine(obisSummary(rows, 'NMS:CINMS')!)).toBe('5,650,862 records of 2,258 species (ES(50) 39.1) in every year; in the 2020s, 2,433,277 records of 668 species (ES(50) 30.3).')
    expect(obisLine({ all: { n: 30, sp: 12, es: null }, decades: [], latest: null, byEov: [] })).toBe('30 records of 12 species (ES(50) not defined (under 50 records)) in every year.')
  })

  it('is null for a place the file does not hold', () => {
    expect(obisSummary(rows, 'NMS:MBNMS')).toBeNull()
  })

  it('tries the place\'s own collection, then its copies\', each once', () => {
    expect(obisColls('noaa_sanctuaries', [{ collection: 'places' }, { collection: 'noaa_sanctuaries' }, { collection: 'mpa_inventory' }])).toEqual(['noaa_sanctuaries', 'places', 'mpa_inventory'])
    expect(obisColls(null)).toEqual([])
    expect(placeExactUrl({ base: 'https://x/obis-h3/v20261012' }, 'places')).toBe('https://x/obis-h3/v20261012/place_exact/coll=places/indicators.parquet')
  })

  it('writes the box as WKT for OBIS, in two parts across the antimeridian', () => {
    expect(bboxWkt([-120.6, 33.4, -118.9, 34.2])).toBe('POLYGON((-120.6 33.4, -118.9 33.4, -118.9 34.2, -120.6 34.2, -120.6 33.4))')
    expect(bboxWkt([177.8, 19.4, 199, 31.8])).toBe('MULTIPOLYGON(((177.8 19.4, 180 19.4, 180 31.8, 177.8 31.8, 177.8 19.4)), ((-180 19.4, -161 19.4, -161 31.8, -180 31.8, -180 19.4)))')
    expect(bboxWkt([-180, -90, 180, 90])).toBe('POLYGON((-180 -90, 180 -90, 180 90, -180 90, -180 -90))')
    expect(obisLinks([0, 0, 1, 1]).mapper).toBe('https://mapper.obis.org/?geometry=' + encodeURIComponent('POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))'))
  })
})

// ---- AquaMaps cells ----

const GRID: CellGrid = { ncol: 7200, nrow: 3600, x0: -180, y0: 90, res: 0.05 }

describe('the place on the 0.05 degree grid', () => {
  it('numbers cells row-major from the north-west, 1-based, and tiles them by 5 degrees', () => {
    expect(cellAt(0, 0, GRID, 5)).toEqual({ cellId: 1, tile: 0 })
    expect(cellAt(0, 7199, GRID, 5)).toEqual({ cellId: 7200, tile: 71 })
    expect(cellAt(100, 100, GRID, 5)).toEqual({ cellId: 100 * 7200 + 101, tile: 73 })
    // CINMS, -120.5 E 34 N: row 1120, column 1190, tile 11 * 72 + 11 (the atlas's tile=803)
    expect(cellAt(1120, 1190, GRID, 5).tile).toBe(803)
  })

  it('tests a point against a polygon with a hole', () => {
    const rings = [[[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]], [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]
    expect([inRings(0.5, 0.5, rings), inRings(2, 2, rings), inRings(5, 5, rings)]).toEqual([true, false, false])
  })

  it('takes the cells whose centre is inside: a 0.1 degree square holds four', () => {
    const sq = { type: 'Polygon', coordinates: [[[0, 0], [0.1, 0], [0.1, 0.1], [0, 0.1], [0, 0]]] }
    const cells = placeCells(sq, GRID, 5)!
    expect([...cells.keys()].sort((a, b) => a - b)).toEqual([1798 * 7200 + 3601, 1798 * 7200 + 3602, 1799 * 7200 + 3601, 1799 * 7200 + 3602])
  })

  it('keeps a part too small for a cell centre as the cell under it', () => {
    const tiny = { type: 'MultiPolygon', coordinates: [[[[0.01, 0.01], [0.02, 0.01], [0.02, 0.02], [0.01, 0.01]]]] }
    expect([...placeCells(tiny, GRID, 5)!.keys()]).toEqual([1799 * 7200 + 3601])
  })

  it('wraps an unwrapped longitude past 180 onto the grid', () => {
    const past = { type: 'Polygon', coordinates: [[[190, 0], [190.05, 0], [190.05, 0.05], [190, 0.05], [190, 0]]] }
    const plain = { type: 'Polygon', coordinates: [[[-170, 0], [-169.95, 0], [-169.95, 0.05], [-170, 0.05], [-170, 0]]] }
    expect([...placeCells(past, GRID, 5)!.keys()]).toEqual([...placeCells(plain, GRID, 5)!.keys()])
  })

  it('refuses a place over the cell limit, and has no cells without a polygon', () => {
    const big = { type: 'Polygon', coordinates: [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]] }
    expect(placeCells(big, GRID, 5, 1000)).toBeNull()
    expect(placeCells({ type: 'Point', coordinates: [0, 0] }, GRID, 5)!.size).toBe(0)
  })

  it('groups cells by tile, ascending', () => {
    expect(tilesOf(new Map([[30, 2], [10, 1], [20, 2]]))).toEqual([{ tile: 1, ids: [10] }, { tile: 2, ids: [20, 30] }])
  })
})

describe('the row groups that hold the place', () => {
  const meta = (ranges: [number, number, number][]): MetaLike => ({
    row_groups: ranges.map(([n, lo, hi]) => ({ num_rows: BigInt(n), columns: [{ meta_data: { path_in_schema: ['cell_id'], statistics: { min_value: lo, max_value: hi } } }] })),
  })

  it('reads only the groups whose cell range holds a cell of the place, adjacent ones as one read', () => {
    const m = meta([[100, 1, 50], [100, 50, 99], [100, 100, 150], [100, 151, 200], [100, 201, 260]])
    expect(groupsHolding(m, 'cell_id', [60, 120, 210])).toEqual([{ rowStart: 100, rowEnd: 300 }, { rowStart: 400, rowEnd: 500 }])
    expect(groupsHolding(m, 'cell_id', [300])).toEqual([])
  })

  it('reads a group without statistics', () => {
    expect(groupsHolding({ row_groups: [{ num_rows: 5, columns: [] }] }, 'cell_id', [1])).toEqual([{ rowStart: 0, rowEnd: 5 }])
  })
})

describe('the AquaMaps species of the place', () => {
  const lookup = [
    { aphia_id: 1n, scientific_name: 'Sebastes miniatus', common_name: 'vermilion rockfish', eov: 'fish', redlist_code: 'LC', worms_url: 'w1', aquamaps_url: 'a1' },
    { aphia_id: 2, scientific_name: 'Megaptera novaeangliae', common_name: 'humpback whale', eov: 'marineMammals', redlist_code: 'LC' },
    { aphia_id: 3, scientific_name: 'Caretta caretta', eov: 'seaTurtles' },
  ]
  const tile = [
    { cell: 10, species: 1, suit: 80 }, { cell: 11, species: 1, suit: 40 }, { cell: 99, species: 1, suit: 100 },
    { cell: 10, species: 2, suit: 90 }, { cell: 11, species: 3, suit: 0 }, { cell: 12, species: 4, suit: 5 },
  ]

  it('ranks equal cell counts by the mean suitability, then the best cell', () => {
    const t = [{ cell: 1, species: 1, suit: 100 }, { cell: 2, species: 1, suit: 20 }, { cell: 1, species: 2, suit: 70 }, { cell: 2, species: 2, suit: 70 }]
    expect(sdmSpecies(t, new Set([1, 2]), []).map((s) => s.aphiaId)).toEqual([2, 1])
  })

  it('lists the species suitable in a cell of the place, most cells first; a neighbour\'s cell and a zero do not count', () => {
    const list = sdmSpecies(tile, new Set([10, 11, 12]), lookup)
    expect(list.map((s) => [s.aphiaId, s.cells, s.maxSuit, s.meanSuit])).toEqual([[1, 2, 80, 60], [2, 1, 90, 90], [4, 1, 5, 5]])
    expect(list[0]).toMatchObject({ name: 'Sebastes miniatus', common: 'vermilion rockfish', group: 'fish', worms: 'w1' })
    expect(list[2].name).toBe('AphiaID 4')
    expect(list[0].share).toBeCloseTo(2 / 3)
  })

  it('counts by group and says it in one line', () => {
    const list = sdmSpecies(tile, new Set([10, 11, 12]), lookup)
    expect(byGroup(list)).toEqual([{ group: 'fish', n: 1 }, { group: 'marineMammals', n: 1 }, { group: 'other', n: 1 }])
    expect(sdmLine(list, 3, 0.05)).toBe("3 species (fish 1, marine mammals 1, other 1) suitable in at least one of the place's 3 cells of 0.05°.")
  })

  it('writes the list as CSV', () => {
    const csv = sdmCsv('NMS:CINMS', sdmSpecies(tile, new Set([10]), lookup))
    expect(csv.split('\n')[0]).toBe('place_id,aphia_id,scientific_name,common_name,eov,redlist_code,cells,share_of_cells,max_suitability,mean_suitability,worms_url,aquamaps_url')
    expect(csv.split('\n')[1]).toBe('NMS:CINMS,2,Megaptera novaeangliae,humpback whale,marineMammals,LC,1,1.0000,90,90.0,,')
  })

  it('reads the atlas:cell_species hook with its urls made absolute', () => {
    const c = {
      'atlas:cell_species': { layout: 'tiles', tile_deg: 5, href_template: './cell_species/tile={tile}/data_0.parquet', lookup_asset: 'species',
        grid: { ncol: 7200, nrow: 3600, x0: -180, y0: 90, res: 0.05 }, key_column: 'cell_id', species_column: 'aphia_id', value_column: 'suit', value_unit: 'percent', group_column: 'eov' },
      assets: { species: { href: './species.parquet' } },
    }
    const h = parseCellSpecies(c, 'https://x/atlas/aquamaps_eov/collection.json')!
    expect([h.tileTemplate, h.lookupUrl, h.tileDeg, h.keyColumn]).toEqual(['https://x/atlas/aquamaps_eov/cell_species/tile={tile}/data_0.parquet', 'https://x/atlas/aquamaps_eov/species.parquet', 5, 'cell_id'])
    expect(parseCellSpecies({ 'atlas:cell_species': { ...c['atlas:cell_species'], layout: 'h3' }, assets: c.assets }, 'https://x/')).toBeNull()
    expect(parseCellSpecies({}, 'https://x/')).toBeNull()
  })
})
