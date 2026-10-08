"""checks on a built collection (used by the tests, by `build_gazetteer.py check` and by the sync workflow)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import shapely

from .mixed import MIXED_TYPE_IDS, max_span_any
from .table import COMMON
from .tiles import read_pmtiles


def check_parquet(path: Path, cfg: dict) -> list[str]:
  """every problem found in a staged places.parquet (empty list = good)."""
  problems: list[str] = []
  f = pq.ParquetFile(path)
  t = f.read()
  names = t.column_names
  for c in COMMON + ["bbox", "geometry"]:
    if c not in names:
      problems.append(f"missing column {c}")
  if problems:
    return problems
  if len({n.lower() for n in names}) != len(names):
    problems.append("column names collide ignoring case")
  ids = t.column("place_id").to_pylist()
  if len(set(ids)) != len(ids):
    problems.append("place_id not unique")
  pats = [(s.get("place_id") or cfg.get("place_id"))["pattern"] for s in cfg["sources"]]
  bad = [i for i in ids if not any(re.fullmatch(p, i or "") for p in pats)]
  if bad:
    problems.append(f"{len(bad)} place_id(s) match no pattern, e.g. {bad[:3]}")
  for c in ("license", "attribution", "status", "status_source", "name", "source_url", "authority", "place_type"):
    empties = sum(1 for v in t.column(c).to_pylist() if not (v or "").strip())
    if empties:
      problems.append(f"{empties} row(s) with empty {c}")
  if set(t.column("license").to_pylist()) != {cfg["license"]}:
    problems.append("license differs from the config")
  geoms = shapely.from_wkb(t.column("geometry").to_pylist())
  if not shapely.is_valid(geoms).all():
    problems.append(f"{int((~shapely.is_valid(geoms)).sum())} invalid geometries")
  gtype = cfg.get("geometry_type", "MultiPolygon")
  if cfg.get("mixed_geometry"):
    if set(shapely.get_type_id(geoms)) - MIXED_TYPE_IDS:
      problems.append("geometries are not all Multi* (MultiPoint / MultiLineString / MultiPolygon)")
  elif set(shapely.get_type_id(geoms)) != {{"Point": 0, "LineString": 1, "MultiPolygon": 6}[gtype]}:
    problems.append(f"geometries are not all {gtype}")
  if [g.geom_type for g in geoms] != t.column("geom_type").to_pylist():
    problems.append("geom_type column does not match the geometry types")
  b = shapely.bounds(geoms)
  if b[:, 0].min() < -180 or b[:, 2].max() > 180 or b[:, 1].min() < -90 or b[:, 3].max() > 90:
    problems.append("coordinates outside [-180, 180] x [-90, 90]")
  spans = [max_span_any(g) for g in geoms]
  if max(spans) > 180:
    problems.append(f"a ring jumps the antimeridian (edge span {max(spans):.1f} degrees)")
  bb = t.column("bbox").combine_chunks()
  cov = np.column_stack([np.array(bb.field(k).to_pylist()) for k in ("xmin", "ymin", "xmax", "ymax")])
  if not np.allclose(cov, b):
    problems.append("bbox column does not match the geometry bounds")
  geo = json.loads(f.schema_arrow.metadata[b"geo"])
  col = geo["columns"]["geometry"]
  if geo["version"] != "1.1.0" or col["encoding"] != "WKB" or "covering" not in col:
    problems.append("geo metadata is not GeoParquet 1.1 WKB with a bbox covering")
  if b"gazetteer:provenance" not in f.schema_arrow.metadata:
    problems.append("no provenance in the parquet metadata")
  return problems


def check_pmtiles(path: Path, slug: str) -> list[str]:
  """problems in a staged places.pmtiles: it must carry attribution, a name, a description and layer `slug`."""
  problems: list[str] = []
  header, meta = read_pmtiles(path)
  if not (meta.get("attribution") or "").strip():
    problems.append("PMTiles metadata has no attribution")
  for k in ("name", "description"):
    if not (meta.get(k) or "").strip():
      problems.append(f"PMTiles metadata has no {k}")
  layers = [lyr.get("id") for lyr in meta.get("vector_layers", [])]
  if layers != [slug]:
    problems.append(f"PMTiles vector layers are {layers}, expected [{slug!r}]")
  if header["tile_type"] != 1:
    problems.append("PMTiles tile type is not MVT")
  return problems
