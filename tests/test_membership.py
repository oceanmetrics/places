"""gazetteer/membership.py: place x H3 cells with the share of each cell inside, on synthetic places."""
import json

import h3
import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from gazetteer import membership as m


def square(x0, y0, size=1.0):
  return Polygon([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)])


def weighted_area(cells, shares, res):
  """sum of share x cell area in the equal-area plane."""
  return float(np.sum(shares * shapely.area(m.cell_polygons(cells, res))))


def test_shares_add_up_to_the_place_area():
  g = square(-121, 34, 1.0)
  out = m.place_membership(g, res_max=5, min_share=0)
  true = m.to_plane(g).area
  for res, (cells, shares) in out.items():
    assert weighted_area(cells, shares, res) == pytest.approx(true, rel=1e-9), res
    assert (shares > 0).all() and (shares <= 1).all()


def test_a_cell_as_a_place_is_that_cell_with_share_one():
  cell = h3.latlng_to_cell(34.5, -120.5, 4)
  g = Polygon([(lng, lat) for lat, lng in h3.cell_to_boundary(cell)])
  cells, shares = m.place_membership(g, res_max=4)[4]
  assert dict(zip(cells, shares))[cell] == pytest.approx(1, abs=1e-9)
  assert weighted_area(cells, shares, 4) == pytest.approx(m.to_plane(g).area, rel=1e-6)


def test_inside_cells_have_share_one_and_edge_cells_less():
  cells, shares = m.place_membership(square(-125, 30, 4.0), res_max=4)[4]
  centre = h3.latlng_to_cell(32, -123, 4)
  assert dict(zip(cells, shares))[centre] == 1
  assert (shares < 1).any()


def test_a_sliver_under_one_percent_of_the_cell_and_of_the_place_is_dropped():
  g = square(-125, 30, 4.0)
  full = dict(zip(*m.place_membership(g, res_max=5, min_share=0)[5]))
  kept = dict(zip(*m.place_membership(g, res_max=5)[5]))
  dropped = set(full) - set(kept)
  assert dropped and all(full[c] < m.MIN_SHARE for c in dropped)
  assert all(kept[c] >= m.MIN_SHARE for c in kept)  # in a large place, the cell rule alone decides


def test_a_place_smaller_than_one_percent_of_a_coarse_cell_keeps_the_cells_it_touches():
  g = square(-120.05, 34.0, 0.1)  # ~100 km2, a res-1 cell is ~600,000 km2
  cells, shares = m.place_membership(g, res_max=2)[1]
  assert len(cells) >= 1 and shares.max() < m.MIN_SHARE
  assert weighted_area(cells, shares, 1) == pytest.approx(m.to_plane(g).area, rel=0.01)


def test_cells_are_sorted_and_unique():
  for cells, _ in m.place_membership(square(-121, 34, 1.0), res_max=5).values():
    assert list(cells) == sorted(set(cells))


def test_antimeridian_split_place_is_whole_and_counted_once():
  # a 1-degree square across 180, stored as two parts (179.5..180 and -180..-179.5)
  g = MultiPolygon([square(179.5, -10, 0.5), Polygon([(-180, -10), (-179.5, -10), (-179.5, -9), (-180, -9), (-180, -10)])])
  out = m.place_membership(g, res_max=4, min_share=0)
  true = m.to_plane(g).area
  for res, (cells, shares) in out.items():
    assert weighted_area(cells, shares, res) == pytest.approx(true, rel=1e-6), res
    assert len(cells) == len(set(cells))


def test_a_place_inside_the_polar_cell_is_found():
  g = square(10, 82, 5.0)
  out = m.place_membership(g, res_max=3, min_share=0)
  true = m.to_plane(g).area
  for res, (cells, shares) in out.items():
    assert weighted_area(cells, shares, res) == pytest.approx(true, rel=1e-6), res


def test_points_and_lines_have_no_membership():
  assert m.place_membership(Point(0, 0)) == {}
  assert m.place_membership(LineString([(0, 0), (1, 1)])) == {}


def collection(rows):
  return pa.table({"place_id": [r[0] for r in rows], "geometry": [shapely.to_wkb(r[1]) for r in rows]})


def test_collection_membership_unions_components_and_skips_lines():
  t = collection([("t:b", square(-121, 34, 0.5)), ("t:a", square(-120, 34, 0.5)), ("t:a", square(-119.5, 34, 0.5)),
                  ("t:line", LineString([(0, 0), (1, 1)]))])
  out = m.collection_membership(t, res_max=4)
  t4 = out[4]
  assert t4.schema == m.SCHEMA
  ids = t4.column("place_id").to_pylist()
  assert ids == sorted(ids) and set(ids) == {"t:a", "t:b"}
  a = t4.filter(pc.equal(t4.column("place_id"), "t:a"))
  whole = dict(zip(*m.place_membership(shapely.box(-120, 34, -119, 34.5), res_max=4)[4]))
  got = dict(zip(a.column("h3").to_pylist(), a.column("share").to_pylist()))
  assert got.keys() == whole.keys()
  assert all(got[c] == pytest.approx(whole[c], abs=1e-6) for c in got)


def test_workers_give_the_same_result():
  t = collection([("t:b", square(-121, 34, 0.5)), ("t:a", square(-110, 20, 0.7)), ("t:c", square(150, -30, 0.2))])
  one, many = m.collection_membership(t, res_max=5), m.collection_membership(t, res_max=5, workers=2)
  assert all(one[r].equals(many[r]) for r in one)


def test_write_membership_splits_res_6_and_7_by_parent(tmp_path):
  t = collection([("t:a", square(-121, 34, 0.3)), ("t:b", square(-110, 20, 0.3))])
  man = m.write_membership(m.collection_membership(t, res_max=7), tmp_path, version="1.2.3")
  assert man["res"] == [1, 2, 3, 4, 5, 6, 7] and man["parent_res"] == {"6": 2, "7": 3}
  assert json.loads((tmp_path / "h3" / "membership.json").read_text()) == man
  by_res = {}
  for f in man["files"]:
    by_res.setdefault(f["res"], []).append(f)
    tb = pq.read_table(tmp_path / f["path"])
    assert tb.num_rows == f["rows"] and tb.schema.equals(m.SCHEMA)
    if f["res"] in (6, 7):
      assert f["path"] == f"h3/res={f['res']}/p={f['parent']}/membership.parquet"
      assert {h3.cell_to_parent(c, m.PARENT_RES[f["res"]]) for c in tb.column("h3").to_pylist()} == {f["parent"]}
    else:
      assert f["parent"] is None and f["path"] == f"h3/res={f['res']}/membership.parquet"
  assert len(by_res[5]) == 1 and len(by_res[7]) >= 2  # two places far apart: two res-3 parents at least
  assert man["rows"] == sum(f["rows"] for f in man["files"])
  par = pq.read_table(tmp_path / man["parents"]).to_pylist()
  want = {(r["place_id"], f["res"], f["parent"]) for f in man["files"] if f["parent"]
          for r in pq.read_table(tmp_path / f["path"]).to_pylist()}
  assert {(r["place_id"], r["res"], r["parent"]) for r in par} == want and len(par) == len(want)


# regressions: noaa_efh, 2026-10-22, "unable to assign free hole to a shell" killed the whole --missing run ----

def bowtie_with_hole(x0=-180.0, y0=0.0):
  """an invalid polygon (a bowtie, so a self-intersecting shell, with a hole in one lobe) just east of the antimeridian;
  the cells that cross it are matched against its copy shifted by +360."""
  return Polygon([(x0, y0), (x0 + 10, y0 + 10), (x0 + 10, y0), (x0, y0 + 10), (x0, y0)],
                 [[(x0 + 1, y0 + 4), (x0 + 2.5, y0 + 4), (x0 + 2.5, y0 + 6), (x0 + 1, y0 + 6), (x0 + 1, y0 + 4)]])


def test_regression_free_hole_antimeridian_lobe(monkeypatch):
  bow = m.to_plane(bowtie_with_hole())
  assert not shapely.is_valid(bow)
  # clip_by_rect hands back such a piece for a valid place; both the piece and its +360 copy must not reach GEOS invalid
  monkeypatch.setattr(m, "subdivide", lambda g, max_vertices=m.MAX_VERTICES: [bow])
  cells = np.array(sorted({h3.latlng_to_cell(la, lo, 3) for la in np.arange(-2, 12, 0.5) for lo in np.arange(-185, -165, 0.5)}))
  polys = m.cell_polygons(cells, 3)
  shifted = shapely.affinity.translate(bow, xoff=360)  # the lobe as the antimeridian cells see it, x ~ 180..190
  assert any(shapely.intersects(polys, shifted))
  with pytest.raises(shapely.errors.GEOSException):  # the bug: the intersection raises on the invalid piece
    shapely.intersection(polys, np.full(len(polys), shifted, dtype=object))
  geom = shapely.make_valid(bowtie_with_hole())
  pieces = m.place_pieces(geom)
  assert pieces and all(shapely.is_valid(p) for p in pieces)
  warnings = []
  out = m.place_membership(geom, res_max=4, min_share=0, warnings=warnings)
  true = shapely.make_valid(bow).area
  for res, (cs, shares) in out.items():
    assert weighted_area(cs, shares, res) == pytest.approx(true, rel=1e-9), res
  assert warnings == []  # made valid once per place, so no cell needed a fallback


def test_a_raising_cell_is_retried_buffered_then_given_the_centre_rule(monkeypatch):
  g = square(-121, 34, 1.0)
  clean = dict(zip(*m.place_membership(g, res_max=4, min_share=0)[4]))
  real = shapely.intersection
  calls = {"n": 0}

  def raise_once(a, b, **kw):  # the vectorised call raises, then the per-cell retry works
    calls["n"] += 1
    if calls["n"] == 1:
      raise shapely.errors.GEOSException("TopologyException: unable to assign free hole to a shell")
    return real(a, b, **kw)

  monkeypatch.setattr(shapely, "intersection", raise_once)
  w1 = []
  once = dict(zip(*m.place_membership(g, res_max=4, min_share=0, warnings=w1, place_id="t:a")[4]))
  assert once.keys() == clean.keys() and all(once[c] == pytest.approx(clean[c], abs=1e-9) for c in once)

  def always(a, b, **kw):
    raise shapely.errors.GEOSException("TopologyException: unable to assign free hole to a shell")

  monkeypatch.setattr(shapely, "intersection", always)
  w2 = []
  centre = dict(zip(*m.place_membership(g, res_max=4, min_share=0, warnings=w2, place_id="t:a")[4]))
  assert set(centre.values()) <= {1.0}  # cells are in or out by their centre
  assert all(w["place_id"] == "t:a" and "centre-in rule" in w["reason"] and w["cell"] for w in w2)
  inside = {w["cell"] for w in w2 if "share 1" in w["reason"]}
  assert inside == set(centre)
  assert len(w2) > len(centre)  # the dropped cells are listed too


def test_one_bad_place_does_not_abort_the_collection(monkeypatch):
  real = m.cell_shares

  def flaky(cells, res, pieces, tree, warnings=None, place_id=None):
    if place_id == "t:b":
      raise shapely.errors.GEOSException("TopologyException: unable to assign free hole to a shell at 201.0 0.8")
    return real(cells, res, pieces, tree, warnings, place_id)

  monkeypatch.setattr(m, "cell_shares", flaky)
  t = collection([("t:a", square(-121, 34, 0.5)), ("t:b", square(-110, 20, 0.5)), ("t:c", square(150, -30, 0.2))])
  warnings = []
  out = m.collection_membership(t, res_max=4, warnings=warnings)
  assert set(out[4].column("place_id").to_pylist()) == {"t:a", "t:c"}
  assert [(w["place_id"], w["cell"]) for w in warnings] == [("t:b", None)]
  assert "place skipped" in warnings[0]["reason"] and "GEOSException" in warnings[0]["reason"]


def test_warnings_are_written_into_membership_json(tmp_path):
  t = collection([("t:a", square(-121, 34, 0.3))])
  w = [{"place_id": "t:a", "cell": "8429a1dffffffff", "reason": "x"}]
  man = m.write_membership(m.collection_membership(t, res_max=4), tmp_path, version="1", extra={"warnings": w})
  assert json.loads((tmp_path / "h3" / "membership.json").read_text())["warnings"] == w == man["warnings"]


# the writer works a partition at a time ----

def write_membership_global(tables, out_dir, version, parent_res=m.PARENT_RES, min_share=m.MIN_SHARE, extra=None,
                            row_group_size=65536):
  """the writer before 2026-10-22, kept as the reference: one global take per partition, on whole-res tables."""
  root = out_dir / "h3"
  manifest = {"version": version, "min_share": min_share, "columns": ["place_id", "h3", "share"],
              "share": "fraction of the cell's area inside the place (equal-area plane), float32",
              "res": sorted(tables), "parent_res": {str(k): v for k, v in parent_res.items() if k in tables},
              "files": []}
  for res, t in sorted(tables.items()):
    if res in parent_res:
      parents = np.array([h3.cell_to_parent(c, parent_res[res]) for c in t.column("h3").to_pylist()])
      order = np.argsort(parents, kind="stable")
      keys, starts = np.unique(parents[order], return_index=True)
      groups = {str(k): order[a:z] for k, a, z in zip(keys, starts, list(starts[1:]) + [len(order)])}
    else:
      groups = {None: np.arange(t.num_rows)}
    for p, idx in groups.items():
      part = t.take(pa.array(idx))
      rel = f"h3/res={res}/membership.parquet" if p is None else f"h3/res={res}/p={p}/membership.parquet"
      f = out_dir / rel
      f.parent.mkdir(parents=True, exist_ok=True)
      pq.write_table(part, f, compression="zstd", row_group_size=row_group_size)
      manifest["files"].append({"res": res, "parent": p, "path": rel, "rows": part.num_rows,
                                "places": len(set(part.column("place_id").to_pylist())), "bytes": f.stat().st_size})
  idx = sorted({(pid, res, h3.cell_to_parent(c, parent_res[res])) for res, t in tables.items() if res in parent_res
                for pid, c in zip(t.column("place_id").to_pylist(), t.column("h3").to_pylist())})
  pq.write_table(pa.table({"place_id": [i[0] for i in idx], "res": pa.array([i[1] for i in idx], pa.int8()),
                           "parent": [i[2] for i in idx]}), root / "parents.parquet", compression="zstd")
  manifest["parents"] = "h3/parents.parquet"
  manifest["rows"] = sum(x["rows"] for x in manifest["files"])
  manifest["bytes"] = sum(x["bytes"] for x in manifest["files"])
  manifest.update(extra or {})
  (root / "membership.json").write_text(json.dumps(manifest, indent=2) + "\n")
  return manifest


def synthetic_collection():
  return collection([("t:b", square(-121, 34, 0.4)), ("t:a", square(-120, 34, 0.3)), ("t:a", square(-119.5, 34, 0.3)),
                     ("t:c", square(-60, -30, 0.5)), ("t:d", square(150, -30, 0.2)), ("t:line", LineString([(0, 0), (1, 1)]))])


def assert_same_files(man_a, man_b, dir_a, dir_b):
  assert man_a == man_b
  for rel in ["h3/parents.parquet", "h3/membership.json"] + [f["path"] for f in man_a["files"]]:
    assert (dir_a / rel).read_bytes() == (dir_b / rel).read_bytes(), rel


def test_u64_cells_are_the_strings_of_h3_and_parents_are_h3_parents():
  cells = sorted(set(h3.get_res0_cells()) | set(h3.cell_to_children("8029fffffffffff", 3)) | set(_pole_children()))
  u = m.cells_to_u64(cells)
  assert m.u64_to_cells(u).to_pylist() == cells
  for res in (7, 3):
    kids = sorted({k for c in cells[:40:8] for k in h3.cell_to_children(h3.cell_to_children(c, 2)[3], res)}
                  | set(_pole_children(res)))
    uk = m.cells_to_u64(kids)
    for pr in (1, 2, 3):
      if pr < res:
        assert m.u64_to_cells(m.parent_u64(uk, pr)).to_pylist() == [h3.cell_to_parent(c, pr) for c in kids]


def _pole_children(res=3):
  return [h3.latlng_to_cell(90, 0, res), h3.latlng_to_cell(-90, 0, res), h3.latlng_to_cell(0, 180, res)]


def test_the_written_partitions_read_back_with_the_previous_schema(tmp_path):
  t = synthetic_collection()
  tables = m.collection_membership(t, res_max=7)
  man = m.write_membership(m.compute_membership(t, res_max=7), tmp_path / "new", version="1")
  write_membership_global(tables, tmp_path / "old", version="1")
  for f in man["files"]:
    new, old = pq.ParquetFile(tmp_path / "new" / f["path"]), pq.ParquetFile(tmp_path / "old" / f["path"])
    assert new.schema_arrow.equals(old.schema_arrow) and new.schema_arrow.equals(m.SCHEMA)
    assert pq.read_table(tmp_path / "new" / f["path"]).schema.equals(m.SCHEMA)  # place_id plain string, not dictionary
    assert new.schema.to_arrow_schema().field("place_id").type == pa.string()
    assert new.schema.equals(old.schema)  # the Parquet physical schema too


def test_regression_write_membership_offset_overflow(tmp_path, monkeypatch):
  """protectedseas_fisheries (2026-10-22): the global `take` over a whole res of that layer failed with "offset overflow
  while concatenating arrays" (more than 2 GB of string offsets in one column). the writer now builds each partition from
  its own rows, BLOCK_ROWS at a time; with BLOCK_ROWS and the row group tiny it takes that path on every partition (many
  blocks per file, runs cut, rows carried between blocks) and must write the files the global take wrote."""
  t = synthetic_collection()
  tables = m.collection_membership(t, res_max=7)
  assert max(tb.num_rows for tb in tables.values()) > 200
  monkeypatch.setattr(m, "BLOCK_ROWS", 7)
  monkeypatch.setattr(m, "ROW_GROUP", 50)
  for src, name in ((m.compute_membership(t, res_max=7), "compact"), (tables, "tables")):
    got = m.write_membership(src, tmp_path / name, version="1", extra={"warnings": []})
    want = write_membership_global(tables, tmp_path / ("ref_" + name), version="1", extra={"warnings": []},
                                   row_group_size=50)
    assert_same_files(got, want, tmp_path / name, tmp_path / ("ref_" + name))
    assert any(pq.ParquetFile(tmp_path / name / f["path"]).num_row_groups > 1 for f in got["files"])


def test_write_membership_with_the_default_sizes_equals_the_global_take(tmp_path):
  t = synthetic_collection()
  tables = m.collection_membership(t, res_max=7)
  got = m.write_membership(m.compute_membership(t, res_max=7), tmp_path / "new", version="1")
  want = write_membership_global(tables, tmp_path / "old", version="1")
  assert_same_files(got, want, tmp_path / "new", tmp_path / "old")


def test_membership_counts_rows_and_places():
  mem = m.compute_membership(synthetic_collection(), res_max=5)
  tables = m.collection_membership(synthetic_collection(), res_max=5)
  assert all(mem.rows(r) == tables[r].num_rows for r in mem.res)
  assert mem.places() == 4 and mem.res == [1, 2, 3, 4, 5]
