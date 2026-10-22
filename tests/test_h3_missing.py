"""scripts/build_h3_membership.py --missing: which polygon layers still need a membership."""
import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "build_h3_membership.py"
spec = importlib.util.spec_from_file_location("build_h3_membership", SCRIPT)
bh = importlib.util.module_from_spec(spec)
sys.modules["build_h3_membership"] = bh
spec.loader.exec_module(bh)

A, B = "a" * 64, "b" * 64


def row(slug, kind="vector", geom="MultiPolygon", sha=A):
  has = kind == "vector"
  return {"slug": slug, "kind": kind, "geom_type": geom, "parquet": f"https://x.test/{slug}/places.parquet" if has else None,
          "parquet_sha256": sha if has else None}


LJ = {"layers": [
  row("current"),                            # membership built from this parquet: not selected
  row("stale"),                              # membership built from an older parquet (places 1.2.1 vs 2.0.0)
  row("never_built"),                        # no membership.json on the bucket
  row("plain_polygon", geom="Polygon"),      # Polygon counts as well as MultiPolygon
  row("lines", geom="MultiLineString"),      # no polygons, no membership
  row("points", geom="Point"),
  row("mr_eez", kind="raster"),              # a reference layer has no parquet of ours
  row("fao_high_seas", kind="derived"),
]}
MANIFESTS = {"current": {"places_sha256": A}, "stale": {"places_sha256": B}, "never_built": None}


def test_missing_slugs_selects_absent_and_stale_polygon_vector_layers_only():
  assert bh.missing_slugs(LJ, MANIFESTS) == ["never_built", "plain_polygon", "stale"]


def test_missing_slugs_is_empty_when_every_polygon_layer_is_current():
  lj = {"layers": [row("a"), row("b", sha=B)]}
  assert bh.missing_slugs(lj, {"a": {"places_sha256": A}, "b": {"places_sha256": B}}) == []


def test_a_polygon_row_without_a_parquet_is_not_selected():
  # nothing to build a membership from
  r = {**row("odd"), "parquet": None, "parquet_sha256": None}
  assert bh.missing_slugs({"layers": [r]}, {}) == []


def test_published_membership_reads_the_bucket_host_and_treats_403_404_as_absent():
  seen = []

  def fetch(url):
    seen.append(url)
    if "gone" in url:
      raise urllib.error.HTTPError(url, 404, "nf", {}, io.BytesIO(b""))
    if "denied" in url:
      raise urllib.error.HTTPError(url, 403, "fb", {}, io.BytesIO(b""))
    if "broken" in url:
      raise urllib.error.HTTPError(url, 500, "err", {}, io.BytesIO(b""))
    return json.dumps({"places_sha256": A}).encode()

  base, direct = "https://storage.test/g/", "https://bucket.test/g/"
  assert bh.published_membership({"slug": "ok"}, base, direct, fetch) == {"places_sha256": A}
  assert seen == ["https://bucket.test/g/ok/h3/membership.json"]
  assert bh.published_membership({"slug": "gone"}, base, direct, fetch) is None
  assert bh.published_membership({"slug": "denied"}, base, direct, fetch) is None
  import pytest
  with pytest.raises(urllib.error.HTTPError):
    bh.published_membership({"slug": "broken"}, base, direct, fetch)
