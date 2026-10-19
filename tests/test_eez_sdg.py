"""proto/eez_sdg: one SDG value per Marine Regions EEZ (latest year; territory, else sovereign; none for shared zones)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "proto" / "eez_sdg"))
from sdg import eez_value, eez_values, latest_by_area  # noqa: E402


def rec(code, year, value):
  return {"geoAreaCode": str(code), "timePeriodStart": float(year), "value": value}


def test_latest_numeric_year_per_area():
  recs = [rec(8, 2020, "10"), rec(8, 2024, "12.5"), rec(8, 2025, "NaN?"), rec(8, 2026, "NaN"), rec(56, 2019, "3"), rec(56, 2021, None)]
  assert latest_by_area(recs) == {8: {"value": 12.5, "year": 2024}, 56: {"value": 3.0, "year": 2019}}


def test_territory_then_sovereign_then_none():
  latest = {250: {"value": 40.0, "year": 2025}, 540: {"value": 7.0, "year": 2024}}
  ncl = {"pol_type": "200NM", "un_ter1": 540, "un_sov1": 250}   # New Caledonia: reported itself
  pyf = {"pol_type": "200NM", "un_ter1": 258, "un_sov1": 250}   # unreported territory: France's value
  assert eez_value(ncl, latest) == {"value": 7.0, "year": 2024, "m49": 540, "basis": "territory"}
  assert eez_value(pyf, latest) == {"value": 40.0, "year": 2025, "m49": 250, "basis": "sovereign"}
  assert eez_value({"pol_type": "200NM", "un_ter1": 1, "un_sov1": None}, latest) is None


def test_joint_regimes_and_overlapping_claims_get_no_value():
  latest = {250: {"value": 40.0, "year": 2025}}
  for pol in ("Joint regime", "Overlapping claim"):
    assert eez_value({"pol_type": pol, "un_ter1": 250, "un_sov1": 250}, latest) is None


def test_eez_values_keyed_by_mrgid_string():
  eezs = [{"source_id": 3293, "name": "Belgian EEZ", "pol_type": "200NM", "un_ter1": 56, "un_sov1": 56}]
  out = eez_values(eezs, {"ER_MRN_MPA": [rec(56, 2024, "80")]})
  assert out == {"3293": {"name": "Belgian EEZ", "pol_type": "200NM",
                          "ER_MRN_MPA": {"value": 80.0, "year": 2024, "m49": 56, "basis": "territory"}}}
