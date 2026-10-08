"""scripts/validate_contribution.py: the accept path, one test per rejection rule, the OM:<ulid> id pattern."""
import importlib.util
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("validate_contribution", ROOT / "scripts" / "validate_contribution.py")
vc = importlib.util.module_from_spec(spec)
sys.modules["validate_contribution"] = vc  # dataclasses look the module up by name
spec.loader.exec_module(vc)

ULID = "01J9ZQ3X7K8M2N4P5R6S7T8V9W"
DIRNAME = f"OM-{ULID}"
SQUARE_CCW = [[-120.5, 34.4], [-120.4, 34.4], [-120.4, 34.5], [-120.5, 34.5], [-120.5, 34.4]]
META = {"name": "Test Reef", "place_type": "habitat", "license": "CC0-1.0", "attribution": "A. Tester"}


def feature(geometry, **extra):
  return {"type": "Feature", "properties": {}, "geometry": geometry, **extra}


def polygon(ring=None):
  return {"type": "Polygon", "coordinates": [ring or SQUARE_CCW]}


def make(tmp_path, geo=None, meta=None, name=DIRNAME, raw_geo=None, raw_meta=None):
  """write a contribution dir; geo / meta default to the accept-path fixture, raw_* write the text verbatim."""
  d = tmp_path / name
  d.mkdir()
  g = feature(polygon()) if geo is None else geo
  (d / "place.geojson").write_text(raw_geo if raw_geo is not None else json.dumps(g))
  if meta is not False:
    (d / "meta.json").write_text(raw_meta if raw_meta is not None else json.dumps(META if meta is None else meta))
  return d


def run(d, **kw):
  return vc.validate_contribution(d, catalog=kw.pop("catalog", None), contrib=kw.pop("contrib", None), **kw)


def has(msgs, *needles):
  return any(all(n in m for n in needles) for m in msgs)


# accept ----
def test_accepts_a_clean_polygon(tmp_path):
  r = run(make(tmp_path))
  assert r.ok and r.errors == [] and r.warnings == []
  assert r.geometry.geom_type == "MultiPolygon" and r.meta["name"] == "Test Reef"


def test_accepts_feature_collection_of_one_and_all_licences_and_orcid(tmp_path):
  for i, lic in enumerate(("CC0-1.0", "CC-BY-4.0", "ODbL-1.0")):
    geo = {"type": "FeatureCollection", "features": [feature(polygon())]}
    meta = {**META, "license": lic, "contributor_orcid": "0000-0002-1825-009X", "source_url": "https://example.org/x"}
    sub = tmp_path / str(i)
    sub.mkdir()
    assert run(make(sub, geo, meta)).ok


def test_accepts_points_and_lines(tmp_path):
  (tmp_path / "p").mkdir()
  (tmp_path / "l").mkdir()
  assert run(make(tmp_path / "p", feature({"type": "Point", "coordinates": [-120.5, 34.4]}))).ok
  assert run(make(tmp_path / "l", feature({"type": "LineString", "coordinates": [[-120.5, 34.4], [-120.4, 34.5]]}))).ok


def test_documentation_example_is_valid():
  """contrib/OM-01EXAMPE.../ is the worked example in CONTRIBUTING.md; it must always pass."""
  d = ROOT / "contrib" / "OM-01EXAMPE000000000000000000"
  r = run(d)
  assert r.ok, r.errors
  assert r.meta["example"] is True


# geojson rules ----
def test_rejects_unparseable_geojson(tmp_path):
  r = run(make(tmp_path, raw_geo="{not json"))
  assert not r.ok and has(r.errors, "does not parse")


def test_rejects_missing_files(tmp_path):
  d = make(tmp_path, meta=False)
  r = run(d)
  assert has(r.errors, "meta.json is missing")
  (d / "place.geojson").unlink()
  assert has(run(d).errors, "place.geojson is missing")


def test_rejects_feature_collection_of_two(tmp_path):
  geo = {"type": "FeatureCollection", "features": [feature(polygon()), feature(polygon())]}
  assert has(run(make(tmp_path, geo)).errors, "exactly one Feature", "found 2")


def test_rejects_bare_geometry_and_geometrycollection(tmp_path):
  (tmp_path / "a").mkdir()
  (tmp_path / "b").mkdir()
  assert has(run(make(tmp_path / "a", polygon())).errors, "must be Feature or FeatureCollection")
  gc = feature({"type": "GeometryCollection", "geometries": []})
  assert has(run(make(tmp_path / "b", gc)).errors, "not accepted")


def test_rejects_non_4326_crs_member(tmp_path):
  geo = feature(polygon(), crs={"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3857"}})
  assert has(run(make(tmp_path, geo)).errors, "not EPSG:4326")


def test_accepts_crs84_member(tmp_path):
  geo = feature(polygon(), crs={"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}})
  assert run(make(tmp_path, geo)).ok


def test_rejects_projected_coordinates(tmp_path):
  ring = [[-13400000, 4000000], [-13300000, 4000000], [-13300000, 4100000], [-13400000, 4100000], [-13400000, 4000000]]
  assert has(run(make(tmp_path, feature(polygon(ring)))).errors, "not EPSG:4326 degrees")


def test_rejects_file_over_size_cap(tmp_path, monkeypatch):
  monkeypatch.setattr(vc, "MAX_BYTES", 100)
  assert has(run(make(tmp_path)).errors, "the cap is")


def test_size_cap_is_five_megabytes():
  assert vc.MAX_BYTES == 5 * 1024 * 1024 and vc.MAX_VERTICES == 100_000


def test_rejects_vertex_count_over_cap(tmp_path, monkeypatch):
  monkeypatch.setattr(vc, "MAX_VERTICES", 4)
  assert has(run(make(tmp_path)).errors, "exceeds the cap of 4")


def test_rejects_empty_and_nonfinite_geometry(tmp_path):
  (tmp_path / "a").mkdir()
  (tmp_path / "b").mkdir()
  assert has(run(make(tmp_path / "a", feature({"type": "Polygon", "coordinates": []}))).errors, "no coordinates")
  # json.dumps writes NaN as a bare NaN token, which Python's json parser accepts
  bad = feature({"type": "Point", "coordinates": [float("nan"), 1.0]})
  assert has(run(make(tmp_path / "b", bad)).errors, "NaN")


# geometry repair ----
def test_clockwise_ring_is_corrected_with_a_warning(tmp_path):
  r = run(make(tmp_path, feature(polygon(SQUARE_CCW[::-1]))))
  assert r.ok and has(r.warnings, "winding corrected")
  assert r.geometry.geoms[0].exterior.is_ccw


def test_self_intersecting_bowtie_is_repaired_with_a_warning(tmp_path):
  bow = [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]
  r = run(make(tmp_path, feature(polygon(bow))))
  assert r.ok and has(r.warnings, "repaired with make_valid")
  assert r.geometry.is_valid and r.geometry.area == pytest.approx(2.0)


def test_unfixable_polygon_is_rejected(tmp_path):
  line = [[0, 0], [1, 1], [2, 2], [0, 0]]  # zero-area ring: nothing polygonal survives repair
  r = run(make(tmp_path, feature(polygon(line))))
  assert not r.ok and has(r.errors, "cannot be repaired")


# antimeridian ----
def test_polygon_across_the_antimeridian_is_split(tmp_path):
  ring = [[170, 0], [-170, 0], [-170, 10], [170, 10], [170, 0]]  # jumps 170 -> -170: crosses the dateline
  r = run(make(tmp_path, feature(polygon(ring))))
  assert r.ok and has(r.warnings, "split at +/-180", "2 part")
  b = r.geometry.bounds
  assert b[0] == -180 and b[2] == 180 and len(r.geometry.geoms) == 2
  assert r.geometry.area == pytest.approx(200.0)


def test_polygon_unwrapped_past_180_is_split(tmp_path):
  ring = [[170, 0], [190, 0], [190, 10], [170, 10], [170, 0]]
  r = run(make(tmp_path, feature(polygon(ring))))
  assert r.ok and r.geometry.bounds[0] >= -180 and r.geometry.bounds[2] == 180
  assert len(r.geometry.geoms) == 2 and r.geometry.area == pytest.approx(200.0)


def test_point_outside_180_is_rejected(tmp_path):
  assert has(run(make(tmp_path, feature({"type": "Point", "coordinates": [190, 10]}))).errors, "outside [-180, 180]")


# meta.json rules ----
@pytest.mark.parametrize("drop", ["name", "place_type", "license", "attribution"])
def test_rejects_missing_required_meta_field(tmp_path, drop):
  meta = {k: v for k, v in META.items() if k != drop}
  r = run(make(tmp_path, meta=meta))
  assert not r.ok and has(r.errors, drop, "required")


@pytest.mark.parametrize("lic", ["CC-BY-NC-4.0", "MIT", "proprietary", "cc0-1.0", "CC0", "", None])
def test_rejects_anything_but_the_three_licences(tmp_path, lic):
  r = run(make(tmp_path, meta={**META, "license": lic}))
  assert not r.ok and has(r.errors, "license")


def test_unlicensed_contribution_is_rejected_with_the_reason(tmp_path):
  meta = {k: v for k, v in META.items() if k != "license"}
  assert has(run(make(tmp_path, meta=meta)).errors, "license is required", "cannot be redistributed")


def test_rejects_unknown_place_type(tmp_path):
  r = run(make(tmp_path, meta={**META, "place_type": "pirate_cove"}))
  assert has(r.errors, "place_type 'pirate_cove' is not one of")


@pytest.mark.parametrize("orcid", ["0000-0002-1825-009", "0000000218250097", "0000-0002-1825-009Y", "orcid.org/0000-0002-1825-0097"])
def test_rejects_malformed_orcid(tmp_path, orcid):
  assert has(run(make(tmp_path, meta={**META, "contributor_orcid": orcid})).errors, "contributor_orcid")


def test_rejects_bad_source_url_and_non_object_meta(tmp_path):
  (tmp_path / "a").mkdir()
  (tmp_path / "b").mkdir()
  assert has(run(make(tmp_path / "a", meta={**META, "source_url": "ftp://x"})).errors, "source_url")
  assert has(run(make(tmp_path / "b", raw_meta="[1]")).errors, "must be a JSON object")


def test_rejects_unparseable_meta(tmp_path):
  assert has(run(make(tmp_path, raw_meta="{")).errors, "meta.json does not parse")


def test_unknown_meta_key_is_a_warning(tmp_path):
  r = run(make(tmp_path, meta={**META, "colour": "red"}))
  assert r.ok and has(r.warnings, "unknown key", "colour")


# ids and directory names ----
@pytest.mark.parametrize("good", [f"OM:{ULID}", "OM:01EXAMPE000000000000000000", "OM:7ZZZZZZZZZZZZZZZZZZZZZZZZZ"])
def test_om_ulid_id_pattern_accepts(good):
  assert vc.ID_RE.fullmatch(good)
  assert vc.id_to_dir(good) == good.replace(":", "-") and vc.dir_to_id(vc.id_to_dir(good)) == good


@pytest.mark.parametrize("bad", [
  "OM:", "om:" + ULID, "OM-" + ULID, f"OM:{ULID}0", f"OM:{ULID[:-1]}",   # wrong prefix, separator or length
  "OM:81J9ZQ3X7K8M2N4P5R6S7T8V9W",                                      # first character above 7 overflows the timestamp
  "OM:01J9ZQ3X7K8M2N4P5R6S7T8V9I", "OM:01J9ZQ3X7K8M2N4P5R6S7T8V9L",      # I, L, O, U are not Crockford base32
  "OM:01J9ZQ3X7K8M2N4P5R6S7T8V9O", "OM:01J9ZQ3X7K8M2N4P5R6S7T8V9U", "OM:01j9zq3x7k8m2n4p5r6s7t8v9w",
])
def test_om_ulid_id_pattern_rejects(bad):
  assert not vc.ID_RE.fullmatch(bad)
  with pytest.raises(ValueError):
    vc.id_to_dir(bad)


def test_rejects_directory_not_named_om_ulid(tmp_path):
  r = run(make(tmp_path, name="my-reef"))
  assert not r.ok and has(r.errors, "is not OM-<ulid>")
  with pytest.raises(ValueError):
    vc.dir_to_id("my-reef")


# name collisions ----
def staged(tmp_path, rows, sub="catalog/staging/x"):
  d = tmp_path / sub
  d.mkdir(parents=True)
  pq.write_table(pa.table({"name": [n for n, _ in rows], "place_type": [t for _, t in rows]}), d / "places.parquet")
  return tmp_path / "catalog"


def test_name_collision_with_same_place_type_warns_not_rejects(tmp_path):
  cat = staged(tmp_path, [("TEST  reef", "habitat")])
  (tmp_path / "w").mkdir()
  r = run(make(tmp_path / "w"), catalog=cat)
  assert r.ok and has(r.warnings, "already used by another habitat place")


def test_same_name_other_place_type_does_not_warn(tmp_path):
  cat = staged(tmp_path, [("Test Reef", "lease")])
  (tmp_path / "w").mkdir()
  assert run(make(tmp_path / "w"), catalog=cat).warnings == []


def test_name_collision_with_another_contribution_warns(tmp_path):
  other = tmp_path / "contrib"
  other.mkdir()
  make(other, name="OM-" + "0" * 26)
  mine = other / DIRNAME
  mine.mkdir()
  (mine / "place.geojson").write_text(json.dumps(feature(polygon())))
  (mine / "meta.json").write_text(json.dumps(META))
  r = run(mine, contrib=other)
  assert r.ok and has(r.warnings, "already used")


# cli ----
def test_cli_exit_codes_and_messages(tmp_path, capsys):
  good = make(tmp_path)
  (tmp_path / "x").mkdir()
  bad = make(tmp_path / "x", meta={**META, "license": "MIT"}, name="OM-" + "1" * 26)
  nocat = ["--catalog", str(tmp_path / "none"), "--contrib", str(tmp_path / "none")]
  assert vc.main([str(good), *nocat]) == 0
  assert "ok:" in capsys.readouterr().out
  assert vc.main([str(good), str(bad), *nocat]) == 1
  out = capsys.readouterr().out
  assert "FAILED" in out and "license 'MIT' is not accepted" in out


# CONTRIBUTING.md stays true ----
def test_contributing_one_liner_makes_a_valid_ulid_and_lists_the_licences():
  import re
  import subprocess
  doc = (ROOT / "CONTRIBUTING.md").read_text()
  cmd = re.search(r'python3 -c "(import time,secrets;[^"]+)"', doc).group(1)
  ulid = subprocess.run([sys.executable, "-c", cmd], capture_output=True, text=True, check=True).stdout.strip()
  assert vc.ID_RE.fullmatch(f"OM:{ulid}")
  assert all(lic in doc for lic in vc.LICENSES)
