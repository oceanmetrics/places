"""same-place groups across (and within) collections, for the index's `group_id` and the client's grouped search.

two index rows are the same place when their names match after normalising (accents, case, spacing), their geometry
kind matches (point, line, polygon) and they cover the same ground: bbox IoU >= IOU_MIN for lines and polygons,
centres within POINT_TOL degrees for points. checked against the live index on 2026-10-16: 43 cross-collection
pairs make 19 groups (national marine sanctuaries and parks in noaa_sanctuaries, mpa_inventory, noaa_hapc and
erddap-places' `places`; the smallest IoU 0.81, Monitor NMS) and 2 groups are HAPCs listed twice in noaa_hapc;
homonyms (GEBCO features in different oceans), zones split into several polygons and a seamount beside the HAPC named
after it do not. placeholder names never group: FWS names species without a common name "No common name", so
overlapping habitats of different Mariana plants shared one name.

every copy stays in the index (each has its own licence, vintage and geometry); apps choose which copy to show.
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

IOU_MIN = 0.8
POINT_TOL = 0.001   # degrees, about 100 m
PLACEHOLDER = re.compile(r"^(no common name|unnamed|unknown|no name|n/?a)\b")

# which copy of a place an app shows by default (layers.json `search_rank`, lower first): the agency's own layer (0),
# then layers that re-use other agencies' boundaries (1: the MPA Inventory, ProtectedSeas Navigator; HAPCs drawn on
# sanctuary lines), then
# legacy copies (2: erddap-places' `places`). an app can override it (client `search({ group, prefer })`).
SEARCH_RANK = {"mpa_inventory": 1, "noaa_hapc": 1, "protectedseas_navigator": 1, "places": 2}


def search_rank(slug: str) -> int:
  return SEARCH_RANK.get(slug, 0)


def norm_name(s: str | None) -> str:
  """lower case, accents and repeated spaces removed: the name key two copies must share."""
  if not s:
    return ""
  s = "".join(c for c in unicodedata.normalize("NFD", s) if not unicodedata.combining(c))
  return " ".join(s.lower().split())


def kind(geom_type: str | None) -> str:
  t = (geom_type or "").lower()
  return "point" if "point" in t else "line" if "line" in t else "polygon" if "polygon" in t else t


def _box(r: dict):
  b = r.get("bbox")
  return (b["xmin"], b["ymin"], b["xmax"], b["ymax"]) if b and None not in b.values() else None


def bbox_iou(a, b) -> float:
  """intersection over union of two [xmin, ymin, xmax, ymax] boxes (unwrapped: xmax may exceed 180)."""
  ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
  iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
  inter = ix * iy
  union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
  return inter / union if union > 0 else 0.0


def same_place(a: dict, b: dict) -> bool:
  """the pair rule for two index rows with the same normalised name."""
  if kind(a.get("geom_type")) != kind(b.get("geom_type")):
    return False
  ba, bb = _box(a), _box(b)
  if ba is None or bb is None:
    return False
  area_a, area_b = (ba[2] - ba[0]) * (ba[3] - ba[1]), (bb[2] - bb[0]) * (bb[3] - bb[1])
  if area_a > 0 and area_b > 0:
    return bbox_iou(ba, bb) >= IOU_MIN
  # points, and lines whose box has no area: the same position within POINT_TOL
  return all(abs(x - y) <= POINT_TOL for x, y in zip(ba, bb))


def same_place_groups(rows: list[dict]) -> list[str | None]:
  """group_id per row: `<collection>/<place_id>` of the group's first member in that order, None for a place with no
  other copy. rows need name, collection, place_id, geom_type and bbox (a dict of xmin, ymin, xmax, ymax)."""
  parent = list(range(len(rows)))

  def find(i):
    while parent[i] != i:
      parent[i] = parent[parent[i]]
      i = parent[i]
    return i

  by_name = defaultdict(list)
  for i, r in enumerate(rows):
    k = norm_name(r.get("name"))
    if k and not PLACEHOLDER.match(k):
      by_name[k].append(i)
  for idx in by_name.values():
    for x in range(len(idx)):
      for y in range(x + 1, len(idx)):
        i, j = idx[x], idx[y]
        if same_place(rows[i], rows[j]):
          parent[find(i)] = find(j)

  members = defaultdict(list)
  for i in range(len(rows)):
    members[find(i)].append(i)
  out: list[str | None] = [None] * len(rows)
  for m in members.values():
    if len(m) > 1:
      gid = min(f"{rows[i]['collection']}/{rows[i]['place_id']}" for i in m)
      for i in m:
        out[i] = gid
  return out
