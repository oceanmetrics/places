"""status, status_source, status_date, status_upstream and status_history (place level) and the layer-level status.

place level: a collection default (`status:` in the config), optionally overridden by a hand-kept, dated event log
(`status.events`, e.g. sources/boem/wind_lease_status_events.csv): the latest event of a key is its current status
and every event goes into `status_history`. `status.upstream` names the native field holding the source's own
status code, copied verbatim into `status_upstream` (it may disagree with our `status`; that is the point).

layer level: `layer_status` (one event) and/or `layer_status_history` (ascending events) in the config, written to
collection.json as `gazetteer:status` / `gazetteer:status_history` (scripts/build_layers_json.py carries them into
layers.json as `status`, `status_history` and `status_label`).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import re
from pathlib import Path

log = logging.getLogger(__name__)

DATE_RE = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")      # 2026, 2026-07 or 2026-07-10
EVENT_COLUMNS = ["lease_number", "date", "status", "source", "note"]


# place-level event log ----
def load_events(path: str | Path) -> dict[str, list[dict]]:
  """event log CSV (lease_number,date,status,source,note) -> {key: [event, ...]} ascending by date.

  every event needs a date (YYYY, YYYY-MM or YYYY-MM-DD), a status and a source URL; a repeated
  (key, date, status) is an error. events on the same date keep the file order.
  """
  out: dict[str, list[dict]] = {}
  seen = set()
  with open(path, newline="", encoding="utf-8") as fh:
    rd = csv.DictReader(fh)
    missing = [c for c in EVENT_COLUMNS if c not in (rd.fieldnames or [])]
    if missing:
      raise ValueError(f"{path}: missing column(s) {missing}")
    for i, row in enumerate(rd, start=2):
      r = {k: (row.get(k) or "").strip() for k in EVENT_COLUMNS}
      key = r["lease_number"]
      if not key:
        continue
      if not DATE_RE.match(r["date"]):
        raise ValueError(f"{path}:{i}: date {r['date']!r} is not YYYY, YYYY-MM or YYYY-MM-DD")
      if not r["status"] or not r["source"].startswith("http"):
        raise ValueError(f"{path}:{i}: an event needs a status and a source URL")
      if (key, r["date"], r["status"]) in seen:
        raise ValueError(f"{path}:{i}: duplicate event {key} {r['date']} {r['status']}")
      seen.add((key, r["date"], r["status"]))
      out.setdefault(key, []).append({"date": r["date"], "value": r["status"], "source": r["source"], "note": r["note"]})
  return {k: sorted(v, key=lambda e: e["date"]) for k, v in out.items()}


def history_json(events: list[dict] | None) -> str | None:
  """ascending events -> the `status_history` JSON string ([{date, value, source, note}]); None when there are none."""
  if not events:
    return None
  return json.dumps([{k: e.get(k) or None for k in ("date", "value", "source", "note")} for e in events],
                    ensure_ascii=False, separators=(",", ":"))


def _iso_date(value) -> str:
  """epoch milliseconds, datetime, date or string -> 'YYYY-MM-DD' (strings pass through); None -> ''."""
  if value is None or value == "":
    return ""
  if isinstance(value, (int, float)):
    return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()
  if isinstance(value, dt.datetime):
    return value.date().isoformat()
  return str(value)


def resolve_status(cfg_status: dict, attrs: dict, data_last_edit: str | None, events: dict | None = None,
                   events_key_field: str | None = None, retrieved: str | None = None) -> tuple[str, str, str]:
  """(status, status_source, status_date) for one row.

  value: a literal, or 'field:NAME' (a native attribute, lower-cased; `default` when empty).
  date: a literal ('2025-07-30'), 'data_last_edit' (the source's last edit day; EMPTY when the source serves no edit
  date, never the retrieval day: an app shows status_date as the date the status took effect, so "designated
  2026-10-14" for a 2024 sanctuary would be false) or 'field:NAME' (a native date attribute).
  the latest event of the row's key (matched on the exact events_key_field value) wins over the default.
  """
  spec = str(cfg_status.get("date") or "")
  if spec == "data_last_edit":
    date = (data_last_edit or "")[:10]
  elif spec.startswith("field:"):
    date = _iso_date(attrs.get(spec[6:]))
  else:
    date = spec
  value = cfg_status["value"]
  if str(value).startswith("field:"):             # status from a native attribute (lower-cased), else `default`
    value = str(attrs.get(value[6:]) or "").strip().lower() or cfg_status.get("default", "unknown")
  result = (value, cfg_status["source"], date)
  hit = row_events(attrs, events, events_key_field)
  if hit:
    last = hit[-1]
    result = (last["value"], last["source"], last["date"])
  return result


def row_events(attrs: dict, events: dict | None, key_field: str | None) -> list[dict]:
  """the events logged for one row (exact key match), ascending; [] when none."""
  if not events or not key_field:
    return []
  return events.get(str(attrs.get(key_field) or "").strip()) or []


def upstream_status(cfg_status: dict, attrs: dict) -> str | None:
  """the source's own status code, verbatim (stripped), from the native field named by `status.upstream`; else None."""
  field = cfg_status.get("upstream")
  if not field:
    return None
  v = attrs.get(field)
  return None if v is None or str(v).strip() == "" else str(v).strip()


def unmatched_events(events: dict, attrs_list: list[dict], key_field: str) -> list[str]:
  """event-log keys that no row matched (the source dropped the lease, or the key is mistyped)."""
  have = {str(a.get(key_field) or "").strip() for a in attrs_list}
  missing = sorted(k for k in events if k not in have)
  for k in missing:
    log.warning("status event key %r matches no feature", k)
  return missing


# layer level ----
def _event(e: dict, where: str) -> dict:
  if not isinstance(e, dict):
    raise ValueError(f"{where}: must be a mapping with value, date and source")
  out = {"date": str(e.get("date") or "").strip(), "value": str(e.get("value") or "").strip(),
         "source": str(e.get("source") or "").strip(), "note": " ".join(str(e.get("note") or "").split()) or None}
  errs = [f"{where}.{k} missing" for k in ("value", "date", "source") if not out[k]]
  if out["date"] and not DATE_RE.match(out["date"]):
    errs.append(f"{where}.date {out['date']!r} is not YYYY, YYYY-MM or YYYY-MM-DD")
  if errs:
    raise ValueError("; ".join(errs))
  return out


def layer_status(cfg: dict) -> tuple[dict | None, list[dict] | None]:
  """(status, history) of the layer as a whole, from `layer_status` and/or `layer_status_history`; (None, None) when
  the config documents none.

  history is ascending by date; status is the given `layer_status`, else the latest history event. a status
  without a history becomes a one-event history; a given status must be the latest event of a given history.
  """
  st, hist = cfg.get("layer_status"), cfg.get("layer_status_history")
  if not st and not hist:
    return None, None
  if hist is not None and not isinstance(hist, list):
    raise ValueError("layer_status_history must be a list of events")
  history = sorted((_event(e, f"layer_status_history[{i}]") for i, e in enumerate(hist or [])), key=lambda e: e["date"])
  status = _event(st, "layer_status") if st else history[-1]
  if not history:
    history = [status]
  elif st and (history[-1]["date"], history[-1]["value"]) != (status["date"], status["value"]):
    raise ValueError("layer_status must be the latest event of layer_status_history")
  return dict(status), history
