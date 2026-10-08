import datetime as dt

import pytest

from conftest import lease_cfg, lease_result, square
from gazetteer.status import load_overlay, resolve_status, unmatched_overlay
from gazetteer.table import build_rows

LAYER = {"value": "active", "source": "https://example.test/layer", "date": "data_last_edit"}


def test_overlay_marks_ocs_p_0561_relinquished(tmp_path):
  cfg = lease_cfg(tmp_path)
  res = lease_result([(71, "OCS-P 0561", "Commercial", "RWE", square(0, 0)),
                      (72, "OCS-P 0562", "Commercial", "CalNorth", square(2, 0)),
                      (73, "OCS-P 0563", "Commercial", "Atlas", square(4, 0))])
  rows, _, _ = build_rows(cfg, [res])
  by = {r["source_id"]: r for r in rows}
  assert (by["OCS-P 0561"]["status"], by["OCS-P 0561"]["status_date"]) == ("relinquished", "2026-09-03")
  assert by["OCS-P 0561"]["status_source"] == "https://example.test/ca"
  assert by["OCS-P 0562"]["status"] == "active" and by["OCS-P 0562"]["status_date"] == ""
  # not in the overlay: the layer default, dated by the layer's last edit
  assert by["OCS-P 0563"]["status"] == "active"
  assert by["OCS-P 0563"]["status_source"] == "https://example.test/layer"
  assert by["OCS-P 0563"]["status_date"] == "2025-03-04"


def test_atlantic_lease_with_the_same_number_is_not_touched_by_the_pacific_overlay(tmp_path):
  cfg = lease_cfg(tmp_path)
  res = lease_result([(909, "OCS-A 0561", "Commercial", "Commonwealth Wind", square(0, 0)),
                      (71, "OCS-P 0561", "Commercial", "RWE", square(5, 0))])
  rows, _, _ = build_rows(cfg, [res])
  by = {r["place_id"]: r for r in rows}
  assert by["BOEM:OCS-A 0561"]["status"] == "active"
  assert by["BOEM:OCS-P 0561"]["status"] == "relinquished"


def test_partial_date_year_is_kept_as_given(tmp_path):
  cfg = lease_cfg(tmp_path)
  rows, _, _ = build_rows(cfg, [lease_result([(75, "OCS-P 0565", "Commercial", "Invenergy", square(0, 0))])])
  assert (rows[0]["status"], rows[0]["status_date"]) == ("cancelled", "2026")


def test_every_row_carries_status_columns(tmp_path):
  cfg = lease_cfg(tmp_path)
  rows, _, _ = build_rows(cfg, [lease_result([(1, "OCS-A 0001", "Commercial", "X", square(0, 0))])])
  assert all(rows[0][k] for k in ("status", "status_source", "status_date"))


def test_status_date_from_a_native_epoch_ms_field():
  ms = int(dt.datetime(1991, 5, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
  s = resolve_status({"value": "active", "source": "s", "date": "field:LSE_STAT_EFF_DT"}, {"LSE_STAT_EFF_DT": ms}, None)
  assert s == ("active", "s", "1991-05-01")
  assert resolve_status({"value": "active", "source": "s", "date": "field:LSE_STAT_EFF_DT"}, {}, None)[2] == ""


def test_literal_date_and_constant_status():
  s = resolve_status({"value": "rescinded", "source": "u", "date": "2025-07-30"}, {}, "2025-02-20")
  assert s == ("rescinded", "u", "2025-07-30")


def test_overlay_loader_and_unmatched_keys(tmp_path):
  cfg = lease_cfg(tmp_path)
  ov = load_overlay(tmp_path / "boem" / "overlay.csv")
  assert ov["OCS-P 0561"]["status"] == "relinquished"
  assert unmatched_overlay(ov, [{"LEASE_NUMBER": "OCS-P 0561"}], "LEASE_NUMBER") == ["OCS-P 0562", "OCS-P 0565"]
  (tmp_path / "boem" / "dup.csv").write_text("lease_number,status,status_source,status_date\nA,x,y,z\nA,x,y,z\n")
  with pytest.raises(ValueError, match="duplicate"):
    load_overlay(tmp_path / "boem" / "dup.csv")


def test_the_shipped_overlay_matches_the_brief():
  from conftest import ROOT
  ov = load_overlay(ROOT / "sources" / "boem" / "wind_lease_status.csv")
  assert {k: v["status"] for k, v in ov.items()} == {
    "OCS-P 0565": "cancelled", "OCS-P 0561": "relinquished", "OCS-P 0564": "settlement_pending",
    "OCS-P 0562": "active", "OCS-P 0563": "active"}
  assert ov["OCS-P 0561"]["status_date"] == "2026-09-03" and ov["OCS-P 0565"]["status_date"] == "2026"
  assert all(v["status_source"] == "https://www.boem.gov/renewable-energy/state-activities/california" for v in ov.values())
