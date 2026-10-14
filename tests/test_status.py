import datetime as dt
import json

import pytest

from conftest import ROOT, lease_cfg, lease_result, square
from gazetteer.config import load_all, validate_config
from gazetteer.status import (history_json, layer_status, load_events, resolve_status, unmatched_events,
                              upstream_status)
from gazetteer.table import build_rows

CA = "https://www.boem.gov/renewable-energy/state-activities/california"


# place level: the event log ----
def test_latest_event_marks_ocs_p_0561_relinquished(tmp_path):
  cfg = lease_cfg(tmp_path)
  res = lease_result([(71, "OCS-P 0561", "Commercial", "RWE", square(0, 0)),
                      (72, "OCS-P 0562", "Commercial", "CalNorth", square(2, 0)),
                      (73, "OCS-P 0563", "Commercial", "Atlas", square(4, 0))])
  rows, _, _ = build_rows(cfg, [res])
  by = {r["source_id"]: r for r in rows}
  assert (by["OCS-P 0561"]["status"], by["OCS-P 0561"]["status_date"]) == ("relinquished", "2026-09-03")
  assert by["OCS-P 0561"]["status_source"] == "https://example.test/ca"
  assert (by["OCS-P 0562"]["status"], by["OCS-P 0562"]["status_date"]) == ("active", "2023-06-01")
  # not in the log: the layer default, dated by the layer's last edit, no history
  assert by["OCS-P 0563"]["status"] == "active"
  assert by["OCS-P 0563"]["status_source"] == "https://example.test/layer"
  assert by["OCS-P 0563"]["status_date"] == "2025-03-04"
  assert by["OCS-P 0563"]["status_history"] is None


def test_status_history_is_the_ascending_event_list_as_json(tmp_path):
  cfg = lease_cfg(tmp_path)
  rows, _, _ = build_rows(cfg, [lease_result([(71, "OCS-P 0561", "Commercial", "RWE", square(0, 0))])])
  # the log lists the 2026-08-04 settlement after the relinquishment: history is sorted by date
  assert json.loads(rows[0]["status_history"]) == [
    {"date": "2023-06-01", "value": "active", "source": "https://example.test/lease-0561", "note": "lease issued"},
    {"date": "2026-08-04", "value": "settlement_pending", "source": "https://example.test/ca", "note": "settlement, agreement"},
    {"date": "2026-09-03", "value": "relinquished", "source": "https://example.test/ca", "note": None}]


def test_atlantic_lease_with_the_same_number_is_not_touched_by_the_pacific_log(tmp_path):
  cfg = lease_cfg(tmp_path)
  res = lease_result([(909, "OCS-A 0561", "Commercial", "Commonwealth Wind", square(0, 0)),
                      (71, "OCS-P 0561", "Commercial", "RWE", square(5, 0))])
  rows, _, _ = build_rows(cfg, [res])
  by = {r["place_id"]: r for r in rows}
  assert by["BOEM:OCS-A 0561"]["status"] == "active" and by["BOEM:OCS-A 0561"]["status_history"] is None
  assert by["BOEM:OCS-P 0561"]["status"] == "relinquished"


def test_partial_date_year_is_kept_as_given(tmp_path):
  cfg = lease_cfg(tmp_path)
  rows, _, _ = build_rows(cfg, [lease_result([(75, "OCS-P 0565", "Commercial", "Invenergy", square(0, 0))])])
  assert (rows[0]["status"], rows[0]["status_date"]) == ("cancelled", "2026")


def test_every_row_carries_status_columns(tmp_path):
  cfg = lease_cfg(tmp_path)
  rows, _, _ = build_rows(cfg, [lease_result([(1, "OCS-A 0001", "Commercial", "X", square(0, 0))])])
  assert all(rows[0][k] for k in ("status", "status_source", "status_date"))
  assert rows[0]["status_upstream"] is None and rows[0]["status_history"] is None


def test_event_loader_validates_dates_sources_and_duplicates(tmp_path):
  head = "lease_number,date,status,source,note\n"
  bad = {"nodate.csv": "A,,active,https://x.test,\n", "baddate.csv": "A,30/07/2025,active,https://x.test,\n",
         "nosrc.csv": "A,2025,active,,\n", "dup.csv": "A,2025,active,https://x.test,\nA,2025,active,https://y.test,\n"}
  for name, body in bad.items():
    (tmp_path / name).write_text(head + body)
    with pytest.raises(ValueError):
      load_events(tmp_path / name)
  (tmp_path / "cols.csv").write_text("lease_number,status,status_source,status_date\nA,x,y,z\n")   # the retired overlay form
  with pytest.raises(ValueError, match="missing column"):
    load_events(tmp_path / "cols.csv")


def test_unmatched_event_keys(tmp_path):
  lease_cfg(tmp_path)
  ev = load_events(tmp_path / "boem" / "events.csv")
  assert unmatched_events(ev, [{"LEASE_NUMBER": "OCS-P 0561"}], "LEASE_NUMBER") == ["OCS-P 0562", "OCS-P 0565"]


def test_history_json_none_without_events():
  assert history_json([]) is None and history_json(None) is None


# place level: dates and the upstream code ----
def test_status_date_from_a_native_epoch_ms_field():
  ms = int(dt.datetime(1991, 5, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
  s = resolve_status({"value": "active", "source": "s", "date": "field:LSE_STAT_EFF_DT"}, {"LSE_STAT_EFF_DT": ms}, None)
  assert s == ("active", "s", "1991-05-01")
  assert resolve_status({"value": "active", "source": "s", "date": "field:LSE_STAT_EFF_DT"}, {}, None)[2] == ""


def test_literal_date_and_constant_status():
  s = resolve_status({"value": "rescinded", "source": "u", "date": "2025-07-30"}, {}, "2025-02-20")
  assert s == ("rescinded", "u", "2025-07-30")


def test_data_last_edit_without_an_edit_date_leaves_status_date_empty_noaa_sanctuaries_regression(tmp_path):
  # noaa_sanctuaries' layer serves no editingInfo.dataLastEditDate. status_date stays empty rather than take the
  # retrieval day (source_date does fall back to it): the Explorer shows "<status> <status_date>" as when the status
  # took effect, and "Chumash Heritage (designated 2026-10-14)" would state a false designation date.
  spec = {"value": "designated", "source": "u", "date": "data_last_edit"}
  assert resolve_status(spec, {}, None, retrieved="2026-10-08T17:03:26Z") == ("designated", "u", "")
  assert resolve_status(spec, {}, "2025-12-29T13:52:33Z", retrieved="2026-10-08T17:03:26Z")[2] == "2025-12-29"
  cfg = lease_cfg(tmp_path)
  rows, _, _ = build_rows(cfg, [lease_result([(1, "OCS-A 0001", "Commercial", "X", square(0, 0))], edit=None)])
  assert rows[0]["status_date"] == ""
  assert rows[0]["source_date"].isoformat() == "2026-10-08"


def test_status_upstream_is_the_native_code_verbatim():
  spec = {"value": "active", "source": "s", "date": "x", "upstream": "LEASE_STATUS_CD"}
  assert upstream_status(spec, {"LEASE_STATUS_CD": "UNIT"}) == "UNIT"
  assert upstream_status(spec, {"LEASE_STATUS_CD": " Active "}) == "Active"
  assert upstream_status(spec, {"LEASE_STATUS_CD": ""}) is None and upstream_status(spec, {}) is None
  assert upstream_status({k: v for k, v in spec.items() if k != "upstream"}, {"LEASE_STATUS_CD": "UNIT"}) is None


def test_rescinded_areas_keep_boems_stale_area_status_in_status_upstream(tmp_path):
  cfg = {**lease_cfg(tmp_path), "status": {"value": "rescinded", "source": "u", "date": "2025-07-30",
                                           "upstream": "AREA_STATUS"}}
  res = lease_result([(1, "OCS-P 0567", "PSN", "x", square(0, 0))])
  res.features[0]["properties"]["AREA_STATUS"] = "Active"
  res.fields.append({"name": "AREA_STATUS", "type": "string"})
  rows, _, _ = build_rows(cfg, [res])
  assert (rows[0]["status"], rows[0]["status_upstream"], rows[0]["status_history"]) == ("rescinded", "Active", None)


# layer level ----
LAYER = {"value": "rescinded", "date": "2025-07-30", "source": "https://boem.test/notice", "note": "BOEM notice"}


def test_layer_status_alone_becomes_a_one_event_history():
  st, hist = layer_status({"layer_status": LAYER})
  assert st == {"date": "2025-07-30", "value": "rescinded", "source": "https://boem.test/notice", "note": "BOEM notice"}
  assert hist == [st]
  assert layer_status({}) == (None, None)


def test_layer_status_from_history_is_the_latest_event_and_history_is_sorted():
  later = {"value": "rescinded", "date": "2025-07-30", "source": "https://b.test"}
  earlier = {"value": "designated", "date": "2018-10-19", "source": "https://a.test"}
  st, hist = layer_status({"layer_status_history": [later, earlier]})
  assert [e["value"] for e in hist] == ["designated", "rescinded"] and st["value"] == "rescinded"
  assert st["note"] is None


def test_layer_status_must_match_the_latest_history_event_and_needs_value_date_source():
  with pytest.raises(ValueError, match="latest event"):
    layer_status({"layer_status": LAYER, "layer_status_history": [{**LAYER, "date": "2025-07-29"}]})
  with pytest.raises(ValueError, match="layer_status.source missing"):
    layer_status({"layer_status": {"value": "x", "date": "2025"}})
  with pytest.raises(ValueError, match="not YYYY"):
    layer_status({"layer_status": {**LAYER, "date": "July 2025"}})


def test_config_rejects_the_retired_overlay_and_a_bad_layer_status(tmp_path):
  cfg = {k: v for k, v in lease_cfg(tmp_path).items() if not k.startswith("_")}
  validate_config(cfg)
  with pytest.raises(ValueError, match="status.overlay is retired"):
    validate_config({**cfg, "status": {**cfg["status"], "overlay": {"file": "x.csv", "key": "K"}}})
  with pytest.raises(ValueError, match="layer_status.date missing"):
    validate_config({**cfg, "layer_status": {"value": "rescinded", "source": "https://x.test"}})
  with pytest.raises(ValueError, match="status.events needs file and key"):
    validate_config({**cfg, "status": {**cfg["status"], "events": {"file": "x.csv"}}})


# the shipped configs ----
CFGS = load_all(ROOT / "sources")


def test_the_shipped_event_log_current_status_per_california_lease():
  ev = load_events(ROOT / "sources" / "boem" / "wind_lease_status_events.csv")
  cur = {k: (v[-1]["value"], v[-1]["date"]) for k, v in ev.items()}
  assert cur == {"OCS-P 0561": ("relinquished", "2026-09-03"), "OCS-P 0562": ("active", "2023-06-01"),
                 "OCS-P 0563": ("active", "2023-06-01"), "OCS-P 0564": ("settlement_pending", "2026-04-27"),
                 "OCS-P 0565": ("cancelled", "2026-07-10")}
  # every lease starts with its 2023-06-01 issuance; every event cites a boem.gov page
  assert all((v[0]["value"], v[0]["date"]) == ("active", "2023-06-01") for v in ev.values())
  assert all(e["source"].startswith("https://www.boem.gov/") for v in ev.values() for e in v)
  assert ev["OCS-P 0561"][-1]["source"] == CA
  assert CFGS["boem_wind_leases"]["status"]["events"] == {"file": "boem/wind_lease_status_events.csv",
                                                          "key": "LEASE_NUMBER"}


def test_shipped_layer_statuses_and_plain_titles():
  got = {s: layer_status(c)[0] for s, c in CFGS.items() if layer_status(c)[0]}
  assert {s: (st["value"], st["date"]) for s, st in got.items()} == {
    "boem_wind_planning_rescinded": ("rescinded", "2025-07-30"),
    "boem_program_11_draft": ("draft_proposed", "2025-11-20"),
    "noaa_aoa_socal": ("identified", "2025-09-19")}
  assert got["boem_wind_planning_rescinded"]["source"] == CFGS["boem_wind_planning_rescinded"]["source_page"]
  assert CFGS["boem_wind_planning_rescinded"]["title"] == "BOEM offshore wind planning areas"
  assert not any("rescinded" in c["title"] for c in CFGS.values())
  assert CFGS["boem_wind_planning_rescinded"]["status"]["upstream"] == "AREA_STATUS"
  assert CFGS["boem_pacific_og_leases"]["status"]["upstream"] == "LEASE_STATUS_CD"


def test_collection_json_carries_the_layer_status_only_when_documented():
  from gazetteer.stac import layer_status_fields
  f = layer_status_fields({"layer_status": LAYER})
  assert f == {"gazetteer:status": {**LAYER}, "gazetteer:status_history": [{**LAYER}]}
  assert layer_status_fields({"status": {"value": "active"}}) == {}
