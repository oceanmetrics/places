"""line geometry rules: valid MultiLineStrings in EPSG:4326 split at the +/-180 antimeridian (maritime limits, state
lateral boundaries). the polygon twin is geom.clean_geometry."""
from __future__ import annotations

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import LineString, MultiLineString, box


def _lines(geom) -> list[LineString]:
  """the linear parts of any geometry (drops points, polygons and empties)."""
  if geom is None or geom.is_empty:
    return []
  if geom.geom_type == "LineString":
    return [geom]
  if geom.geom_type in ("MultiLineString", "GeometryCollection"):
    return [p for g in geom.geoms for p in _lines(g)]
  return []


def unwrap_line(line: LineString) -> LineString:
  """continuous-longitude copy of a line: a step of more than 180 degrees is a dateline jump (may leave [-180, 180])."""
  xy = np.array(line.coords, dtype=float)[:, :2]
  dx = np.diff(xy[:, 0])
  xy[1:, 0] += np.cumsum(np.where(dx > 180, -360.0, np.where(dx < -180, 360.0, 0.0)))
  return LineString(xy)


def split_line_antimeridian(geom) -> MultiLineString:
  """line(s) that jump across or run past +/-180 -> MultiLineString with every longitude in [-180, 180]; the halves
  meet the meridian at exactly +/-180. lines that stay inside [-180, 180] without jumps come back unchanged."""
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


def clean_multiline_geometry(geom):
  """-> valid 2-D MultiLineString in [-180, 180]; None when nothing linear is left."""
  if geom is None or geom.is_empty:
    return None
  geom = shapely.force_2d(geom)
  from .geom import snap_to_antimeridian
  out = snap_to_antimeridian(split_line_antimeridian(geom))
  parts = [p for p in _lines(out) if p.length > 0]
  return MultiLineString(parts) if parts else None


def max_line_span(geom) -> float:
  """largest longitude step along any line segment (> 180 means a line still jumps the dateline)."""
  span = 0.0
  for line in _lines(geom):
    xs = np.asarray(line.coords)[:, 0]
    if len(xs) > 1:
      span = max(span, float(np.abs(np.diff(xs)).max()))
  return span
