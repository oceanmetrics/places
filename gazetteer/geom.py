"""geometry rules: valid multipolygons in EPSG:4326 split at the +/-180 antimeridian."""
from __future__ import annotations

import numpy as np
import shapely
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box

WORLD = box(-180, -90, 180, 90)


def _unwrap_ring(coords: np.ndarray) -> np.ndarray:
  """make a ring's longitudes continuous: a step of more than 180 degrees is a dateline jump.

  returns an (n, 2) array whose longitudes may leave [-180, 180]. a ring that does not close after
  unwrapping encircles a pole, which this builder does not support (no source layer has one).
  """
  xy = np.array(coords, dtype=float)[:, :2]
  dx = np.diff(xy[:, 0])
  steps = np.where(dx > 180, -360.0, np.where(dx < -180, 360.0, 0.0))
  xy[1:, 0] += np.cumsum(steps)
  if abs(xy[-1, 0] - xy[0, 0]) > 1e-9:
    raise NotImplementedError("ring encircles a pole; antimeridian split is not supported for it")
  return xy


def unwrap_polygon(poly: Polygon) -> Polygon:
  """continuous-longitude copy of a polygon (shell and holes unwrapped; holes aligned to the shell)."""
  shell = _unwrap_ring(poly.exterior.coords)
  mid = (shell[:, 0].min() + shell[:, 0].max()) / 2
  holes = []
  for ring in poly.interiors:
    h = _unwrap_ring(ring.coords)
    hmid = (h[:, 0].min() + h[:, 0].max()) / 2
    h[:, 0] += 360.0 * round((mid - hmid) / 360.0)
    holes.append(h)
  return Polygon(shell, holes)


def _polygons(geom) -> list[Polygon]:
  """the polygonal parts of any geometry (drops points, lines and empties)."""
  if geom is None or geom.is_empty:
    return []
  if geom.geom_type == "Polygon":
    return [geom]
  if geom.geom_type == "MultiPolygon":
    return list(geom.geoms)
  if geom.geom_type == "GeometryCollection":
    return [p for g in geom.geoms for p in _polygons(g)]
  return []


def split_antimeridian(geom):
  """polygon(s) whose edges may cross or leave +/-180 -> MultiPolygon with every longitude in [-180, 180].

  rings that jump across the dateline (179 -> -179) and rings already unwrapped past 180 are both
  accepted; geometry that stays inside [-180, 180] without jumps comes back unchanged. the split
  halves meet the meridian at exactly +/-180.
  """
  parts: list[Polygon] = []
  for poly in _polygons(geom):
    u = unwrap_polygon(poly)
    if not u.is_valid:
      u = shapely.make_valid(u)
    minx, _, maxx, _ = u.bounds
    if minx >= -180 and maxx <= 180:
      parts += _polygons(u)
      continue
    for k in (-1, 0, 1):
      piece = shapely.intersection(u, box(-180 + 360 * k, -90, 180 + 360 * k, 90))
      for p in _polygons(piece):
        parts.append(affinity.translate(p, xoff=-360.0 * k) if k else p)
  return MultiPolygon(parts) if parts else MultiPolygon()


def snap_to_antimeridian(geom, tol: float = 1e-4):
  """vertices within `tol` degrees of +/-180 move onto the meridian. some servers cut at the dateline in Web Mercator
  and land about 1e-5 degrees short of +/-180 (BOEM's Alaska planning areas do), which leaves a visible gap in tiles."""
  def snap(c):
    x = c[:, 0]
    c = c.copy()
    c[np.abs(x - 180.0) <= tol, 0] = 180.0
    c[np.abs(x + 180.0) <= tol, 0] = -180.0
    return c
  return shapely.transform(geom, snap)


def clean_geometry(geom):
  """-> valid, counter-clockwise-shelled MultiPolygon in [-180, 180]; None when nothing polygonal is left."""
  if geom is None or geom.is_empty:
    return None
  geom = shapely.force_2d(geom)
  if not geom.is_valid:
    geom = shapely.make_valid(geom)
  out = snap_to_antimeridian(split_antimeridian(geom))
  if not out.is_valid:
    out = shapely.make_valid(out)
  polys = _polygons(out)
  if not polys:
    return None
  out = MultiPolygon(polys)
  return shapely.orient_polygons(out, exterior_cw=False)


def max_edge_span(geom) -> float:
  """largest longitude step along any ring edge (> 180 means a ring still jumps the dateline)."""
  span = 0.0
  for poly in _polygons(geom):
    for ring in [poly.exterior, *poly.interiors]:
      xs = np.asarray(ring.coords)[:, 0]
      if len(xs) > 1:
        span = max(span, float(np.abs(np.diff(xs)).max()))
  return span


def esri_json_to_geojson(geometry: dict | None):
  """Esri JSON polygon ({"rings": [...]}) -> GeoJSON-like dict (Polygon or MultiPolygon).

  Esri rings: clockwise = outer ring, counter-clockwise = hole. each hole goes to the outer ring that
  contains it. returns None for a missing or ring-less geometry.
  """
  if not geometry or not geometry.get("rings"):
    return None
  outers, holes = [], []
  for ring in geometry["rings"]:
    if len(ring) < 4:
      continue
    poly = Polygon(ring)
    (holes if poly.exterior.is_ccw else outers).append(ring)
  polys = []
  for ring in outers:
    shell = Polygon(ring)
    inner = [h for h in holes if shell.contains(Polygon(h).representative_point())]
    polys.append(Polygon(ring, inner))
  if not polys:
    return None
  geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
  return shapely.geometry.mapping(geom)
