import { describe, expect, it } from 'vitest'
import {
  bboxWkt, byGroup, cellAt, filterSpecies, groupOf, groupsHolding, groupsHoldingText, inRings, nextSort, obisColls, obisLine, obisLinks, obisSpeciesSql, obisSummary, obisValuesSql, parseCellSpecies, placeCells,
  placeExactUrl, placeSpecies, placeSpeciesCsv, placeSpeciesUrl, sdmCsv, sdmLine, sdmSpecies, sortSpecies, speciesCheck, speciesCountLine, speciesCounts,
  DEFAULT_SPECIES_SORT, speciesLookupUrl, tilesOf, type CellGrid, type MetaLike, type ObisLookupRow, type ObisRow, type PlaceSpeciesRow,
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

// ---- OBIS exact: the species of the place ----

// synthetic: place SYN:A has five aphiaids of four names (aphiaids 12 and 13 are one name, key 2); SYN:B is a neighbour in the file
const spRows: PlaceSpeciesRow[] = [
  { place_id: 'SYN:A', aphiaid: 11, name_key: 1, n: 500, year_min: 1990, year_max: 2024 },
  { place_id: 'SYN:A', aphiaid: 12, name_key: 2, n: 30, year_min: 1950, year_max: 1999 },
  { place_id: 'SYN:A', aphiaid: 13, name_key: 2, n: 70, year_min: 1970, year_max: 2011 },
  { place_id: 'SYN:A', aphiaid: 14n, name_key: 3, n: 70n, year_min: 2021, year_max: 2021 },
  { place_id: 'SYN:A', aphiaid: 15, name_key: 4, n: 1, year_min: null, year_max: null },
  { place_id: 'SYN:B', aphiaid: 11, name_key: 1, n: 9, year_min: 2005, year_max: 2006 },
]
const spLookup: ObisLookupRow[] = [
  { aphiaid: 11, species: 'Synthetica alpha', class: 'Teleostei' },
  { aphiaid: 12, species: 'Synthetica beta', class: 'Aves' },
  { aphiaid: 13n, species: 'Synthetica beta', class: 'Aves', eov: 'seabirds', redlist_code: 'EN' },
  { aphiaid: 14, species: 'Synthetica gamma', class: null },
]
// the indicators of SYN:A as the release writes them: every year 4 species (the record without a year counts), the 2020s 2
const spInd: ObisRow[] = [
  { place_id: 'SYN:A', eov: 'all', decade: null, n: 601, sp: 4, es: 3 },
  { place_id: 'SYN:A', eov: 'all', decade: 1990, n: 400, sp: 2, es: null },
  { place_id: 'SYN:A', eov: 'all', decade: 2020, n: 570, sp: 2, es: null },
]

describe('OBIS exact: the species of the place', () => {
  const list = placeSpecies(spRows, 'SYN:A', spLookup)

  it('merges the aphiaids of one name, sums records and spans the years, most records first', () => {
    expect(list.map((s) => [s.name, s.n, s.yearMin, s.yearMax])).toEqual([
      ['Synthetica alpha', 500, 1990, 2024], ['Synthetica beta', 100, 1950, 2011], ['Synthetica gamma', 70, 2021, 2021], ['AphiaID 15', 1, null, null],
    ])
    expect(list[1]).toMatchObject({ nameKey: 2, aphiaId: 13, eov: 'seabirds', cls: 'Aves', redlist: 'EN' })
    expect(list[1].worms).toBe('https://www.marinespecies.org/aphia.php?p=taxdetails&id=13')
  })

  it('leaves the other places of the file out, and has nothing for a place the file lacks', () => {
    expect(placeSpecies(spRows, 'SYN:B', spLookup).map((s) => s.n)).toEqual([9])
    expect(placeSpecies(spRows, 'SYN:Z', spLookup)).toEqual([])
  })

  it('breaks a tie in records by the name', () => {
    const r: PlaceSpeciesRow[] = [{ place_id: 'P', aphiaid: 2, name_key: 2, n: 5, year_min: 2000, year_max: 2001 }, { place_id: 'P', aphiaid: 1, name_key: 1, n: 5, year_min: 2000, year_max: 2001 }]
    expect(placeSpecies(r, 'P', [{ aphiaid: 1, species: 'Zeta' }, { aphiaid: 2, species: 'Alpha' }]).map((s) => s.name)).toEqual(['Alpha', 'Zeta'])
  })

  it('names the group by the EOV when the lookup gives it, else by the class, else "other"', () => {
    expect(list.map(groupOf)).toEqual(['Teleostei', 'seabirds', 'other', 'other'])
  })

  // the rule: the species count of the list is the `sp` of the indicators row, every year and in the latest decade
  it('counts N species (names) and M in the latest decade, and they equal the sp of the indicators row', () => {
    const sum = obisSummary(spInd, 'SYN:A')!
    const c = speciesCounts(list, sum.latest?.decade ?? null)
    expect(c).toEqual({ all: 4, latest: { decade: 2020, n: 2 } })
    expect(c.all).toBe(sum.all!.sp)
    expect(c.latest!.n).toBe(sum.latest!.sp)
    expect(speciesCheck(c, sum)).toBeNull()
    expect(speciesCountLine(c)).toBe('4 species with records in the place (exact), 2 in the latest decade (the 2020s).')
  })

  it('counts aphiaids, not names, would be 5: richness is the names', () => {
    expect(spRows.filter((r) => r.place_id === 'SYN:A').length).toBe(5)
    expect(list.length).toBe(4)
  })

  it('warns when the live numbers disagree with the indicators row, naming both', () => {
    const sum = obisSummary(spInd, 'SYN:A')!
    const w = speciesCheck(speciesCounts(list.filter((s) => s.nameKey !== 3), 2020), sum)!
    expect(w).toContain('3 species in the list against 4 in the indicators for every year')
    expect(w).toContain('1 against 2 for the 2020s')   // the dropped species (gamma, 2021) was one of the two of the 2020s
  })

  it('says only the every-year count when the place has no decade, and does not warn without indicators', () => {
    expect(speciesCountLine(speciesCounts(list, null))).toBe('4 species with records in the place (exact).')
    expect(speciesCheck(speciesCounts(list, null), { all: null, latest: null })).toBeNull()
  })

  it('writes the list as CSV, quoting names with commas', () => {
    const csv = placeSpeciesCsv('SYN:A', placeSpecies(spRows, 'SYN:A', [{ aphiaid: 11, species: 'Synthetica, alpha', class: 'Teleostei' }]))
    expect(csv.split('\n')[0]).toBe('place_id,aphiaid,name_key,scientific_name,eov,class,redlist_code,records,year_min,year_max,worms_url')
    expect(csv.split('\n')[1]).toBe('SYN:A,11,1,"Synthetica, alpha",,Teleostei,,500,1990,2024,https://www.marinespecies.org/aphia.php?p=taxdetails&id=11')
  })

  it('finds the files next to the release', () => {
    expect(placeSpeciesUrl({ base: 'https://x/obis-h3/v1' }, 'places')).toBe('https://x/obis-h3/v1/place_exact/coll=places/species.parquet')
    expect(speciesLookupUrl({ base: 'https://x/obis-h3/v1/' })).toBe('https://x/obis-h3/v1/species/species.parquet')
  })
})

// the species table of the Place page: filter, sort, the Reproduce text (parity rows 64 and 70)
describe('OBIS exact: filter and sort the species table', () => {
  const list = placeSpecies(spRows, 'SYN:A', spLookup)   // alpha 500 (Teleostei), beta 100 (seabirds, EN), gamma 70 (other), AphiaID 15 1 (no years)

  it('an empty query keeps the whole list in its order, a copy', () => {
    expect(filterSpecies(list, '  ').map((s) => s.name)).toEqual(list.map((s) => s.name))
    expect(filterSpecies(list, '')).not.toBe(list)
  })

  it('matches a fragment of the name, the group or the IUCN code, any case, every word', () => {
    expect(filterSpecies(list, 'BETA').map((s) => s.nameKey)).toEqual([2])
    expect(filterSpecies(list, 'seabird').map((s) => s.nameKey)).toEqual([2])
    expect(filterSpecies(list, 'teleo').map((s) => s.nameKey)).toEqual([1])
    expect(filterSpecies(list, 'iucn en').map((s) => s.nameKey)).toEqual([2])
    expect(filterSpecies(list, 'synthetica alpha').map((s) => s.nameKey)).toEqual([1])
    expect(filterSpecies(list, 'synthetica nothing')).toEqual([])
  })

  it('records, most first, is the default and the order the list arrives in', () => {
    expect(DEFAULT_SPECIES_SORT).toEqual({ key: 'records', dir: 'desc' })
    expect(sortSpecies(list).map((s) => s.n)).toEqual([500, 100, 70, 1])
    expect(sortSpecies(list, { key: 'records', dir: 'asc' }).map((s) => s.n)).toEqual([1, 70, 100, 500])
  })

  it('sorts by name and by group, A to Z or Z to A, ignoring case', () => {
    expect(sortSpecies(list, { key: 'name', dir: 'asc' }).map((s) => s.name)).toEqual(['AphiaID 15', 'Synthetica alpha', 'Synthetica beta', 'Synthetica gamma'])
    expect(sortSpecies(list, { key: 'name', dir: 'desc' }).map((s) => s.name)[0]).toBe('Synthetica gamma')
    expect(sortSpecies(list, { key: 'group', dir: 'asc' }).map(groupOf)).toEqual(['other', 'other', 'seabirds', 'Teleostei'])
  })

  it('sorts by the last year, and a species with no year is last in both directions', () => {
    expect(sortSpecies(list, { key: 'last', dir: 'desc' }).map((s) => s.yearMax)).toEqual([2024, 2021, 2011, null])
    expect(sortSpecies(list, { key: 'last', dir: 'asc' }).map((s) => s.yearMax)).toEqual([2011, 2021, 2024, null])
  })

  it('breaks a tie by records, then the name; leaves its input alone', () => {
    const before = list.map((s) => s.name)
    const byGroupAsc = sortSpecies(list, { key: 'group', dir: 'asc' })
    expect(byGroupAsc.slice(0, 2).map((s) => s.name)).toEqual(['Synthetica gamma', 'AphiaID 15'])   // both "other": 70 records before 1
    expect(list.map((s) => s.name)).toEqual(before)
  })

  it('a header click flips the sorted column, and starts a new one in its natural order', () => {
    expect(nextSort(DEFAULT_SPECIES_SORT, 'records')).toEqual({ key: 'records', dir: 'asc' })
    expect(nextSort(DEFAULT_SPECIES_SORT, 'name')).toEqual({ key: 'name', dir: 'asc' })
    expect(nextSort({ key: 'name', dir: 'asc' }, 'name')).toEqual({ key: 'name', dir: 'desc' })
    expect(nextSort({ key: 'name', dir: 'asc' }, 'last')).toEqual({ key: 'last', dir: 'desc' })
    expect(nextSort({ key: 'name', dir: 'asc' }, 'group')).toEqual({ key: 'group', dir: 'asc' })
  })
})

describe('the Reproduce text of the Species section', () => {
  const base = 'https://x/obis-h3/v1/'
  it('names the values file and the place, in order of eov and decade', () => {
    expect(obisValuesSql(placeExactUrl({ base }, 'sanctuaries'), 'NMS:CINMS')).toBe(
      "SELECT * FROM 'https://x/obis-h3/v1/place_exact/coll=sanctuaries/indicators.parquet'\nWHERE place_id = 'NMS:CINMS' ORDER BY eov, decade NULLS FIRST;")
  })
  it('names the species file, the names file and the place, one row per name key, most records first', () => {
    const sql = obisSpeciesSql(placeSpeciesUrl({ base }, 'sanctuaries'), speciesLookupUrl({ base }), 'NMS:CINMS')
    expect(sql).toContain("FROM 'https://x/obis-h3/v1/place_exact/coll=sanctuaries/species.parquet' s")
    expect(sql).toContain("LEFT JOIN 'https://x/obis-h3/v1/species/species.parquet' l USING (aphiaid)")
    expect(sql).toContain("WHERE s.place_id = 'NMS:CINMS'")
    expect(sql).toContain('GROUP BY s.name_key ORDER BY records DESC;')
  })
  it('doubles a quote in a place id, so an id cannot end the string', () => {
    expect(obisValuesSql('https://x/f.parquet', "A'B")).toContain("place_id = 'A''B'")
    expect(obisSpeciesSql('https://x/s.parquet', 'https://x/l.parquet', "A'B")).toContain("s.place_id = 'A''B'")
  })
})

describe('the row groups that can hold a place (the file is sorted by place_id)', () => {
  const meta = (g: [number, string, string][]): MetaLike => ({
    row_groups: g.map(([n, lo, hi]) => ({ num_rows: n, columns: [{ meta_data: { path_in_schema: ['place_id'], statistics: { min_value: lo, max_value: hi } } }] })),
  })
  // a place may span two groups (the boundary one: MRGID:5694 ends the first group and starts the second)
  const m = meta([[100, 'MRGID:21787', 'MRGID:5694'], [100, 'MRGID:5694', 'MRGID:8324'], [100, 'MRGID:8324', 'MRGID:8389']])

  it('reads the one group, or the neighbours when the place spans them, adjacent ones as one read', () => {
    expect(groupsHoldingText(m, 'place_id', 'MRGID:3000')).toEqual([{ rowStart: 0, rowEnd: 100 }])
    expect(groupsHoldingText(m, 'place_id', 'MRGID:5694')).toEqual([{ rowStart: 0, rowEnd: 200 }])
    expect(groupsHoldingText(m, 'place_id', 'MRGID:8389')).toEqual([{ rowStart: 200, rowEnd: 300 }])
    expect(groupsHoldingText(m, 'place_id', 'MRGID:9')).toEqual([])
  })

  it('reads a group without string statistics', () => {
    expect(groupsHoldingText({ row_groups: [{ num_rows: 7, columns: [] }] }, 'place_id', 'X')).toEqual([{ rowStart: 0, rowEnd: 7 }])
  })
})
