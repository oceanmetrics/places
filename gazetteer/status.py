"""status, status_source and status_date: a collection default, optionally overridden by a hand-kept overlay."""
from __future__ import annotations

import csv
import datetime as dt
import logging
from pathlib import Path

log = logging.getLogger(__name__)


def load_overlay(path: str | Path) -> dict[str, dict]:
  """overlay CSV (lease_number,status,status_source,status_date) -> {lease_number: row}; a duplicate key is an error."""
  out: dict[str, dict] = {}
  with open(path, newline="", encoding="utf-8") as fh:
    for row in csv.DictReader(fh):
      key = (row["lease_number"] or "").strip()
      if not key:
        continue
      if key in out:
        raise ValueError(f"{path}: duplicate overlay key {key!r}")
      out[key] = {k: (row.get(k) or "").strip() for k in ("status", "status_source", "status_date")}
  return out


def _iso_date(value) -> str:
  """epoch milliseconds, datetime, date or string -> 'YYYY-MM-DD' (strings pass through); None -> ''."""
  if value is None or value == "":
    return ""
  if isinstance(value, (int, float)):
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()
  if isinstance(value, dt.datetime):
    return value.date().isoformat()
  return str(value)


def resolve_status(cfg_status: dict, attrs: dict, data_last_edit: str | None, overlay: dict | None = None,
                   overlay_key_field: str | None = None) -> tuple[str, str, str]:
  """(status, status_source, status_date) for one row.

  date: a literal ('2025-07-30'), 'data_last_edit' (the source's last edit day) or 'field:NAME' (a native
  date attribute). an overlay row (matched on the exact overlay_key_field value) wins over the default.
  """
  spec = str(cfg_status.get("date") or "")
  if spec == "data_last_edit":
    date = (data_last_edit or "")[:10]
  elif spec.startswith("field:"):
    date = _iso_date(attrs.get(spec[6:]))
  else:
    date = spec
  result = (cfg_status["value"], cfg_status["source"], date)
  if overlay and overlay_key_field:
    hit = overlay.get(str(attrs.get(overlay_key_field) or "").strip())
    if hit:
      result = (hit["status"], hit["status_source"], hit["status_date"])
  return result


def unmatched_overlay(overlay: dict, attrs_list: list[dict], key_field: str) -> list[str]:
  """overlay keys that no row matched (the source dropped the lease, or the key is mistyped)."""
  have = {str(a.get(key_field) or "").strip() for a in attrs_list}
  missing = sorted(k for k in overlay if k not in have)
  for k in missing:
    log.warning("status overlay key %r matches no feature", k)
  return missing
