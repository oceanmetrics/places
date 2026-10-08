"""mixed-geometry collections (`mixed_geometry: true`): points, lines and polygons in one layer, each normalised to its
Multi* type (MultiPoint, MultiLineString, MultiPolygon), EPSG:4326, split at +/-180, with `geom_type` set per row."""
from __future__ import annotations

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, MultiPoint, box

from .geom import clean_geometry, max_edge_span, snap_to_antimeridian

MIXED_TYPES = ("MultiPoint", "MultiLineString", "MultiPolygon")
MIXED_TYPE_IDS = {4, 5, 6}


def _lines(geom) -> list[LineString]:
  """the linear parts of any geometry (drops points, polygons and empties)."""
  if geom is None or geom.is_empty:
    return []
  if geom.geom_type == "LineString":
    return [geom]
  if geom.geom_type in ("MultiLineString", "GeometryCollection"):
    return [p for g in geom.geoms for p in _lines(g)]
  return []


def _points(geom) -> list:
  if geom is None or geom.is_empty:
    return []
  if geom.geom_type == "Point":
    return [geom]
  if geom.geom_type in ("MultiPoint", "GeometryCollection"):
    return [p for g in geom.geoms for p in _points(g)]
  return []


def unwrap_line(line: LineString) -> LineString:
  """continuous-longitude copy of a line: a step of more than 180 degrees is a dateline jump."""
  xy = np.array(line.coords, dtype=float)[:, :2]
  dx = np.diff(xy[:, 0])
  xy[1:, 0] += np.cumsum(np.where(dx > 180, -360.0, np.where(dx < -180, 360.0, 0.0)))
  return LineString(xy)


def split_line_antimeridian(geom) -> MultiLineString:
  """line(s) that jump across or run past +/-180 -> MultiLineString with every longitude in [-180, 180].

  lines that stay inside [-180, 180] without jumping come back unchanged; the halves of a split line meet the
  meridian at exactly +/-180.
  """
  parts: list[LineString] = []
  for line in _lines(geom):
    u = unwrap_line(line)
    minx, _, maxx, _ = u.bounds
    if minx >= -180 and maxx <= 180:
      parts.append(u)
      continue
    for k in (-1, 0, 1):
      piece = shapely.intersection(u, box(-180 + 360 * k, -90, 180 + 360 * k, 90))
      for p in _lines(piece):
        parts.append(affinity.translate(p, xoff=-360.0 * k) if k else p)
  return MultiLineString(parts) if parts else MultiLineString()


def clean_mixed_geometry(geom):
  """any geometry -> a valid MultiPoint / MultiLineString / MultiPolygon in [-180, 180], or None when empty.

  a mixed collection holds one kind per feature; when a geometry has several, polygons win over lines over points.
  """
  if geom is None or geom.is_empty:
    return None
  geom = shapely.force_2d(geom)
  if geom.geom_type in ("Polygon", "MultiPolygon") or (
      geom.geom_type == "GeometryCollection" and any(g.geom_type in ("Polygon", "MultiPolygon") for g in geom.geoms)):
    return clean_geometry(geom)
  if _lines(geom):
    out = snap_to_antimeridian(split_line_antimeridian(geom))
    return out if not out.is_empty else None
  pts = _points(geom)
  if pts:
    out = MultiPoint(pts)
    return out
  return None


def max_span_any(geom) -> float:
  """largest longitude step along any polygon ring edge or line segment (> 180 means it still jumps the dateline)."""
  span = max_edge_span(geom)
  for line in _lines(geom):
    xs = np.asarray(line.coords)[:, 0]
    if len(xs) > 1:
      span = max(span, float(np.abs(np.diff(xs)).max()))
  return span


def morton_order(geoms) -> list[int]:
  """row order that keeps neighbours together: the index of each geometry sorted by the Z-order (Morton) code of its
  bounding-box centre on a 16-bit lon/lat grid, features wider than 60 degrees of longitude or 30 of latitude last. a spatially clustered GeoParquet lets a reader skip row groups
  (rashid PTL-DAT-006); ties keep the input order."""
  b = shapely.bounds(np.array(list(geoms), dtype=object))
  lon = np.clip(((b[:, 0] + b[:, 2]) / 2 + 180) / 360, 0, 1)
  lat = np.clip(((b[:, 1] + b[:, 3]) / 2 + 90) / 180, 0, 1)
  x, y = (lon * 65535).astype(np.uint32), (lat * 65535).astype(np.uint32)

  def spread(v):
    v = (v | (v << 8)) & 0x00FF00FF
    v = (v | (v << 4)) & 0x0F0F0F0F
    v = (v | (v << 2)) & 0x33333333
    return (v | (v << 1)) & 0x55555555

  code = spread(x).astype(np.uint64) | (spread(y).astype(np.uint64) << np.uint64(1))
  # features that span a large part of the globe (ridge lines, dateline-split planning areas) would stretch the bbox
  # of any row group they sit in: they go last, together
  wide = ((b[:, 2] - b[:, 0]) > 60) | ((b[:, 3] - b[:, 1]) > 30)
  return [int(i) for i in np.lexsort((np.arange(len(code)), code, wide))]
