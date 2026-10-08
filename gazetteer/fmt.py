"""tiny template language for names, ids and source ids: "{FIELD}", "{FIELD|filter}", "{FIELD|map:table}".

values are stripped; None becomes ''. filters: strip (default), lease_number, prefix:<text> (text + value when
non-empty), map:<table> (lookup in the config's `maps`, a missing key keeps the value), slug.
"""
from __future__ import annotations

import re

_FIELD = re.compile(r"\{([^{}|]+)((?:\|[^{}|]+)*)\}")


def normalize_lease_number(value: str | None) -> str:
  """BOEM lease number -> formal form: 'P00202' -> 'OCS-P 0202', 'OCS-A 0501' unchanged, 'OCS-G 37334 Provisional' -> 'OCS-G 37334'."""
  v = (value or "").strip()
  if not v:
    return ""
  m = re.fullmatch(r"([A-Z])0*(\d+)", v)          # legacy Pacific style, e.g. P00202
  if m:
    return f"OCS-{m.group(1)} {int(m.group(2)):04d}"
  m = re.match(r"OCS-([A-Z])\s+0*(\d+)\b", v)      # formal style: renormalise the padding, drop qualifiers ("... Provisional")
  if m:
    return f"OCS-{m.group(1)} {int(m.group(2)):04d}"
  return v


def slug(value: str) -> str:
  return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _apply(value: str, flt: str, maps: dict) -> str:
  name, _, arg = flt.partition(":")
  if name == "strip":
    return value.strip()
  if name == "lease_number":
    return normalize_lease_number(value)
  if name == "prefix":
    return f"{arg}{value}" if value else ""
  if name == "map":
    return str(maps[arg].get(value, value))
  if name == "slug":
    return slug(value)
  raise ValueError(f"unknown template filter: {flt}")


def render(template: str, attrs: dict, maps: dict | None = None) -> str:
  """fill a template from a row's native attributes; runs of whitespace collapse to one space."""
  maps = maps or {}

  def sub(m: re.Match) -> str:
    field, filters = m.group(1), [f for f in m.group(2).split("|") if f]
    raw = attrs.get(field)
    value = "" if raw is None else str(raw).strip()
    for f in filters:
      value = _apply(value, f, maps)
    return value

  return re.sub(r"\s+", " ", _FIELD.sub(sub, template)).strip()
