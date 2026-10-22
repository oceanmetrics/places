"""scripts/build_layers_json.py: the exact manifest row for a synthetic collection, the merge and the offline paths."""
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_layers_json.py"
spec = importlib.util.spec_from_file_location("build_layers_json", SCRIPT)
bl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bl)

COLL = {
  "type": "Collection", "id": "acme_leases", "stac_version": "1.1.0", "title": "Acme leases",
  "description": "x", "license": "CC-PDDC",
  "links": [
    {"rel": "pmtiles", "href": "./places.pmtiles", "type": "application/vnd.pmtiles", "pmtiles:layers": ["acme_leases"]},
    {"rel": "license", "href": "https://example.org/pd", "type": "text/html"},
  ],
  "assets": {"places-tiles": {"href": "./places.pmtiles", "type": "application/vnd.pmtiles"}},
  "geoparquet:geometry_type": "MultiPolygon", "geoparquet:feature_count": 7, "table:row_count": 7,
  "updated": "2026-10-01T12:00:00Z", "pmtiles:layers": ["acme_leases"],
  "extent": {"spatial": {"bbox": [[-125.0, 32.0, -117.0, 42.0]]}},
  "providers": [{"name": "Acme Agency", "roles": ["producer", "licensor"], "url": "https://acme.example/"},
                {"name": "Ocean Metrics LLC", "roles": ["processor", "host"], "url": "https://oceanmetrics.io"}],
  "gazetteer:authority": "ACME", "gazetteer:place_type": "lease",
  "gazetteer:attribution": "Acme Agency, via   MarineCadastre. Public domain. Processed by Ocean Metrics.",
  "gazetteer:provenance": {"version": "1.0.3"},
}


def test_row_exact():
  row = bl.layer_row(COLL)
  assert row == {
    "slug": "acme_leases", "title": "Acme leases", "collection": "acme_leases", "kind": "vector", "raster": None, "display": None,
    "pmtiles": "https://storage.oceanmetrics.io/gazetteer/acme_leases/places.pmtiles",
    "source_layer": "acme_leases", "geom_type": "MultiPolygon", "n": 7,
    "updated": "2026-10-01T12:00:00Z", "version": "1.0.3",
    "paint": {"fill": {"fill-color": "#e08a1e", "fill-opacity": 0.45},
              "line": {"line-color": "#a85f00", "line-width": 1}},
    "authority": "ACME", "place_type": "lease", "bbox": [-125.0, 32.0, -117.0, 42.0],
    "attribution": "Acme Agency, via MarineCadastre. Public domain. Processed by Ocean Metrics.",
    "attribution_html": '<a href="https://acme.example/">Acme Agency</a>, via MarineCadastre. Public domain. Processed by Ocean Metrics.',
    "license": "CC-PDDC", "license_url": "https://example.org/pd",
    "citation": "Acme Agency, via MarineCadastre. Public domain. Processed by Ocean Metrics. Acme leases, v1.0.3. "
                "Ocean Metrics gazetteer, 2026. https://storage.oceanmetrics.io/gazetteer/acme_leases/",
    "source_link": None,
    # an older collection (no layer status, no parquet asset, no ledger) keeps the new keys, all null
    "status": None, "status_history": None, "status_label": None, "search_rank": 0, "created": None, "source_date": None,
    "parquet": None, "parquet_sha256": None, "h3": None,
    "access": "public",                       # no `gazetteer:access` in an older collection
  }


REF = {
  "type": "Collection", "id": "mr_eez", "stac_version": "1.1.0", "title": "Marine Regions EEZ (v12)", "license": "CC-BY-4.0",
  "links": [], "assets": {}, "geoparquet:geometry_type": "MultiPolygon", "geoparquet:feature_count": 285,
  "extent": {"spatial": {"bbox": [[-180.0, -85.5, 180.0, 87.0]]}},
  "gazetteer:authority": "MRGID", "gazetteer:place_type": "eez",
  "gazetteer:attribution": "Flanders Marine Institute (2023). Maritime Boundaries Geodatabase, version 12.",
  "gazetteer:raster": {"tiles": "https://geo.example/wmts?LAYER=eez&TILEMATRIX=EPSG:900913:{z}&TILEROW={y}&TILECOL={x}",
                       "maxzoom": 12, "link": "https://www.marineregions.org/eez.php"},
}


def test_reference_collection_is_a_raster_row_with_no_files_of_ours():
  # marine regions asked us not to republish their products (2026-10-16): the map draws their own tiles
  row = bl.layer_row(REF)
  assert row["kind"] == "raster"
  assert row["raster"] == {"tiles": [REF["gazetteer:raster"]["tiles"]], "tile_size": 256, "minzoom": 0, "maxzoom": 12,
                           "link": "https://www.marineregions.org/eez.php", "feature_url": None,
                           "info_url": None, "info_id": None}
  assert row["pmtiles"] is None and row["source_layer"] is None and row["parquet"] is None and row["h3"] is None
  assert row["paint"] == {"raster": {"raster-opacity": 0.8}}
  assert row["n"] == 285 and row["license"] == "CC-BY-4.0"
  assert bl.is_map_layer(REF) and not bl.has_pmtiles(REF)
  assert not bl.is_map_layer({**REF, "gazetteer:raster": {"tiles": []}})


def test_source_link_from_the_collection_or_its_publisher_page():
  # every row links back to its source gazetteer (marine regions, navigator) for credit (2026-10-19)
  assert bl.source_link({**REF, "gazetteer:source_link": {"href": "https://www.marineregions.org/", "title": "Marine Regions"}}) \
    == {"href": "https://www.marineregions.org/", "title": "Marine Regions"}
  old = {**COLL, "links": COLL["links"] + [{"rel": "via", "href": "https://acme.example/data", "type": "text/html",
                                              "title": "Upstream publisher page"}]}
  assert bl.source_link(old) == {"href": "https://acme.example/data", "title": "Acme Agency"}
  assert bl.layer_row(old)["source_link"] == {"href": "https://acme.example/data", "title": "Acme Agency"}


def test_h3_is_advertised_only_for_the_parquet_it_was_built_from(tmp_path):
  rows = [{"slug": "a", "parquet_sha256": SHA_NEW}, {"slug": "b", "parquet_sha256": SHA_NEW},
          {"slug": "c", "parquet_sha256": None}, {"slug": "d", "parquet_sha256": SHA_NEW}]
  mans = {"a": {"places_sha256": SHA_NEW}, "b": {"places_sha256": SHA_OLD}, "c": {"places_sha256": None}}
  got = bl.attach_h3(rows, mans, "https://x.test/g/")
  assert [r["h3"] for r in got] == ["https://x.test/g/a/h3/membership.json", None, None, None]
  # the local build wins over the published one; a slug with neither is absent
  (tmp_path / "a" / "h3").mkdir(parents=True)
  (tmp_path / "a" / "h3" / "membership.json").write_text(json.dumps({"places_sha256": "local"}))
  pub = {"https://x.test/g/a/h3/membership.json": {"places_sha256": "pub"},
         "https://x.test/g/b/h3/membership.json": {"places_sha256": "pub"}}
  def fetch(u):
    if u not in pub:
      raise OSError("404")
    return pub[u]
  assert bl.h3_manifests(["a", "b", "c"], tmp_path, "https://x.test/g/", fetch) == \
    {"a": {"places_sha256": "local"}, "b": {"places_sha256": "pub"}}


SHA_OLD, SHA_NEW = "a" * 64, "b" * 64
NOTICE = "https://boem.test/notice"
RESCINDED = {
  **COLL, "id": "boem_wind_planning_rescinded", "title": "BOEM offshore wind planning areas",
  "assets": {**COLL["assets"], "places": {"href": "./places.parquet", "type": "application/vnd.apache.parquet",
                                          "file:checksum": "1220" + SHA_NEW, "roles": ["data"]}},
  "gazetteer:status": {"value": "rescinded", "date": "2025-07-30", "source": NOTICE, "note": "BOEM notice"},
  "gazetteer:status_history": [{"date": "2025-07-30", "value": "rescinded", "source": NOTICE, "note": "BOEM notice"}],
  "gazetteer:provenance": {"version": "1.1.0", "sources": [
    {"component": "outline", "data_last_edit": "2025-02-20T16:17:31Z"},
    {"component": "block", "data_last_edit": "2025-02-20T16:28:20Z"}, {"component": "x", "data_last_edit": None}]},
}
LEDGER = {"current_version": "1.0.0", "versions": [
  {"version": "1.0.0", "created": "2026-10-08T14:58:54.296318Z", "assets": {"places.parquet": {"sha256": SHA_OLD}}}]}


def test_row_layer_status_versions_and_parquet_pin():
  row = bl.layer_row(RESCINDED, ledger=LEDGER)
  sub = {k: row[k] for k in ("title", "status", "status_history", "status_label", "created", "updated", "source_date",
                             "version", "parquet", "parquet_sha256")}
  assert sub == {
    "title": "BOEM offshore wind planning areas",
    "status": {"value": "rescinded", "date": "2025-07-30", "source": NOTICE, "note": "BOEM notice"},
    "status_history": [{"date": "2025-07-30", "value": "rescinded", "source": NOTICE, "note": "BOEM notice"}],
    "status_label": "rescinded 2025-07-30", "created": "2026-10-08", "updated": "2026-10-01T12:00:00Z",
    "source_date": "2025-02-20", "version": "1.1.0",
    "parquet": "https://storage.oceanmetrics.io/gazetteer/boem_wind_planning_rescinded/places.parquet",
    # 1.1.0 is staged, not in the ledger yet: the collection's own checksum
    "parquet_sha256": SHA_NEW}


def test_parquet_sha256_is_the_ledger_entry_for_the_rows_version():
  coll = {**RESCINDED, "gazetteer:provenance": {**RESCINDED["gazetteer:provenance"], "version": "1.0.0"}}
  assert bl.layer_row(coll, ledger=LEDGER)["parquet_sha256"] == SHA_OLD
  assert bl.parquet_sha256({"assets": {}}, "1.0.0", None) is None


def test_status_label_underscores_become_spaces():
  assert bl.status_label({"value": "draft_proposed", "date": "2025-11-20"}) == "draft proposed 2025-11-20"
  assert bl.status_label({"value": "settlement_pending", "date": ""}) == "settlement pending"
  assert bl.status_label(None) is None and bl.status_label({}) is None


def test_local_rows_take_created_from_the_published_ledger(tmp_path):
  d = tmp_path / "boem_wind_planning_rescinded"
  d.mkdir()
  (d / "collection.json").write_text(json.dumps(RESCINDED))
  url = "https://storage.oceanmetrics.io/gazetteer/boem_wind_planning_rescinded/versions.json"
  assert bl.local_rows(tmp_path, fetch=lambda u: {url: LEDGER}[u])[0]["created"] == "2026-10-08"
  assert bl.local_rows(tmp_path)[0]["created"] is None                     # offline, never published: unknown

  def boom(u):
    raise OSError("offline")
  assert bl.local_rows(tmp_path, fetch=boom)[0]["created"] is None
  (d / "versions.json").write_text(json.dumps({"versions": [{"version": "0.9.0", "created": "2026-09-01T00:00:00Z"}]}))
  assert bl.local_rows(tmp_path, fetch=boom)[0]["created"] == "2026-09-01"  # a staged ledger wins


def test_search_rank_puts_the_agency_layer_before_aggregators_and_legacy_copies():
  rank = lambda slug: bl.layer_row({**COLL, "id": slug})["search_rank"]
  assert (rank("noaa_sanctuaries"), rank("mpa_inventory"), rank("noaa_hapc"), rank("places")) == (0, 1, 1, 2)
  assert rank("protectedseas_mpa") == 1 and rank("mr_eez") == 0
  # regression: the rank named the retired protectedseas_navigator, so its six groups ranked with the agency layers
  assert {rank(f"protectedseas_{g}") for g in ("mpa", "fisheries", "jurisdiction", "vessel", "human_use", "other")} == {1}


def test_legacy_places_layer_gets_a_real_title_regression():
  # erddap-places' `places` was published with the portolan default title "Places"; the site credited sanctuaries to it
  row = bl.layer_row({**COLL, "id": "places", "title": "Places"})
  assert row["title"].startswith("erddap-places statistics places")
  assert row["title"] in row["citation"]
  assert bl.layer_row({**COLL, "id": "places", "title": "Sanctuaries for erddap-places"})["title"] == "Sanctuaries for erddap-places"
  assert bl.layer_row(COLL)["title"] == "Acme leases"


def test_style_overrides_default_paint():
  style = {"layers": [{"id": "a", "type": "fill", "paint": {"fill-color": "#123456", "fill-opacity": 0.8}}]}
  paint = bl.layer_row(COLL, style)["paint"]
  assert paint["fill"] == {"fill-color": "#123456", "fill-opacity": 0.8}
  assert paint["line"] == {"line-color": "#a85f00", "line-width": 1}   # untouched by the style


@pytest.mark.parametrize("gt,keys", [("MultiPolygon", {"fill", "line"}), ("Polygon", {"fill", "line"}),
                                     ("MultiLineString", {"line"}), ("Point", {"circle"}), ("MultiPoint", {"circle"})])
def test_paint_kinds_by_geom_type(gt, keys):
  assert set(bl.layer_row({**COLL, "geoparquet:geometry_type": gt})["paint"]) == keys


def test_attribution_falls_back_to_providers_and_version_to_published():
  c = {k: v for k, v in COLL.items() if k not in ("gazetteer:attribution", "gazetteer:provenance")}
  row = bl.layer_row(c, version="2.0.0")
  assert row["attribution"] == "Acme Agency. Processed by Ocean Metrics."
  assert row["version"] == "2.0.0"
  assert row["attribution_html"].startswith('<a href="https://acme.example/">Acme Agency</a>.')


def test_attribution_html_escapes():
  c = {**COLL, "gazetteer:attribution": "<script>x</script> & Acme Agency"}
  assert "<script>" not in bl.layer_row(c)["attribution_html"]


def test_license_url_from_spdx_when_no_link():
  c = {**COLL, "license": "CC-BY-4.0", "links": [l for l in COLL["links"] if l["rel"] != "license"]}
  assert bl.layer_row(c)["license_url"] == "https://creativecommons.org/licenses/by/4.0/"


def test_has_pmtiles_excludes_data_only_collections():
  assert bl.has_pmtiles(COLL)
  assert not bl.has_pmtiles({"id": "erddap_x", "links": [], "assets": {"d": {"type": "application/json"}}})


def test_local_rows_read_collection_and_sibling_style(tmp_path):
  d = tmp_path / "acme_leases"
  (d / "styles").mkdir(parents=True)
  (d / "collection.json").write_text(json.dumps(COLL))
  (d / "styles" / "default.json").write_text(json.dumps({"layers": [{"type": "line", "paint": {"line-width": 3}}]}))
  (tmp_path / "noise").mkdir()                       # a staged dir without a collection.json is ignored
  rows = bl.local_rows(tmp_path)
  assert [r["slug"] for r in rows] == ["acme_leases"]
  assert rows[0]["paint"]["line"] == {"line-color": "#a85f00", "line-width": 3}


def test_merge_local_replaces_published_and_sorts():
  pub = [{"slug": "b", "v": "pub"}, {"slug": "a", "v": "pub"}]
  loc = [{"slug": "b", "v": "loc"}, {"slug": "c", "v": "loc"}]
  assert bl.merge_rows(pub, loc) == [{"slug": "a", "v": "pub"}, {"slug": "b", "v": "loc"}, {"slug": "c", "v": "loc"}]


def test_remote_rows_from_fake_catalog():
  files = {
    "https://x.test/g/catalog.json": {"links": [{"rel": "child", "href": "./acme_leases/collection.json"},
                                                 {"rel": "child", "href": "./erddap/foo/collection.json"},
                                                 {"rel": "root", "href": "./catalog.json"}]},
    "https://x.test/g/versions.json": {"collections": {"acme_leases": {"current_version": "1.4.0"}}},
    "https://x.test/g/acme_leases/collection.json": {k: v for k, v in COLL.items() if k != "gazetteer:provenance"}
                                                       | {"assets": {**COLL["assets"], "styles/default": {"href": "./styles/default.json"}}},
    "https://x.test/g/acme_leases/styles/default.json": {"layers": [{"type": "fill", "paint": {"fill-color": "#000000"}}]},
    "https://x.test/g/erddap/foo/collection.json": {"id": "foo", "assets": {}, "links": []},
    "https://x.test/g/acme_leases/versions.json": {"versions": [{"version": "1.0.0", "created": "2026-10-08T14:58:54Z"}]},
  }
  rows = bl.remote_rows("https://x.test/g/", fetch=lambda u: files[u])
  assert [r["slug"] for r in rows] == ["acme_leases"]
  assert rows[0]["version"] == "1.4.0"
  assert rows[0]["paint"]["fill"]["fill-color"] == "#000000"
  assert rows[0]["pmtiles"] == "https://x.test/g/acme_leases/places.pmtiles"
  assert rows[0]["created"] == "2026-10-08"


def test_remote_unreachable_is_empty_not_fatal():
  def boom(url):
    raise OSError("offline")
  assert bl.remote_rows("https://x.test/g/", fetch=boom) == []


def test_main_offline_writes_manifest(tmp_path):
  d = tmp_path / "st" / "acme_leases"
  d.mkdir(parents=True)
  (d / "collection.json").write_text(json.dumps(COLL))
  out = tmp_path / "layers.json"
  assert bl.main(["--staging", str(tmp_path / "st"), "--out", str(out), "--no-remote"]) == 0
  m = json.loads(out.read_text())
  assert m["schema"] == 1 and [r["slug"] for r in m["layers"]] == ["acme_leases"]
  # pmtiles stay canonical (storage host); base_direct is the redirect-free bucket host apps MAY rewrite onto
  assert m["base"] == "https://storage.oceanmetrics.io/gazetteer/"
  assert m["base_direct"] == "https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/"   # path-style (2746599)
  assert m["layers"][0]["pmtiles"].startswith(m["base"])


def test_mixed_geometry_collection_row_regression():
  # gebco_undersea: geoparquet:geometry_type is a list (MultiLineString, MultiPoint, MultiPolygon); used to crash the build
  coll = {**COLL, "id": "gebco_undersea", "geoparquet:geometry_type": ["MultiLineString", "MultiPoint", "MultiPolygon"]}
  row = bl.layer_row(coll)
  assert row["geom_type"] == "Mixed"
  assert set(row["paint"]) == {"fill", "line", "circle"}
  assert bl.geom_kind(["MultiPolygon"]) == "polygon" and bl.geom_kind(["Point", "MultiPoint"]) == "point"
  assert bl.layer_row({**COLL, "geoparquet:geometry_type": ["MultiPolygon"]})["geom_type"] == "MultiPolygon"


def test_crossing_extent_is_unwrapped_for_fit_bounds():
  """a collection extent crossing +/-180 (west > east) goes to layers.json unwrapped (east + 360), like the index bbox."""
  coll = {**COLL, "extent": {"spatial": {"bbox": [[177.8, -15.4, -64.5, 48.5]]}}}
  assert bl.layer_row(coll)["bbox"] == [177.8, -15.4, 295.5, 48.5]
  assert bl.layer_row(COLL)["bbox"] == [-125.0, 32.0, -117.0, 42.0]
  assert bl.layer_row({**COLL, "extent": {}})["bbox"] is None


def test_reads_go_to_the_s3_origin_not_the_cdn():
  """regression: the CDN caches versions.json for a day, so a build right after a publish read the old versions."""
  assert bl.origin(bl.BASE + "versions.json") == bl.BASE_DIRECT + "versions.json"
  assert bl.origin("file:///tmp/layers.json") == "file:///tmp/layers.json"


def test_raster_row_carries_the_identify_template():
  """click-to-identify on a reference layer (Marine Regions, 2026-10-20): GetFeatureInfo template + response field."""
  url = "https://geo.vliz.be/geoserver/MarineRegions/wms?REQUEST=GetFeatureInfo&BBOX={bbox}&PROPERTYNAME=mrgid,geoname"
  r = bl.raster_source({"gazetteer:raster": {"tiles": ["https://t/{z}/{x}/{y}.png"], "info_url": url, "info_id": "mrgid"}})
  assert (r["info_url"], r["info_id"]) == (url, "mrgid")
