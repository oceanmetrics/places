import datetime as dt
import json

import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import Polygon

from conftest import lease_cfg, lease_result, square
from gazetteer.table import COMMON, build_rows, coerce, native_names, to_table, write_geoparquet
from gazetteer.validate import check_parquet


def build(tmp_path, rows=None):
  cfg = lease_cfg(tmp_path)
  rows = rows or [(71, "OCS-P 0561", "Commercial", "RWE", square(-124, 41)),
                  (500, "OCS-A 0497", "Easement", "VA DOE", square(-75, 36)),
                  (477, "OCS-A 0497", "Commercial", "VA DOE", square(-76, 36))]
  r, fields, dropped = build_rows(cfg, [lease_result(rows)])
  return cfg, r, fields, dropped, to_table(r, fields)


def test_common_columns_come_first_then_natives_then_bbox_and_geometry(tmp_path):
  _, _, _, _, t = build(tmp_path)
  assert t.column_names[:len(COMMON)] == COMMON
  assert t.column_names[-2:] == ["bbox", "geometry"]
  assert {"OBJECTID", "LEASE_NUMBER", "LEASE_TYPE", "COMPANY"} <= set(t.column_names)


def test_native_name_equal_to_a_common_column_ignoring_case_is_suffixed(tmp_path):
  _, rows, fields, _, t = build(tmp_path)
  assert native_names([{"name": "NAME"}, {"name": "STATE"}, {"name": "Version"}]) == {
    "NAME": "NAME_src", "STATE": "STATE", "Version": "Version_src"}
  assert "NAME_src" in t.column_names and "NAME" not in t.column_names
  assert len({c.lower() for c in t.column_names}) == t.num_columns          # DuckDB is case-insensitive
  assert rows[0]["name"].startswith("OCS-P 0561 Commercial - RWE")          # the derived name is not clobbered


def test_license_and_attribution_on_every_row(tmp_path):
  _, rows, _, _, t = build(tmp_path)
  assert set(t.column("license").to_pylist()) == {"CC-PDDC"}
  assert all(v == "BOEM test credit" for v in t.column("attribution").to_pylist())


def test_place_ids_unique_and_extra_polygon_suffixed(tmp_path):
  _, _, _, _, t = build(tmp_path)
  assert sorted(t.column("place_id").to_pylist()) == ["BOEM:OCS-A 0497", "BOEM:OCS-A 0497:easement", "BOEM:OCS-P 0561"]


def test_feature_without_a_polygon_is_dropped_and_reported(tmp_path):
  rows = [(1, "OCS-A 0001", "Commercial", "X", square(0, 0)), (2, "OCS-A 0002", "Commercial", "Y", None)]
  _, r, _, dropped, t = build(tmp_path, rows)
  assert t.num_rows == 1 and len(dropped) == 1 and "no polygon" in dropped[0]


def test_antimeridian_crossing_geometry_is_split_in_the_table(tmp_path):
  wrapped = Polygon([(170, 50), (-170, 50), (-170, 60), (170, 60), (170, 50)])
  _, _, _, _, t = build(tmp_path, [(1, "OCS-A 0001", "Commercial", "X", wrapped)])
  g = shapely.from_wkb(t.column("geometry").to_pylist())[0]
  assert g.geom_type == "MultiPolygon" and len(g.geoms) == 2 and g.bounds[0] == -180 and g.bounds[2] == 180


def test_esri_epoch_ms_becomes_a_utc_timestamp_and_numbers_are_coerced():
  assert coerce(686534400000, "date") == dt.datetime(1991, 10, 4, 0, 0, tzinfo=dt.timezone.utc)
  assert coerce(-55296000000, "date").year == 1968
  assert coerce("12", "int") == 12 and coerce(float("nan"), "float") is None and coerce(None, "string") is None


def test_geoparquet_roundtrip_is_valid_geoparquet_1_1(tmp_path):
  cfg, _, _, _, t = build(tmp_path)
  path = tmp_path / "places.parquet"
  geo = write_geoparquet(t, path, {"sources": [], "slug": "t_leases"})
  back = pq.ParquetFile(path)
  meta = json.loads(back.schema_arrow.metadata[b"geo"])
  assert meta["version"] == "1.1.0" and meta["primary_column"] == "geometry"
  col = meta["columns"]["geometry"]
  assert col["encoding"] == "WKB" and col["geometry_types"] == ["MultiPolygon"]
  assert col["covering"]["bbox"]["xmin"] == ["bbox", "xmin"]
  assert col["crs"]["id"] == {"authority": "EPSG", "code": 4326}
  assert back.read().num_rows == 3 and geo == meta
  assert json.loads(back.schema_arrow.metadata[b"gazetteer:provenance"])["slug"] == "t_leases"


def test_check_parquet_passes_a_good_file_and_flags_a_missing_licence(tmp_path):
  cfg, rows, fields, _, t = build(tmp_path)
  good = tmp_path / "good.parquet"
  write_geoparquet(t, good, {"sources": []})
  assert check_parquet(good, cfg) == []
  for r in rows:
    r["license"] = ""
  bad = tmp_path / "bad.parquet"
  write_geoparquet(to_table(rows, fields), bad, {"sources": []})
  assert any("empty license" in p for p in check_parquet(bad, cfg))


# row groups: a getPlace is a range read, so groups are small and the footer stays bounded ----
def _wide_table(n, cols=30, payload=2000):
  import pyarrow as pa
  data = {"place_id": [f"T:{i:05d}" for i in range(n)], "geom_type": ["Polygon"] * n}
  for c in range(cols - 4):
    data[f"c{c}"] = ["x"] * n
  data["bbox"] = pa.StructArray.from_arrays([pa.array([float(i)] * n) for i in range(4)], names=["xmin", "ymin", "xmax", "ymax"])
  data["geometry"] = pa.array([b"g" * payload] * n, type=pa.binary())
  return pa.table(data)


def test_auto_row_group_size_is_one_row_for_a_modest_polygon_layer():
  from gazetteer.table import auto_row_group_size
  assert auto_row_group_size(_wide_table(300, payload=100_000)) == 1


def test_auto_row_group_size_grows_when_the_footer_budget_runs_out():
  from gazetteer.table import FOOTER_BUDGET, FOOTER_BYTES_PER_COLUMN, auto_row_group_size
  t = _wide_table(3000, payload=100_000)
  rg = auto_row_group_size(t)
  assert rg > 1 and -(-t.num_rows // rg) * t.num_columns * FOOTER_BYTES_PER_COLUMN <= FOOTER_BUDGET


def test_auto_row_group_size_keeps_a_tiny_table_in_one_group():
  from gazetteer.table import auto_row_group_size
  t = _wide_table(40, payload=10)
  assert auto_row_group_size(t) == 40


def test_written_row_groups_prune_a_place_id_lookup(tmp_path):
  """regression: one 5 MB row group (or Morton groups with overlapping place_id ranges) made getPlace read the whole file."""
  t = _wide_table(300, payload=50_000)
  write_geoparquet(t, tmp_path / "p.parquet", {})
  md = pq.ParquetFile(tmp_path / "p.parquet").metadata
  assert md.num_row_groups == 300 and all(md.row_group(i).num_rows == 1 for i in range(md.num_row_groups))
  pid = next(j for j in range(md.row_group(0).num_columns) if md.row_group(0).column(j).path_in_schema == "place_id")
  hit = [i for i in range(md.num_row_groups)
         if md.row_group(i).column(pid).statistics.min <= "T:00123" <= md.row_group(i).column(pid).statistics.max]
  assert hit == [123]
  # statistics only for place_id and bbox: the name-like columns carry none (a small footer)
  assert not md.row_group(0).column(1).is_stats_set
