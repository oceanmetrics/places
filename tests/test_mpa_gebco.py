"""rules of the mpa_inventory (NOAA MPA Inventory) and gebco_undersea (GEBCO Gazetteer) collections: ids, the licence on
every row, native fields kept, mixed point / line / polygon geometry; plus checks on their staged outputs."""
import json
import re

import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, Polygon

from conftest import ROOT, STAGING, square
from gazetteer.config import load_all
from gazetteer.fetch import SourceResult
from gazetteer.mixed import clean_mixed_geometry, max_span_any, morton_order
from gazetteer.stac import style_json
from gazetteer.table import build_rows, geo_metadata, to_table, write_geoparquet
from gazetteer.tiles import read_pmtiles
from gazetteer.validate import check_parquet, check_pmtiles

CFGS = load_all(ROOT / "sources")
MPA, GEB = CFGS["mpa_inventory"], CFGS["gebco_undersea"]
MPA_PLAIN, GEB_PLAIN = {**MPA, "spatial_sort": False}, {**GEB, "spatial_sort": False}      # input order, for row-by-row asserts
GEBCO_CITATION = "IHO-IOC GEBCO Gazetteer of Undersea Feature Names, www.gebco.net"


def result(feats, fields, url="https://example.test/FeatureServer/0", edit="2025-01-15T18:28:55Z"):
  return SourceResult(features=[{"properties": p, "geometry": g} for p, g in feats],
                      fields=[{"name": n, "type": t} for n, t in fields], source_url=url, item_id="item",
                      data_last_edit=edit, retrieved="2026-10-08T12:00:00Z", record_count=len(feats), checksum="abc")


MPA_FIELDS = [("FID", "int"), ("Site_ID", "string"), ("Site_Name", "string"), ("State", "string"), ("ProSeasID", "string"),
              ("WDPA_Cd", "int"), ("AreaKm", "float")]


def mpa_rows(feats):
  return build_rows(MPA_PLAIN, [result(feats, MPA_FIELDS)])


# config -------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("cfg,prefix,ptype", [(MPA, "MPAINV:", "mpa"), (GEB, "GEBCO:", "undersea_feature")])
def test_collection_declares_licence_attribution_id_pattern_and_place_type(cfg, prefix, ptype):
  assert cfg["license"] and cfg["license_url"].startswith("https://") and len(cfg["attribution"].split()) > 5
  assert cfg["place_type"] == ptype and cfg["authority"] == prefix.rstrip(":")
  pat = cfg["place_id"]["pattern"]
  assert re.fullmatch(pat, prefix + "123") and not re.fullmatch(pat, "OTHER:123")
  assert all(s["url"].startswith("https://services2.arcgis.com/C8EMgrsFcRFL6LrL/") for s in cfg["sources"])


def test_mpa_inventory_is_public_domain_and_one_polygon_layer():
  assert MPA["license"] == "CC-PDDC" and "Public domain" in MPA["attribution"] and len(MPA["sources"]) == 1
  assert MPA["sources"][0]["expected_count"] == 981 and not MPA.get("mixed_geometry")


def test_gebco_licence_text_is_recorded_verbatim_from_the_item():
  note = " ".join(GEB["license_note"].split())
  assert f'"Please include the following citation when data from the gazetteer are used or reproduced in reports, presentations and other products: {GEBCO_CITATION}"' in note
  assert GEBCO_CITATION in GEB["attribution"] and "IHO Data Centre for Digital Bathymetry" in note
  assert [s["component"] for s in GEB["sources"]] == ["polygon", "line", "point"]    # the first keeps a shared bare id
  assert GEB["mixed_geometry"] and GEB["id_collisions"] == "suffix_component"


# mpa_inventory rules ------------------------------------------------------------------------------------------------

def test_mpa_ids_names_and_every_native_field_including_the_crosswalk_keys_are_kept():
  rows, fields, dropped = mpa_rows([
    ({"FID": 1, "Site_ID": "CA123", "Site_Name": "Point Lobos SMR", "State": "CA", "ProSeasID": "PS0001", "WDPA_Cd": 555, "AreaKm": 2.5},
     square(-122, 36))])
  r = rows[0]
  assert r["place_id"] == "MPAINV:CA123" and r["source_id"] == "CA123" and r["name"] == "Point Lobos SMR"
  assert r["place_type"] == "mpa" and r["authority"] == "MPAINV" and r["geom_type"] == "MultiPolygon"
  assert (r["ProSeasID"], r["WDPA_Cd"], r["Site_ID"], r["State"], r["AreaKm"], r["FID"]) == ("PS0001", 555, "CA123", "CA", 2.5, 1)
  assert [f["name"] for f in fields] == [n for n, _ in MPA_FIELDS] and dropped == []


def test_mpa_missing_crosswalk_ids_stay_null():
  rows, *_ = mpa_rows([({"FID": 2, "Site_ID": "FL9", "Site_Name": "X", "State": "FL", "ProSeasID": None, "WDPA_Cd": None, "AreaKm": 1.0}, square(-80, 25))])
  assert rows[0]["ProSeasID"] is None and rows[0]["WDPA_Cd"] is None


def test_mpa_duplicate_site_id_and_a_malformed_one_are_rejected():
  dup = [({"FID": i, "Site_ID": "CA1", "Site_Name": "A"}, square(0, 0)) for i in (1, 2)]
  with pytest.raises(ValueError, match="duplicate"):
    mpa_rows(dup)
  with pytest.raises(ValueError, match="do not match"):
    mpa_rows([({"FID": 1, "Site_ID": "CA 1/2", "Site_Name": "A"}, square(0, 0))])


def test_mpa_licence_and_attribution_on_every_row_and_dateline_polygon_is_split():
  wrapped = Polygon([(179, 20), (-179, 20), (-179, 21), (179, 21), (179, 20)])
  rows, fields, _ = mpa_rows([({"FID": 1, "Site_ID": "MNM1", "Site_Name": "Papahanaumokuakea"}, wrapped),
                              ({"FID": 2, "Site_ID": "CA1", "Site_Name": "B"}, square(-122, 36))])
  t = to_table(rows, fields)
  assert set(t.column("license").to_pylist()) == {"CC-PDDC"}
  assert all("Marine Protected Areas Center" in a for a in t.column("attribution").to_pylist())
  g = shapely.from_wkb(t.column("geometry").to_pylist())[0]
  assert len(g.geoms) == 2 and g.bounds[0] == -180 and g.bounds[2] == 180


# gebco_undersea rules -----------------------------------------------------------------------------------------------

GEB_FIELDS = [("NAME", "string"), ("TYPE", "string"), ("FEATURE_ID", "int"), ("OBJECTID", "int")]


def gebco(poly=(), line=(), point=()):
  def feats(items):
    return [({"NAME": n, "TYPE": ty, "FEATURE_ID": fid, "OBJECTID": oid}, g) for oid, (n, ty, fid, g) in enumerate(items, 1)]
  return build_rows(GEB_PLAIN, [result(feats(poly), GEB_FIELDS), result(feats(line), GEB_FIELDS), result(feats(point), GEB_FIELDS)])


def test_gebco_feature_id_is_the_id_and_a_point_twin_of_a_polygon_gets_a_suffix():
  rows, _, _ = gebco(poly=[("Satsuma", "Seamount", 2741, square(140, 30))],
                     point=[("Satsuma", "Seamount", 2741, Point(140.5, 30.5)), ("Lone", "Bank", 77, Point(1, 1))])
  by = {r["place_id"]: r for r in rows}
  assert sorted(by) == ["GEBCO:2741", "GEBCO:2741:point", "GEBCO:77"]
  assert by["GEBCO:2741"]["component"] == "polygon" and by["GEBCO:2741"]["geom_type"] == "MultiPolygon"
  assert by["GEBCO:2741:point"]["component"] == "point" and by["GEBCO:2741:point"]["geom_type"] == "MultiPoint"
  assert {r["source_id"] for r in rows} == {"2741", "77"}                 # the suffix is in place_id only


def test_gebco_bare_id_goes_to_the_first_configured_source_not_the_first_fetched():
  rows, _, _ = gebco(poly=[("Emperor", "Seamount Chain", 904, square(170, 40))],
                     line=[("Emperor", "Seamount Chain", 904, LineString([(170, 40), (171, 41)]))],
                     point=[("Emperor", "Seamount Chain", 904, Point(170, 40))])
  assert {r["place_id"]: r["component"] for r in rows} == {"GEBCO:904": "polygon", "GEBCO:904:line": "line", "GEBCO:904:point": "point"}


def test_gebco_name_is_name_plus_generic_term_and_the_native_name_is_kept_as_name_src():
  rows, fields, _ = gebco(point=[(" Sultanah", "Canyon", 1, Point(0, 0)), ("Acapulco", "Seamounts", 2, Point(1, 1))])
  assert [r["name"] for r in rows] == ["Sultanah Canyon", "Acapulco Seamounts"]
  assert rows[0]["NAME_src"] == " Sultanah" and rows[0]["TYPE"] == "Canyon" and rows[0]["FEATURE_ID"] == 1
  assert "NAME_src" in [f["name"] for f in fields] and "NAME" not in [f["name"] for f in fields]


def test_gebco_every_row_carries_licence_attribution_and_a_matching_geom_type(tmp_path):
  rows, fields, _ = gebco(poly=[("A", "Bank", 1, square(0, 0))], line=[("B", "Ridge", 2, LineString([(0, 0), (1, 1)]))],
                          point=[("C", "Hill", 3, Point(0, 0))])
  t = to_table(rows, fields)
  assert set(t.column("license").to_pylist()) == {"LicenseRef-IHO-IOC-GEBCO-Gazetteer"}
  assert all(GEBCO_CITATION in a for a in t.column("attribution").to_pylist())
  assert t.column("geom_type").to_pylist() == ["MultiPolygon", "MultiLineString", "MultiPoint"]
  assert [g.geom_type for g in shapely.from_wkb(t.column("geometry").to_pylist())] == t.column("geom_type").to_pylist()
  path = tmp_path / "places.parquet"
  geo = write_geoparquet(t, path, {"sources": [], "slug": "gebco_undersea"})
  assert geo["columns"]["geometry"]["geometry_types"] == ["MultiLineString", "MultiPoint", "MultiPolygon"]
  assert "orientation" not in geo["columns"]["geometry"] and geo_metadata(t) == geo
  assert check_parquet(path, GEB) == []


def test_check_parquet_flags_a_geom_type_that_disagrees_with_the_geometry(tmp_path):
  rows, fields, _ = gebco(point=[("C", "Hill", 3, Point(0, 0))])
  rows[0]["geom_type"] = "MultiPolygon"
  path = tmp_path / "bad.parquet"
  write_geoparquet(to_table(rows, fields), path, {"sources": []})
  assert any("geom_type column does not match" in p for p in check_parquet(path, GEB))


def test_a_polygon_collection_still_rejects_a_line_row(tmp_path):
  rows, fields, _ = gebco(line=[("B", "Ridge", 2, LineString([(0, 0), (1, 1)]))])
  path = tmp_path / "lines.parquet"
  write_geoparquet(to_table(rows, fields), path, {"sources": []})
  assert check_parquet(path, GEB) == []
  assert any("not all MultiPolygon" in p for p in check_parquet(path, {**GEB, "mixed_geometry": False}))


# mixed geometry cleaning --------------------------------------------------------------------------------------------

def test_points_become_multipoint_and_lines_multilinestring():
  assert clean_mixed_geometry(Point(1, 2)).geom_type == "MultiPoint"
  assert clean_mixed_geometry(MultiPoint([(1, 2), (3, 4)])).geom_type == "MultiPoint"
  assert clean_mixed_geometry(LineString([(0, 0), (1, 1)])).geom_type == "MultiLineString"
  assert clean_mixed_geometry(square(0, 0)).geom_type == "MultiPolygon"
  assert clean_mixed_geometry(None) is None and clean_mixed_geometry(Point()) is None


def test_line_jumping_the_dateline_is_split_at_exactly_180():
  out = clean_mixed_geometry(LineString([(170, 10), (-170, 12)]))
  assert out.geom_type == "MultiLineString" and len(out.geoms) == 2
  assert out.bounds[0] == -180 and out.bounds[2] == 180 and max_span_any(out) < 180
  xs = sorted(round(c[0], 6) for g in out.geoms for c in g.coords)
  assert xs[0] == -180 and xs[1] == -170 and xs[2] == 170 and xs[3] == 180
  assert [round(c[1], 6) for g in out.geoms for c in g.coords if abs(c[0]) == 180] == [11.0, 11.0]    # the cut is at lat 11


def test_line_already_split_by_the_server_is_unchanged_and_snaps_to_the_meridian():
  server = MultiLineString([LineString([(179.9, 5), (179.99999, 6)]), LineString([(-179.99999, 6), (-179.9, 7)])])
  out = clean_mixed_geometry(server)
  assert len(out.geoms) == 2 and out.bounds[0] == -180 and out.bounds[2] == 180
  assert clean_mixed_geometry(LineString([(10, 0), (20, 5)])).wkt == "MULTILINESTRING ((10 0, 20 5))"


def test_polygon_beats_line_beats_point_in_a_geometry_collection():
  gc = GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)]), square(0, 0)])
  assert clean_mixed_geometry(gc).geom_type == "MultiPolygon"
  assert clean_mixed_geometry(GeometryCollection([Point(0, 0), LineString([(0, 0), (1, 1)])])).geom_type == "MultiLineString"


def test_max_span_any_sees_a_line_segment_that_jumps():
  assert max_span_any(LineString([(170, 0), (-170, 0)])) == 340 and max_span_any(Point(1, 1)) == 0.0


def test_mixed_style_has_a_layer_per_geometry_kind_and_the_default_style_is_unchanged():
  kinds = {l["type"]: l["filter"][2] for l in style_json("gebco_undersea", 8, "Mixed")["layers"] if l["type"] != "line"}
  assert kinds == {"fill": "Polygon", "circle": "Point"}
  assert [l["filter"][2] for l in style_json("gebco_undersea", 8, "Mixed")["layers"] if l["type"] == "line"] == ["Polygon", "LineString"]
  assert [l["type"] for l in style_json("x", 5)["layers"]] == ["fill", "line"]


def test_spatial_sort_clusters_neighbours_and_is_stable():
  pts = [Point(-120, 35), Point(150, -40), Point(-121, 36), Point(151, -41), Point(-120.5, 35.5)]
  order = morton_order(pts)
  assert sorted(order) == [0, 1, 2, 3, 4]
  west = [i for i, k in enumerate(order) if k in (0, 2, 4)]
  assert west == list(range(west[0], west[0] + 3))                 # the three western points are contiguous
  assert morton_order([Point(1, 1)] * 3) == [0, 1, 2]              # ties keep the input order


def test_spatial_sort_is_applied_only_when_the_collection_asks_for_it():
  feats = [({"FID": i, "Site_ID": f"CA{i}", "Site_Name": "x"}, sq) for i, sq in
           [(1, square(-120, 35)), (2, square(150, -40)), (3, square(-121, 36)), (4, square(151, -41))]]
  plain, *_ = build_rows(MPA_PLAIN, [result(feats, MPA_FIELDS)])
  sorted_rows, *_ = build_rows(MPA, [result(feats, MPA_FIELDS)])
  assert [r["Site_ID"] for r in plain] == ["CA1", "CA2", "CA3", "CA4"]
  ids = [r["Site_ID"] for r in sorted_rows]
  assert sorted(ids) == ["CA1", "CA2", "CA3", "CA4"] and ids != ["CA1", "CA2", "CA3", "CA4"]
  assert {frozenset(ids[:2]), frozenset(ids[2:])} == {frozenset({"CA1", "CA3"}), frozenset({"CA2", "CA4"})}    # neighbours adjacent


def test_spatial_sort_puts_globe_spanning_features_last_so_they_do_not_stretch_row_groups():
  geoms = [LineString([(-180, 10), (180, 12)]), Point(0, 0), Point(100, 50), LineString([(-179, 1), (-178, 2)])]
  order = morton_order(geoms)
  assert order[-1] == 0 and sorted(order) == [0, 1, 2, 3]


def test_a_custom_licence_is_declared_other_in_stac_and_spdx_style_on_the_rows():
  assert GEB["stac_license"] == "other" and GEB["license"].startswith("LicenseRef-") and GEB["license_url"].startswith("https://")
  assert not MPA.get("stac_license")


# staged outputs (skipped when the collection was not built) ---------------------------------------------------------

COUNTS = {"mpa_inventory": 981, "gebco_undersea": 5412}


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
  assert coll["id"] == slug and coll["license"] == (CFGS[slug].get("stac_license") or CFGS[slug]["license"]) and coll["geoparquet:feature_count"] == COUNTS[slug]
  assert coll["gazetteer:attribution"] and set(coll["assets"]) >= {"places", "places-tiles", "provenance"}
  _, meta = read_pmtiles(d / "places.pmtiles")
  assert meta["attribution"] == coll["gazetteer:attribution"] and [lyr["id"] for lyr in meta["vector_layers"]] == [slug]


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_provenance_has_the_six_fields_and_the_item_licence_text(slug):
  prov = json.loads((staged(slug) / "provenance.json").read_text())
  for s in prov["sources"]:
    assert all(s.get(k) not in (None, "") for k in ("source_url", "source_item_id", "data_last_edit", "retrieved", "record_count", "checksum"))
    assert s.get("source_license") and s.get("source_attribution")


def test_staged_mpa_inventory_keeps_the_crosswalk_keys_and_has_unique_site_ids():
  d = staged("mpa_inventory")
  t = pq.read_table(d / "places.parquet", columns=["place_id", "Site_ID", "ProSeasID", "WDPA_Cd", "place_type", "geom_type"])
  assert len(set(t.column("place_id").to_pylist())) == 981
  assert all(p == f"MPAINV:{s}" for p, s in zip(t.column("place_id").to_pylist(), t.column("Site_ID").to_pylist()))
  assert set(t.column("place_type").to_pylist()) == {"mpa"} and set(t.column("geom_type").to_pylist()) == {"MultiPolygon"}
  assert sum(v is not None for v in t.column("ProSeasID").to_pylist()) > 100 and sum(v is not None for v in t.column("WDPA_Cd").to_pylist()) > 100
  names = pq.ParquetFile(d / "places.parquet").schema_arrow.names
  assert len(names) >= 15 + 35 - 3 and "ProSeasID" in names and "WDPA_Cd" in names


def test_staged_gebco_has_all_three_geometry_types_and_the_verbatim_citation():
  d = staged("gebco_undersea")
  t = pq.read_table(d / "places.parquet", columns=["place_id", "component", "geom_type", "FEATURE_ID", "license", "attribution"]).to_pylist()
  by_comp = {c: sum(r["component"] == c for r in t) for c in ("polygon", "line", "point")}
  assert by_comp == {"polygon": 1652, "line": 1128, "point": 2632}
  assert {r["geom_type"] for r in t} == {"MultiPolygon", "MultiLineString", "MultiPoint"}
  assert all(GEBCO_CITATION in r["attribution"] for r in t) and {r["license"] for r in t} == {GEB["license"]}
  bare = [r for r in t if ":" not in r["place_id"].split("GEBCO:")[1]]
  assert all(r["place_id"] == f"GEBCO:{r['FEATURE_ID']}" for r in bare)
  assert {r["place_id"].rsplit(":", 1)[1] for r in t if r["place_id"].count(":") == 2} <= {"line", "point"}
  prov = json.loads((d / "provenance.json").read_text())
  assert GEBCO_CITATION in re.sub(r"<[^>]+>", "", prov["sources"][0]["source_license"])     # the item licenseInfo, kept as served (HTML)
