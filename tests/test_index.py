"""scripts/build_index.py: exact index rows, bbox struct and the id crosswalk for a synthetic two-collection fixture."""
import importlib.util
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import LineString, Polygon

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_index.py"
spec = importlib.util.spec_from_file_location("build_index", SCRIPT)
bi = importlib.util.module_from_spec(spec)
sys.modules["build_index"] = bi
spec.loader.exec_module(bi)

BBOX_T = pa.struct([("xmin", pa.float64()), ("ymin", pa.float64()), ("xmax", pa.float64()), ("ymax", pa.float64())])


def square(x0, y0, size=2.0):
  return Polygon([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)])


def bbox_of(g):
  x0, y0, x1, y1 = g.bounds
  return {"xmin": x0, "ymin": y0, "xmax": x1, "ymax": y1}


def write_layer(dirpath: Path, cols: dict, coll: dict):
  """a staged collection: places.parquet (WKB geometry + bbox struct) and collection.json."""
  dirpath.mkdir(parents=True, exist_ok=True)
  geoms = cols.pop("_geoms")
  cols["bbox"] = pa.array([bbox_of(g) for g in geoms], type=BBOX_T)
  cols["geometry"] = pa.array([shapely.to_wkb(g) for g in geoms], type=pa.binary())
  pq.write_table(pa.table(cols), dirpath / "places.parquet")
  (dirpath / "collection.json").write_text(json.dumps(coll))


@pytest.fixture
def staging(tmp_path):
  st = tmp_path / "staging"
  # collection 1: MPA Inventory rows carrying ProSeasID and WDPA_Cd (and a place with neither)
  g1, g2, g3 = square(-120, 30), square(-118, 33, 4.0), square(-100, 20)
  write_layer(st / "noaa_mpa_inventory", {
    "place_id": ["MPA:AAA1", "MPA:BBB2", "MPA:CCC3"], "name": ["Alpha", "Beta", "Gamma"],
    "place_type": ["protected_area"] * 3, "geom_type": ["MultiPolygon"] * 3, "area_km2": [10.5, None, 3.0],
    "license": ["CC-PDDC"] * 3, "attribution": ["NOAA MPA Center"] * 3, "version": ["1.0.0"] * 3,
    "ProSeasID": ["939", "1204.0", None], "WDPA_Cd": ["555", "0", " "], "_geoms": [g1, g2, g3],
  }, {"id": "noaa_mpa_inventory", "updated": "2026-10-01T00:00:00Z", "gazetteer:authority": "MPA"})
  # collection 2: marine regions with MRGID place_ids (one with a part suffix) and a native mrgid column;
  # no license/version/authority columns, so those come from the collection metadata
  l1 = LineString([(-10, 0), (10, 4)])
  write_layer(st / "mr_eez", {
    "place_id": ["MRGID:8439", "MRGID:5668:north", "PSGID:77"], "name": ["EEZ A", "EEZ B", "Reserve"],
    "mrgid": [8439, 5668, None], "_geoms": [square(-133, -28, 12.0), square(5, 5), l1],
  }, {"id": "mr_eez", "updated": "2026-10-02T00:00:00Z", "license": "CC-BY-4.0", "version": "2.0.0",
      "geoparquet:geometry_type": "MultiPolygon", "gazetteer:authority": "MRGID", "gazetteer:place_type": "eez",
      "gazetteer:attribution": "Flanders Marine Institute  (VLIZ)."})
  return st


def run(staging, out):
  srcs = bi.merge_sources([], bi.local_sources(staging))
  stats = bi.build(srcs, out)
  return srcs, stats, pq.read_table(out / "places_index.parquet").to_pylist(), pq.read_table(out / "crosswalk.parquet").to_pylist()


def test_discovery_is_sorted_local_and_wins_over_published(staging, tmp_path):
  loc = bi.local_sources(staging)
  assert [s.slug for s in loc] == ["mr_eez", "noaa_mpa_inventory"]
  pub = [bi.Source("mr_eez", tmp_path / "x.parquet", {}, "published"), bi.Source("zzz", tmp_path / "z.parquet", {}, "published")]
  merged = bi.merge_sources(pub, loc)
  assert [(s.slug, s.origin) for s in merged] == [("mr_eez", "local"), ("noaa_mpa_inventory", "local"), ("zzz", "published")]


def test_parquet_href_only_for_collections_with_a_places_parquet():
  assert bi.parquet_href({"assets": {"places": {"href": "./places.parquet"}, "t": {"href": "./places.pmtiles"}}}) == "./places.parquet"
  assert bi.parquet_href({"assets": {"data": {"href": "./dhw_5km.json"}}}) is None
  assert bi.parquet_href({}) is None


def test_index_rows_exact(staging, tmp_path):
  _, stats, rows, _ = run(staging, tmp_path / "out")
  assert stats["counts"] == {"mr_eez": 3, "noaa_mpa_inventory": 3}
  by = {r["place_id"]: r for r in rows}
  assert len(rows) == 6 and list(by) == ["MRGID:8439", "MRGID:5668:north", "PSGID:77", "MPA:AAA1", "MPA:BBB2", "MPA:CCC3"]
  assert by["MPA:AAA1"] == {
    "place_id": "MPA:AAA1", "name": "Alpha", "authority": "MPA", "place_type": "protected_area",
    "geom_type": "MultiPolygon", "collection": "noaa_mpa_inventory",
    "bbox": {"xmin": -120.0, "ymin": 30.0, "xmax": -118.0, "ymax": 32.0},
    "centroid_lon": -119.0, "centroid_lat": 31.0, "area_km2": 10.5, "license": "CC-PDDC",
    "attribution": "NOAA MPA Center", "version": "1.0.0", "updated": "2026-10-01T00:00:00Z"}
  assert by["MPA:BBB2"]["area_km2"] is None  # null where absent
  # no row columns for these: collection metadata fills them; squash() collapses the doubled space
  b = by["MRGID:8439"]
  assert (b["authority"], b["place_type"], b["license"], b["version"], b["geom_type"]) == ("MRGID", "eez", "CC-BY-4.0", "2.0.0", "MultiPolygon")
  assert b["attribution"] == "Flanders Marine Institute (VLIZ)."
  assert b["area_km2"] is None
  # geometry-derived type and centroid for a line without a geom_type column
  line = by["PSGID:77"]
  assert (line["geom_type"], line["centroid_lon"], line["centroid_lat"]) == ("LineString", 0.0, 2.0)


def test_bbox_is_a_struct_of_doubles_and_matches_the_geometry(staging, tmp_path):
  run(staging, tmp_path / "out")
  schema = pq.read_schema(tmp_path / "out" / "places_index.parquet")
  assert schema.field("bbox").type == BBOX_T
  assert [str(schema.field(n).type) for n in ("place_id", "centroid_lon", "area_km2", "updated")] == ["string", "double", "double", "string"]
  assert "geometry" not in schema.names
  for r in pq.read_table(tmp_path / "out" / "places_index.parquet").to_pylist():
    assert r["bbox"]["xmin"] <= r["centroid_lon"] <= r["bbox"]["xmax"]
    assert r["bbox"]["ymin"] <= r["centroid_lat"] <= r["bbox"]["ymax"]


def test_bbox_and_type_fall_back_to_the_geometry_when_the_columns_are_absent(tmp_path):
  d = tmp_path / "st" / "bare"
  d.mkdir(parents=True)
  g = square(10, 10, 4.0)
  pq.write_table(pa.table({"place_id": ["X:1"], "geometry": pa.array([shapely.to_wkb(g)], type=pa.binary())}), d / "places.parquet")
  _, _, rows, _ = run(tmp_path / "st", tmp_path / "out")
  assert rows[0]["bbox"] == {"xmin": 10.0, "ymin": 10.0, "xmax": 14.0, "ymax": 14.0}
  assert (rows[0]["geom_type"], rows[0]["authority"], rows[0]["centroid_lon"]) == ("Polygon", "X", 12.0)
  assert rows[0]["name"] is None and rows[0]["license"] is None


def test_crosswalk_maps_mpa_inventory_to_psgid_and_wdpa(staging, tmp_path):
  _, stats, _, xw = run(staging, tmp_path / "out")
  by = {r["place_id"]: r for r in xw}
  assert by["MPA:AAA1"] == {"place_id": "MPA:AAA1", "mrgid": None, "psgid": "939", "wdpa_id": "555",
                            "mpainv_site_id": "AAA1", "mpatlas_id": None, "wikidata_qid": None, "gers_id": None}
  # 1204.0 -> '1204'; WDPA_Cd 0 and blank are unknown
  assert (by["MPA:BBB2"]["psgid"], by["MPA:BBB2"]["wdpa_id"], by["MPA:BBB2"]["mpainv_site_id"]) == ("1204", None, "BBB2")
  assert (by["MPA:CCC3"]["psgid"], by["MPA:CCC3"]["wdpa_id"]) == (None, None)


def test_crosswalk_prefixes_and_native_columns(staging, tmp_path):
  _, stats, _, xw = run(staging, tmp_path / "out")
  by = {r["place_id"]: r for r in xw}
  assert by["MRGID:8439"]["mrgid"] == "8439"
  assert by["MRGID:5668:north"]["mrgid"] == "5668"  # part suffix is not part of the MRGID
  assert by["PSGID:77"]["psgid"] == "77" and by["PSGID:77"]["mrgid"] is None
  assert stats["crosswalk"] == {"mrgid": 2, "psgid": 3, "wdpa_id": 1, "mpainv_site_id": 3, "mpatlas_id": 0,
                                "wikidata_qid": 0, "gers_id": 0}
  assert stats["crosswalk_rows"] == len(xw) == 6
  assert pq.read_schema(tmp_path / "out" / "crosswalk.parquet").names == ["place_id"] + bi.XW_COLS


def test_mpainv_prefix_is_also_recognised():
  assert bi.prefix_id("MPAINV:12") == ("mpainv_site_id", "12")
  assert bi.prefix_id("NMS:FKNMS") is None and bi.prefix_id("nocolon") is None
  assert [bi.clean_id(v) for v in (None, "", " 0 ", 7.0, "abc", float("nan"))] == [None, None, None, "7", "abc", None]


def test_row_groups_are_capped_at_5000(tmp_path):
  d = tmp_path / "st" / "big"
  d.mkdir(parents=True)
  n = 12000
  pq.write_table(pa.table({"place_id": [f"B:{i}" for i in range(n)],
                           "geometry": pa.array([shapely.to_wkb(shapely.Point(i % 100, 0)) for i in range(n)], type=pa.binary())}),
                 d / "places.parquet", row_group_size=3000)
  run(tmp_path / "st", tmp_path / "out")
  md = pq.ParquetFile(tmp_path / "out" / "places_index.parquet").metadata
  assert md.num_rows == n and max(md.row_group(i).num_rows for i in range(md.num_row_groups)) <= 5000


def test_cli_is_idempotent_and_writes_collection_json_and_readme(staging, tmp_path, capsys):
  out = tmp_path / "out"
  args = ["--staging", str(staging), "--out", str(out), "--no-remote"]
  assert bi.main(args) == 0
  first = {p.name: p.read_bytes() for p in out.iterdir()}
  assert bi.main(args) == 0
  assert {p.name: p.read_bytes() for p in out.iterdir()} == first
  assert sorted(first) == ["README.md", "collection.json", "crosswalk.parquet", "places_index.parquet"]
  coll = json.loads(first["collection.json"])
  assert (coll["id"], coll["license"]) == ("index", "CC0-1.0")
  assert set(coll["assets"]) == {"places_index", "crosswalk", "documentation"}
  assert coll["assets"]["places_index"]["table:row_count"] == 6
  assert coll["updated"] == "2026-10-02T00:00:00Z"
  text = capsys.readouterr().out
  assert "noaa_mpa_inventory" in text and "TOTAL" in text


def test_unreachable_published_catalog_is_skipped_with_a_warning(tmp_path, capsys):
  def boom(url, timeout=60):
    raise OSError("offline")
  assert bi.remote_sources("https://example.test/", tmp_path, fetch=boom) == []
  assert "unreachable" in capsys.readouterr().err


def test_remote_children_without_a_places_parquet_are_skipped(tmp_path):
  docs = {
    "https://example.test/g/catalog.json": {"links": [{"rel": "child", "href": "./places/collection.json"},
                                                      {"rel": "child", "href": "./erddap/x/collection.json"}]},
    "https://example.test/g/versions.json": {"collections": {"places": {"current_version": "1.2.0"}}},
    "https://example.test/g/places/collection.json": {"id": "places", "assets": {"places": {"href": "./places.parquet"}}},
    "https://example.test/g/erddap/x/collection.json": {"id": "x", "assets": {"data": {"href": "./x.json"}}},
  }
  got = []

  def get_file(url, dest):
    got.append(url)
    return dest

  srcs = bi.remote_sources("https://example.test/g/", tmp_path, fetch=lambda u, timeout=60: docs[u], get_file=get_file)
  assert [(s.slug, s.version, s.origin) for s in srcs] == [("places", "1.2.0", "published")]
  assert got == ["https://example.test/g/places/places.parquet"]
