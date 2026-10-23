// the Species section of the place page, its rules in plain functions (tested on synthetic rows and tiles):
//
// - OBIS, exact: the obis-h3 release's `place_exact/coll=<coll>/indicators.parquet` holds one row per place x EOV x decade
//   (decade null = every year) with records `n`, species `sp` and ES(50) `es`, computed point-in-polygon on the place
//   itself (obisindicators). the per-species list is not in the release, so the section links the OBIS mapper and the
//   OBIS checklist API for the place's box.
// - AquaMaps (SDM): the atlas collection `aquamaps_eov` declares `atlas:cell_species`, a cell -> species table tiled by
//   5 degrees over the 0.05 degree grid (`cell_id` row-major from the north-west corner, 1-based). the place's cells are
//   the cells whose centre falls inside its polygon (exact on the native grid, as the vision's "exact is the record" rule
//   asks; the tiles are not H3, so the place's H3 membership is not a step here); the tiles' row groups are sorted by cell,
//   so only the groups whose cell range holds one of the place's cells are read. a species is listed when it is suitable
//   (suitability 1 to 100) in at least one of them.
// the reading is speciesRead.ts (hyparquet, a lazy chunk).

// ---- OBIS, exact ----

/** obis-h3's pointer to the current release */
export const OBIS_LATEST = 'https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/obis-h3/latest.json'

export interface ObisRelease { release: string; base: string; obis_snapshot?: string; worms_version?: string; built_at?: string }

export const placeExactUrl = (release: Pick<ObisRelease, 'base'>, coll: string) => `${release.base.replace(/\/?$/, '/')}place_exact/coll=${coll}/indicators.parquet`

/** the collections whose place_exact file may hold the place: its own, then those of its copies in other layers, each once */
export function obisColls(own: string | null | undefined, copies: readonly { collection: string }[] = []): string[] {
  return [...new Set([own, ...copies.map((c) => c.collection)].filter((c): c is string => !!c))]
}

export interface ObisRow { place_id: string; eov: string; decade: number | null; n: number | null; sp: number | null; es: number | null }

export interface ObisDecade { decade: number; n: number; sp: number; es: number | null }

export interface ObisSummary {
  /** every year: records, species, ES(50) */
  all: { n: number; sp: number; es: number | null } | null
  /** by decade, oldest first */
  decades: ObisDecade[]
  /** the latest decade with records */
  latest: ObisDecade | null
  /** species and records by EOV group (every year), most species first; `all` left out */
  byEov: { eov: string; sp: number; n: number }[]
}

const num = (v: unknown): number | null => (v === null || v === undefined || Number.isNaN(Number(v)) ? null : Number(v))

/** the place's OBIS rows as the section says them; null when the file has none for the place */
export function obisSummary(rows: readonly ObisRow[], placeId: string): ObisSummary | null {
  const mine = rows.filter((r) => r.place_id === placeId)
  if (!mine.length) return null
  const all = mine.find((r) => r.eov === 'all' && r.decade == null)
  const decades = mine.filter((r) => r.eov === 'all' && r.decade != null && (num(r.n) ?? 0) > 0)
    .map((r) => ({ decade: Number(r.decade), n: num(r.n) ?? 0, sp: num(r.sp) ?? 0, es: num(r.es) }))
    .sort((a, b) => a.decade - b.decade)
  const byEov = mine.filter((r) => r.eov !== 'all' && r.decade == null && (num(r.sp) ?? 0) > 0)
    .map((r) => ({ eov: r.eov, sp: num(r.sp) ?? 0, n: num(r.n) ?? 0 }))
    .sort((a, b) => b.sp - a.sp || a.eov.localeCompare(b.eov))
  return {
    all: all ? { n: num(all.n) ?? 0, sp: num(all.sp) ?? 0, es: num(all.es) } : null,
    decades, latest: decades.at(-1) ?? null, byEov,
  }
}

const int = (n: number) => Math.round(n).toLocaleString('en-US')
const es = (v: number | null) => (v == null ? 'ES(50) not defined (under 50 records)' : `ES(50) ${v.toFixed(1)}`)

/** "5,650,862 records of 2,258 species (ES(50) 39.1) in every year; in the 2020s, 2,433,277 records of 668 species (ES(50) 30.3)." */
export function obisLine(s: ObisSummary): string {
  const a = s.all ? `${int(s.all.n)} records of ${int(s.all.sp)} species (${es(s.all.es)}) in every year` : 'No records in every year'
  const l = s.latest ? `; in the ${s.latest.decade}s, ${int(s.latest.n)} records of ${int(s.latest.sp)} species (${es(s.latest.es)})` : ''
  return `${a}${l}.`
}

/** the EOV groups as the section names them */
export const EOV_LABEL: Record<string, string> = {
  fish: 'fish', hardCorals: 'hard corals', seaTurtles: 'sea turtles', marineMammals: 'marine mammals', seabirds: 'seabirds',
  seagrasses: 'seagrasses', mangroves: 'mangroves', macroalgae: 'macroalgae', zooplankton: 'zooplankton', phytoplankton: 'phytoplankton',
}
export const eovLabel = (eov: string) => EOV_LABEL[eov] ?? eov

/**
 * the place's box as WKT for OBIS (longitudes in -180..180): one polygon, or two when the box crosses the antimeridian
 * (west > east, or an unwrapped east beyond 180)
 */
export function bboxWkt(b: readonly number[]): string {
  const wrap = (x: number) => (x > 180 ? x - 360 : x < -180 ? x + 360 : x)
  const r = (x: number) => Math.round(x * 1e4) / 1e4
  const [w0, s, e0, n] = b.map(Number)
  const w = wrap(w0), e = wrap(e0)
  const ring = (a: number, c: number) => `((${r(a)} ${r(s)}, ${r(c)} ${r(s)}, ${r(c)} ${r(n)}, ${r(a)} ${r(n)}, ${r(a)} ${r(s)}))`
  if (e0 - w0 >= 360) return `POLYGON${ring(-180, 180)}`
  return w <= e ? `POLYGON${ring(w, e)}` : `MULTIPOLYGON(${ring(w, 180)}, ${ring(-180, e)})`
}

/** the OBIS mapper and the OBIS checklist (species list, JSON) for the place's box */
export function obisLinks(bbox: readonly number[]): { mapper: string; checklist: string } {
  const g = encodeURIComponent(bboxWkt(bbox))
  return { mapper: `https://mapper.obis.org/?geometry=${g}`, checklist: `https://api.obis.org/v3/checklist?geometry=${g}&size=1000` }
}

// ---- AquaMaps: the place's cells on the 0.05 degree grid ----

export interface CellGrid { ncol: number; nrow: number; x0: number; y0: number; res: number }

/** the `atlas:cell_species` hook as the section reads it */
export interface CellSpeciesHook {
  /** the tile parquet with `{tile}` left in, absolute */
  tileTemplate: string
  /** the species lookup parquet, absolute */
  lookupUrl: string
  tileDeg: number
  grid: CellGrid
  keyColumn: string
  speciesColumn: string
  valueColumn: string
  valueUnit: string
  groupColumn: string | null
}

const isObj = (v: unknown): v is Record<string, any> => typeof v === 'object' && v !== null && !Array.isArray(v)

/** the hook of a collection, its urls resolved against the collection's own url; null when it declares none or an unusable one */
export function parseCellSpecies(c: unknown, collectionUrl: string): CellSpeciesHook | null {
  if (!isObj(c) || !isObj(c['atlas:cell_species'])) return null
  const d = c['atlas:cell_species']
  const g = d.grid
  const lookup = c.assets?.[d.lookup_asset]?.href
  if (d.layout !== 'tiles' || typeof d.href_template !== 'string' || !d.href_template.includes('{tile}') || typeof lookup !== 'string') return null
  if (!isObj(g) || ![g.ncol, g.nrow, g.res].every((x) => Number(x) > 0) || ![g.x0, g.y0].every(Number.isFinite)) return null
  if (!(Number(d.tile_deg) > 0) || !d.key_column || !d.species_column || !d.value_column) return null
  const abs = (u: string) => new URL(u.replace('{tile}', '__TILE__'), collectionUrl).href.replace('__TILE__', '{tile}')
  return {
    tileTemplate: abs(d.href_template), lookupUrl: abs(lookup), tileDeg: Number(d.tile_deg),
    grid: { ncol: g.ncol, nrow: g.nrow, x0: g.x0, y0: g.y0, res: g.res },
    keyColumn: d.key_column, speciesColumn: d.species_column, valueColumn: d.value_column, valueUnit: d.value_unit ?? '',
    groupColumn: d.group_column ?? null,
  }
}

const EPS = 1e-9

/** a cell by its row and column: the 1-based id, row-major from the north-west corner, and the 5 degree tile that holds it */
export function cellAt(row: number, col: number, grid: CellGrid, tileDeg: number): { cellId: number; tile: number } {
  const side = Math.round(tileDeg / grid.res)
  return { cellId: row * grid.ncol + col + 1, tile: Math.floor(row / side) * Math.ceil(grid.ncol / side) + Math.floor(col / side) }
}

/** is the point inside the polygon (its rings: the outer one and its holes, by the even-odd rule)? */
export function inRings(x: number, y: number, rings: readonly (readonly number[])[][]): boolean {
  let inside = false
  for (const ring of rings) {
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j]
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside
    }
  }
  return inside
}

type Geom = { type: string; coordinates: any }

/**
 * the grid cells whose centre falls inside the place's polygon, each once, by cell id -> tile; longitudes past ±180 (an
 * unwrapped place) wrap onto the grid. a part too small to hold a cell centre (a bank of Flower Garden Banks) counts the
 * cell under its box's centre, so no part of the place is lost. at most `max` cells (a larger place is `null`: not listed)
 */
export function placeCells(geometry: Geom | null | undefined, grid: CellGrid, tileDeg: number, max = 200_000): Map<number, number> | null {
  const polys: number[][][][] = geometry?.type === 'Polygon' ? [geometry.coordinates] : geometry?.type === 'MultiPolygon' ? geometry.coordinates : []
  const out = new Map<number, number>()
  for (const rings of polys) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
    for (const [x, y] of rings[0] ?? []) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y) }
    if (!Number.isFinite(x0)) continue
    const r0 = Math.max(0, Math.floor((grid.y0 - y1) / grid.res + EPS)), r1 = Math.min(grid.nrow - 1, Math.floor((grid.y0 - y0) / grid.res + EPS))
    const c0 = Math.floor((x0 - grid.x0) / grid.res + EPS), c1 = Math.floor((x1 - grid.x0) / grid.res + EPS)
    if ((r1 - r0 + 1) * (c1 - c0 + 1) > max * 4) return null
    let found = false
    const add = (r: number, c: number) => {
      const { cellId, tile } = cellAt(r, ((c % grid.ncol) + grid.ncol) % grid.ncol, grid, tileDeg)
      out.set(cellId, tile)
      found = true
    }
    for (let r = r0; r <= r1; r++) {
      const lat = grid.y0 - (r + 0.5) * grid.res
      for (let c = c0; c <= c1; c++) {
        const lon = grid.x0 + (c + 0.5) * grid.res
        if (!inRings(lon, lat, rings)) continue
        add(r, c)
        if (out.size > max) return null
      }
    }
    if (!found) add(Math.floor((grid.y0 - (y0 + y1) / 2) / grid.res + EPS), Math.floor(((x0 + x1) / 2 - grid.x0) / grid.res + EPS))
  }
  return out
}

/** the tiles that hold the cells, ascending, each with its cell ids ascending */
export function tilesOf(cells: ReadonlyMap<number, number>): { tile: number; ids: number[] }[] {
  const by = new Map<number, number[]>()
  for (const [id, tile] of cells) (by.get(tile) ?? by.set(tile, []).get(tile)!).push(id)
  return [...by.entries()].sort((a, b) => a[0] - b[0]).map(([tile, ids]) => ({ tile, ids: ids.sort((a, b) => a - b) }))
}

/** the slice of hyparquet's FileMetaData the row-group rule reads */
export interface MetaLike {
  row_groups: { num_rows: bigint | number; columns: { meta_data?: { path_in_schema: string[]; statistics?: Record<string, unknown> } }[] }[]
}

/** the first index in sorted `ids` that is >= v */
const lowerBound = (ids: readonly number[], v: number) => {
  let lo = 0, hi = ids.length
  while (lo < hi) { const m = (lo + hi) >> 1; if (ids[m] < v) lo = m + 1; else hi = m }
  return lo
}

/** the row ranges of the row groups whose key min/max holds one of the (sorted) ids; a group without statistics always does */
export function groupsHolding(meta: MetaLike, key: string, ids: readonly number[]): { rowStart: number; rowEnd: number }[] {
  const out: { rowStart: number; rowEnd: number }[] = []
  let start = 0
  for (const rg of meta.row_groups) {
    const n = Number(rg.num_rows)
    const st = rg.columns.find((c) => c.meta_data?.path_in_schema.join('.') === key)?.meta_data?.statistics
    const lo = num(st?.min_value ?? st?.min), hi = num(st?.max_value ?? st?.max)
    const i = lo == null ? 0 : lowerBound(ids, lo)
    if (lo == null || hi == null || (i < ids.length && ids[i] <= hi)) out.push({ rowStart: start, rowEnd: start + n })
    start += n
  }
  // adjacent ranges as one read
  return out.reduce<{ rowStart: number; rowEnd: number }[]>((acc, r) => {
    const last = acc.at(-1)
    if (last && last.rowEnd === r.rowStart) last.rowEnd = r.rowEnd; else acc.push({ ...r })
    return acc
  }, [])
}

// ---- AquaMaps: the species of the place ----

export interface SdmSpecies {
  aphiaId: number
  name: string
  common: string | null
  group: string | null
  redlist: string | null
  /** cells of the place where it is suitable, and their share of the place's cells */
  cells: number
  share: number
  /** the highest and the mean suitability over those cells (percent) */
  maxSuit: number
  meanSuit: number
  worms: string | null
  aquamaps: string | null
}

export interface SpeciesLookupRow {
  aphia_id: number | bigint
  scientific_name?: string | null
  common_name?: string | null
  eov?: string | null
  redlist_code?: string | null
  worms_url?: string | null
  aquamaps_url?: string | null
}

/**
 * the species suitable in at least one of the place's cells, joined with the lookup: most cells first, then the highest
 * mean suitability over them, then the highest single cell, then the name. `rows` may hold cells outside the place (a row group's neighbours); only `cells` count
 */
export function sdmSpecies(rows: readonly { cell: number; species: number; suit: number }[], cells: ReadonlySet<number> | ReadonlyMap<number, unknown>,
  lookup: readonly SpeciesLookupRow[]): SdmSpecies[] {
  const acc = new Map<number, { cells: Set<number>; max: number; sum: number }>()
  for (const r of rows) {
    if (!cells.has(r.cell) || !(r.suit > 0)) continue
    const a = acc.get(r.species) ?? acc.set(r.species, { cells: new Set(), max: 0, sum: 0 }).get(r.species)!
    if (a.cells.has(r.cell)) continue
    a.cells.add(r.cell)
    a.max = Math.max(a.max, r.suit)
    a.sum += r.suit
  }
  const info = new Map(lookup.map((l) => [Number(l.aphia_id), l]))
  const total = cells.size || 1
  return [...acc.entries()].map(([id, a]) => {
    const l = info.get(id)
    return {
      aphiaId: id, name: l?.scientific_name ?? `AphiaID ${id}`, common: l?.common_name ?? null, group: l?.eov ?? null, redlist: l?.redlist_code ?? null,
      cells: a.cells.size, share: a.cells.size / total, maxSuit: a.max, meanSuit: a.sum / a.cells.size,
      worms: l?.worms_url ?? null, aquamaps: l?.aquamaps_url ?? null,
    }
  }).sort((x, y) => y.cells - x.cells || y.meanSuit - x.meanSuit || y.maxSuit - x.maxSuit || x.name.localeCompare(y.name))
}

/** species by group, most first */
export function byGroup(list: readonly Pick<SdmSpecies, 'group'>[]): { group: string; n: number }[] {
  const m = new Map<string, number>()
  for (const s of list) m.set(s.group ?? 'other', (m.get(s.group ?? 'other') ?? 0) + 1)
  return [...m.entries()].map(([group, n]) => ({ group, n })).sort((a, b) => b.n - a.n || a.group.localeCompare(b.group))
}

/** "1,234 species (fish 1,100, hard corals 80, ...) suitable in at least one of the place's 412 cells of 0.05°." */
export function sdmLine(list: readonly SdmSpecies[], cells: number, res: number): string {
  const groups = byGroup(list).map((g) => `${eovLabel(g.group)} ${int(g.n)}`).join(', ')
  return `${int(list.length)} species${groups ? ` (${groups})` : ''} suitable in at least one of the place's ${int(cells)} cells of ${res}°.`
}

const csvCell = (v: unknown) => {
  const s = v == null ? '' : String(v)
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

/** the list as CSV, one row per species */
export function sdmCsv(placeId: string, list: readonly SdmSpecies[]): string {
  const head = ['place_id', 'aphia_id', 'scientific_name', 'common_name', 'eov', 'redlist_code', 'cells', 'share_of_cells', 'max_suitability', 'mean_suitability', 'worms_url', 'aquamaps_url']
  const rows = list.map((s) => [placeId, s.aphiaId, s.name, s.common, s.group, s.redlist, s.cells, s.share.toFixed(4), s.maxSuit, s.meanSuit.toFixed(1), s.worms, s.aquamaps])
  return [head, ...rows].map((r) => r.map(csvCell).join(',')).join('\n') + '\n'
}
