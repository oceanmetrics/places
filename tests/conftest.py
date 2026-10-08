import datetime as dt
from pathlib import Path

import pytest
import shapely
from shapely.geometry import Polygon

from gazetteer.fetch import SourceResult

ROOT = Path(__file__).resolve().parent.parent
STAGING = ROOT / "catalog" / "staging"


def square(x0, y0, size=1.0):
  return Polygon([(x0, y0), (x0 + size, y0), (x0 + size, y0 + size), (x0, y0 + size), (x0, y0)])


def lease_cfg(tmp_path, overlay_rows=None, status_date="data_last_edit"):
  """a minimal wind-lease config with its overlay CSV written under tmp_path/boem/."""
  (tmp_path / "boem").mkdir(exist_ok=True)
  rows = overlay_rows if overlay_rows is not None else [
    "OCS-P 0561,relinquished,https://example.test/ca,2026-09-03",
    "OCS-P 0565,cancelled,https://example.test/ca,2026",
    "OCS-P 0562,active,https://example.test/ca,",
  ]
  (tmp_path / "boem" / "overlay.csv").write_text("lease_number,status,status_source,status_date\n" + "\n".join(rows) + "\n")
  return {
    "slug": "t_leases", "title": "t", "description": "t", "authority": "BOEM", "place_type": "lease", "version": "1.0.0",
    "license": "CC-PDDC", "license_url": "https://example.test/pd", "attribution": "BOEM test credit",
    "providers": [{"name": "BOEM", "roles": ["producer"], "url": "https://boem.gov"}],
    "place_id": {"rule": "lease", "pattern": r"^BOEM:OCS-[A-Z] \d{4,5}(:[a-z0-9-]+)?$"},
    "name": "{LEASE_NUMBER} {LEASE_TYPE} - {COMPANY}", "source_id": "{LEASE_NUMBER}",
    "status": {"value": "active", "source": "https://example.test/layer", "date": status_date,
               "overlay": {"file": "boem/overlay.csv", "key": "LEASE_NUMBER"}},
    "sources": [{"kind": "arcgis", "url": "https://example.test/FeatureServer/8"}],
    "_sources_dir": str(tmp_path),
  }


def lease_result(rows, edit="2025-03-04T12:31:41Z"):
  """a SourceResult from (OBJECTID, LEASE_NUMBER, LEASE_TYPE, COMPANY, geometry) tuples."""
  feats = [{"properties": {"OBJECTID": oid, "LEASE_NUMBER": num, "LEASE_TYPE": typ, "COMPANY": co, "NAME": "native"},
            "geometry": g} for oid, num, typ, co, g in rows]
  fields = [{"name": "OBJECTID", "type": "int"}, {"name": "LEASE_NUMBER", "type": "string"},
            {"name": "LEASE_TYPE", "type": "string"}, {"name": "COMPANY", "type": "string"},
            {"name": "NAME", "type": "string"}]
  return SourceResult(features=feats, fields=fields, source_url="https://example.test/FeatureServer/8",
                      data_last_edit=edit, retrieved="2026-10-08T12:00:00Z", record_count=len(feats), checksum="abc")


@pytest.fixture
def cfg(tmp_path):
  return lease_cfg(tmp_path)
