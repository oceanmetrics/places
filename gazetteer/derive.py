"""kind `derive`: a collection computed from other collections of the gazetteer (their built places.parquet).

source config (one source per derived collection):

    - kind: derive
      url: <page that documents the derivation or the first input>      # the provenance `source_url`
      op: intersect                                                     # the only operation so far
      inputs:                                                           # exactly two, in this order
        - {slug: mr_high_seas,     id_column: high_seas_id}             # `id_column`: the piece's column holding
        - {slug: fao_major_areas,  id_column: fao_id, carry: [F_CODE, NAME_EN, OCEAN]}   # that input's place_id
      min_area_km2: 100                                                 # pieces below this (geodesic) area are dropped
      min_part_km2: 0                                                   # polygon fragments below this are dropped (0: keep)

`op: intersect` makes one piece per pair of input places whose intersection has polygonal area, e.g. the one global
high seas polygon x the 19 FAO major areas = one high-seas piece per FAO area. each piece keeps its parents' place_ids
in the `id_column`s (two plain columns, so a reader can join without parsing the piece's id), the `carry` columns of an
input verbatim, and `area_km2` (geodesic, WGS84 ellipsoid). pieces under `min_area_km2` are slivers where two
boundaries almost agree: they are dropped and reported in the build's `dropped` notes.

inputs are read from the first directory that holds `<slug>/places.parquet`: `PLACES_INTERNAL` (default
~/data/oceanmetrics/places-internal: the private copies of reference collections such as Marine Regions), then
`PLACES_STAGING` (default catalog/staging next to this package). the inputs' geometry is stored split at +/-180, so a
planar intersection is right on both sides of the antimeridian. the derived geometry is as restricted as its most
restricted input: a derived collection from a reference collection is itself a reference collection (config
`display`, see stac.py), never published as files.
"""
from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq
import shapely
from pyproj import Geod
from shapely.geometry import MultiPolygon

from .fetch import SourceResult, now_iso
from .geom import _polygons

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parent.parent
OPS = {"intersect"}
GEOD = Geod(ellps="WGS84")


def input_dirs() -> list[Path]:
  """where to look for an input's `<slug>/places.parquet`, in order: PLACES_INTERNAL, then PLACES_STAGING."""
  internal = Path(os.environ.get("PLACES_INTERNAL") or "~/data/oceanmetrics/places-internal").expanduser()
  staging = Path(os.environ.get("PLACES_STAGING") or REPO / "catalog" / "staging").expanduser()
  return [internal, staging]


def find_input(slug: str, dirs: list[Path]) -> Path:
  for d in dirs:
    p = Path(d) / slug / "places.parquet"
    if p.exists():
      return p
  raise FileNotFoundError(f"derive input {slug}: no places.parquet in {[str(Path(d) / slug) for d in dirs]} "
                          "(set PLACES_INTERNAL / PLACES_STAGING)")


def geodesic_area_km2(geom) -> float:
  """geodesic area (km2) of a polygonal geometry on the WGS84 ellipsoid."""
  return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


def read_input(path: Path, carry: list[str]) -> list[dict]:
  """[{place_id, geom, props}] of a built places.parquet; `props` holds the `carry` columns (an absent one is an error)."""
  t = pq.read_table(path)
  missing = [c for c in carry if c not in t.column_names]
  if missing:
    raise ValueError(f"{path}: no column(s) {missing} to carry")
  geoms = shapely.from_wkb(t.column("geometry").to_pylist())
  cols = {c: t.column(c).to_pylist() for c in carry}
  return [{"place_id": pid, "geom": g, "props": {c: cols[c][i] for c in carry}}
          for i, (pid, g) in enumerate(zip(t.column("place_id").to_pylist(), geoms))]


def file_sha256(path: Path) -> str:
  h = hashlib.sha256()
  with open(path, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
      h.update(chunk)
  return h.hexdigest()


def field_type(arrow_type) -> str:
  """an Arrow type -> the builder's field type (int | float | string)."""
  s = str(arrow_type)
  return "int" if s.startswith(("int", "uint")) else "float" if s.startswith(("float", "double")) else "string"


def inputs_checksum(ins: list[dict], paths: list[Path]) -> str:
  """one sha-256 over the inputs' file hashes (the derived source's change token)."""
  return hashlib.sha256("".join(f"{i['slug']}:{file_sha256(p)}" for i, p in zip(ins, paths)).encode()).hexdigest()


def probe_derive(src: dict, published: dict | None, dirs: list[Path] | None = None) -> dict:
  """change token for `detect`: the inputs' checksum when both are on this machine, else the published one (unchanged).
  a rebuilt input changes the token, so the derived collection follows on the next run."""
  ins = src.get("inputs") or []
  try:
    paths = [find_input(i["slug"], dirs if dirs is not None else input_dirs()) for i in ins]
  except FileNotFoundError:
    return {"checksum": ((published or {}).get("sources") or [{}])[0].get("checksum")}
  return {"checksum": inputs_checksum(ins, paths)}


def intersect_pieces(a: list[dict], b: list[dict], a_col: str, b_col: str, min_area_km2: float = 100.0,
                     min_part_km2: float = 0.0) -> tuple[list[dict], list[str]]:
  """(pieces, dropped notes): one piece per (a, b) pair whose intersection has polygonal area, in (a, b) order.

  a piece is {a_col: a place_id, b_col: b place_id, **b's carry props (a's first), 'area_km2', 'geom'} with the polygonal
  part of the intersection only (shared boundaries make lines and points, which are discarded). polygon fragments under
  `min_part_km2` are dropped first (their area is reported), then pieces under `min_area_km2`."""
  dropped: list[str] = []
  b_geoms = np.array([x["geom"] for x in b], dtype=object)
  tree = shapely.STRtree(b_geoms)
  pieces = []
  for x in a:
    for j in sorted(tree.query(x["geom"], predicate="intersects")):
      y = b[j]
      polys = _polygons(shapely.intersection(x["geom"], y["geom"]))
      if min_part_km2 > 0:
        small = [p for p in polys if geodesic_area_km2(p) < min_part_km2]
        polys = [p for p in polys if geodesic_area_km2(p) >= min_part_km2]
        if small:
          dropped.append(f"{x['place_id']} x {y['place_id']}: dropped {len(small)} fragment(s) under {min_part_km2:g} km2 "
                         f"({sum(geodesic_area_km2(p) for p in small):.3f} km2 in all)")
      if not polys:
        continue
      geom = MultiPolygon(polys)
      area = geodesic_area_km2(geom)
      if area < min_area_km2:
        dropped.append(f"{x['place_id']} x {y['place_id']}: dropped sliver of {area:.3f} km2 (under {min_area_km2:g} km2)")
        continue
      pieces.append({a_col: x["place_id"], b_col: y["place_id"], **x["props"], **y["props"], "area_km2": area, "geom": geom})
  return pieces, dropped


def fetch_derive(src: dict, dirs: list[Path] | None = None) -> SourceResult:
  """build the derived features of one `kind: derive` source from its inputs' built parquet files."""
  op = src.get("op")
  if op not in OPS:
    raise ValueError(f"derive: op must be one of {sorted(OPS)}, got {op!r}")
  ins = src.get("inputs") or []
  if len(ins) != 2 or not all(i.get("slug") and i.get("id_column") for i in ins):
    raise ValueError("derive: inputs must be two {slug, id_column[, carry]} entries")
  dirs = dirs if dirs is not None else input_dirs()
  paths = [find_input(i["slug"], dirs) for i in ins]
  loaded = [read_input(p, i.get("carry") or []) for p, i in zip(paths, ins)]
  pieces, dropped = intersect_pieces(loaded[0], loaded[1], ins[0]["id_column"], ins[1]["id_column"],
                                     float(src.get("min_area_km2", 100)), float(src.get("min_part_km2", 0)))
  carried = [c for i in ins for c in (i.get("carry") or [])]
  types = {c: field_type(pq.read_schema(paths[k]).field(c).type) for k, i in enumerate(ins) for c in (i.get("carry") or [])}
  fields = ([{"name": i["id_column"], "type": "string"} for i in ins]
            + [{"name": c, "type": types[c]} for c in carried] + [{"name": "area_km2", "type": "float"}])
  feats = [{"properties": {k: v for k, v in p.items() if k != "geom"}, "geometry": p["geom"]} for p in pieces]
  sha = inputs_checksum(ins, paths)
  log.info("derive %s: %d piece(s), %d dropped", op, len(feats), len(dropped))
  return SourceResult(
    features=feats, fields=fields, source_url=src["url"], item_id=f"{op}({', '.join(i['slug'] for i in ins)})",
    component=src.get("component"), data_last_edit=None, retrieved=now_iso(), record_count=len(feats), checksum=sha,
    extra={"dropped": dropped,
           "derived_from": [{"slug": i["slug"], "parquet_sha256": file_sha256(p), "rows": len(rows)}
                            for i, p, rows in zip(ins, paths, loaded)],
           "derive": {"op": op, "min_area_km2": float(src.get("min_area_km2", 100)),
                      "min_part_km2": float(src.get("min_part_km2", 0))}})
