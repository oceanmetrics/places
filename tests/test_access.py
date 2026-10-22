"""`access: public | unlisted` (default public): config -> collection.json `gazetteer:access` -> layers.json `access`,
and the places of an unlisted collection are left out of the search index."""
from pathlib import Path

import pyarrow as pa

from gazetteer import stac
from test_index import square, write_layer, bi
from test_layers_json import COLL, bl


def test_access_fields_default_public_and_carry_unlisted():
  assert stac.access_fields({}) == {"gazetteer:access": "public"}
  assert stac.access_fields({"access": "public"}) == {"gazetteer:access": "public"}
  assert stac.access_fields({"access": "unlisted"}) == {"gazetteer:access": "unlisted"}


def test_collection_json_carries_gazetteer_access(cfg, tmp_path):
  """build_collection end to end on a tiny reference collection (no data files to write)."""
  d = tmp_path / "t_leases"
  (d / "styles").mkdir(parents=True)
  for f in ("styles/default.json", "provenance.json", "README.md"):
    (d / f).write_text("{}")
  cfg = {**cfg, "license_url": "https://example.test/pd", "source_page": "https://example.test/page",
         "reference": {"tiles": "https://t.test/{z}/{x}/{y}.png"}}
  table = pa.table({"place_id": ["BOEM:1"]})
  geo = {"columns": {"geometry": {"bbox": [-1, -1, 1, 1], "geometry_types": ["MultiPolygon"]}}}
  prov = {"sources": [{"source_url": "https://example.test/FeatureServer/8", "component": None}], "version": "1.0.0"}
  hdr = {"min_zoom": 0, "max_zoom": 5, "center": [0, 0, 0]}
  make = lambda c: stac.build_collection(c, table, geo, prov, d, hdr, "2026-10-22T00:00:00Z", {})
  assert make(cfg)["gazetteer:access"] == "public"
  assert make({**cfg, "access": "unlisted"})["gazetteer:access"] == "unlisted"


def test_layers_json_row_takes_access_from_the_collection_default_public():
  assert bl.layer_row(COLL)["access"] == "public"                       # an older collection has no key
  assert bl.layer_row({**COLL, "gazetteer:access": "public"})["access"] == "public"
  assert bl.layer_row({**COLL, "gazetteer:access": "unlisted"})["access"] == "unlisted"


def test_an_unlisted_collection_keeps_its_layers_json_row():
  """the row stays (a link to the layer works); the client filters it out of lists."""
  rows = bl.merge_rows([], [bl.layer_row({**COLL, "gazetteer:access": "unlisted"})])
  assert [(r["slug"], r["access"]) for r in rows] == [("acme_leases", "unlisted")]


def test_listed_drops_unlisted_collections_from_the_index_sources():
  mk = lambda slug, coll: bi.Source(slug, Path(f"{slug}.parquet"), coll, "published")
  srcs = [mk("a", {}), mk("b", {"gazetteer:access": "unlisted"}), mk("c", {"gazetteer:access": "public"}),
          mk("d", {"gazetteer:access": None})]
  assert [s.slug for s in bi.listed(srcs)] == ["a", "c", "d"]


def test_an_unlisted_collections_places_never_reach_the_search_index(tmp_path):
  import pyarrow.parquet as pq
  st = tmp_path / "staging"
  for slug, access in (("pub_layer", "public"), ("hidden_layer", "unlisted")):
    write_layer(st / slug, {"place_id": [f"X:{slug}"], "name": [slug], "_geoms": [square(0, 0)]},
                {"id": slug, "gazetteer:authority": "X", "gazetteer:access": access})
  out = tmp_path / "index"
  bi.build(bi.listed(bi.merge_sources([], bi.local_sources(st))), out)
  rows = pq.read_table(out / "places_index.parquet").to_pylist()
  assert [r["place_id"] for r in rows] == ["X:pub_layer"]
  assert [r["collection"] for r in rows] == ["pub_layer"]
