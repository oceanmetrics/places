import re

import pytest

from conftest import ROOT
from gazetteer.config import load_all, validate_config

EXPECTED = {"boem_wind_leases", "boem_wind_planning_rescinded", "boem_ocs_planning", "boem_program_11_draft",
            "boem_pacific_og_leases", "noaa_aoa_socal"}
CFGS = load_all(ROOT / "sources")


def test_six_collections_are_configured():
  assert EXPECTED <= set(CFGS)  # other collections may be added alongside


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
