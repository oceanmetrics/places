"""antimeridian-aware bboxes for the published metadata (the GeoParquet `geo` bbox, STAC extents, layers.json).

RFC 7946 section 5, which STAC and GeoParquet both follow: [west, south, east, north] with west > east crosses
+/-180. Geometries are stored split at +/-180 (`geom.split_antimeridian`), so a plain min/max over their coordinates
gives a place like Papahanaumokuakea (177.8..180 plus -180..-161) the band round the whole globe. The rule here gives
it [177.8, s, -161, n] instead.

The per-row `bbox` covering column is NOT changed: readers filter it with plain xmin <= x <= xmax comparisons.

Twin of `union_bbox()` in oceanmetrics/erddap-places catalog/erin_layers/bbox.py and `unionBbox()` in its
app/src/lib/gazetteer.ts; tests/fixtures/union_bbox_cases.json is a copy of its catalog/tests/union_bbox_cases.json.

  uv run python -m gazetteer.bbox join-extent <collection.json> [--data <places.parquet> ...]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pyarrow.parquet as pq
import shapely


def union_bbox(boxes) -> list[float]:
  """the smallest [west, south, east, north] holding every box (a box may itself cross +/-180).

  longitude is a circle: the result leaves out the widest stretch no box covers. boxes covering every longitude
  give -180..180; a tie keeps the box that does not cross.
  """
  boxes = [list(b)[:4] for b in boxes]
  if not boxes:
    raise ValueError("union_bbox: no boxes")
  s, n = min(b[1] for b in boxes), max(b[3] for b in boxes)
  spans = sorted(s_ for w, _, e, _ in boxes for s_ in ([(w, e)] if w <= e else [(w, 180.0), (-180.0, e)]))
  merged: list[list[float]] = []
  for a, b in spans:
    if merged and a <= merged[-1][1]:
      merged[-1][1] = max(merged[-1][1], b)
    else:
      merged.append([a, b])
  # the widest gap: round the back of the globe (last span to first) or between two spans
  w, e = merged[0][0], merged[-1][1]
  gap = w + 360 - e
  for left, right in zip(merged, merged[1:]):
    if right[0] - left[1] > gap:
      gap, w, e = right[0] - left[1], right[0], left[1]
  return [float(w), float(s), float(e), float(n)]


def wrap_bbox(b) -> list[float]:
  """an unwrapped bbox (east beyond 180, as the index stores a place cut at +/-180) as a crossing one."""
  w, s, e, n = (float(x) for x in list(b)[:4])
  if e - w >= 360:
    return [-180.0, s, 180.0, n]
  return [w, s, e - 360, n] if e > 180 else [w, s, e, n]


def unwrap_bbox(b) -> list[float]:
  """a crossing bbox (west > east) with east moved past 180, for map fitBounds (which wants west < east)."""
  w, s, e, n = (float(x) for x in list(b)[:4])
  return [w, s, e + 360, n] if w > e else [w, s, e, n]


def place_bbox(geom) -> list[float] | None:
  """one place's bbox: its parts grouped by side of +/-180 when they span more than 180 degrees of longitude (as
  erddap-places `placeLobes()` groups them), then unioned. None for an empty geometry."""
  if geom is None or shapely.is_empty(geom):
    return None
  parts = [p.bounds for p in shapely.get_parts(geom) if not p.is_empty]
  if max(b[2] for b in parts) - min(b[0] for b in parts) <= 180:
    return union_bbox([[min(b[0] for b in parts), min(b[1] for b in parts),
                        max(b[2] for b in parts), max(b[3] for b in parts)]])
  sides = [[b for b in parts if (b[0] + b[2]) / 2 < 0], [b for b in parts if (b[0] + b[2]) / 2 >= 0]]
  return union_bbox([[min(b[0] for b in g), min(b[1] for b in g), max(b[2] for b in g), max(b[3] for b in g)]
                     for g in sides if g])


def geometries_bbox(geoms) -> list[float]:
  """the union of every place's bbox, for a whole file or collection."""
  boxes = [b for b in (place_bbox(g) for g in geoms) if b is not None]
  return union_bbox(boxes)


def parquet_bbox(path: Path, column: str = "geometry") -> list[float]:
  """`geometries_bbox()` of a GeoParquet file's WKB geometry column."""
  wkb = pq.read_table(path, columns=[column]).column(column).to_pylist()
  return geometries_bbox(shapely.from_wkb([w for w in wkb if w is not None]))


def join_extent(collection_json: Path, data: list[Path] | None = None) -> list[list[float]]:
  """portolan 0.8.0 `add` writes a crossing extent as its two halves ([-180..e], [w..180]); STAC reads the FIRST bbox
  as the overall extent, so join every extent bbox into one `union_bbox()`. returns the new extent.

  with `data` (GeoParquet files) the extent is measured from them instead: on a republish portolan unions the new
  bbox with the extent already in collection.json, so a collection first published as -180..180 would keep it."""
  c = json.loads(Path(collection_json).read_text())
  boxes = c["extent"]["spatial"]["bbox"]
  joined = [union_bbox([parquet_bbox(Path(d)) for d in data] if data else boxes)]
  if joined != boxes:
    c["extent"]["spatial"]["bbox"] = joined
    Path(collection_json).write_text(json.dumps(c, indent=2, ensure_ascii=False) + "\n")
  return joined


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(prog="python -m gazetteer.bbox", description=__doc__.split("\n\n")[0])
  sub = ap.add_subparsers(dest="cmd", required=True)
  j = sub.add_parser("join-extent", help="join a collection.json extent into one antimeridian-aware bbox")
  j.add_argument("collection", nargs="+", type=Path)
  j.add_argument("--data", nargs="+", type=Path, help="measure the extent from these GeoParquet files")
  a = ap.parse_args(argv)
  for c in a.collection:
    print(f"{c}: extent {join_extent(c, a.data)}")
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
