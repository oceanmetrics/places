"""the MarineCadastre first-15 collections: id patterns per authority, licence on every row, line geometry rules,
and checks on the staged outputs (skipped for a collection that was not built)."""
import re

import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import LineString, MultiLineString, Polygon

from conftest import ROOT, STAGING
from gazetteer.config import load_all, validate_config
from gazetteer.fmt import render
from gazetteer.geom import max_edge_span
from gazetteer.ids import build_place_ids, check_place_ids
from gazetteer.lines import clean_multiline_geometry, max_line_span, split_line_antimeridian
from gazetteer.status import resolve_status
from gazetteer.table import build_rows, to_table
from gazetteer.validate import check_parquet, check_pmtiles
from gazetteer.fetch import SourceResult

CFGS = load_all(ROOT / "sources")

# slug -> (features served 2026-10-08, geometry type id: 5 MultiLineString / 6 MultiPolygon)
MC15 = {
  "noaa_sanctuaries": (47, 6), "noaa_mpa_inventory": (981, 6), "noaa_nerrs": (30, 6), "noaa_marine_monuments": (32, 6),
  "noaa_state_lateral_boundaries": (19, 5), "noaa_state_submerged_lands": (483, 6), "noaa_maritime_limits": (246, 5),
  "noaa_hapc": (237, 6), "noaa_esa_critical_habitat": (2114, 6), "fws_critical_habitat_final": (803, 6),
  "fws_critical_habitat_proposed": (70, 6), "noaa_vessel_routing_measures": (327, 6), "noaa_submarine_cables": (2816, 6),
  "usace_danger_zones": (422, 6),
}
# slug -> (authority, a valid example id, an id that must not match)
IDS = {
  "noaa_sanctuaries": ("ONMS", "ONMS:chumash-heritage-national-marine-sanctuary", "ONMS:Chumash"),
  "noaa_mpa_inventory": ("MPA", "MPA:AK25", "MPA:"),
  "noaa_nerrs": ("NERRS", "NERRS:ACE", "NERRS:ace"),
  "noaa_marine_monuments": ("MC", "MC:monuments:mariana-trench", "MC:monument:x"),
  "noaa_state_lateral_boundaries": ("MC", "MC:state_lateral:23-33", "MC:state_lateral:23 - 33"),
  "noaa_state_submerged_lands": ("MC", "MC:submerged_lands:482", "MC:submerged_lands:x"),
  "noaa_maritime_limits": ("NOAA-OCS", "NOAA-OCS:B0322", "NOAA-OCS:322"),
  "noaa_hapc": ("NMFS", "NMFS:HAPC:12", "NMFS:CH:12"),
  "noaa_esa_critical_habitat": ("NMFS", "NMFS:CH:100061937:part", "NMFS:HAPC:1"),
  "fws_critical_habitat_final": ("FWS", "FWS:CH:4228", "FWS:CHP:4228"),
  "fws_critical_habitat_proposed": ("FWS", "FWS:CHP:6827", "FWS:CH:6827"),
  "noaa_vessel_routing_measures": ("MC", "MC:vrm:327", "MC:vrm:"),
  "noaa_submarine_cables": ("MC", "MC:cables:2816", "MC:cable:1"),
  "usace_danger_zones": ("USACE", "USACE:ME:334-50-a-1:part-2", "USACE:ME:334.50(a)"),
}


def staged(slug):
  d = STAGING / slug
  if not (d / "places.parquet").exists():
    pytest.skip(f"{slug} not built")
  return d


# config rules --------------------------------------------------------------------------------------------------------

def test_all_fourteen_configs_are_present_and_valid():
  assert set(MC15) <= set(CFGS)


@pytest.mark.parametrize("slug", sorted(MC15))
def test_license_attribution_and_controlled_place_type(slug):
  c = CFGS[slug]
  assert c["license"] == "CC-PDDC" and c["license_url"].startswith("https://")
  assert "Public domain" in c["attribution"] and "Processed by Ocean Metrics" in c["attribution"]
  assert len(c["license_note"].split()) > 5
  assert c["place_type"] in {"protected_area", "jurisdiction", "maritime_limit", "habitat", "restricted_area",
                             "navigation_measure", "infrastructure"}


@pytest.mark.parametrize("slug", sorted(IDS))
def test_id_pattern_per_authority(slug):
  authority, good, bad = IDS[slug]
  c = CFGS[slug]
  assert c["authority"] == authority
  pats = [(s.get("place_id") or c["place_id"])["pattern"] for s in c["sources"]]
  assert good.startswith(authority + ":")
  assert any(re.fullmatch(p, good) for p in pats)
  assert not any(re.fullmatch(p, bad) for p in pats)


@pytest.mark.parametrize("slug", sorted(MC15))
def test_source_points_at_the_item_and_expects_the_served_count(slug):
  c = CFGS[slug]
  assert sum(s["expected_count"] for s in c["sources"]) == MC15[slug][0]
  assert all(re.fullmatch(r"[0-9a-f]{32}", s["item_id"]) for s in c["sources"])


def test_a_config_with_an_unknown_geometry_type_is_rejected():
  with pytest.raises(ValueError, match="geometry_type"):
    validate_config({"slug": "x", "geometry_type": "Circle"})


# id, status and name rules (synthetic fixtures) ----------------------------------------------------------------------

def test_sanctuary_sections_get_a_second_id_segment_and_whole_sites_do_not():
  cfg = CFGS["noaa_sanctuaries"]["place_id"]
  attrs = [{"sitename": "Channel Islands National Marine Sanctuary", "unitname": "Santa Barbara Section"},
           {"sitename": "Chumash Heritage National Marine Sanctuary", "unitname": None}]
  ids = build_place_ids(cfg, attrs)
  assert ids == ["ONMS:channel-islands-national-marine-sanctuary:santa-barbara-section",
                 "ONMS:chumash-heritage-national-marine-sanctuary"]
  check_place_ids(ids, cfg["pattern"])
  assert render(CFGS["noaa_sanctuaries"]["name"], attrs[0]) == "Channel Islands National Marine Sanctuary - Santa Barbara Section"


def test_regression_danger_zone_repeats_are_suffixed_in_objectid_order_not_an_error():
  cfg = CFGS["usace_danger_zones"]["place_id"]
  attrs = [{"state": "ME", "boundaryidentifier": "334.50(a)(1)", "objectid": 9},
           {"state": "ME", "boundaryidentifier": "334.50(a)(1)", "objectid": 3},
           {"state": "ME", "boundaryidentifier": "334.50(a)(1)", "objectid": 7},
           {"state": "WA", "boundaryidentifier": "See RNC 18400 (Note B)", "objectid": 1}]
  ids = build_place_ids(cfg, attrs)
  assert ids == ["USACE:ME:334-50-a-1:part-2", "USACE:ME:334-50-a-1", "USACE:ME:334-50-a-1:part",
                 "USACE:WA:see-rnc-18400-note-b"]
  check_place_ids(ids, cfg["pattern"])


def test_regression_nmfs_float_ids_are_rounded_not_rendered_with_noise():
  cfg = CFGS["noaa_esa_critical_habitat"]["place_id"]
  attrs = [{"ID": 100062107.99999999, "OBJECTID": 5}, {"ID": 100062108.0, "OBJECTID": 6}, {"ID": 100000077.0, "OBJECTID": 1}]
  ids = build_place_ids(cfg, attrs)
  assert ids == ["NMFS:CH:100062108", "NMFS:CH:100062108:part", "NMFS:CH:100000077"]
  check_place_ids(ids, cfg["pattern"])


def test_template_without_dedupe_still_rejects_duplicates():
  with pytest.raises(ValueError, match="duplicate place_id"):
    build_place_ids({"template": "MC:x:{a}"}, [{"a": 1}, {"a": 1}])


def test_default_filter_names_the_unnamed_cable_areas():
  name = CFGS["noaa_submarine_cables"]["name"]
  assert render(name, {"shortname": None, "objectid": 7}) == "Submarine cable area (7)"
  assert render(name, {"shortname": "AMX1", "objectid": 8}) == "AMX1 (8)"


def test_nmfs_critical_habitat_status_comes_from_the_chstatus_attribute():
  st = CFGS["noaa_esa_critical_habitat"]["status"]
  assert resolve_status(st, {"CHSTATUS": "Final"}, "2025-02-18T00:00:00Z")[0] == "final"
  assert resolve_status(st, {"CHSTATUS": "Proposed"}, None)[0] == "proposed"
  assert resolve_status(st, {"CHSTATUS": None}, None)[0] == "unknown"           # default when the attribute is empty
  assert resolve_status({"value": "active", "source": "s", "date": "2025-01-01"}, {"CHSTATUS": "Final"}, None)[0] == "active"


# line geometry -------------------------------------------------------------------------------------------------------

def test_line_inside_the_world_is_unchanged():
  g = clean_multiline_geometry(LineString([(-125, 40), (-124, 41)]))
  assert g.geom_type == "MultiLineString" and len(g.geoms) == 1 and g.bounds == (-125, 40, -124, 41)


def test_line_jumping_the_antimeridian_is_split_at_180():
  out = split_line_antimeridian(LineString([(170, 50), (-170, 52)]))      # the short way crosses 180
  assert out.geom_type == "MultiLineString" and len(out.geoms) == 2
  assert out.bounds[0] == -180 and out.bounds[2] == 180 and max_line_span(out) < 180
  east = [g for g in out.geoms if g.bounds[0] >= 170][0]
  assert east.bounds[2] == 180 and abs(east.coords[-1][1] - 51.0) < 1e-9   # meets the meridian halfway in latitude


def test_line_past_180_is_split_not_dropped():
  out = clean_multiline_geometry(LineString([(178, 60), (182, 61)]))
  assert out.bounds[0] <= -178 and out.bounds[2] == 180 and len(out.geoms) == 2


def test_cleaning_drops_points_polygons_and_empty_lines():
  assert clean_multiline_geometry(None) is None
  assert clean_multiline_geometry(LineString()) is None
  assert clean_multiline_geometry(Polygon([(0, 0), (1, 0), (1, 1), (0, 0)])) is None


def test_edge_span_check_sees_lines_too():
  assert max_line_span(MultiLineString([[(179, 0), (-179, 1)]])) == 358
  assert max_edge_span(MultiLineString([[(179, 0), (-179, 1)]])) == 0       # the polygon helper ignores lines


def test_line_collection_rows_have_geom_type_multilinestring_and_licence(tmp_path):
  cfg = {**CFGS["noaa_maritime_limits"], "_sources_dir": str(tmp_path)}
  feats = [{"properties": {"BOUND_ID": "B0001", "REGION": "Alaska", "FEAT_TYPE": "Maritime Boundary", "APPRV_DATE": 1162512000000},
            "geometry": LineString([(179, 52), (-179, 53)])}]
  fields = [{"name": "BOUND_ID", "type": "string"}, {"name": "REGION", "type": "string"},
            {"name": "FEAT_TYPE", "type": "string"}, {"name": "APPRV_DATE", "type": "date"}]
  res = [SourceResult(features=feats, fields=fields, source_url=s["url"], component=s.get("component"),
                      data_last_edit=None, retrieved="2026-10-08T12:00:00Z", record_count=1, checksum="x")
         for s in cfg["sources"]]
  res[1:] = [SourceResult(features=[], fields=fields, source_url=r.source_url, component=r.component,
                          retrieved="2026-10-08T12:00:00Z", record_count=0, checksum="x") for r in res[1:]]
  rows, flds, dropped = build_rows(cfg, res)
  t = to_table(rows, flds)
  assert t.num_rows == 1 and not dropped
  assert t.column("geom_type").to_pylist() == ["MultiLineString"]
  assert t.column("place_id").to_pylist() == ["NOAA-OCS:B0001"]
  assert t.column("status_date").to_pylist() == ["2006-11-03"]
  assert t.column("license").to_pylist() == ["CC-PDDC"] and t.column("attribution").to_pylist()[0]
  g = shapely.from_wkb(t.column("geometry").to_pylist())[0]
  assert g.geom_type == "MultiLineString" and g.bounds[0] == -180 and g.bounds[2] == 180


# staged outputs ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slug", sorted(MC15))
def test_staged_parquet_and_pmtiles_pass_every_check(slug):
  d = staged(slug)
  assert check_parquet(d / "places.parquet", CFGS[slug]) == []
  assert check_pmtiles(d / "places.pmtiles", slug) == []


@pytest.mark.parametrize("slug", sorted(MC15))
def test_staged_count_geometry_and_licence_on_every_row(slug):
  d = staged(slug)
  t = pq.read_table(d / "places.parquet")
  n, type_id = MC15[slug]
  assert abs(t.num_rows - n) <= max(1, n // 50)                         # served count, minus any geometry-less feature
  assert set(shapely.get_type_id(shapely.from_wkb(t.column("geometry").to_pylist()))) == {type_id}
  assert set(t.column("license").to_pylist()) == {"CC-PDDC"}
  assert all(v.strip() for v in t.column("attribution").to_pylist())
  assert set(t.column("authority").to_pylist()) == {IDS[slug][0]}
  pats = [(s.get("place_id") or CFGS[slug]["place_id"])["pattern"] for s in CFGS[slug]["sources"]]
  assert all(any(re.fullmatch(p, i) for p in pats) for i in t.column("place_id").to_pylist())


@pytest.mark.parametrize("slug", sorted(MC15))
def test_staged_provenance_carries_the_item_licence_text(slug):
  import json
  d = staged(slug)
  prov = json.loads((d / "provenance.json").read_text())
  for s in prov["sources"]:
    assert all(s.get(k) not in (None, "") for k in ("source_url", "source_item_id", "retrieved", "record_count", "checksum"))
    assert s.get("source_license")                                       # the item's licenseInfo, verbatim
    if slug != "noaa_esa_critical_habitat":                               # that item has no accessInformation
      assert s.get("source_attribution")


def test_staged_california_sanctuaries_and_antimeridian_lines():
  d = staged("noaa_sanctuaries")
  ids = set(pq.read_table(d / "places.parquet", columns=["place_id"]).column("place_id").to_pylist())
  assert "ONMS:chumash-heritage-national-marine-sanctuary" in ids
  assert "ONMS:channel-islands-national-marine-sanctuary:santa-barbara-section" in ids


def test_staged_maritime_limits_have_three_components_and_cross_the_dateline_in_two_parts():
  d = staged("noaa_maritime_limits")
  t = pq.read_table(d / "places.parquet", columns=["component", "bbox"]).to_pylist()
  assert {r["component"] for r in t} == {"territorial_sea_12nm", "contiguous_zone_24nm", "eez_200nm"}
  assert any(r["bbox"]["xmin"] == -180.0 and r["bbox"]["xmax"] == 180.0 for r in t)


def test_staged_nmfs_critical_habitat_statuses_are_the_three_source_values():
  d = staged("noaa_esa_critical_habitat")
  st = set(pq.read_table(d / "places.parquet", columns=["status"]).column("status").to_pylist())
  assert st == {"final", "proposed", "designated"}
