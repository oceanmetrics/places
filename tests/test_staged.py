"""checks on the real staged outputs (catalog/staging/<slug>/); skipped for a collection that was not built."""
import json

import pyarrow.parquet as pq
import pytest

from conftest import ROOT, STAGING
from gazetteer.config import load_all
from gazetteer.tiles import read_pmtiles
from gazetteer.validate import check_parquet, check_pmtiles

CFGS = load_all(ROOT / "sources")
COUNTS = {"boem_wind_leases": 52, "boem_wind_planning_rescinded": 3325, "boem_ocs_planning": 27,
          "boem_program_11_draft": 20, "boem_pacific_og_leases": 34, "noaa_aoa_socal": 10}


def staged(slug):
  d = STAGING / slug
  if not (d / "places.parquet").exists():
    pytest.skip(f"{slug} not built")
  return d


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_parquet_and_pmtiles_pass_every_check(slug):
  d = staged(slug)
  assert check_parquet(d / "places.parquet", CFGS[slug]) == []
  assert check_pmtiles(d / "places.pmtiles", slug) == []


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_feature_counts(slug):
  d = staged(slug)
  n = pq.ParquetFile(d / "places.parquet").metadata.num_rows
  assert n == COUNTS[slug]
  coll = json.loads((d / "collection.json").read_text())
  assert coll["geoparquet:feature_count"] == n and coll["license"] == "CC-PDDC" and coll["id"] == slug
  assert coll["gazetteer:attribution"] and set(coll["assets"]) >= {"places", "places-tiles", "provenance"}


@pytest.mark.parametrize("slug", sorted(COUNTS))
def test_staged_provenance_has_the_six_fields(slug):
  d = staged(slug)
  prov = json.loads((d / "provenance.json").read_text())
  for s in prov["sources"]:
    assert all(s.get(k) not in (None, "") for k in ("source_url", "retrieved", "record_count", "checksum"))
    assert "source_item_id" in s and "data_last_edit" in s


def test_california_wind_leases_carry_the_boem_page_status():
  d = staged("boem_wind_leases")
  t = pq.read_table(d / "places.parquet", columns=["place_id", "status", "status_date", "status_source"]).to_pylist()
  by = {r["place_id"]: r for r in t}
  assert by["BOEM:OCS-P 0561"]["status"] == "relinquished" and by["BOEM:OCS-P 0561"]["status_date"] == "2026-09-03"
  assert by["BOEM:OCS-P 0565"]["status"] == "cancelled"
  assert by["BOEM:OCS-P 0564"]["status"] == "settlement_pending"
  assert by["BOEM:OCS-P 0562"]["status"] == by["BOEM:OCS-P 0563"]["status"] == "active"
  assert by["BOEM:OCS-A 0501"]["status"] == "active"


def test_rescinded_planning_areas_are_all_rescinded_on_2025_07_30():
  d = staged("boem_wind_planning_rescinded")
  t = pq.read_table(d / "places.parquet", columns=["status", "status_date", "component"]).to_pylist()
  assert {(r["status"], r["status_date"]) for r in t} == {("rescinded", "2025-07-30")}
  assert {r["component"] for r in t} == {"outline", "block"}


def test_alaska_planning_areas_that_cross_180_are_split():
  d = staged("boem_ocs_planning")
  t = pq.read_table(d / "places.parquet", columns=["source_id", "bbox"]).to_pylist()
  by = {r["source_id"]: r["bbox"] for r in t}
  assert by["ALA"]["xmin"] == -180.0 and by["ALA"]["xmax"] == 180.0
