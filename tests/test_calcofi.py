"""CalCOFI stations and lines: parsing of the published tables, the core-75 rule, ids, line geometry, config, staged output."""
import json

import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import LineString, Point

from conftest import ROOT, STAGING
from gazetteer import calcofi
from gazetteer.config import load_all, validate_config
from gazetteer.fetch import SourceResult
from gazetteer.ids import build_place_ids, check_place_ids
from gazetteer.stac import style_json
from gazetteer.table import build_rows, geo_metadata, to_table
from gazetteer.validate import check_parquet, check_pmtiles

CFGS = load_all(ROOT / "sources")
ST, LN = CFGS["calcofi_stations"], CFGS["calcofi_lines"]

# real rows of CalCOFIStationOrder.csv (calcofi.org, last modified 2022-02-06); lines 93.3 and 91.7 plus one extended-pattern row
CSV = """Order Occ,Line,Sta,Lat (dec),Lat (deg),Lat (min),Lat (deg min),Lon (dec),Lon (deg),Lon (min),Lon (deg min),Est Depth,Sta Type
1,93.3,26.7,32.95637,32,57.4,32 57.38,-117.30538,117,18.3,117 18.32,63,ROS
3,91.7,26.4,33.2435,33,14.6,33 14.61,-117.46542,117,27.9,117 27.93,20,SCCOOS
5,93.3,30,32.84637,32,50.8,32 50.78,-117.53122,117,31.9,117 31.87,846,ROS
4,93.3,28,32.91304,32,54.8,32 54.78,-117.39438,117,23.7,117 23.66,609,ROS
113,60,100,36.28077,36,16.8,36 16.85,-126.48559,126,29.1,126 29.14,,ROS
112,60,90,36.6141,36,36.8,36 36.85,-125.77099,125,46.3,125 46.26,4516,ROS
"""
# the 75-station KML: station placemarks named "LLL.L SSS.S", plus a facility placemark and a folder name that are not stations
KML = """<?xml version="1.0"?><kml><Document><name>CalCOFI 75 Standard Stations</name>
<Placemark><name>093.3 026.7</name><Point><coordinates>-117.3,32.9,0</coordinates></Point></Placemark>
<Placemark><name>093.3 028.0</name><Point><coordinates>-117.4,32.9,0</coordinates></Point></Placemark>
<Placemark><name>093.3 030.0</name><Point><coordinates>-117.5,32.8,0</coordinates></Point></Placemark>
<Placemark><name>091.7 026.4</name><Point><coordinates>-117.4,33.2,0</coordinates></Point></Placemark>
<Placemark><name>UCSD Nimitz Marine Facility</name><Point><coordinates>-117.2,32.7,0</coordinates></Point></Placemark>
</Document></kml>"""
ROWS = calcofi.parse_station_order(CSV)
CORE = calcofi.parse_core_keys(KML)


def result(product):
  feats, fields, notes = calcofi.build_features(product, ROWS, CORE)
  return SourceResult(features=feats, fields=fields, source_url="https://example.test/CalCOFIStationOrder.csv",
                      data_last_edit="2022-02-06T22:56:27Z", retrieved="2026-10-08T12:00:00Z",
                      record_count=len(feats), checksum="abc", extra={"dropped": notes})


# parsing ----------------------------------------------------------------------------------------------------------

def test_padded_keys_match_the_database_site_key_form():
  assert calcofi.pad(93.3) == "093.3" and calcofi.pad(30) == "030.0" and calcofi.pad(120) == "120.0"
  assert calcofi.station_key(93.3, 30) == "093.3 030.0" and calcofi.station_key(60, 100) == "060.0 100.0"


def test_station_order_csv_is_parsed_with_a_blank_depth_as_none():
  by = {(r["line"], r["station"]): r for r in ROWS}
  assert len(ROWS) == 6
  assert by[(93.3, 30.0)] == {"line": 93.3, "station": 30.0, "lat": 32.84637, "lon": -117.53122, "order_occ": 5,
                              "depth_est_m": 846, "sta_type": "ROS"}
  assert by[(60.0, 100.0)]["depth_est_m"] is None and by[(91.7, 26.4)]["sta_type"] == "SCCOOS"


def test_core_keys_are_the_station_placemarks_only():
  assert CORE == {"093.3 026.7", "093.3 028.0", "093.3 030.0", "091.7 026.4"}


# stations ---------------------------------------------------------------------------------------------------------

def test_known_station_coordinates_line_93_3_station_30():
  """the published position of 093.3 030.0 (calcofi.org Station Positions table): 32.84637 N, 117.53122 W."""
  feats, _, _ = calcofi.station_features(ROWS, CORE)
  f = next(x for x in feats if x["properties"]["station_key"] == "093.3 030.0")
  assert (f["geometry"].x, f["geometry"].y) == (-117.53122, 32.84637)
  g = next(x for x in feats if x["properties"]["station_key"] == "093.3 026.7")["geometry"]
  assert (g.x, g.y) == (-117.30538, 32.95637)


def test_core_75_flag_follows_the_75_station_kml_and_the_rest_are_extended():
  feats, _, notes = calcofi.station_features(ROWS, CORE)
  p = {f["properties"]["station_key"]: f["properties"] for f in feats}
  assert p["093.3 030.0"]["in_core_75"] is True and p["093.3 030.0"]["sampling_pattern"] == "core_75"
  assert p["091.7 026.4"]["in_core_75"] is True                      # the SCCOOS inshore stations are in the 75
  assert p["060.0 090.0"]["in_core_75"] is False and p["060.0 090.0"]["sampling_pattern"] == "extended"
  assert notes == []


def test_a_core_key_without_a_position_is_reported():
  _, _, notes = calcofi.station_features(ROWS, CORE | {"083.3 043.0"})
  assert notes == ["core-75 station 083.3 043.0 has no position in the station table"]


def test_station_place_ids_follow_the_pattern():
  feats, _, _ = calcofi.station_features(ROWS, CORE)
  ids = build_place_ids(ST["place_id"], [f["properties"] for f in feats])
  assert "CALCOFI:093.3_030.0" in ids and "CALCOFI:060.0_100.0" in ids and len(set(ids)) == len(ROWS)
  check_place_ids(ids, ST["place_id"]["pattern"])
  with pytest.raises(ValueError):
    check_place_ids(["CALCOFI:93.3_30.0"], ST["place_id"]["pattern"])


def test_station_rows_are_points_with_typed_columns():
  rows, fields, dropped = build_rows(ST, [result("stations")])
  t = to_table(rows, fields)
  assert set(t.column("geom_type").to_pylist()) == {"Point"} and set(t.column("place_type").to_pylist()) == {"station"}
  assert t.schema.field("in_core_75").type == "bool" or str(t.schema.field("in_core_75").type) == "bool"
  assert t.schema.field("line").type == "double" or str(t.schema.field("line").type) == "double"
  row = next(r for r in rows if r["place_id"] == "CALCOFI:093.3_030.0")
  assert row["name"] == "CalCOFI station 093.3 030.0" and row["license"] == "CC-BY-4.0" and row["status"] == "active"
  assert row["line"] == 93.3 and row["station"] == 30.0 and row["depth_est_m"] == 846
  assert json.loads(json.dumps(geo_metadata(t)))["columns"]["geometry"]["geometry_types"] == ["Point"]
  assert "orientation" not in geo_metadata(t)["columns"]["geometry"]


# lines ------------------------------------------------------------------------------------------------------------

def test_lines_run_nearshore_to_offshore_whatever_the_row_order():
  """regression: the CSV is in order of occupation, not station number (93.3 is listed 26.7, 30, 28 here)."""
  feats, _, _ = calcofi.line_features(ROWS, CORE)
  f = next(x for x in feats if x["properties"]["line_id"] == "093.3")
  assert list(f["geometry"].coords) == [(-117.30538, 32.95637), (-117.39438, 32.91304), (-117.53122, 32.84637)]
  p = f["properties"]
  assert (p["n_stations"], p["n_core_75"], p["in_core_75"], p["station_min"], p["station_max"]) == (3, 3, True, 26.7, 30.0)
  g = f["geometry"]
  d = [Point(c).distance(Point(g.coords[0])) for c in g.coords]
  assert d == sorted(d)


def test_line_length_is_geodesic_km():
  feats, _, _ = calcofi.line_features(ROWS, CORE)
  f = next(x for x in feats if x["properties"]["line_id"] == "093.3")
  assert 20 < f["properties"]["length_km"] < 40          # 26.7 -> 30.0 is 3.3 station units of 20 nmi on a 60 degree line


def test_single_station_lines_have_no_linestring_and_are_reported():
  feats, _, notes = calcofi.line_features(ROWS, CORE)
  assert {x["properties"]["line_id"] for x in feats} == {"093.3", "060.0"}
  assert notes == ["line 091.7 has one listed station (091.7 026.4, SCCOOS): no linestring"]


def test_extended_only_line_is_not_core():
  feats, _, _ = calcofi.line_features(ROWS, CORE)
  p = next(x for x in feats if x["properties"]["line_id"] == "060.0")["properties"]
  assert p["in_core_75"] is False and p["n_core_75"] == 0 and p["n_stations"] == 2


def test_line_place_ids_and_rows():
  rows, fields, dropped = build_rows(LN, [result("lines")])
  assert sorted(r["place_id"] for r in rows) == ["CALCOFI:line-060.0", "CALCOFI:line-093.3"]
  assert {r["geom_type"] for r in rows} == {"LineString"} and {r["place_type"] for r in rows} == {"transect"}
  assert dropped == ["line 091.7 has one listed station (091.7 026.4, SCCOOS): no linestring"]
  check_place_ids([r["place_id"] for r in rows], LN["place_id"]["pattern"])


# geometry guard and style -----------------------------------------------------------------------------------------

def test_simple_geometry_must_match_the_declared_type_and_range():
  assert calcofi.clean_simple_geometry(Point(-117.5, 32.8), "Point").equals(Point(-117.5, 32.8))
  assert calcofi.clean_simple_geometry(LineString([(0, 0), (1, 1)]), "Point") is None
  assert calcofi.clean_simple_geometry(Point(-200, 10), "Point") is None
  assert calcofi.clean_simple_geometry(None, "Point") is None
  assert calcofi.clean_simple_geometry(shapely.force_3d(Point(-117.5, 32.8, 5)), "Point").has_z is False


def test_default_styles_follow_the_geometry_type():
  assert [l["type"] for l in style_json("calcofi_stations", 10, "Point")["layers"]] == ["circle"]
  assert [l["type"] for l in style_json("calcofi_lines", 10, "LineString")["layers"]] == ["line"]
  assert [l["type"] for l in style_json("x", 5)["layers"]] == ["fill", "line"]


# config -----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,gt,pt", [(ST, "Point", "station"), (LN, "LineString", "transect")])
def test_licence_attribution_and_types_are_recorded(cfg, gt, pt):
  assert cfg["license"] == "CC-BY-4.0" and cfg["license_url"].startswith("https://creativecommons.org/licenses/by/4.0")
  assert "calcofi.org" in cfg["attribution"] and "CalCOFI" in cfg["attribution"]
  assert "data-usage-policy" in cfg["license_note"]
  assert cfg["geometry_type"] == gt and cfg["place_type"] == pt and cfg["authority"] == "CALCOFI"
  assert cfg["sources"][0]["kind"] == "calcofi_positions" and cfg["sources"][0]["url"].startswith("https://calcofi.org/")


def test_config_rejects_an_unknown_geometry_type():
  bad = {k: v for k, v in ST.items() if not k.startswith("_")} | {"geometry_type": "Polygon"}
  with pytest.raises(ValueError, match="geometry_type"):
    validate_config(bad, "t")


# staged output (skipped until `uv run build.py build --slug calcofi_stations --slug calcofi_lines`) ---------------

def staged(slug):
  d = STAGING / slug
  if not (d / "places.parquet").exists():
    pytest.skip(f"{slug} not built")
  return d


def rows_of(slug):
  return pq.read_table(staged(slug) / "places.parquet").drop_columns(["geometry", "bbox"]).to_pylist()


def test_staged_collections_pass_every_check():
  for slug, cfg in (("calcofi_stations", ST), ("calcofi_lines", LN)):
    d = staged(slug)
    assert check_parquet(d / "places.parquet", cfg) == [] and check_pmtiles(d / "places.pmtiles", slug) == []
    coll = json.loads((d / "collection.json").read_text())
    assert coll["license"] == "CC-BY-4.0" and coll["gazetteer:attribution"]


def test_staged_stations_113_with_75_core_and_38_extended():
  rows = rows_of("calcofi_stations")
  assert len(rows) == 113 and sum(r["in_core_75"] for r in rows) == 75
  assert sum(r["sampling_pattern"] == "extended" for r in rows) == 38
  assert {r["sta_type"] for r in rows if r["sta_type"] == "SCCOOS" and not r["in_core_75"]} == set()  # all nine SCCOOS are core
  assert sum(r["sta_type"] == "SCCOOS" for r in rows) == 9


def test_staged_core_75_is_exactly_the_stations_on_lines_76_7_and_above():
  """how the flag was cross-checked: CalCOFI describes the 75 as lines 76.7 to 93.3 (66 stations) + 9 SCCOOS stations; in the
  published table that is every station with line >= 76.7 and none north of it (lines 60.0 to 73.3 are the extended grid)."""
  rows = rows_of("calcofi_stations")
  assert all(r["in_core_75"] == (r["line"] >= 76.7) for r in rows)
  assert sum(r["sta_type"] == "ROS" for r in rows if r["in_core_75"]) == 66


def test_staged_known_coordinates_line_93_3_station_30():
  d = staged("calcofi_stations")
  t = pq.read_table(d / "places.parquet", columns=["place_id", "geometry", "station_key", "line", "station"]).to_pylist()
  r = next(x for x in t if x["place_id"] == "CALCOFI:093.3_030.0")
  g = shapely.from_wkb(r["geometry"])
  assert (g.x, g.y) == (-117.53122, 32.84637) and (r["line"], r["station"], r["station_key"]) == (93.3, 30.0, "093.3 030.0")


def test_staged_lines_are_the_eleven_multi_station_lines():
  rows = rows_of("calcofi_lines")
  assert len(rows) == 11
  ids = sorted(r["place_id"] for r in rows)
  assert ids[0] == "CALCOFI:line-060.0" and ids[-1] == "CALCOFI:line-093.3"
  assert sum(r["in_core_75"] for r in rows) == 6
  prov = json.loads((staged("calcofi_lines") / "provenance.json").read_text())
  assert len(prov["dropped"]) == 7 and prov["sources"][0]["source_url"].endswith("CalCOFIStationOrder.csv")


def test_staged_every_station_lies_on_its_line_within_a_kilometre():
  """the polyline passes through every listed station (vertices), so each station is within 1 km of its line."""
  st = pq.read_table(staged("calcofi_stations") / "places.parquet", columns=["line_id", "geometry"]).to_pylist()
  ln = {r["line_id"]: shapely.from_wkb(r["geometry"]) for r in
        pq.read_table(staged("calcofi_lines") / "places.parquet", columns=["line_id", "geometry"]).to_pylist()}
  for r in st:
    if r["line_id"] in ln:
      assert ln[r["line_id"]].distance(shapely.from_wkb(r["geometry"])) < 0.01   # ~1 km in degrees


@pytest.mark.network
def test_live_station_table_still_has_the_known_row():
  import requests
  text = requests.get(ST["sources"][0]["url"], timeout=60).text
  by = {(r["line"], r["station"]): r for r in calcofi.parse_station_order(text)}
  assert len(by) == 113 and (by[(93.3, 30.0)]["lat"], by[(93.3, 30.0)]["lon"]) == (32.84637, -117.53122)
