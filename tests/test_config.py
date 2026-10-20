import re

import pytest

from conftest import ROOT
from gazetteer.config import load_all, validate_config

EXPECTED = {"boem_wind_leases", "boem_wind_planning_rescinded", "boem_ocs_planning", "boem_program_11_draft",
            "boem_pacific_og_leases", "noaa_aoa_socal"}
ALL = EXPECTED | {"calcofi_lines", "calcofi_stations", "fws_critical_habitat_final", "fws_critical_habitat_proposed",
                  "gebco_undersea", "mpa_inventory", "mr_contiguous_zones", "mr_ecs", "mr_eez", "mr_goas", "mr_high_seas",
                  "mr_territorial_seas", "mr_world_heritage_marine", "noaa_esa_critical_habitat", "noaa_hapc",
                  "noaa_marine_monuments", "noaa_maritime_limits", "noaa_nerrs", "noaa_sanctuaries",
                  "noaa_state_lateral_boundaries", "noaa_state_submerged_lands", "noaa_submarine_cables",
                  "noaa_vessel_routing_measures", "usace_danger_zones"}
CFGS = load_all(ROOT / "sources")


def test_six_collections_are_configured():
  assert EXPECTED <= set(CFGS)  # other collections may be added alongside


def test_the_whole_collection_set_is_configured_and_retired_slugs_are_gone():
  assert len(ALL) == 30 and ALL <= set(CFGS)
  assert "noaa_mpa_inventory" not in CFGS  # retired: duplicate of mpa_inventory (MPAINV: ids)
  assert len({c["authority"] + ":" + c["slug"] for c in CFGS.values()}) == len(CFGS)


@pytest.mark.parametrize("slug", sorted(EXPECTED))
def test_license_attribution_and_pattern_are_set(slug):
  c = CFGS[slug]
  assert c["license"] == "CC-PDDC" and c["license_url"].startswith("https://")
  assert len(c["attribution"].split()) > 5 and "Public domain" in c["attribution"]
  assert c["place_type"] in {"lease", "planning_area", "aoa"}
  for s in c["sources"]:
    pid = s.get("place_id") or c["place_id"]
    re.compile(pid["pattern"])


def test_validation_names_every_problem():
  with pytest.raises(ValueError) as e:
    validate_config({"slug": "Bad Slug", "place_type": "x", "sources": [{"kind": "ftp"}]})
  msg = str(e.value)
  assert "slug must be snake_case" in msg and "license" in msg and "attribution" in msg and "place_type" in msg


def test_patch_bump_for_the_sync_workflow():
  from gazetteer.pipeline import bump_patch, next_version
  assert bump_patch("1.0.0") == "1.0.1" and bump_patch("1.2.9") == "1.2.10"

  class R:
    def __init__(self, code, body=None):
      self.status_code, self._b = code, body

    def json(self):
      return self._b

    def raise_for_status(self):
      pass

  class S:
    def __init__(self, r):
      self.r = r

    def get(self, url, timeout=None):
      return self.r

  cfg = {"slug": "boem_wind_leases", "version": "1.0.0"}
  assert next_version(cfg, "https://x", S(R(404))) == "1.0.0"
  assert next_version(cfg, "https://x", S(R(200, {"collections": {}}))) == "1.0.0"
  assert next_version(cfg, "https://x", S(R(200, {"collections": {"boem_wind_leases": {"current_version": "1.0.3"}}}))) == "1.0.4"


def test_change_detection_rules():
  from gazetteer.pipeline import changed_sources
  pub = {"sources": [{"data_last_edit": "2025-03-04T19:31:41Z", "record_count": 52, "checksum": "a"}]}
  same = [{"data_last_edit": "2025-03-04T19:31:41Z", "record_count": 52}]
  assert changed_sources({}, pub, same) is None
  assert "data_last_edit" in changed_sources({}, pub, [{"data_last_edit": "2026-01-01T00:00:00Z", "record_count": 52}])
  assert "record_count" in changed_sources({}, pub, [{"data_last_edit": "2025-03-04T19:31:41Z", "record_count": 53}])
  assert changed_sources({}, None, same) == "not published yet"
  nodate = {"sources": [{"data_last_edit": None, "checksum": "a"}]}
  assert changed_sources({}, nodate, [{"data_last_edit": None, "checksum": "a"}]) is None
  assert changed_sources({}, nodate, [{"data_last_edit": None, "checksum": "b"}]) == "payload checksum changed"
  zipped = {"sources": [{"data_last_edit": "2025-08-19T00:00:00Z", "http": {"etag": "e1", "last_modified": "L", "content_length": 5}}]}
  assert changed_sources({}, zipped, [{"data_last_edit": None, "etag": "e1", "last_modified": "L", "content_length": 5}]) is None
  assert "etag" in changed_sources({}, zipped, [{"data_last_edit": None, "etag": "e2", "last_modified": "L", "content_length": 5}])


def test_detect_all_reports_a_failed_probe_and_checks_the_others():
  """regression: one 403 (NOAA's CDN redirecting to an expired pre-signed S3 URL, 2026-10-16) stopped detection for
  every collection."""
  import requests
  from gazetteer.pipeline import detect_all

  def one(cfg, base):
    if cfg["slug"] == "bad":
      raise requests.HTTPError("403 Client Error: Forbidden for url: https://s3.amazonaws.com/x.zip")
    return {"slug": cfg["slug"], "changed": True, "reason": "data_last_edit changed"}

  res = detect_all([{"slug": "a"}, {"slug": "bad"}, {"slug": "c"}], "https://x", detect_one=one)
  assert [r["slug"] for r in res] == ["a", "bad", "c"]
  assert res[0]["changed"] and res[2]["changed"]
  assert res[1]["changed"] is False and res[1]["error"] is True and res[1]["reason"].startswith("probe failed: HTTPError: 403")


def test_detect_all_reports_an_arcgis_error_body_and_checks_the_others():
  """regression: NOAA's maritime boundaries MapServer answered 'Could not find service' (an ArcGIS error body, raised
  as RuntimeError by `fetch.arcgis_json`, 2026-10-19) and stopped detection for every collection."""
  from gazetteer.pipeline import detect_all

  def one(cfg, base):
    if cfg["slug"] == "bad":
      raise RuntimeError("ArcGIS error from https://x/MapServer/1: {'code': 500, 'message': 'Could not find service.'}")
    return {"slug": cfg["slug"], "changed": False, "reason": "unchanged"}

  res = detect_all([{"slug": "a"}, {"slug": "bad"}, {"slug": "c"}], "https://x", detect_one=one)
  assert [r["slug"] for r in res] == ["a", "bad", "c"]
  assert res[1]["changed"] is False and res[1]["error"] is True
  assert res[1]["reason"].startswith("probe failed: RuntimeError: ArcGIS error")
  assert "error" not in res[0] and "error" not in res[2]


# extends / include / tile_args / style / id_sort ----

def _base_yaml(d, name="_base.yml", **extra):
  import yaml
  cfg = {"slug": "base_never_built", "title": "T", "description": "D", "authority": "PSGID", "place_type": "managed_area",
         "version": "1.0.0", "license": "CC-BY-4.0", "attribution": "A", "name": "{n}", "source_id": "{id}",
         "place_id": {"template": "PSGID:{id}", "pattern": "^PSGID:.+$"},
         "providers": [{"name": "P", "roles": ["producer"]}],
         "status": {"value": "current", "source": "https://x", "date": "data_last_edit"},
         "sources": [{"kind": "navigator_export", "url": "https://x"}], **extra}
  (d / name).write_text(yaml.safe_dump(cfg))


def test_extends_merges_the_base_and_load_all_skips_bases(tmp_path):
  import yaml
  from gazetteer.config import load_all
  d = tmp_path / "src" / "ps"
  d.mkdir(parents=True)
  _base_yaml(d)
  (d / "group.yml").write_text(yaml.safe_dump({"extends": "_base.yml", "slug": "ps_group", "title": "Group",
      "sources": [{"kind": "navigator_export", "url": "https://x", "include": {"category_name": ["A"]}}]}))
  cfgs = load_all(tmp_path / "src")
  assert list(cfgs) == ["ps_group"]                                       # the base is not a layer
  c = cfgs["ps_group"]
  assert (c["title"], c["license"], c["attribution"]) == ("Group", "CC-BY-4.0", "A")
  assert c["sources"][0]["include"] == {"category_name": ["A"]} and "extends" not in c


def test_extends_needs_an_underscore_base(tmp_path):
  import yaml
  from gazetteer.config import load_layer_config
  _base_yaml(tmp_path, "base.yml")
  (tmp_path / "g.yml").write_text(yaml.safe_dump({"extends": "base.yml", "slug": "g"}))
  with pytest.raises(ValueError, match="must start with '_'"):
    load_layer_config(tmp_path / "g.yml")


def test_include_and_exclude_rules_by_source_kind(cfg):
  lease_cfg = cfg
  from gazetteer.config import validate_config
  cfg = {**lease_cfg, "sources": [{**lease_cfg["sources"][0], "include": {"F": ["x"]}}]}
  with pytest.raises(ValueError, match="include is not supported for arcgis"):
    validate_config(cfg)
  cfg = {**lease_cfg, "sources": [{**lease_cfg["sources"][0], "kind": "shapefile_zip", "exclude": {"F": ["x"]}}]}
  with pytest.raises(ValueError, match="exclude is only supported for arcgis and navigator_export"):
    validate_config(cfg)
  cfg = {**lease_cfg, "sources": [{**lease_cfg["sources"][0], "kind": "navigator_export", "include": {"F": []}}]}
  with pytest.raises(ValueError, match="include must map a native field"):
    validate_config(cfg)


def test_tile_args_style_and_row_order_are_checked(cfg):
  lease_cfg = cfg
  from gazetteer.config import validate_config
  for bad, msg in [({"tile_args": ["-z5"]}, "tile_args"), ({"tile_args": "--x"}, "tile_args"),
                   ({"style": {"fill_colour": "#fff"}}, "style takes only"),
                   ({"spatial_sort": True, "id_sort": True}, "exclusive")]:
    with pytest.raises(ValueError, match=msg):
      validate_config({**lease_cfg, **bad})
  validate_config({**lease_cfg, "tile_args": ["--low-detail=10"], "style": {"fill_color": "#2b7bb9", "fill_opacity": 0.1}})


def test_reference_info_url_needs_bbox_and_info_id(cfg):
  base = {**cfg, "reference": {"tiles": "https://t/{z}/{x}/{y}.png"}}
  with pytest.raises(ValueError, match="info_url needs \\{bbox\\}"):
    validate_config({**base, "reference": {**base["reference"], "info_url": "https://w?x=1", "info_id": "mrgid"}})
  with pytest.raises(ValueError, match="needs reference.info_id"):
    validate_config({**base, "reference": {**base["reference"], "info_url": "https://w?BBOX={bbox}"}})
  validate_config({**base, "reference": {**base["reference"], "info_url": "https://w?BBOX={bbox}", "info_id": "mrgid"}})
