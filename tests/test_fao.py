"""FAO major fishing areas (fao_major_areas) and the high seas cut by them (fao_high_seas, kind `derive`): config and
licence rules, the generalised WFS fetch, ids and names, the intersection rules (synthetic geometry only: no Marine
Regions geometry or file from the internal store is ever used here), and the reference / display metadata.
staged-output checks skip for a collection that was not built."""
import json
import re
import subprocess

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from pyproj import Geod
from shapely.geometry import MultiPolygon, box

from conftest import ROOT, STAGING, square
from gazetteer import derive, fetch_wfs, pipeline, stac
from gazetteer.config import PLACE_TYPES, load_all, load_layer_config, validate_config
from gazetteer.fetch import SourceResult
from gazetteer.geom import max_edge_span
from gazetteer.pipeline import NO_TILES, write_metadata
from gazetteer.table import build_rows, to_table, write_geoparquet
from gazetteer.validate import check_parquet

CFGS = load_all(ROOT / "sources")
FAO = CFGS["fao_major_areas"]
HS = CFGS["fao_high_seas"]
GEOD = Geod(ellps="WGS84")


def km2(geom) -> float:
  """geodesic area from pyproj directly (the expected value; derive.geodesic_area_km2 is the code under test)."""
  return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


# fao_major_areas: config ---------------------------------------------------------------------------------------------

def test_fao_major_areas_is_cc_by_with_the_mandatory_citation_and_both_licences_on_record():
  assert FAO["license"] == "CC-BY-4.0" and FAO["license_url"].startswith("https://creativecommons.org/licenses/by/4.0")
  assert "FAO. 2024. FAO Major Fishing Areas for Statistical Purposes. In: FAO Fisheries and Aquaculture Division [online]." in FAO["attribution"]
  assert "License: CC-BY 4.0" in FAO["attribution"]
  note = " ".join(FAO["license_note"].split())
  assert "edition 2026.1.0" in note and "FAO Statistical Database Terms of Use" in note
  assert "CC BY-NC-SA 4.0" in note and "cwp-fishing-area" in note        # the codelist page's licence, recorded, not used for the geometry
  assert "ac02a460-da52-11dc-9d70-0017f293bd28" in note
  assert "illustration only" in " ".join(FAO["description"].split())      # FAO's boundary disclaimer


def test_fao_major_areas_reads_the_major_level_of_the_coastline_erased_layer():
  src = FAO["sources"][0]
  assert (src["kind"], src["url"], src["type_name"]) == ("wfs", "https://www.fao.org/fishery/geoserver/fifao/wfs", "fifao:FAO_AREAS_ERASE")
  assert src["cql_filter"] == "F_LEVEL='MAJOR'" and src["sort_by"] == "F_CODE" and src["expected_count"] == 19
  assert "mr" not in src                                                 # no Marine Regions columns
  assert FAO["place_type"] == "statistical_area" and "statistical_area" in PLACE_TYPES and FAO["authority"] == "FAO"


@pytest.mark.parametrize("pid,ok", [("FAO:21", True), ("FAO:88", True), ("FAO:21.1.1", False), ("FAOHS:21", False), ("FAO:", False)])
def test_fao_place_id_pattern(pid, ok):
  assert bool(re.fullmatch(FAO["place_id"]["pattern"], pid)) is ok


def test_fao_ids_names_and_page_links_from_a_synthetic_major_area():
  props = {"ID": "fao:21", "F_CODE": "21", "F_LEVEL": "MAJOR", "F_STATUS": "endorsed", "F_NAME": "Atlantic, Northwest",
           "OCEAN": "Atlantic", "SUBOCEAN": "2", "F_AREA": "21", "NAME_EN": "Atlantic, Northwest"}
  feats = [{"properties": props, "geometry": MultiPolygon([square(0, 0)])}]
  res = SourceResult(features=feats, fields=fetch_wfs.native_fields(feats), source_url="https://example.test/wfs",
                     data_last_edit="2026-02-02T00:00:00Z", retrieved="2026-10-20T12:00:00Z", record_count=1, checksum="abc")
  rows, fields, dropped = build_rows(FAO, [res])
  r = rows[0]
  assert (r["place_id"], r["name"], r["source_id"], r["place_type"], r["authority"]) == ("FAO:21", "Atlantic, Northwest", "21", "statistical_area", "FAO")
  assert r["status"] == "current" and r["status_date"] == "2026-02-02" and not dropped
  assert r["F_CODE"] == "21" and r["OCEAN"] == "Atlantic"
  assert FAO["place_url"].replace("{F_CODE}", r["F_CODE"]) == "https://www.fao.org/fishery/area/21/en"


# the WFS fetch, generalised -----------------------------------------------------------------------------------------

class FakeResp:
  def __init__(self, text="", js=None):
    self.text, self._js, self.content, self.status_code = text, js, (text or json.dumps(js)).encode(), 200

  def json(self):
    return self._js

  def raise_for_status(self):
    pass


class FakeGeoServer:
  """a GeoServer WFS holding 5 major areas; records every request's url and params."""
  def __init__(self, n=5):
    self.n, self.calls, self.headers = n, [], {}

  def get(self, url, params=None, **kw):
    self.calls.append((url, dict(params)))
    if params.get("request") == "GetCapabilities":
      return FakeResp('<FeatureType xmlns:fifao="http://www.fao.org/fi"><Name>fifao:FAO_AREAS_ERASE</Name>'
                      '<Title>FAO statistical areas (Marine) - Erased by coastline</Title></FeatureType>')
    if params.get("resultType") == "hits":
      return FakeResp(f'<wfs:FeatureCollection numberMatched="{self.n}" numberReturned="0"/>')
    feats = [{"type": "Feature", "properties": {"F_CODE": str(18 + 10 * i), "F_LEVEL": "MAJOR", "NAME_EN": f"Area {i}", "AREA_KM2": i * 1.5},
              "geometry": shapely.geometry.mapping(MultiPolygon([square(10 * i, 0)]))}
             for i in range(params["startIndex"], min(params["startIndex"] + params["count"], self.n))]
    return FakeResp(js={"type": "FeatureCollection", "features": feats})


def test_a_non_marine_regions_wfs_source_pages_with_its_filter_url_and_sort_key():
  srv = FakeGeoServer(5)
  src = {**FAO["sources"][0], "page_size": 2}
  r = fetch_wfs.fetch_wfs(src, delay=0, s=srv)
  assert {u for u, _ in srv.calls} == {"https://www.fao.org/fishery/geoserver/fifao/wfs"}
  data_calls = [p for _, p in srv.calls if p["request"] == "GetFeature"]                 # GetCapabilities takes no filter
  assert len(data_calls) == 4 and all(p["CQL_FILTER"] == "F_LEVEL='MAJOR'" and p["typeNames"] == "fifao:FAO_AREAS_ERASE" for p in data_calls)
  pages = [(p["startIndex"], p["count"], p["sortBy"]) for _, p in srv.calls if "startIndex" in p]
  assert pages == [(0, 2, "F_CODE"), (2, 2, "F_CODE"), (4, 2, "F_CODE")]
  assert r.record_count == 5 and len(r.features) == 5
  assert r.data_last_edit == "2026-02-02T00:00:00Z"                     # `released`: the layer serves no edit date
  assert r.extra["http"]["etag"] == "FAO statistical areas (Marine) - Erased by coastline|5"
  assert r.features[1]["properties"] == {"F_CODE": "28", "F_LEVEL": "MAJOR", "NAME_EN": "Area 1", "AREA_KM2": 1.5}   # no mr_* columns
  assert r.fields == [{"name": "F_CODE", "type": "string"}, {"name": "F_LEVEL", "type": "string"},
                      {"name": "NAME_EN", "type": "string"}, {"name": "AREA_KM2", "type": "float"}]


def test_a_non_marine_regions_wfs_source_without_sort_by_is_refused():
  src = {k: v for k, v in FAO["sources"][0].items() if k != "sort_by"}
  with pytest.raises(ValueError, match="needs `sort_by`"):
    fetch_wfs.fetch_wfs(src, delay=0, s=FakeGeoServer())


def test_the_wfs_endpoint_falls_back_to_marine_regions_and_the_unfiltered_request_has_no_cql():
  """regression: the Marine Regions configs keep their endpoint; no `cql_filter` adds no CQL_FILTER parameter."""
  assert fetch_wfs.endpoint({"type_name": "x"}) == fetch_wfs.WFS_URL
  assert fetch_wfs.endpoint({"url": "https://example.test/wfs"}) == "https://example.test/wfs"
  assert fetch_wfs.endpoint({"url": "https://example.test/wfs", "wfs_url": "https://other.test/wfs"}) == "https://other.test/wfs"
  assert "CQL_FILTER" not in fetch_wfs.wfs_params({"type_name": "MarineRegions:eez"}, request="GetFeature")
  assert all(fetch_wfs.endpoint(CFGS[s]["sources"][0]) == fetch_wfs.WFS_URL for s in CFGS if s.startswith("mr_"))


# derive: config -------------------------------------------------------------------------------------------------------

def test_fao_high_seas_config_is_a_derived_reference_drawn_by_the_fao_layer():
  src = HS["sources"][0]
  assert src["kind"] == "derive" and src["op"] == "intersect" and src["min_area_km2"] == 100
  assert [(i["slug"], i["id_column"]) for i in src["inputs"]] == [("mr_high_seas", "high_seas_id"), ("fao_major_areas", "fao_id")]
  assert HS["display"] == {"via": "fao_major_areas", "id_from": "fao_id"} and "reference" not in HS
  assert HS["place_type"] == "high_seas_area" and HS["authority"] == "FAOHS" and HS["source_id"] == "{fao_id}"
  assert HS["license"] == "CC-BY-4.0"
  assert "10.14284/696" in HS["attribution"] and "FAO. 2024. FAO Major Fishing Areas" in HS["attribution"]   # both credits
  assert "VLIZ asked us not to republish" in " ".join(HS["description"].split())


def with_(cfg, **kw):
  return {**cfg, **kw}


def problems(cfg):
  with pytest.raises(ValueError) as e:
    validate_config(cfg, "t")
  return str(e.value)


def test_derive_source_rules():
  src = HS["sources"][0]
  bad_op = with_(HS, sources=[{**src, "op": "union"}])
  assert "op must be 'intersect'" in problems(bad_op)
  one_input = with_(HS, sources=[{**src, "inputs": src["inputs"][:1]}])
  assert "inputs must be two {slug, id_column[, carry]} entries" in problems(one_input)
  same_col = with_(HS, sources=[{**src, "inputs": [src["inputs"][0], {**src["inputs"][1], "id_column": "high_seas_id"}]}])
  assert "the inputs' id_column must differ" in problems(same_col)
  neg = with_(HS, sources=[{**src, "min_area_km2": -1}])
  assert "min_area_km2 must be a number >= 0" in problems(neg)
  validate_config(HS)                                                   # the real config is fine


def test_display_rules():
  assert "display must be {via" in problems(with_(HS, display={"via": "fao_major_areas"}))
  assert "display.via cannot be the collection itself" in problems(with_(HS, display={"via": "fao_high_seas", "id_from": "fao_id"}))
  both = with_(HS, reference={"tiles": "https://example.test/{z}/{x}/{y}.png"})
  assert "`reference` (the publisher's tiles) or `display`" in problems(both)


def test_derive_is_a_known_kind_and_new_place_types_exist():
  from gazetteer.config import KINDS
  assert "derive" in KINDS and {"statistical_area", "high_seas_area"} <= PLACE_TYPES


# derive: the intersection rules (synthetic geometry) ------------------------------------------------------------------

def place(pid, geom, **props):
  return {"place_id": pid, "geom": geom, "props": props}


def test_one_piece_per_overlapping_pair_with_parent_ids_carried_columns_and_geodesic_area():
  """two squares (the 'high seas' parents) and an overlapping rectangle, plus a far square that meets nothing."""
  a = [place("HS:1", square(0, 0, 2.0)), place("HS:2", square(10, 0, 2.0))]
  b = [place("F:21", box(1, 0, 11, 2), F_CODE="21", NAME_EN="Atlantic, Northwest"),
       place("F:99", square(50, 50, 2.0), F_CODE="99", NAME_EN="Far")]
  pieces, dropped = derive.intersect_pieces(a, b, "hs_id", "fao_id", min_area_km2=100)
  assert dropped == []
  assert [(p["hs_id"], p["fao_id"], p["F_CODE"], p["NAME_EN"]) for p in pieces] == [
    ("HS:1", "F:21", "21", "Atlantic, Northwest"), ("HS:2", "F:21", "21", "Atlantic, Northwest")]
  assert [p["geom"].bounds for p in pieces] == [(1.0, 0.0, 2.0, 2.0), (10.0, 0.0, 11.0, 2.0)]
  assert all(p["geom"].geom_type == "MultiPolygon" for p in pieces)
  assert pieces[0]["area_km2"] == pytest.approx(km2(box(1, 0, 2, 2)), rel=1e-9)
  assert pieces[1]["area_km2"] == pytest.approx(km2(box(10, 0, 11, 2)), rel=1e-9)


def test_pieces_that_only_touch_along_an_edge_make_no_piece_and_no_note():
  pieces, dropped = derive.intersect_pieces([place("A", square(0, 0, 2.0))], [place("B", square(2, 0, 2.0))], "a", "b")
  assert pieces == [] and dropped == []


def test_a_sliver_under_the_threshold_is_dropped_and_reported_with_its_area():
  a = [place("HS:1", box(0, 0, 10, 2))]
  b = [place("F:1", box(0, 0, 9.9999, 2), F_CODE="1"), place("F:2", box(9.9999, 0, 20, 2), F_CODE="2")]
  pieces, dropped = derive.intersect_pieces(a, b, "hs_id", "fao_id", min_area_km2=100)
  assert [p["fao_id"] for p in pieces] == ["F:1"]
  sliver = km2(box(9.9999, 0, 10, 2))
  assert 0 < sliver < 100
  assert dropped == [f"HS:1 x F:2: dropped sliver of {sliver:.3f} km2 (under 100 km2)"]
  kept, none = derive.intersect_pieces(a, b, "hs_id", "fao_id", min_area_km2=1)          # a lower threshold keeps it
  assert [p["fao_id"] for p in kept] == ["F:1", "F:2"] and none == []


def test_polygon_fragments_under_min_part_are_dropped_before_the_piece_threshold():
  a = [place("HS:1", MultiPolygon([box(0, 0, 4, 4), box(10, 0, 10.001, 0.001)]))]
  b = [place("F:1", box(-1, -1, 20, 5), F_CODE="1")]
  keep, dropped = derive.intersect_pieces(a, b, "hs_id", "fao_id", min_area_km2=0, min_part_km2=1.0)
  assert len(keep) == 1 and len(keep[0]["geom"].geoms) == 1 and keep[0]["geom"].bounds == (0.0, 0.0, 4.0, 4.0)
  tiny = km2(box(10, 0, 10.001, 0.001))
  assert dropped == [f"HS:1 x F:1: dropped 1 fragment(s) under 1 km2 ({tiny:.3f} km2 in all)"]
  whole, none = derive.intersect_pieces(a, b, "hs_id", "fao_id", min_area_km2=0)
  assert len(whole[0]["geom"].geoms) == 2 and none == []                # off by default


def test_antimeridian_inputs_cut_at_180_intersect_on_both_sides():
  """parents stored split at +/-180 (as every built collection is): the high seas as two halves, FAO X across the line
  (two halves), FAO Y west of it. X's piece keeps both halves, Y's one; no ring jumps the dateline."""
  hs = [place("HS:1", MultiPolygon([box(170, 0, 180, 2), box(-180, 0, -170, 2)]))]
  fao = [place("F:61", MultiPolygon([box(175, -1, 180, 3), box(-180, -1, -175, 3)]), F_CODE="61"),
         place("F:67", box(170, -1, 175, 3), F_CODE="67"), place("F:71", box(-175, -1, -170, 3), F_CODE="71")]
  pieces, dropped = derive.intersect_pieces(hs, fao, "hs_id", "fao_id", min_area_km2=100)
  assert dropped == [] and [p["fao_id"] for p in pieces] == ["F:61", "F:67", "F:71"]
  x, y = pieces[0]["geom"], pieces[1]["geom"]
  assert sorted(g.bounds for g in x.geoms) == [(-180.0, 0.0, -175.0, 2.0), (175.0, 0.0, 180.0, 2.0)]
  assert y.bounds == (170.0, 0.0, 175.0, 2.0)
  assert max(max_edge_span(x), max_edge_span(y)) <= 10
  assert pieces[0]["area_km2"] == pytest.approx(2 * km2(box(175, 0, 180, 2)), rel=1e-9)
  assert pieces[1]["area_km2"] == pytest.approx(km2(box(170, 0, 175, 2)), rel=1e-9)
  assert shapely.union_all([p["geom"] for p in pieces]).equals(hs[0]["geom"])          # nothing lost, nothing added


def test_the_pieces_of_a_tiling_add_up_to_the_first_input():
  """FAO areas that tile the whole box leave nothing out of the high seas: the pieces' union is the high seas."""
  hs = [place("HS:1", box(0, 0, 10, 6))]
  fao = [place(f"F:{k}", box(k * 2.5, -1, k * 2.5 + 2.5, 7), F_CODE=str(k)) for k in range(4)]
  pieces, _ = derive.intersect_pieces(hs, fao, "hs_id", "fao_id")
  assert len(pieces) == 4
  union = shapely.union_all([p["geom"] for p in pieces])
  assert union.equals(hs[0]["geom"]) and shapely.symmetric_difference(union, hs[0]["geom"]).area == 0
  assert sum(p["area_km2"] for p in pieces) == pytest.approx(sum(km2(box(k * 2.5, 0, k * 2.5 + 2.5, 6)) for k in range(4)), rel=1e-9)


# derive: reading inputs, building rows ----------------------------------------------------------------------------------

def write_input(root, slug, rows):
  """a minimal built places.parquet: place_id, WKB geometry and the given extra columns."""
  d = root / slug
  d.mkdir(parents=True, exist_ok=True)
  cols = {"place_id": [r["place_id"] for r in rows],
          "geometry": [shapely.to_wkb(r["geom"]) for r in rows]}
  for c in rows[0].get("props", {}):
    cols[c] = [r["props"][c] for r in rows]
  pq.write_table(pa.table(cols), d / "places.parquet")
  return d / "places.parquet"


def synthetic_inputs(root):
  write_input(root, "mr_high_seas", [place("MRGID:63203", MultiPolygon([box(0, 0, 10, 2), box(40, 0, 50, 2)]))])
  write_input(root, "fao_major_areas", [
    place("FAO:21", MultiPolygon([box(0, -1, 4, 3)]), F_CODE="21", NAME_EN="Atlantic, Northwest", OCEAN="Atlantic"),
    place("FAO:27", MultiPolygon([box(4, -1, 12, 3), box(38, -1, 52, 3)]), F_CODE="27", NAME_EN="Atlantic, Northeast", OCEAN="Atlantic"),
    place("FAO:37", MultiPolygon([box(100, -1, 104, 3)]), F_CODE="37", NAME_EN="Mediterranean and Black Sea", OCEAN="Atlantic")])


def test_fetch_derive_reads_the_inputs_and_names_the_pieces_by_the_config_templates(tmp_path):
  synthetic_inputs(tmp_path)
  res = derive.fetch_derive(HS["sources"][0], dirs=[tmp_path])
  assert res.record_count == 2 and res.source_url == "https://doi.org/10.14284/696"
  assert res.item_id == "intersect(mr_high_seas, fao_major_areas)"
  assert res.fields == [{"name": "high_seas_id", "type": "string"}, {"name": "fao_id", "type": "string"},
                        {"name": "F_CODE", "type": "string"}, {"name": "NAME_EN", "type": "string"},
                        {"name": "OCEAN", "type": "string"}, {"name": "area_km2", "type": "float"}]
  rows, fields, dropped = build_rows(HS, [res])
  assert [r["place_id"] for r in rows] == ["FAOHS:21", "FAOHS:27"] and not dropped        # no high seas in FAO 37: no piece
  assert [r["name"] for r in rows] == ["High seas, Atlantic, Northwest (FAO 21) ".strip(), "High seas, Atlantic, Northeast (FAO 27)"]
  assert [(r["high_seas_id"], r["fao_id"], r["source_id"]) for r in rows] == [("MRGID:63203", "FAO:21", "FAO:21"), ("MRGID:63203", "FAO:27", "FAO:27")]
  assert [r["place_type"] for r in rows] == ["high_seas_area"] * 2 and {r["license"] for r in rows} == {"CC-BY-4.0"}
  assert rows[0]["_geom"].bounds == (0.0, 0.0, 4.0, 2.0)
  assert sorted(g.bounds for g in rows[1]["_geom"].geoms) == [(4.0, 0.0, 10.0, 2.0), (40.0, 0.0, 50.0, 2.0)]
  assert rows[1]["area_km2"] == pytest.approx(km2(box(4, 0, 10, 2)) + km2(box(40, 0, 50, 2)), rel=1e-9)
  prov = res.extra["derived_from"]
  assert [(d["slug"], d["rows"]) for d in prov] == [("mr_high_seas", 1), ("fao_major_areas", 3)]
  assert all(re.fullmatch(r"[0-9a-f]{64}", d["parquet_sha256"]) for d in prov)


def test_the_built_table_passes_the_collection_checks(tmp_path):
  synthetic_inputs(tmp_path / "in")
  res = derive.fetch_derive(HS["sources"][0], dirs=[tmp_path / "in"])
  rows, fields, _ = build_rows(HS, [res])
  table = to_table(rows, fields)
  out = tmp_path / "places.parquet"
  write_geoparquet(table, out, {"version": "1.0.0", "sources": []})
  assert check_parquet(out, HS) == []
  assert {"high_seas_id", "fao_id", "F_CODE", "area_km2"} <= set(table.column_names)


def test_inputs_come_from_the_first_directory_that_has_them(tmp_path):
  first, second = tmp_path / "internal", tmp_path / "staging"
  write_input(second, "mr_high_seas", [place("MRGID:63203", box(0, 0, 1, 1))])
  assert derive.find_input("mr_high_seas", [first, second]) == second / "mr_high_seas" / "places.parquet"
  write_input(first, "mr_high_seas", [place("MRGID:63203", box(0, 0, 1, 1))])
  assert derive.find_input("mr_high_seas", [first, second]) == first / "mr_high_seas" / "places.parquet"
  with pytest.raises(FileNotFoundError, match="derive input fao_major_areas.*PLACES_INTERNAL"):
    derive.find_input("fao_major_areas", [first, second])


def test_input_directories_follow_the_environment(monkeypatch, tmp_path):
  monkeypatch.setenv("PLACES_INTERNAL", str(tmp_path / "i"))
  monkeypatch.setenv("PLACES_STAGING", str(tmp_path / "s"))
  assert derive.input_dirs() == [tmp_path / "i", tmp_path / "s"]
  monkeypatch.delenv("PLACES_INTERNAL")
  monkeypatch.delenv("PLACES_STAGING")
  d = derive.input_dirs()
  assert d[0].name == "places-internal" and d[1] == ROOT / "catalog" / "staging"


def test_a_missing_carry_column_is_an_error_naming_it(tmp_path):
  write_input(tmp_path, "mr_high_seas", [place("MRGID:63203", box(0, 0, 1, 1))])
  write_input(tmp_path, "fao_major_areas", [place("FAO:21", box(0, 0, 1, 1), F_CODE="21")])
  with pytest.raises(ValueError, match=r"no column\(s\) \['NAME_EN', 'OCEAN'\] to carry"):
    derive.fetch_derive(HS["sources"][0], dirs=[tmp_path])


def test_detect_token_is_the_inputs_checksum_or_the_published_one_when_they_are_absent(tmp_path):
  src = HS["sources"][0]
  published = {"sources": [{"checksum": "pub"}]}
  assert derive.probe_derive(src, published, dirs=[tmp_path]) == {"checksum": "pub"}
  assert derive.probe_derive(src, None, dirs=[tmp_path]) == {"checksum": None}
  synthetic_inputs(tmp_path)
  tok = derive.probe_derive(src, published, dirs=[tmp_path])
  assert tok == {"checksum": derive.fetch_derive(src, dirs=[tmp_path]).checksum}
  write_input(tmp_path, "mr_high_seas", [place("MRGID:63203", box(0, 0, 11, 2))])        # a changed input changes the token
  assert derive.probe_derive(src, published, dirs=[tmp_path]) != tok
  assert pipeline.changed_sources(HS, published, [tok]) == "payload checksum changed"
  assert pipeline.changed_sources(HS, {"sources": [{"checksum": tok["checksum"]}]}, [tok]) is None


# reference / display: no files of ours, drawn by another collection -------------------------------------------------------

def build_synthetic(tmp_path, monkeypatch):
  synthetic_inputs(tmp_path / "in")
  monkeypatch.setattr(pipeline, "fetch_source", lambda src, cache, delay=0.5, s=None: derive.fetch_derive(src, dirs=[tmp_path / "in"]))
  pipeline.build_layer(HS, tmp_path / "staging", tmp_path / "cache")
  return tmp_path / "staging" / "fao_high_seas"


def test_a_display_collection_builds_with_no_pmtiles_and_is_marked_reference(tmp_path, monkeypatch):
  out = build_synthetic(tmp_path, monkeypatch)
  assert sorted(p.name for p in out.iterdir()) == ["AGENTS.md", "README.md", "collection.json", "places.parquet", "provenance.json", "styles"]
  coll = json.loads((out / "collection.json").read_text())
  assert coll["gazetteer:reference"] is True and coll["gazetteer:display"] == {"via": "fao_major_areas", "id_from": "fao_id"}
  assert "gazetteer:raster" not in coll and "pmtiles:layers" not in coll
  assert sorted(coll["assets"]) == ["documentation", "provenance", "styles/default"]          # no data, no tiles
  assert not any(l["rel"] == "pmtiles" for l in coll["links"])
  assert {"rel": "related", "href": "../fao_major_areas/collection.json", "type": "application/json",
          "title": "Drawn by the map tiles of fao_major_areas"} in coll["links"]
  prov = json.loads((out / "provenance.json").read_text())
  assert prov["record_count"] == 2 and prov["sources"][0]["derived_from"][0]["slug"] == "mr_high_seas"
  assert prov["sources"][0]["derive"] == {"op": "intersect", "min_area_km2": 100.0, "min_part_km2": 0.0}


def test_the_readme_and_agents_files_tell_outside_agents_how_to_draw_a_display_collection(tmp_path, monkeypatch):
  out = build_synthetic(tmp_path, monkeypatch)
  for f in ("README.md", "AGENTS.md"):
    txt = " ".join((out / f).read_text().split())
    assert "no parquet or PMTiles" in txt
    assert '`kind: "derived"`' in txt and '"via": "fao_major_areas"' in txt and '"id_from": "fao_id"' in txt
    assert "index row's `source_id`" in txt and "FAOHS:21" in txt and "FAO:21" in txt
    assert "Do not mirror or redistribute" in txt


def test_the_layers_json_row_of_a_display_collection(tmp_path, monkeypatch):
  import importlib.util
  spec = importlib.util.spec_from_file_location("build_layers_json", ROOT / "scripts" / "build_layers_json.py")
  bl = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(bl)
  coll = json.loads((build_synthetic(tmp_path, monkeypatch) / "collection.json").read_text())
  assert bl.is_map_layer(coll)
  row = bl.layer_row(coll)
  assert row["kind"] == "derived" and row["display"] == {"via": "fao_major_areas", "id_from": "fao_id"}
  assert row["pmtiles"] is None and row["source_layer"] is None and row["raster"] is None and row["parquet"] is None
  assert row["n"] == 2 and row["place_type"] == "high_seas_area" and row["license"] == "CC-BY-4.0"


def test_publish_script_refuses_the_data_files_of_a_display_collection(tmp_path, monkeypatch):
  """publish_collections.sh's is_reference() reads gazetteer:reference from collection.json, which a display
  collection carries: its parquet goes to the private store, never the pub tree (and the upload step refuses it)."""
  out = build_synthetic(tmp_path, monkeypatch)
  script = (ROOT / "scripts" / "publish_collections.sh").read_text()
  line = next(l for l in script.splitlines() if l.startswith("is_reference()"))
  ok = subprocess.run(["bash", "-c", f'{line}\nis_reference "$1"', "_", str(out)])
  assert ok.returncode == 0
  (tmp_path / "plain").mkdir()
  (tmp_path / "plain" / "collection.json").write_text(json.dumps({"id": "x"}))
  no = subprocess.run(["bash", "-c", f'{line}\nis_reference "$1"', "_", str(tmp_path / "plain")])
  assert no.returncode == 1
  assert "REFUSED: reference collection $s has data files in the pub tree" in script


def test_is_reference_covers_reference_and_display_only():
  assert stac.is_reference(HS) and stac.is_reference(CFGS["mr_eez"]) and not stac.is_reference(FAO)


# staged outputs (skipped unless built) ----------------------------------------------------------------------------------

@pytest.mark.skipif(not (STAGING / "fao_major_areas" / "places.parquet").exists(), reason="fao_major_areas not built")
def test_staged_fao_major_areas():
  t = pq.read_table(STAGING / "fao_major_areas" / "places.parquet")
  ids = t.column("place_id").to_pylist()
  assert len(ids) == 19 and ids == sorted(ids, key=lambda i: int(i.split(":")[1]))
  assert {"FAO:21", "FAO:37", "FAO:88"} <= set(ids)
  assert set(t.column("F_LEVEL").to_pylist()) == {"MAJOR"}
  assert check_parquet(STAGING / "fao_major_areas" / "places.parquet", FAO) == []


@pytest.mark.skipif(not (STAGING / "fao_high_seas" / "places.parquet").exists(), reason="fao_high_seas not built")
def test_staged_fao_high_seas():
  t = pq.read_table(STAGING / "fao_high_seas" / "places.parquet")
  ids = t.column("place_id").to_pylist()
  assert len(ids) == 18 and "FAOHS:37" not in ids and "FAOHS:21" in ids          # all but the Mediterranean and Black Sea
  assert set(t.column("high_seas_id").to_pylist()) == {"MRGID:63203"}
  assert all(f"FAO:{i.split(':')[1]}" == f for i, f in zip(ids, t.column("fao_id").to_pylist()))
  assert check_parquet(STAGING / "fao_high_seas" / "places.parquet", HS) == []
