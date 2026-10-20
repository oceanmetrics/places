"""tiny template language for names, ids and source ids: "{FIELD}", "{FIELD|filter}", "{FIELD|map:table}".

values are stripped; None becomes ''. filters: strip (default), lease_number, prefix:<text> (text + value when
non-empty), map:<table> (lookup in the config's `maps`, a missing key keeps the value), slug,
round (nearest integer), default:<text> (text when the value is empty), blank:<text> (empty when the value is <text>,
ignoring case: a source's placeholder), else:<FIELD> (that field's value when the value is empty).
"""
from __future__ import annotations

import re

_FIELD = re.compile(r"\{([^{}|]+)((?:\|[^{}|]+)*)\}")


def normalize_lease_number(value: str | None) -> str:
  """BOEM lease number -> formal form: 'P00202' -> 'OCS-P 0202', 'OCS-A 0501' unchanged, 'OCS-G 37334 Provisional' -> 'OCS-G 37334',
  'OCS-A-00467' -> 'OCS-A 0467'; other forms ('OCS-FL-2000', the placeholder 'OCS-A-XXXX') are kept as served."""
  v = (value or "").strip()
  if not v:
    return ""
  m = re.fullmatch(r"([A-Z])0*(\d+)", v)          # legacy Pacific style, e.g. P00202
  if m:
    return f"OCS-{m.group(1)} {int(m.group(2)):04d}"
  m = re.match(r"OCS-([A-Z])(?:\s+|-)0*(\d+)\b", v)   # formal style, or hyphenated (marine minerals 'OCS-G-23707'):
  #                                                   renormalise the padding, drop qualifiers ("... Provisional")
  if m:
    return f"OCS-{m.group(1)} {int(m.group(2)):04d}"
  return v


def slug(value: str) -> str:
  return re.sub(r"[^a-z0-9]+", "-", (value or "").lower()).strip("-")


def _apply(value: str, flt: str, maps: dict, attrs: dict) -> str:
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
  if name == "round":
    try:
      return str(int(round(float(value))))        # float ids with noise (100062107.99999999 -> 100062108)
    except ValueError:
      return value
  if name == "default":
    return value if value else arg
  if name == "blank":
    return "" if value.lower() == arg.lower() else value
  if name == "else":
    return value if value else str(attrs.get(arg) or "").strip()
  raise ValueError(f"unknown template filter: {flt}")


def render(template: str, attrs: dict, maps: dict | None = None) -> str:
  """fill a template from a row's native attributes; runs of whitespace collapse to one space."""
  maps = maps or {}

  def sub(m: re.Match) -> str:
    field, filters = m.group(1), [f for f in m.group(2).split("|") if f]
    raw = attrs.get(field)
    value = "" if raw is None else str(raw).strip()
    for f in filters:
      value = _apply(value, f, maps, attrs)
    return value

  return re.sub(r"\s+", " ", _FIELD.sub(sub, template)).strip()
