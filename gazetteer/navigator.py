"""ProtectedSeas Navigator: the Direct Data Export for API users -> shapely features (source kind `navigator_export`).

the export (from ProtectedSeas, Alex Driedger, 2026-10-16) comes as subsets split by Level of Fishing Protection
(LFP0..LFP5 inside national EEZs, plus the high seas), each as a CSV (every attribute, no geometry) and a zipped
shapefile (geometry and `ps_id` only); the full catalog is all subsets together, joined on `ps_id`. field names
match the Navigator API v2 (https://protectedseas.gitbook.io/navigator-api-docs/field-reference/site-keys).

  <export>/csv/*.csv          one row per site
  <export>/shp/<subset>/*.shp  boundaries, EPSG:4326, `PS_ID` only

sites whose boundaries are withheld for redistribution reasons are already absent from the export. a site is kept
when it is marine: `location_type` 0 (marine), 2 (island) or unknown, or any marine area (`percent_marine_area` > 0);
inland-only sites (lakes, rivers, land) are dropped and counted. the supplied areas (`total_area`, km2) come from the
full-resolution boundaries, so the index uses them rather than an area recomputed from the (simplified) geometry.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.csv as pacsv
import shapely

from .fetch import SourceResult, exclude_features, include_features, now_iso

MARINE_LOCATION_TYPES = {0, 2}


def export_dir(src: dict, cache_dir: Path) -> Path:
  """the export folder: `src.path` (absolute, or relative to the repo), else <cache_dir>/export."""
  p = Path(src["path"]) if src.get("path") else cache_dir / "export"
  return p if p.is_absolute() else Path(__file__).resolve().parent.parent / p


def read_attributes(csv_dir: Path) -> pa.Table:
  """every CSV subset as one table (columns unified across subsets; a column missing from a subset is null)."""
  files = sorted(csv_dir.glob("*.csv"))
  if not files:
    raise FileNotFoundError(f"no CSV subsets in {csv_dir}")
  opts = pacsv.ConvertOptions(strings_can_be_null=True, column_types={"ps_id": pa.string(), "wdpa_id": pa.string(),
                                                                       "primary_site_id": pa.string()})
  parse = pacsv.ParseOptions(newlines_in_values=True)   # purpose / restrictions / allowed text spans lines
  tabs = [pacsv.read_csv(f, parse_options=parse, convert_options=opts) for f in files]
  return pa.concat_tables(tabs, promote_options="permissive")


def read_boundaries(shp_dir: Path) -> dict[str, object]:
  """ps_id -> shapely geometry (2D) from every shapefile subset."""
  import pyogrio.raw

  out: dict[str, object] = {}
  shps = sorted(shp_dir.glob("**/*.shp"))
  if not shps:
    raise FileNotFoundError(f"no shapefiles under {shp_dir}")
  for shp in shps:
    meta, _, geoms, field_data = pyogrio.raw.read(str(shp))
    ids = field_data[[f.lower() for f in meta["fields"]].index("ps_id")]   # the shapefiles call it PS_ID
    for pid, g in zip(ids, shapely.force_2d(shapely.from_wkb(geoms))):
      out[str(pid)] = g
  return out


def is_marine(location_type, percent_marine) -> bool:
  if location_type is None or location_type in MARINE_LOCATION_TYPES:
    return True
  return percent_marine is not None and percent_marine > 0


def arrow_kind(t: pa.DataType) -> str:
  if pa.types.is_integer(t):
    return "int"
  if pa.types.is_floating(t):
    return "float"
  if pa.types.is_boolean(t):
    return "bool"
  if pa.types.is_date(t) or pa.types.is_timestamp(t):
    return "date"
  return "string"


def plain(v):
  if isinstance(v, dt.date) and not isinstance(v, dt.datetime):
    return dt.datetime(v.year, v.month, v.day, tzinfo=dt.timezone.utc)
  return v


def export_checksum(d: Path) -> str:
  """sha256 over the CSV bytes and each shapefile's size: changes with any new export, cheap on 2 GB of boundaries."""
  h = hashlib.sha256()
  for f in sorted((d / "csv").glob("*.csv")):
    h.update(f.name.encode())
    h.update(f.read_bytes())
  for f in sorted((d / "shp").glob("**/*.shp")):
    h.update(f"{f.name}:{f.stat().st_size}".encode())
  return h.hexdigest()


def fetch_navigator_export(src: dict, cache_dir: Path) -> SourceResult:
  d = export_dir(src, cache_dir)
  attrs = read_attributes(d / "csv")
  geoms = read_boundaries(d / "shp")
  fields = [{"name": f.name, "type": arrow_kind(f.type)} for f in attrs.schema]
  feats, inland, no_boundary = [], 0, 0
  for row in attrs.to_pylist():
    if not is_marine(row.get("location_type"), row.get("percent_marine_area")):
      inland += 1
      continue
    g = geoms.get(str(row["ps_id"]))
    if g is None or shapely.is_empty(g):
      no_boundary += 1
      continue
    feats.append({"properties": {k: plain(v) for k, v in row.items()}, "geometry": g})
  feats, left_out = include_features(feats, src.get("include"))     # one collection per group of categories
  feats, excluded = exclude_features(feats, src.get("exclude"))
  last = max((r for r in attrs.column("last_update").to_pylist() if r), default=None)
  return SourceResult(
    features=feats, fields=fields, source_url=src["url"], item_id=src.get("item_id", ""),
    component=src.get("component"),
    data_last_edit=f"{last.isoformat()}T00:00:00Z" if last else None, retrieved=now_iso(), record_count=len(feats),
    checksum=export_checksum(d),
    extra={"export": src.get("export_label", d.name), "sites_in_export": attrs.num_rows, "dropped_inland": inland,
           "dropped_no_boundary": no_boundary, "not_included": left_out or None, "excluded": excluded or None})


def probe_navigator_export(src: dict, cache_dir: Path, published: dict | None) -> dict:
  """change token for `detect`: the export's checksum when the export is on this machine, else the published one
  (unchanged; a new export is built by hand until the API sync lands)."""
  d = export_dir(src, cache_dir)
  if (d / "csv").exists():
    return {"checksum": export_checksum(d)}
  old = ((published or {}).get("sources") or [{}])[0]
  return {"checksum": old.get("checksum")}
