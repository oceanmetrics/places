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


# getPlace is a range read: footer + the row groups whose place_id min/max admit the id ----
WAVE1 = ["calcofi_lines", "calcofi_stations", "fws_critical_habitat_proposed", "gebco_undersea", "mpa_inventory", "noaa_hapc",
         "noaa_marine_monuments", "noaa_maritime_limits", "noaa_nerrs", "noaa_sanctuaries", "noaa_state_lateral_boundaries",
         "noaa_state_submerged_lands", "noaa_submarine_cables", "noaa_vessel_routing_measures", "usace_danger_zones"]


def lookup_bytes(path, place_id):
  """bytes of row-group data a client reads for one place: every row group whose place_id statistics admit the id
  (a group without statistics must be read), as hyparquet's filter { place_id: { $eq } } does. The footer
  (md.serialized_size, read once per file and cached) comes on top; it is asserted separately below."""
  md = pq.ParquetFile(path).metadata
  total = 0
  for i in range(md.num_row_groups):
    g = md.row_group(i)
    col = next(g.column(j) for j in range(g.num_columns) if g.column(j).path_in_schema == "place_id")
    st = col.statistics
    if st is None or not st.has_min_max or st.min <= place_id <= st.max:
      total += sum(g.column(j).total_compressed_size for j in range(g.num_columns))
  return total


def test_mpa_inventory_getplace_reads_under_1mb():
  """regression: one getPlace of MPAINV:CA136 pulled 30.5 MB (10 Morton row groups of 100 rows, overlapping id ranges)."""
  d = staged("mpa_inventory")
  assert lookup_bytes(d / "places.parquet", "MPAINV:CA136") < 1_000_000


def test_noaa_sanctuaries_getplace_does_not_read_the_whole_file():
  """regression: the layer was ONE 5.5 MB row group, so every lookup read the file."""
  d = staged("noaa_sanctuaries")
  md = pq.ParquetFile(d / "places.parquet").metadata
  assert md.num_row_groups == md.num_rows == 47
  pid = pq.read_table(d / "places.parquet", columns=["place_id"]).column(0)[0].as_py()
  assert lookup_bytes(d / "places.parquet", pid) < 600_000


@pytest.mark.parametrize("slug", WAVE1)
def test_wave1_row_groups_keep_the_footer_small_and_rows_carry_the_collection_version(slug):
  d = staged(slug)
  md = pq.ParquetFile(d / "places.parquet").metadata
  assert md.serialized_size < 1_300_000                      # the footer is read once by every opener
  if md.num_rows > 1 and md.num_row_groups == 1:
    assert (d / "places.parquet").stat().st_size < 300_000   # a single-group table is only allowed when it is tiny
  versions = set(pq.read_table(d / "places.parquet", columns=["version"]).column(0).to_pylist())
  coll = json.loads((d / "collection.json").read_text())
  assert versions == {coll.get("version") or coll["gazetteer:provenance"]["version"]} and versions != {"1.0.0"}   # republishes of 1.0.0
