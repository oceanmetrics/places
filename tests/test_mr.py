"""Marine Regions (mr_*) rules: WFS fetch + annotation, MRGID ids, licence/attribution, antimeridian, staged outputs."""
import json
import re

import numpy as np
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import Polygon

from conftest import ROOT, STAGING, square
from gazetteer import fetch_wfs
from gazetteer.config import load_all
from gazetteer.geom import clean_geometry, max_edge_span
from gazetteer.pipeline import changed_sources
from gazetteer.table import build_rows
from gazetteer.validate import check_parquet, check_pmtiles

CFGS = {k: v for k, v in load_all(ROOT / "sources").items() if k.startswith("mr_")}
COUNTS = {"mr_eez": 285, "mr_territorial_seas": 230, "mr_contiguous_zones": 220, "mr_high_seas": 1, "mr_ecs": 147,
          "mr_goas": 10, "mr_world_heritage_marine": 60}
DOIS = {"mr_eez": "10.14284/632", "mr_territorial_seas": "10.14284/633", "mr_contiguous_zones": "10.14284/630",
        "mr_high_seas": "10.14284/696", "mr_ecs": "10.14284/697", "mr_goas": "10.14284/542",
        "mr_world_heritage_marine": "10.14284/592"}
PLACE_TYPES = {"mr_eez": "eez", "mr_territorial_seas": "territorial_sea", "mr_contiguous_zones": "contiguous_zone",
               "mr_high_seas": "high_seas", "mr_ecs": "ecs", "mr_goas": "ocean_sea", "mr_world_heritage_marine": "world_heritage"}
MRGID_ID = re.compile(r"^MRGID:\d+(:[a-z0-9-]+)?$")


# config rules ---------------------------------------------------------------------------------------------------------

def test_seven_cc_by_collections_and_none_of_the_gated_products():
  assert set(CFGS) == set(COUNTS)
  gated = {"iho", "lme", "meow", "longhurst", "contourite"}
  assert not any(g in slug for slug in CFGS for g in gated)


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_config_carries_licence_doi_citation_and_disclaimer(slug):
  c = CFGS[slug]
  assert c["license"] == "CC-BY-4.0" and c["license_url"].startswith("https://creativecommons.org/licenses/by/4.0")
  assert c["place_type"] == PLACE_TYPES[slug] and c["authority"] == "MRGID"
  assert f"https://doi.org/{DOIS[slug]}" in c["attribution"] and "MarineRegions.org" in c["attribution"]
  assert "no legal value" in " ".join(c["description"].split())
  src = c["sources"][0]
  assert src["kind"] == "wfs" and src["expected_count"] == COUNTS[slug]
  assert src["mr"]["doi"] == DOIS[slug] and src["mr"]["license"] == "CC-BY-4.0"
  assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", src["mr"]["released"])
  assert re.compile(c["place_id"]["pattern"]).fullmatch("MRGID:8325")


def test_goas_has_a_distinct_mrgid_for_each_of_its_ten_features():
  m = CFGS["mr_goas"]["sources"][0]["mrgid"]["map"]
  assert len(m) == 10 and len(set(m.values())) == 10 and m["Arctic Ocean"] == 1906 and m["Mediterranean Region"] == 4278


# annotate / ids -------------------------------------------------------------------------------------------------------

def test_mrgid_uri_is_the_canonical_http_form():
  assert fetch_wfs.mrgid_uri("8325") == "http://marineregions.org/mrgid/8325"


def test_a_repeated_mrgid_gets_a_deterministic_suffix_and_the_first_keeps_the_bare_id():
  assert fetch_wfs.assign_parts([7, 7, 9, 7], ["part", "buffer", "part", "buffer"]) == ["", ":buffer", "", ":buffer-2"]
  assert fetch_wfs.assign_parts([1, 2], ["part", "part"]) == ["", ""]


def test_mrgid_comes_from_the_field_even_as_a_string_or_from_the_name_map():
  assert fetch_wfs.resolve_mrgid({"mrgid": "26836"}, {"field": "mrgid"}) == 26836
  spec = {"lookup_field": "name", "map": {"Arctic Ocean": 1906}}
  assert fetch_wfs.resolve_mrgid({"name": "Arctic Ocean"}, spec) == 1906
  with pytest.raises(ValueError, match="no MRGID configured"):
    fetch_wfs.resolve_mrgid({"name": "Nowhere"}, spec)
  with pytest.raises(ValueError, match="without an MRGID"):
    fetch_wfs.resolve_mrgid({"mrgid": None}, {"field": "mrgid"})


def test_infer_type():
  assert fetch_wfs.infer_type([1, None, 3]) == "int"
  assert fetch_wfs.infer_type([1, 2.5]) == "float"
  assert fetch_wfs.infer_type(["a", 1]) == "string"
  assert fetch_wfs.infer_type([None, None]) == "string"


def _result(cfg, props_geoms):
  feats = [{"properties": dict(p), "geometry": g} for p, g in props_geoms]
  src = cfg["sources"][0]
  fields = fetch_wfs.annotate(feats, src)
  return fetch_wfs.SourceResult(features=feats, fields=fields, source_url="https://example.test/wfs", item_id=src["type_name"],
                                data_last_edit="2023-10-25T00:00:00Z", retrieved="2026-10-08T12:00:00Z",
                                record_count=len(feats), checksum="abc")


def test_every_row_has_mrgid_id_licence_attribution_and_the_mr_provenance_columns():
  cfg = CFGS["mr_eez"]
  res = _result(cfg, [({"mrgid": 8325, "geoname": "Fijian Exclusive Economic Zone", "area_km2": 1281000}, square(0, 0)),
                      ({"mrgid": 8444, "geoname": "United States Exclusive Economic Zone (American Samoa)", "area_km2": 405830},
                       square(5, 5))])
  rows, fields, dropped = build_rows(cfg, [res])
  assert [r["place_id"] for r in rows] == ["MRGID:8325", "MRGID:8444"] and not dropped
  for r in rows:
    assert MRGID_ID.fullmatch(r["place_id"]) and r["place_type"] == "eez" and r["license"] == "CC-BY-4.0"
    assert "10.14284/632" in r["attribution"] and r["attribution"].strip()
    assert r["mrgid_uri"] == f"http://marineregions.org/mrgid/{r['mrgid']}"
    assert (r["mr_product_version"], r["mr_product_doi"], r["mr_license"]) == ("12", "10.14284/632", "CC-BY-4.0")
    assert r["mr_product"].endswith("Exclusive Economic Zones (200NM)") and r["mr_modified"].year == 2023
  assert rows[0]["name"] == "Fijian Exclusive Economic Zone" and rows[0]["source_id"] == "8325"
  assert [f["name"] for f in fields][:8] == [n for n, _ in fetch_wfs.MR_FIELDS]


def test_two_features_sharing_an_mrgid_keep_place_id_unique():
  cfg = CFGS["mr_world_heritage_marine"]
  res = _result(cfg, [({"mrgid": "26836", "full_name": "Site", "buffer": "false"}, square(0, 0)),
                      ({"mrgid": "26836", "full_name": "Site", "buffer": "true"}, square(5, 5))])
  rows, _, _ = build_rows(cfg, [res])
  assert [r["place_id"] for r in rows] == ["MRGID:26836", "MRGID:26836:buffer"]


def test_goas_features_get_their_configured_mrgid_as_a_column():
  cfg = CFGS["mr_goas"]
  res = _result(cfg, [({"name": "Arctic Ocean", "area_km2": 1}, square(0, 0))])
  rows, _, _ = build_rows(cfg, [res])
  assert rows[0]["place_id"] == "MRGID:1906" and rows[0]["mrgid"] == 1906 and rows[0]["name_src"] == "Arctic Ocean"


# fetch paging (mock) --------------------------------------------------------------------------------------------------

class FakeResp:
  def __init__(self, text="", js=None):
    self.text, self._js, self.content, self.status_code = text, js, (text or json.dumps(js)).encode(), 200

  def json(self):
    return self._js

  def raise_for_status(self):
    pass


class FakeSession:
  def __init__(self, n, page_log):
    self.n, self.page_log = n, page_log
    self.headers = {}

  def get(self, url, params=None, **kw):
    if params.get("request") == "GetCapabilities":
      return FakeResp('<FeatureType xmlns:x="y"><Name>MarineRegions:eez</Name><Title>Exclusive Economic Zones (200 NM) (v12, world, 2023)</Title></FeatureType>')
    if params.get("resultType") == "hits":
      return FakeResp(f'<wfs:FeatureCollection numberMatched="{self.n}" numberReturned="0"/>')
    start, count = params["startIndex"], params["count"]
    self.page_log.append((start, count, params["srsName"], params["sortBy"], params["outputFormat"]))
    feats = [{"type": "Feature", "properties": {"mrgid": 100 + i, "geoname": f"Zone {i}", "area_km2": i},
              "geometry": shapely.geometry.mapping(shapely.MultiPolygon([square(i, 0)]))} for i in range(start, min(start + count, self.n))]
    return FakeResp(js={"type": "FeatureCollection", "features": feats})


def test_fetch_wfs_pages_serially_with_srs_sort_and_a_count_check():
  log = []
  src = {**CFGS["mr_eez"]["sources"][0], "page_size": 4, "expected_count": 10}
  r = fetch_wfs.fetch_wfs(src, delay=0, s=FakeSession(10, log))
  assert [p[0] for p in log] == [0, 4, 8] and {p[2:] for p in log} == {("EPSG:4326", "mrgid", "application/json")}
  assert r.record_count == 10 and len(r.features) == 10 and r.data_last_edit == "2023-10-25T00:00:00Z"
  assert r.extra["http"]["etag"] == "Exclusive Economic Zones (200 NM) (v12, world, 2023)|10"
  assert r.features[3]["properties"]["mrgid_uri"] == "http://marineregions.org/mrgid/103"


def test_fetch_wfs_fails_when_the_layer_pages_short():
  class Short(FakeSession):
    def get(self, url, params=None, **kw):
      if params.get("startIndex", 0) >= 4 and params.get("request") == "GetFeature" and "resultType" not in params:
        return FakeResp(js={"type": "FeatureCollection", "features": []})
      return super().get(url, params, **kw)
  with pytest.raises(RuntimeError, match="paged 4 features but the layer counts 10"):
    fetch_wfs.fetch_wfs({**CFGS["mr_eez"]["sources"][0], "page_size": 4}, delay=0, s=Short(10, []))


def test_change_detection_compares_layer_title_and_count():
  cfg = CFGS["mr_eez"]
  pub = {"sources": [{"http": {"etag": "Exclusive Economic Zones (200 NM) (v12, world, 2023)|285"}, "record_count": 285}]}
  same = {"data_last_edit": None, "record_count": 285, "etag": "Exclusive Economic Zones (200 NM) (v12, world, 2023)|285"}
  assert changed_sources(cfg, pub, [same]) is None
  new = {**same, "etag": "Exclusive Economic Zones (200 NM) (v13, world, 2026)|290"}
  assert "etag" in changed_sources(cfg, pub, [new])


# geometry: antimeridian and the pole edge -----------------------------------------------------------------------------

def test_a_polygon_jumping_the_dateline_is_split_at_180_like_fiji():
  fiji = Polygon([(176.0, -20.0), (179.0, -20.0), (-179.0, -20.0), (-176.0, -20.0), (-176.0, -15.0), (-179.0, -15.0),
                  (179.0, -15.0), (176.0, -15.0), (176.0, -20.0)])
  g = clean_geometry(fiji)
  assert g.bounds[0] == -180.0 and g.bounds[2] == 180.0
  assert len(g.geoms) == 2 and max_edge_span(g) < 180
  assert shapely.is_valid(g) and abs(g.area - 8 * 5) < 1e-6
  assert {round(p.bounds[0]) for p in g.geoms} == {-180, 176} and {round(p.bounds[2]) for p in g.geoms} == {-176, 180}


def test_a_cap_around_the_pole_is_kept_whole_regression_high_seas_arctic():
  # ring along y=90 from -180 to 180 (the planar edge of a polygon holding the pole) used to be read as a dateline jump
  cap = Polygon([(-180, 90), (180, 90), (180, 70), (0, 72), (-180, 70), (-180, 90)])
  g = clean_geometry(cap)
  assert len(g.geoms) == 1 and g.bounds == (-180.0, 70.0, 180.0, 90.0) and shapely.is_valid(g)
  assert max_edge_span(g) <= 180 and abs(g.area - cap.area) < 1e-9


# staged outputs (catalog/staging/<slug>/, built on the mini and rsynced back) -----------------------------------------

def staged(slug):
  d = STAGING / slug
  if not (d / "places.parquet").exists():
    pytest.skip(f"{slug} not built")
  return d


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_collection_passes_every_check_and_has_the_expected_count(slug):
  d = staged(slug)
  assert check_parquet(d / "places.parquet", CFGS[slug]) == [] and check_pmtiles(d / "places.pmtiles", slug) == []
  assert pq.ParquetFile(d / "places.parquet").metadata.num_rows == COUNTS[slug]
  coll = json.loads((d / "collection.json").read_text())
  assert coll["license"] == "CC-BY-4.0" and coll["id"] == slug and coll["gazetteer:attribution"]


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_every_row_has_licence_attribution_mrgid_and_mr_columns(slug):
  t = pq.read_table(staged(slug) / "places.parquet").drop_columns(["geometry", "bbox"]).to_pylist()
  assert len(t) == COUNTS[slug]
  for r in t:
    assert MRGID_ID.fullmatch(r["place_id"]) and r["place_id"].split(":")[1] == str(r["mrgid"])
    assert r["license"] == "CC-BY-4.0" and DOIS[slug] in r["attribution"] and "MarineRegions.org" in r["attribution"]
    assert r["mrgid_uri"] == f"http://marineregions.org/mrgid/{r['mrgid']}" and r["mr_license"] == "CC-BY-4.0"
    assert r["mr_product_doi"] == DOIS[slug] and r["mr_product"] and r["mr_product_version"] and r["mr_modified"]
    assert r["place_type"] == PLACE_TYPES[slug] and r["name"].strip()


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_no_geometry_crosses_180_and_all_stay_inside_the_world(slug):
  g = shapely.from_wkb(pq.read_table(staged(slug) / "places.parquet", columns=["geometry"]).column("geometry").to_pylist())
  b = shapely.bounds(g)
  assert b[:, 0].min() >= -180 and b[:, 2].max() <= 180 and b[:, 1].min() >= -90 and b[:, 3].max() <= 90
  assert max(max_edge_span(x) for x in g) <= 180
  assert shapely.is_valid(g).all()


def test_staged_fiji_eez_is_split_on_the_dateline():
  t = pq.read_table(staged("mr_eez") / "places.parquet", columns=["place_id", "geoname", "iso_ter1", "bbox", "geometry"]).to_pylist()
  fiji = [r for r in t if r["iso_ter1"] == "FJI" and "Exclusive" in r["geoname"]]
  assert fiji, "no Fiji EEZ in the layer"
  g = shapely.from_wkb(fiji[0]["geometry"])
  assert fiji[0]["place_id"].startswith("MRGID:") and len(g.geoms) >= 2
  assert fiji[0]["bbox"]["xmin"] == -180.0 and fiji[0]["bbox"]["xmax"] == 180.0
  east = [p for p in g.geoms if p.bounds[2] == 180.0]
  west = [p for p in g.geoms if p.bounds[0] == -180.0]
  assert east and west
  # the two halves meet on the meridian: their vertices on it span overlapping latitudes
  y_e = [y for p in east for x, y in p.exterior.coords if x == 180.0]
  y_w = [y for p in west for x, y in p.exterior.coords if x == -180.0]
  assert y_e and y_w and max(min(y_e), min(y_w)) < min(max(y_e), max(y_w))
  assert -24.5 < min(y_e) and max(y_e) < -12.0     # Fiji's EEZ lies between about 12 and 24 degrees south


def test_staged_russia_and_new_zealand_eez_cross_the_dateline_split():
  t = pq.read_table(staged("mr_eez") / "places.parquet", columns=["iso_ter1", "bbox"]).to_pylist()
  by = {}
  for r in t:
    by.setdefault(r["iso_ter1"], []).append(r["bbox"])
  for iso in ("RUS", "NZL", "USA"):
    assert any(b["xmin"] == -180.0 for b in by[iso]) and any(b["xmax"] == 180.0 for b in by[iso]), iso


def test_staged_goas_mrgids_are_the_configured_ones():
  t = pq.read_table(staged("mr_goas") / "places.parquet", columns=["place_id", "name_src"]).to_pylist()
  m = CFGS["mr_goas"]["sources"][0]["mrgid"]["map"]
  assert {r["name_src"]: r["place_id"] for r in t} == {k: f"MRGID:{v}" for k, v in m.items()}
