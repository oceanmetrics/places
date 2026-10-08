"""place_id rules: one id per row, unique inside a collection, matching the collection's pattern."""
from __future__ import annotations

import re
from collections import defaultdict

from .fmt import render, slug


def suffix_duplicates(ids: list[str], labels: list[str], order: list) -> list[str]:
  """make ids unique: of rows sharing an id, the one that sorts first (by `order`) keeps it.

  the others get ':<label slug>' (e.g. ':easement'); a repeat of the same label gets '-2', '-3', ...
  deterministic for a given order, so ids stay stable while the source's sort keys do.
  """
  groups: dict[str, list[int]] = defaultdict(list)
  for i, pid in enumerate(ids):
    groups[pid].append(i)
  out = list(ids)
  for pid, idx in groups.items():
    if len(idx) == 1:
      continue
    idx = sorted(idx, key=lambda i: order[i])
    seen: dict[str, int] = defaultdict(int)
    for rank, i in enumerate(idx):
      if rank == 0:
        continue
      base = f"{pid}:{slug(labels[i]) or 'part'}"
      seen[base] += 1
      out[i] = base if seen[base] == 1 else f"{base}-{seen[base]}"
  return out


def build_place_ids(cfg_id: dict, attrs: list[dict], maps: dict | None = None) -> list[str]:
  """place ids for a list of native-attribute dicts.

  rule `lease`: BOEM:<normalised LEASE_NUMBER>; extra polygons of one lease (easements, split leases) get
  ':<lease type>[-n]', the commercial polygon (then lowest OBJECTID) keeping the bare id.
  otherwise `template` is rendered per row and duplicates are an error.
  """
  if cfg_id.get("rule") == "lease":
    ids = [f"BOEM:{render('{LEASE_NUMBER|lease_number}', a)}" for a in attrs]
    labels = [(a.get("LEASE_TYPE") or "part") for a in attrs]
    order = [(0 if "commercial" in (a.get("LEASE_TYPE") or "commercial").lower() else 1, a.get("OBJECTID") or 0)
             for a in attrs]
    return suffix_duplicates(ids, labels, order)
  ids = [render(cfg_id["template"], a, maps) for a in attrs]
  dup = sorted({i for i in ids if ids.count(i) > 1})
  if dup:
    raise ValueError(f"duplicate place_id from template {cfg_id['template']!r}: {dup[:5]}")
  return ids


def check_place_ids(ids: list[str], pattern: str) -> None:
  """raise unless every id is non-empty, unique and matches the collection's pattern."""
  bad = [i for i in ids if not re.fullmatch(pattern, i)]
  if bad:
    raise ValueError(f"{len(bad)} place_id(s) do not match {pattern!r}, e.g. {bad[:3]}")
  dup = sorted({i for i in ids if ids.count(i) > 1})
  if dup:
    raise ValueError(f"duplicate place_id(s): {dup[:5]}")
