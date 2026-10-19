"""SDG 14 indicator values per Marine Regions EEZ (prototype): UN SDG Global Database series -> one value per EEZ.

the UN SDG API reports by M49 area code; Marine Regions EEZs carry the M49 code of their territory (`un_ter1`) and
sovereign (`un_sov1`). an EEZ takes its territory's latest value, else its sovereign's (e.g. a territory the UN does
not report separately); joint regimes and overlapping claims (`pol_type` other than 200NM) belong to more than one
state, so they get no value.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import requests

SDG_API = "https://unstats.un.org/sdgapi/v1/sdg/Series/Data"

SERIES = {
  "ER_MRN_MPA": {"indicator": "14.5.1", "short": "Marine KBAs protected", "units": "%", "domain": [0, 100]},
  "EN_MAR_CHLDEV": {"indicator": "14.1.1", "short": "Chlorophyll-a deviation", "units": "%", "domain": None},
  "ER_REG_UNFCIM": {"indicator": "14.6.1", "short": "IUU instruments implemented", "units": "score 1-5",
                    "domain": [1, 5]},
}


def fetch_series(code: str, cache_dir: Path) -> dict:
  """the whole series from the UN SDG API (one request, cached as <code>.json)."""
  f = cache_dir / f"{code}.json"
  if not f.exists():
    r = requests.get(SDG_API, params={"seriesCode": code, "pageSize": 50000}, timeout=300)
    r.raise_for_status()
    cache_dir.mkdir(parents=True, exist_ok=True)
    f.write_text(r.text)
  return json.loads(f.read_text())


def latest_by_area(records: list[dict]) -> dict[int, dict]:
  """M49 code -> {value, year} of the latest year with a numeric value."""
  out: dict[int, dict] = {}
  for r in records:
    try:
      v, code, yr = float(r["value"]), int(r["geoAreaCode"]), int(r["timePeriodStart"])
    except (TypeError, ValueError):
      continue
    if not math.isfinite(v):   # the API serves "NaN" for some country-years
      continue
    if code not in out or yr > out[code]["year"]:
      out[code] = {"value": v, "year": yr}
  return out


def eez_value(eez: dict, latest: dict[int, dict]) -> dict | None:
  """the value for one EEZ row (pol_type, un_ter1, un_sov1), with the M49 area it came from; None when not single-state
  or unreported."""
  if eez.get("pol_type") != "200NM":
    return None
  for basis, key in (("territory", "un_ter1"), ("sovereign", "un_sov1")):
    m49 = eez.get(key)
    if m49 is not None and int(m49) in latest:
      return {**latest[int(m49)], "m49": int(m49), "basis": basis}
  return None


def eez_values(eezs: list[dict], series: dict[str, list[dict]]) -> dict[str, dict]:
  """source_id (MRGID) -> {name, pol_type, <series code>: value or None} for every EEZ row."""
  latest = {code: latest_by_area(recs) for code, recs in series.items()}
  out = {}
  for e in eezs:
    row = {"name": e["name"], "pol_type": e["pol_type"]}
    for code in series:
      row[code] = eez_value(e, latest[code])
    out[str(e["source_id"])] = row
  return out
