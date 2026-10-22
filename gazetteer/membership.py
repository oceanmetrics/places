"""place x H3 membership: the cells of res 1..7 each polygon place covers, with the share of each cell's area inside.

a cell is kept when its share is >= MIN_SHARE (Ben, 2026-10-14: cells "intersected and area-weighted ... keep anything
over 1%"), or when it holds >= MIN_SHARE of the place's own area, so a place smaller than 1% of a coarse cell still has
the cells it touches (their small shares keep any weighted value honest). areas are planar in (lon, sin(lat)), the cylindrical equal-area plane, so a ratio of areas there is a ratio
of areas on the sphere (edges straight in lon/lat, as the GeoParquet geometry itself is drawn).

the cells are found by refining down the hierarchy, testing only cells near a place's edge: at each res the
candidates are classified inside (share 1), edge (0 < share < 1, computed) or outside. the next res tests the children
of the edge cells, of the inside cells next to something that is not inside, and of the edge cells' neighbours (an H3
child pokes out of its parent by a sliver, never beyond the parent's ring of neighbours); the children of an inside
cell whose six neighbours are all inside are inside without a test.

antimeridian: places are stored split at +/-180. a cell crossing it is unwrapped to longitudes past 180, and a cell
around a pole to a band closed along the pole, so every place part is also matched as a copy shifted by +360.

robustness: a valid place can still be cut into invalid pieces (clip_by_rect leaves self-touching rings along its cut),
and GEOS then raises on the intersection (noaa_efh, 2026-10-22: "unable to assign free hole to a shell"). so the pieces
are made valid once per place; a cell whose intersection still raises is retried with buffer(0), then given the
centre-in rule (share 1 when its centre lies in the place, else dropped), and listed in `warnings`. a place that
fails any other way is skipped with a warning; one place never aborts the collection.

memory: a big layer (protectedseas_fisheries, 2026-10-22) has more rows at res 7 than one Arrow string column can hold
(2 GB of offsets), so the rows are never one table. `Membership` keeps each place's cells as uint64 H3 indexes and shares
as float32 (12 bytes a row), and the files are written from it a partition at a time, the strings made per block of
BLOCK_ROWS rows.
"""
from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import h3
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely import STRtree
from shapely.errors import GEOSException

MIN_SHARE = 0.01
RES_MAX = 7
PARENT_RES = {6: 2, 7: 3}  # res 6 and 7 are split by these parents, as the obis-h3 release splits them
MAX_VERTICES = 256         # a place is cut into pieces of at most this many vertices before cells are intersected
INSIDE = 1 - 1e-9

SCHEMA = pa.schema([("place_id", pa.string()), ("h3", pa.string()), ("share", pa.float32())])

ROW_GROUP = 65536          # rows per Parquet row group
BLOCK_ROWS = 1 << 20       # rows turned into Arrow strings at a time: a string column holds 2 GB at most, and a layer has far more rows


# geometry in the equal-area plane ----

def to_plane(geom):
  """lon/lat geometry -> (lon, sin(lat)) geometry."""
  return shapely.transform(geom, lambda xy: np.column_stack([xy[:, 0], np.sin(np.radians(xy[:, 1]))]))


def _polygons(geom) -> list:
  if geom is None or geom.is_empty:
    return []
  if geom.geom_type == "Polygon":
    return [geom]
  if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
    return [p for g in geom.geoms for p in _polygons(g)]
  return []


def valid_polygons(geoms) -> list:
  """the polygonal parts of geometries made valid: make_valid may return a collection with lines or points, dropped."""
  geoms = np.asarray(list(geoms), dtype=object)
  if not len(geoms):
    return []
  bad = ~shapely.is_valid(geoms)
  geoms[bad] = shapely.make_valid(geoms[bad])
  return [p for g in geoms for p in _polygons(g) if p.area > 0]


def subdivide(geom, max_vertices: int = MAX_VERTICES) -> list:
  """cut a polygonal geometry into quadrant pieces of at most max_vertices vertices (PostGIS ST_Subdivide's idea)."""
  out, stack = [], [geom]
  while stack:
    g = stack.pop()
    if g.is_empty:
      continue
    if shapely.get_num_coordinates(g) <= max_vertices:
      out.extend(_polygons(g))
      continue
    x0, y0, x1, y1 = g.bounds
    if x1 - x0 >= y1 - y0:
      xm = (x0 + x1) / 2
      halves = [shapely.clip_by_rect(g, x0, y0, xm, y1), shapely.clip_by_rect(g, xm, y0, x1, y1)]
    else:
      ym = (y0 + y1) / 2
      halves = [shapely.clip_by_rect(g, x0, y0, x1, ym), shapely.clip_by_rect(g, x0, ym, x1, y1)]
    if any(shapely.get_num_coordinates(h) >= shapely.get_num_coordinates(g) for h in halves):
      out.extend(_polygons(g))  # a degenerate split (all vertices on one line): keep it whole
      continue
    stack.extend(halves)
  return [p for p in out if p.area > 0]


def place_pieces(geom) -> list:
  """a place's pieces in the plane: its polygon parts, and the same shifted by +360 (for unwrapped cells)."""
  parts = _polygons(shapely.make_valid(to_plane(geom)))
  if not parts:
    return []
  g = shapely.union_all(parts)
  pieces = valid_polygons(subdivide(g))  # clip_by_rect can leave invalid rings, so once per place, not per cell
  return pieces + [shapely.affinity.translate(p, xoff=360) for p in pieces]


# cells in the plane ----

def _pole_cells(res: int) -> set:
  return {h3.latlng_to_cell(90, 0, res), h3.latlng_to_cell(-90, 0, res)}


def cell_ring(cell: str, poles: set) -> np.ndarray:
  """a cell's ring in the plane, longitudes unwrapped to start in [-180, 180]; around a pole, closed along it."""
  b = np.array(h3.cell_to_boundary(cell))  # (lat, lng)
  x, y = b[:, 1].copy(), np.sin(np.radians(b[:, 0]))
  if cell in poles:
    d = (np.diff(x) + 180) % 360 - 180
    x = x[0] + np.concatenate([[0], np.cumsum(d)])
    if x[-1] < x[0]:
      x, y = x[::-1].copy(), y[::-1].copy()
    if x.min() < -180:
      x += 360 * np.ceil((-180 - x.min()) / 360)
    cap = 1.0 if b[:, 0].mean() > 0 else -1.0
    x = np.concatenate([x, [x[0] + 360, x[0] + 360, x[0]]])
    y = np.concatenate([y, [y[0], cap, cap]])
  elif x.max() - x.min() > 180:
    x[x < 0] += 360
  return np.column_stack([x, y])


def cell_polygons(cells, res: int) -> np.ndarray:
  poles = _pole_cells(res)
  return np.array([shapely.Polygon(cell_ring(c, poles)) for c in cells], dtype=object)


def _warn(warnings, place_id, cell, reason):
  if warnings is not None:
    warnings.append({"place_id": place_id, "cell": cell, "reason": reason})


def _overlap_areas(polys, ci, pj, pieces, cells, warnings=None, place_id=None) -> np.ndarray:
  """area of each (cell, piece) pair's intersection. if GEOS raises, redo pair by pair: retry with both buffered by 0,
  then the centre-in rule for the cell (all its area when its centre lies in a piece, else none); each is a warning."""
  ps = np.asarray(pieces, dtype=object)[pj]
  try:
    return shapely.area(shapely.intersection(polys[ci], ps))
  except GEOSException:
    pass
  a = np.zeros(len(ci))
  hard: dict[int, str] = {}  # cell index -> the GEOS message of the failure buffer(0) did not cure
  soft: dict[int, str] = {}
  for k, (i, p) in enumerate(zip(ci, ps)):
    try:
      a[k] = shapely.area(shapely.intersection(polys[i], p))
      continue
    except GEOSException as e:
      first = str(e)
    try:
      a[k] = shapely.area(shapely.intersection(shapely.buffer(polys[i], 0), shapely.buffer(p, 0)))
      soft[i] = first
    except GEOSException as e:
      hard[i] = str(e)
  for i, msg in soft.items():
    if i not in hard:
      _warn(warnings, place_id, str(cells[i]), f"intersection raised ({msg}); recomputed with the cell and place buffered by 0")
  for i, msg in hard.items():
    centre = shapely.centroid(polys[i])
    inside = any(bool(shapely.contains(pieces[j], centre)) for j in pj[ci == i])
    a[ci == i] = 0
    if inside:
      a[np.flatnonzero(ci == i)[0]] = polys[i].area
    _warn(warnings, place_id, str(cells[i]),
          f"intersection raised ({msg}) and buffer(0) did not cure it; centre-in rule: {'share 1' if inside else 'dropped'}")
  return a


def cell_shares(cells, res: int, pieces: list, tree: STRtree, warnings: list | None = None,
                place_id: str | None = None) -> tuple[np.ndarray, np.ndarray]:
  """(share of each cell's area inside the place (0..1), each cell's area in the plane). `pieces` should be valid
  (place_pieces makes them so); a cell whose intersection still raises is handled as in _overlap_areas and appended
  to `warnings` as {place_id, cell, reason}."""
  if not len(cells):
    return np.zeros(0), np.zeros(0)
  polys = cell_polygons(cells, res)
  ci, pj = tree.query(polys)
  inter = np.zeros(len(cells))
  if len(ci):
    a = _overlap_areas(polys, ci, pj, pieces, cells, warnings, place_id)
    inter = np.bincount(ci, weights=a, minlength=len(cells))
  area = shapely.area(polys)
  return np.clip(inter / area, 0, 1), area


# the refinement ----

def place_membership(geom, res_max: int = RES_MAX, min_share: float = MIN_SHARE, warnings: list | None = None,
                     place_id: str | None = None) -> dict[int, tuple[np.ndarray, np.ndarray]]:
  """{res: (cells, shares)} for res 1..res_max, sorted by cell: every cell with share >= min_share or holding
  >= min_share of the place's area. cells that needed a fallback are appended to `warnings` (see cell_shares)."""
  pieces = place_pieces(geom)
  out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
  if not pieces:
    return out
  tree = STRtree(pieces)
  place_area = sum(p.area for p in pieces) / 2  # the pieces hold the place twice (as is and shifted by 360)
  cand = np.array(sorted(h3.get_res0_cells()))
  deep: list = []  # inside without a test (children of inside cells whose neighbours are all inside)
  for res in range(0, res_max + 1):
    share, area = cell_shares(cand, res, pieces, tree, warnings, place_id)
    if res >= 1:
      keep = (share > 0) & ((share >= min_share) | (share * area >= min_share * place_area))
      cells = np.concatenate([np.array(deep, dtype=object), cand[keep].astype(object)])
      shares = np.concatenate([np.ones(len(deep)), share[keep]])
      order = np.argsort(cells.astype(str), kind="stable")
      out[res] = (cells[order].astype(str), shares[order])
    if res == res_max:
      break
    inside = set(deep) | set(cand[share >= INSIDE])
    edge = set(cand[(share > 0) & (share < INSIDE)])
    parents, deep_next = set(edge), []
    for c in inside:
      if all(n in inside for n in h3.grid_disk(c, 1)):
        deep_next.extend(h3.cell_to_children(c))
      else:
        parents.add(c)
    for c in edge:
      parents.update(h3.grid_disk(c, 1))
    deep_set = set(deep_next)
    nxt = {k for p in parents for k in h3.cell_to_children(p)} - deep_set
    cand, deep = np.array(sorted(nxt), dtype=object), deep_next
  return out


# the compact store ----

_HEX = np.frombuffer(b"0123456789abcdef", dtype=np.uint8)
_NIBBLES = np.arange(56, -1, -4, dtype=np.uint64)  # the 15 hex digits of a cell index (the top nibble is always 0)


def cells_to_u64(cells) -> np.ndarray:
  return np.array([h3.str_to_int(c) for c in cells], dtype=np.uint64)


def u64_to_cells(cells: np.ndarray) -> pa.Array:
  """H3 indexes -> an Arrow string array of their 15 hex digits (what h3.int_to_str gives), without a Python loop."""
  cells = np.asarray(cells, dtype=np.uint64)
  n = len(cells)
  chars = np.ascontiguousarray(_HEX[((cells[:, None] >> _NIBBLES) & np.uint64(15)).astype(np.uint8)])
  offsets = np.arange(n + 1, dtype=np.int32) * 15
  return pa.Array.from_buffers(pa.string(), n, [None, pa.py_buffer(offsets), pa.py_buffer(chars)])


def parent_u64(cells: np.ndarray, res: int) -> np.ndarray:
  """the res-`res` parent of H3 indexes: the resolution field set to `res`, the digits below it set to 7."""
  cells = np.asarray(cells, dtype=np.uint64)
  return (cells & ~(np.uint64(0xF) << np.uint64(52))) | (np.uint64(res) << np.uint64(52)) \
         | np.uint64((1 << (3 * (15 - res))) - 1)


class Membership:
  """the membership of a collection: per res, one (place index, cells, shares) entry per place (or run of one place),
  in place_id, h3 order; cells are uint64 H3 indexes sorted ascending (the order of their strings), shares float32."""

  def __init__(self, res_max: int = RES_MAX):
    self.pids: list[str] = []
    self.entries: dict[int, list[tuple[int, np.ndarray, np.ndarray]]] = {r: [] for r in range(1, res_max + 1)}
    self._index: dict[str, int] = {}

  @property
  def res(self) -> list[int]:
    return sorted(self.entries)

  def add(self, pid: str, cells: np.ndarray, shares: np.ndarray, res: int) -> None:
    if not len(cells):
      return
    i = self._index.setdefault(pid, len(self.pids))
    if i == len(self.pids):
      self.pids.append(pid)
    self.entries[res].append((i, np.asarray(cells, dtype=np.uint64), np.asarray(shares, dtype=np.float32)))

  def rows(self, res: int) -> int:
    return sum(len(e[1]) for e in self.entries[res])

  def places(self) -> int:
    return len({e[0] for es in self.entries.values() for e in es})

  @classmethod
  def from_tables(cls, tables: dict[int, pa.Table]) -> "Membership":
    """a Membership from {res: table(place_id, h3, share)}: a run of equal place_ids is one entry."""
    mem = cls(0)
    for res, t in tables.items():
      mem.entries[res] = []
      ids = t.column("place_id").to_pylist()
      cells = cells_to_u64(t.column("h3").to_pylist())
      shares = t.column("share").to_numpy()
      starts = [0] + [k for k in range(1, len(ids)) if ids[k] != ids[k - 1]]
      for a, z in zip(starts, starts[1:] + [len(ids)]):
        mem.add(ids[a], cells[a:z], shares[a:z], res)
    return mem

  def table(self, res: int) -> pa.Table:
    """res's rows as one table (place_id, h3, share). a chunked table, so it can exceed what one string array holds,
    but it is all in memory: for tests and small collections, the writer does not use it."""
    parts = list(_blocks(self, res, _runs(self, res, None)[None] if self.entries[res] else []))
    return pa.concat_tables(parts) if parts else SCHEMA.empty_table()


def _runs(mem: Membership, res: int, parent_res: int | None) -> dict:
  """{parent (None, or its uint64 index): [(entry, start, stop)]} for the entries of res, parents ascending; within a
  parent the runs are in entry order, so the rows keep their place_id, h3 order."""
  if parent_res is None:
    return {None: [(k, 0, len(e[1])) for k, e in enumerate(mem.entries[res])]}
  out: dict[int, list] = {}
  for k, (_, cells, _) in enumerate(mem.entries[res]):
    par = parent_u64(cells, parent_res)
    if len(par) > 1 and not (par[1:] >= par[:-1]).all():
      raise ValueError("cells of a place must be sorted to be split by parent")
    keys, starts = np.unique(par, return_index=True)
    for key, a, z in zip(keys.tolist(), starts.tolist(), starts[1:].tolist() + [len(par)]):
      out.setdefault(key, []).append((k, a, z))
  return dict(sorted(out.items()))


def _blocks(mem: Membership, res: int, runs: list):
  """tables (place_id, h3, share) of about BLOCK_ROWS rows each, from runs [(entry, start, stop)] in order."""
  pids = pa.array(mem.pids, pa.string())
  buf: list = []
  n = 0

  def flush():
    idx = np.concatenate([np.full(z - a, mem.entries[res][k][0], dtype=np.int32) for k, a, z in buf])
    cells = np.concatenate([mem.entries[res][k][1][a:z] for k, a, z in buf])
    shares = np.concatenate([mem.entries[res][k][2][a:z] for k, a, z in buf])
    place = pa.DictionaryArray.from_arrays(pa.array(idx), pids).dictionary_decode()  # place_id made plain, per block
    return pa.table({"place_id": place, "h3": u64_to_cells(cells), "share": pa.array(shares)}, schema=SCHEMA)

  for k, a, z in runs:
    for s in range(a, z, BLOCK_ROWS):  # a run longer than a block is cut
      e = min(s + BLOCK_ROWS, z)
      buf.append((k, s, e))
      n += e - s
      if n >= BLOCK_ROWS:
        yield flush()
        buf, n = [], 0
  if buf:
    yield flush()


def _one_place(args) -> tuple[str, dict, list]:
  """(place_id, {res: (cells as uint64, shares as float32)}, warnings); a place that fails outright is empty, with a
  warning saying why."""
  pid, wkbs, res_max, min_share = args
  warns: list = []
  try:
    gs = list(shapely.from_wkb(wkbs))
    g = gs[0] if len(gs) == 1 else shapely.union_all(gs)
    out = place_membership(g, res_max, min_share, warns, pid)
    return pid, {r: (cells_to_u64(c), s.astype(np.float32)) for r, (c, s) in out.items()}, warns
  except Exception as e:  # one place must never abort the collection
    return pid, {}, warns + [{"place_id": pid, "cell": None, "reason": f"place skipped: {type(e).__name__}: {e}"}]


def compute_membership(table: pa.Table, res_max: int = RES_MAX, min_share: float = MIN_SHARE,
                       workers: int = 1, warnings: list | None = None) -> Membership:
  """the Membership of the polygon places of a collection table (place_id + WKB geometry).

  rows sorted by place_id, h3; a place may have several rows in the table (components): their geometries are unioned.
  `workers` > 1 computes places in that many processes (the result is identical). cells that needed a fallback, and
  places skipped after an error, are printed and appended to `warnings` as {place_id, cell, reason}.
  """
  ids = table.column("place_id").to_pylist()
  geoms = shapely.from_wkb(np.array(table.column("geometry").to_pylist(), dtype=object))
  by_id: dict[str, list] = {}
  for pid, g in zip(ids, geoms):
    if _polygons(g):
      by_id.setdefault(pid, []).append(g)
  mem = Membership(res_max)
  jobs = [(pid, [shapely.to_wkb(g) for g in by_id[pid]], res_max, min_share) for pid in sorted(by_id)]
  if workers > 1 and len(jobs) > 1:
    # big places first, so one giant does not start last
    order = sorted(range(len(jobs)), key=lambda i: -sum(len(w) for w in jobs[i][1]))
    with ProcessPoolExecutor(workers) as ex:
      done = {r[0]: r for r in ex.map(_one_place, [jobs[i] for i in order], chunksize=1)}
    results = (done.pop(pid) for pid, *_ in jobs)
  else:
    results = map(_one_place, jobs)
  found: list = []
  for pid, out, warns in results:
    found.extend(warns)
    for res, (cells, shares) in out.items():
      mem.add(pid, cells, shares, res)
  if found:
    print(f"  warnings: {len(found)} in {len({w['place_id'] for w in found})} place(s)", flush=True)
    for w in found[:20]:
      print(f"    {w['place_id']} {w['cell'] or '-'}: {w['reason']}"[:300], flush=True)
    if len(found) > 20:
      print(f"    ... {len(found) - 20} more (all in membership.json)", flush=True)
  if warnings is not None:
    warnings.extend(found)
  return mem


def collection_membership(table: pa.Table, res_max: int = RES_MAX, min_share: float = MIN_SHARE,
                          workers: int = 1, warnings: list | None = None) -> dict[int, pa.Table]:
  """{res: table(place_id, h3, share)} for the polygon places of a collection table; see compute_membership. every
  table is in memory: for a big collection use compute_membership and write_membership."""
  mem = compute_membership(table, res_max, min_share, workers, warnings)
  return {r: mem.table(r) for r in mem.res}


# the files ----

def parent_of(cell: str, res: int) -> str:
  return h3.cell_to_parent(cell, res)


def _write_partition(f: Path, blocks, row_group_size: int) -> None:
  """write blocks (tables of SCHEMA) as one Parquet file whose row groups all hold row_group_size rows but the last,
  whatever the block sizes (what pq.write_table gives for the whole table)."""
  f.parent.mkdir(parents=True, exist_ok=True)
  carry = None
  with pq.ParquetWriter(f, SCHEMA, compression="zstd") as w:
    for t in blocks:
      if carry is not None:
        t = pa.concat_tables([carry, t]).combine_chunks()
      n = t.num_rows // row_group_size * row_group_size
      if n:
        w.write_table(t.slice(0, n), row_group_size=row_group_size)
      carry = t.slice(n) if n < t.num_rows else None
    if carry is not None:
      w.write_table(carry, row_group_size=row_group_size)


def write_membership(tables: "dict[int, pa.Table] | Membership", out_dir: Path, version: str,
                     parent_res: dict[int, int] = PARENT_RES, min_share: float = MIN_SHARE,
                     extra: dict | None = None) -> dict:
  """write h3/res=<r>/membership.parquet (res <= 5) and h3/res=<r>/p=<parent>/membership.parquet (split res) under
  out_dir, and h3/membership.json describing them (plus `extra`, e.g. what it was built from); returns that manifest.
  each file is written from its own rows, BLOCK_ROWS at a time, so no table of a whole res is ever built."""
  mem = tables if isinstance(tables, Membership) else Membership.from_tables(tables)
  root = Path(out_dir) / "h3"
  manifest = {"version": version, "min_share": min_share, "columns": ["place_id", "h3", "share"],
              "share": "fraction of the cell's area inside the place (equal-area plane), float32",
              "res": mem.res, "parent_res": {str(k): v for k, v in parent_res.items() if k in mem.entries},
              "files": []}
  parents: set = set()  # which split files hold each place: (place_id, res, parent), so a reader finds them without the others
  for res in mem.res:
    runs = _runs(mem, res, parent_res.get(res))
    for p, rs in runs.items():
      ps = None if p is None else u64_to_cells(np.array([p], dtype=np.uint64))[0].as_py()
      rel = f"h3/res={res}/membership.parquet" if ps is None else f"h3/res={res}/p={ps}/membership.parquet"
      f = Path(out_dir) / rel
      if rs:
        _write_partition(f, _blocks(mem, res, rs), ROW_GROUP)
      else:  # a res with no rows still gets its (empty) file
        f.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(SCHEMA.empty_table(), f, compression="zstd", row_group_size=ROW_GROUP)
      who = {mem.entries[res][k][0] for k, _, _ in rs}
      manifest["files"].append({"res": res, "parent": ps, "path": rel, "rows": sum(z - a for _, a, z in rs),
                                "places": len(who), "bytes": f.stat().st_size})
      if ps is not None:
        parents.update((mem.pids[i], res, ps) for i in who)
  idx = sorted(parents)
  pq.write_table(pa.table({"place_id": [i[0] for i in idx], "res": pa.array([i[1] for i in idx], pa.int8()),
                           "parent": [i[2] for i in idx]}), root / "parents.parquet", compression="zstd")
  manifest["parents"] = "h3/parents.parquet"
  manifest["rows"] = sum(x["rows"] for x in manifest["files"])
  manifest["bytes"] = sum(x["bytes"] for x in manifest["files"])
  manifest.update(extra or {})
  (root / "membership.json").write_text(json.dumps(manifest, indent=2) + "\n")
  return manifest
