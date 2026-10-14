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

MIN_SHARE = 0.01
RES_MAX = 7
PARENT_RES = {6: 2, 7: 3}  # res 6 and 7 are split by these parents, as the obis-h3 release splits them
MAX_VERTICES = 256         # a place is cut into pieces of at most this many vertices before cells are intersected
INSIDE = 1 - 1e-9

SCHEMA = pa.schema([("place_id", pa.string()), ("h3", pa.string()), ("share", pa.float32())])


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
  pieces = subdivide(g)
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


def cell_shares(cells, res: int, pieces: list, tree: STRtree) -> tuple[np.ndarray, np.ndarray]:
  """(share of each cell's area inside the place (0..1), each cell's area in the plane)."""
  if not len(cells):
    return np.zeros(0), np.zeros(0)
  polys = cell_polygons(cells, res)
  ci, pj = tree.query(polys)
  inter = np.zeros(len(cells))
  if len(ci):
    a = shapely.area(shapely.intersection(polys[ci], np.asarray(pieces, dtype=object)[pj]))
    inter = np.bincount(ci, weights=a, minlength=len(cells))
  area = shapely.area(polys)
  return np.clip(inter / area, 0, 1), area


# the refinement ----

def place_membership(geom, res_max: int = RES_MAX, min_share: float = MIN_SHARE) -> dict[int, tuple[np.ndarray, np.ndarray]]:
  """{res: (cells, shares)} for res 1..res_max, sorted by cell: every cell with share >= min_share or holding
  >= min_share of the place's area."""
  pieces = place_pieces(geom)
  out: dict[int, tuple[np.ndarray, np.ndarray]] = {}
  if not pieces:
    return out
  tree = STRtree(pieces)
  place_area = sum(p.area for p in pieces) / 2  # the pieces hold the place twice (as is and shifted by 360)
  cand = np.array(sorted(h3.get_res0_cells()))
  deep: list = []  # inside without a test (children of inside cells whose neighbours are all inside)
  for res in range(0, res_max + 1):
    share, area = cell_shares(cand, res, pieces, tree)
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


def _one_place(args) -> tuple[str, dict]:
  pid, wkbs, res_max, min_share = args
  gs = list(shapely.from_wkb(wkbs))
  g = gs[0] if len(gs) == 1 else shapely.union_all(gs)
  return pid, place_membership(g, res_max, min_share)


def collection_membership(table: pa.Table, res_max: int = RES_MAX, min_share: float = MIN_SHARE,
                          workers: int = 1) -> dict[int, pa.Table]:
  """{res: table(place_id, h3, share)} for the polygon places of a collection table (place_id + WKB geometry).

  rows sorted by place_id, h3; a place may have several rows in the table (components): their geometries are unioned.
  `workers` > 1 computes places in that many processes (the result is identical).
  """
  ids = table.column("place_id").to_pylist()
  geoms = shapely.from_wkb(np.array(table.column("geometry").to_pylist(), dtype=object))
  by_id: dict[str, list] = {}
  for pid, g in zip(ids, geoms):
    if _polygons(g):
      by_id.setdefault(pid, []).append(g)
  cols: dict[int, list] = {r: [[], [], []] for r in range(1, res_max + 1)}
  jobs = [(pid, [shapely.to_wkb(g) for g in by_id[pid]], res_max, min_share) for pid in sorted(by_id)]
  if workers > 1 and len(jobs) > 1:
    # big places first, so one giant does not start last
    order = sorted(range(len(jobs)), key=lambda i: -sum(len(w) for w in jobs[i][1]))
    with ProcessPoolExecutor(workers) as ex:
      done = dict(ex.map(_one_place, [jobs[i] for i in order], chunksize=1))
    results = [(pid, done[pid]) for pid, *_ in jobs]
  else:
    results = map(_one_place, jobs)
  for pid, out in results:
    for res, (cells, shares) in out.items():
      cols[res][0].extend([pid] * len(cells))
      cols[res][1].extend(cells.tolist())
      cols[res][2].extend(shares.tolist())
  return {r: pa.table({"place_id": c[0], "h3": c[1], "share": c[2]}, schema=SCHEMA) for r, c in cols.items()}


# the files ----

def parent_of(cell: str, res: int) -> str:
  return h3.cell_to_parent(cell, res)


def write_membership(tables: dict[int, pa.Table], out_dir: Path, version: str, parent_res: dict[int, int] = PARENT_RES,
                     min_share: float = MIN_SHARE, extra: dict | None = None) -> dict:
  """write h3/res=<r>/membership.parquet (res <= 5) and h3/res=<r>/p=<parent>/membership.parquet (split res) under
  out_dir, and h3/membership.json describing them (plus `extra`, e.g. what it was built from); returns that manifest."""
  root = Path(out_dir) / "h3"
  manifest = {"version": version, "min_share": min_share, "columns": ["place_id", "h3", "share"],
              "share": "fraction of the cell's area inside the place (equal-area plane), float32",
              "res": sorted(tables), "parent_res": {str(k): v for k, v in parent_res.items() if k in tables},
              "files": []}
  for res, t in sorted(tables.items()):
    if res in parent_res:
      parents = np.array([parent_of(c, parent_res[res]) for c in t.column("h3").to_pylist()])
      order = np.argsort(parents, kind="stable")  # stable: rows keep their place_id, h3 order within a parent
      keys, starts = np.unique(parents[order], return_index=True)
      groups = {str(k): order[a:z] for k, a, z in zip(keys, starts, list(starts[1:]) + [len(order)])}
    else:
      groups = {None: np.arange(t.num_rows)}
    for p, idx in groups.items():
      part = t.take(pa.array(idx))
      rel = f"h3/res={res}/membership.parquet" if p is None else f"h3/res={res}/p={p}/membership.parquet"
      f = Path(out_dir) / rel
      f.parent.mkdir(parents=True, exist_ok=True)
      pq.write_table(part, f, compression="zstd", row_group_size=65536)
      manifest["files"].append({"res": res, "parent": p, "path": rel, "rows": part.num_rows,
                                "places": len(set(part.column("place_id").to_pylist())), "bytes": f.stat().st_size})
  # which split files hold each place: (place_id, res, parent), so a reader finds a place's files without the others
  idx = [(pid, res, parent_of(c, parent_res[res])) for res, t in tables.items() if res in parent_res
         for pid, c in zip(t.column("place_id").to_pylist(), t.column("h3").to_pylist())]
  idx = sorted(set(idx))
  pq.write_table(pa.table({"place_id": [i[0] for i in idx], "res": pa.array([i[1] for i in idx], pa.int8()),
                           "parent": [i[2] for i in idx]}), root / "parents.parquet", compression="zstd")
  manifest["parents"] = "h3/parents.parquet"
  manifest["rows"] = sum(x["rows"] for x in manifest["files"])
  manifest["bytes"] = sum(x["bytes"] for x in manifest["files"])
  manifest.update(extra or {})
  (root / "membership.json").write_text(json.dumps(manifest, indent=2) + "\n")
  return manifest
