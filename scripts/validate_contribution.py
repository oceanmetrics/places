#!/usr/bin/env python3
"""validate community contributions to the gazetteer (plan section 10, phase 0: the documented PR path).

a contribution is a directory `contrib/OM-<ulid>/` holding `place.geojson` and `meta.json`; its place id is
`OM:<ulid>` (a ':' is not file-system safe, so the directory spells it `OM-<ulid>`). every rule is a function that
returns problems, so the tests can pin each one:

  geojson     parses; one Feature (or a FeatureCollection of exactly one); file <= 5 MB; <= 100,000 vertices
  geometry    Polygon / MultiPolygon / Point / MultiPoint / LineString / MultiLineString; non-empty, finite
  crs         EPSG:4326 only (a `crs` member naming anything else, or coordinates that are not degrees, is rejected)
  repair      ring winding is corrected automatically; a self-intersecting ring is repaired with make_valid; what
              cannot be repaired is an error. polygons are split at +/-180 like the build pipeline does
  meta.json   name, place_type (gazetteer.config.PLACE_TYPES), license (CC0-1.0 | CC-BY-4.0 | ODbL-1.0, required),
              attribution (required); contributor_orcid, source_url, description optional
  names       a name already used by a staged / published / contributed place of the same place_type is a WARNING

  python scripts/validate_contribution.py contrib/OM-<ulid> [more dirs ...] [--catalog DIR] [--contrib DIR]

exit 0 = every directory clean (warnings are printed), exit 1 = a readable error list. deps: shapely, pyarrow.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
  sys.path.insert(0, str(ROOT))

import pyarrow.parquet as pq  # noqa: E402
import shapely  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from gazetteer.config import PLACE_TYPES  # noqa: E402
from gazetteer.geom import clean_geometry, max_edge_span  # noqa: E402

# limits ----
MAX_BYTES    = 5 * 1024 * 1024
MAX_VERTICES = 100_000
LICENSES     = ("CC0-1.0", "CC-BY-4.0", "ODbL-1.0")
GEOM_TYPES   = {"Polygon", "MultiPolygon", "Point", "MultiPoint", "LineString", "MultiLineString"}
# GeoJSON `crs` names that mean lon/lat degrees on WGS 84 (RFC 7946 drops the member; old files still carry it)
CRS_4326     = {"urn:ogc:def:crs:ogc:1.3:crs84", "urn:ogc:def:crs:epsg::4326", "urn:ogc:def:crs:epsg:6.6:4326",
                "epsg:4326", "crs84", "ogc:crs84"}

# ids ----
# ULID: 26 characters of Crockford base32 (no I L O U); the first is 0-7 so the 48-bit timestamp does not overflow
ULID_RE      = r"[0-7][0-9A-HJKMNP-TV-Z]{25}"
ID_RE        = re.compile(rf"OM:{ULID_RE}")
DIR_RE       = re.compile(rf"OM-{ULID_RE}")
ORCID_RE     = re.compile(r"\d{4}-\d{4}-\d{4}-\d{3}[\dX]")
META_KEYS    = {"name", "place_type", "license", "attribution", "contributor_orcid", "source_url", "description",
                "example"}


def id_to_dir(place_id: str) -> str:
  """`OM:<ulid>` -> `OM-<ulid>` (the directory name)."""
  if not ID_RE.fullmatch(place_id):
    raise ValueError(f"not an OM:<ulid> id: {place_id!r}")
  return place_id.replace(":", "-", 1)


def dir_to_id(dirname: str) -> str:
  """`OM-<ulid>` -> `OM:<ulid>` (the place_id)."""
  if not DIR_RE.fullmatch(dirname):
    raise ValueError(f"not an OM-<ulid> directory name: {dirname!r}")
  return dirname.replace("-", ":", 1)


@dataclass
class Result:
  """errors reject the contribution; warnings are printed but do not fail the check."""
  path: Path
  errors: list[str] = field(default_factory=list)
  warnings: list[str] = field(default_factory=list)
  geometry: object = None            # the normalised geometry (valid, CCW shells, split at +/-180) when it parsed
  meta: dict = field(default_factory=dict)

  @property
  def ok(self) -> bool:
    return not self.errors


# directory name ----
def check_dirname(path: Path) -> list[str]:
  if not DIR_RE.fullmatch(path.name):
    return [f"directory name {path.name!r} is not OM-<ulid> (26-character ULID, Crockford base32, first character 0-7)"]
  return []


# meta.json ----
def check_meta(meta) -> list[str]:
  """every problem with a parsed meta.json (empty list = good)."""
  if not isinstance(meta, dict):
    return ["meta.json must be a JSON object"]
  errs: list[str] = []

  def text(key):
    v = meta.get(key)
    return v.strip() if isinstance(v, str) else ""

  if not text("name"):
    errs.append("meta.json: name is required (a non-empty string)")
  pt = meta.get("place_type")
  if pt is None or pt == "":
    errs.append(f"meta.json: place_type is required, one of {sorted(PLACE_TYPES)}")
  elif pt not in PLACE_TYPES:
    errs.append(f"meta.json: place_type {pt!r} is not one of {sorted(PLACE_TYPES)}")
  lic = meta.get("license")
  if lic is None or lic == "":
    errs.append(f"meta.json: license is required (SPDX id, one of {', '.join(LICENSES)}); a contribution without a "
                "licence cannot be redistributed")
  elif lic not in LICENSES:
    errs.append(f"meta.json: license {lic!r} is not accepted; use one of {', '.join(LICENSES)}")
  if not text("attribution"):
    errs.append("meta.json: attribution is required (the credit line shown with the place)")
  orcid = meta.get("contributor_orcid")
  if orcid not in (None, "") and not (isinstance(orcid, str) and ORCID_RE.fullmatch(orcid)):
    errs.append(f"meta.json: contributor_orcid {orcid!r} is not of the form 0000-0000-0000-000X")
  url = meta.get("source_url")
  if url not in (None, "") and not (isinstance(url, str) and re.fullmatch(r"https?://\S+", url)):
    errs.append(f"meta.json: source_url {url!r} must be an http(s) URL")
  desc = meta.get("description")
  if desc is not None and not isinstance(desc, str):
    errs.append("meta.json: description must be a string")
  ex = meta.get("example")
  if ex is not None and not isinstance(ex, bool):
    errs.append("meta.json: example must be true or false")
  for k in ("name", "attribution"):
    if k in meta and not isinstance(meta[k], str):
      errs.append(f"meta.json: {k} must be a string")
  return errs


# geojson ----
def _crs_errors(doc: dict) -> list[str]:
  crs = doc.get("crs")
  if crs is None:
    return []
  name = ""
  if isinstance(crs, dict):
    props = crs.get("properties")
    name = str(props.get("name", "")) if isinstance(props, dict) else ""
  if name.lower() in CRS_4326:
    return []
  return [f"geojson: crs {name or crs!r} is not EPSG:4326; reproject to WGS 84 longitude/latitude (GeoJSON RFC 7946)"]


def _feature(doc) -> tuple[dict | None, list[str]]:
  """the single Feature of a document, or errors."""
  if not isinstance(doc, dict):
    return None, ["geojson: the top level must be an object"]
  t = doc.get("type")
  if t == "Feature":
    return doc, []
  if t == "FeatureCollection":
    feats = doc.get("features")
    if not isinstance(feats, list) or len(feats) != 1:
      n = len(feats) if isinstance(feats, list) else 0
      return None, [f"geojson: a FeatureCollection must hold exactly one Feature (found {n}); one place per contribution"]
    if not isinstance(feats[0], dict) or feats[0].get("type") != "Feature":
      return None, ["geojson: the FeatureCollection member is not a Feature"]
    return feats[0], []
  return None, [f"geojson: top-level type {t!r} must be Feature or FeatureCollection (of one Feature)"]


def _coords_flat(c):
  """every position of a nested coordinate array."""
  if isinstance(c, (list, tuple)) and c and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in c):
    yield c
  elif isinstance(c, (list, tuple)):
    for v in c:
      yield from _coords_flat(v)


def check_geometry(geom_dict) -> tuple[object, list[str], list[str]]:
  """-> (normalised shapely geometry or None, errors, warnings) for a GeoJSON geometry object."""
  errs: list[str] = []
  warns: list[str] = []
  if not isinstance(geom_dict, dict) or geom_dict.get("type") is None:
    return None, ["geojson: the Feature has no geometry"], warns
  gt = geom_dict.get("type")
  if gt not in GEOM_TYPES:
    return None, [f"geojson: geometry type {gt!r} is not accepted; use one of {sorted(GEOM_TYPES)}"], warns

  # crs / coordinate range, checked on raw positions before shapely sees them
  pos = list(_coords_flat(geom_dict.get("coordinates")))
  if not pos:
    return None, ["geojson: the geometry has no coordinates"], warns
  if any(len(p) < 2 for p in pos):
    return None, ["geojson: a position has fewer than two numbers"], warns
  if any(not (math.isfinite(p[0]) and math.isfinite(p[1])) for p in pos):
    return None, ["geojson: coordinates contain NaN or infinity"], warns
  if len(pos) > MAX_VERTICES:
    return None, [f"geojson: {len(pos):,} vertices exceeds the cap of {MAX_VERTICES:,}; simplify the geometry"], warns
  lons, lats = [p[0] for p in pos], [p[1] for p in pos]
  if min(lats) < -90 or max(lats) > 90 or min(lons) < -360 or max(lons) > 360:
    return None, ["geojson: coordinates are not EPSG:4326 degrees (latitude outside +/-90 or longitude outside "
                  "+/-360); reproject to WGS 84 longitude/latitude"], warns

  try:
    g = shape(geom_dict)
  except Exception as e:  # shapely raises ValueError/TypeError/GEOSException for malformed rings
    return None, [f"geojson: the geometry cannot be built ({e})"], warns
  if g.is_empty:
    return None, ["geojson: the geometry is empty"], warns
  g = shapely.force_2d(g)

  if g.geom_type in ("Polygon", "MultiPolygon"):
    oriented = shapely.orient_polygons(g, exterior_cw=False)
    if not shapely.equals_exact(oriented, g, 0):
      warns.append("geojson: ring winding corrected (exterior rings counter-clockwise, holes clockwise, RFC 7946)")
    if not oriented.is_valid:
      reason = shapely.is_valid_reason(oriented)
      fixed = shapely.make_valid(oriented)
      if fixed.is_empty or fixed.area <= 0:
        return None, [f"geojson: invalid polygon that cannot be repaired ({reason})"], warns
      warns.append(f"geojson: invalid polygon repaired with make_valid ({reason})")
    try:
      out = clean_geometry(oriented)
    except NotImplementedError as e:
      return None, [f"geojson: {e}"], warns
    if out is None:
      return None, ["geojson: no polygon is left after repair; the geometry is unfixable"], warns
    # the antimeridian: report a split (clean_geometry already did it)
    raw_lo, raw_hi = shapely.bounds(oriented)[[0, 2]]
    if raw_lo < -180 or raw_hi > 180 or max_edge_span(oriented) > 180:
      warns.append(f"geojson: split at +/-180 into {len(out.geoms)} part(s), like the build pipeline")
    return out, errs, warns

  # points and lines are not split; longitudes must already sit inside [-180, 180]
  if min(lons) < -180 or max(lons) > 180:
    return None, ["geojson: longitudes outside [-180, 180]; wrap them (only polygons are split at the antimeridian)"], warns
  if g.geom_type in ("LineString", "MultiLineString"):
    if not g.is_valid:
      return None, [f"geojson: invalid line ({shapely.is_valid_reason(g)})"], warns
    parts = [g] if g.geom_type == "LineString" else list(g.geoms)
    if any(abs(b[0] - a[0]) > 180 for ln in parts for a, b in zip(ln.coords, list(ln.coords)[1:])):
      warns.append("geojson: a line segment spans more than 180 degrees of longitude; if it crosses the "
                   "antimeridian, split it into a MultiLineString at +/-180")
  return g, errs, warns


def check_geojson_file(path: Path) -> tuple[object, list[str], list[str]]:
  """-> (geometry, errors, warnings) for place.geojson."""
  if not path.is_file():
    return None, ["place.geojson is missing"], []
  size = path.stat().st_size
  if size > MAX_BYTES:
    return None, [f"place.geojson is {size / 1048576:.1f} MB; the cap is {MAX_BYTES // 1048576} MB; simplify it"], []
  try:
    doc = json.loads(path.read_text(encoding="utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as e:
    return None, [f"place.geojson does not parse as JSON ({e})"], []
  feat, errs = _feature(doc)
  if errs:
    return None, errs, []
  errs = _crs_errors(doc) + _crs_errors(feat)
  if errs:
    return None, errs, []
  return check_geometry(feat.get("geometry"))


# names ----
def _norm(name: str) -> str:
  return " ".join(str(name).casefold().split())


def existing_names(catalog: Path | None, contrib: Path | None = None, skip: Path | None = None) -> dict[str, set[str]]:
  """{place_type: {normalised names}} of staged / published collections (catalog/**/places.parquet) and of the
  other contributions under `contrib`. only the name and place_type columns are read."""
  out: dict[str, set[str]] = {}
  if catalog and catalog.is_dir():
    seen = set()
    for p in sorted([*catalog.glob("*/places.parquet"), *catalog.glob("staging/*/places.parquet")]):
      if p.resolve() in seen:
        continue
      seen.add(p.resolve())
      try:
        t = pq.read_table(p, columns=["name", "place_type"])
      except Exception:  # a parquet without the columns (or unreadable) cannot collide
        continue
      for n, pt in zip(t.column("name").to_pylist(), t.column("place_type").to_pylist()):
        if n and pt:
          out.setdefault(pt, set()).add(_norm(n))
  if contrib and contrib.is_dir():
    for d in sorted(contrib.glob("OM-*")):
      if skip is not None and d.resolve() == skip.resolve():
        continue
      try:
        m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        if m.get("name") and m.get("place_type"):
          out.setdefault(m["place_type"], set()).add(_norm(m["name"]))
      except Exception:
        continue
  return out


def check_name_collision(meta: dict, names: dict[str, set[str]]) -> list[str]:
  n, pt = meta.get("name"), meta.get("place_type")
  if isinstance(n, str) and pt in names and _norm(n) in names[pt]:
    return [f"name {n!r} is already used by another {pt} place (staged, published or contributed); "
            "check this is not a duplicate"]
  return []


# one contribution ----
def validate_contribution(path, catalog: Path | None = None, contrib: Path | None = None) -> Result:
  """validate one `contrib/OM-<ulid>/` directory."""
  path = Path(path)
  r = Result(path=path)
  if not path.is_dir():
    r.errors.append(f"{path} is not a directory")
    return r
  r.errors += check_dirname(path)
  extra = sorted(p.name for p in path.iterdir() if p.name not in ("place.geojson", "meta.json"))
  if extra:
    r.warnings.append(f"unexpected file(s) ignored by the build: {', '.join(extra)}")

  geom, errs, warns = check_geojson_file(path / "place.geojson")
  r.geometry, r.errors, r.warnings = geom, r.errors + errs, r.warnings + warns

  mp = path / "meta.json"
  if not mp.is_file():
    r.errors.append("meta.json is missing")
    return r
  try:
    meta = json.loads(mp.read_text(encoding="utf-8"))
  except (UnicodeDecodeError, json.JSONDecodeError) as e:
    r.errors.append(f"meta.json does not parse as JSON ({e})")
    return r
  r.errors += check_meta(meta)
  if isinstance(meta, dict):
    r.meta = meta
    unknown = sorted(set(meta) - META_KEYS)
    if unknown:
      r.warnings.append(f"meta.json: unknown key(s) ignored: {', '.join(unknown)}")
    r.warnings += check_name_collision(meta, existing_names(catalog, contrib, skip=path))
  return r


# cli ----
def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
  ap.add_argument("dirs", nargs="+", type=Path, help="contribution directories (contrib/OM-<ulid>)")
  ap.add_argument("--catalog", type=Path, default=ROOT / "catalog", help="staged / published collections to check names against")
  ap.add_argument("--contrib", type=Path, default=ROOT / "contrib", help="other contributions to check names against")
  a = ap.parse_args(argv)
  bad = 0
  for d in a.dirs:
    r = validate_contribution(d, catalog=a.catalog, contrib=a.contrib)
    for w in r.warnings:
      print(f"warning: {d}: {w}")
    if r.ok:
      print(f"ok: {d} ({dir_to_id(d.name) if DIR_RE.fullmatch(d.name) else d.name})")
    else:
      bad += 1
      print(f"FAILED: {d}")
      for e in r.errors:
        print(f"  - {e}")
  if bad:
    print(f"\n{bad} of {len(a.dirs)} contribution(s) rejected", file=sys.stderr)
  return 1 if bad else 0


if __name__ == "__main__":
  sys.exit(main())
