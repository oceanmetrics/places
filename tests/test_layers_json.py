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
    "slug": "acme_leases", "title": "Acme leases", "collection": "acme_leases",
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
  }


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
  }
  rows = bl.remote_rows("https://x.test/g/", fetch=lambda u: files[u])
  assert [r["slug"] for r in rows] == ["acme_leases"]
  assert rows[0]["version"] == "1.4.0"
  assert rows[0]["paint"]["fill"]["fill-color"] == "#000000"
  assert rows[0]["pmtiles"] == "https://x.test/g/acme_leases/places.pmtiles"


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
  assert m["base_direct"] == "https://oceanmetrics.io-public.s3.amazonaws.com/gazetteer/"
  assert m["layers"][0]["pmtiles"].startswith(m["base"])


def test_mixed_geometry_collection_row_regression():
  # gebco_undersea: geoparquet:geometry_type is a list (MultiLineString, MultiPoint, MultiPolygon); used to crash the build
  coll = {**COLL, "id": "gebco_undersea", "geoparquet:geometry_type": ["MultiLineString", "MultiPoint", "MultiPolygon"]}
  row = bl.layer_row(coll)
  assert row["geom_type"] == "Mixed"
  assert set(row["paint"]) == {"fill", "line", "circle"}
  assert bl.geom_kind(["MultiPolygon"]) == "polygon" and bl.geom_kind(["Point", "MultiPoint"]) == "point"
  assert bl.layer_row({**COLL, "geoparquet:geometry_type": ["MultiPolygon"]})["geom_type"] == "MultiPolygon"
