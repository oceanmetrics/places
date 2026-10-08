"""rows -> the gazetteer GeoParquet 1.1 table (common columns, native attributes, bbox struct, WKB geometry)."""
from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pyproj
import shapely

from .config import source_setting
from .fetch import SourceResult
from .geom import clean_geometry
from .ids import build_place_ids, check_place_ids
from .fmt import render
from .status import load_overlay, resolve_status, unmatched_overlay

log = logging.getLogger(__name__)

COMMON = ["place_id", "authority", "source_id", "name", "place_type", "geom_type", "status", "status_source",
          "status_date", "source_url", "source_date", "retrieved", "version", "license", "attribution"]
RESERVED = {c.lower() for c in COMMON} | {"component", "bbox", "geometry"}
TS = pa.timestamp("ms", tz="UTC")
BBOX = pa.struct([("xmin", pa.float64()), ("ymin", pa.float64()), ("xmax", pa.float64()), ("ymax", pa.float64())])


def native_names(fields: list[dict]) -> dict[str, str]:
  """native attribute name -> parquet column name. natives keep their names, except one that equals a gazetteer
  column ignoring case (NAME vs name: DuckDB treats column names case-insensitively) gets a '_src' suffix."""
  out = {}
  for f in fields:
    n = f["name"]
    out[n] = f"{n}_src" if n.lower() in RESERVED else n
  return out


def coerce(value, typ: str):
  """a native value -> the Python value for its Arrow type (Esri dates are epoch milliseconds)."""
  if value is None or (isinstance(value, float) and np.isnan(value)):
    return None
  if typ == "int":
    return int(value)
  if typ == "float":
    return float(value)
  if typ == "date":
    if isinstance(value, (int, float)):
      return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc)
    if isinstance(value, str):
      return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return value
  return str(value)


def arrow_type(typ: str) -> pa.DataType:
  return {"int": pa.int64(), "float": pa.float64(), "date": TS}.get(typ, pa.string())


def _iso_day(iso: str | None) -> dt.date | None:
  return dt.date.fromisoformat(iso[:10]) if iso else None


def build_rows(cfg: dict, results: list[SourceResult], version: str | None = None) -> tuple[list[dict], list[dict], list[str]]:
  """normalise fetched sources into (rows, native field defs, dropped notes).

  each row dict holds the common columns, `component` (when configured), the natives under their column
  names and `_geom` (clean shapely MultiPolygon). features with no usable polygon are dropped and reported.
  """
  maps = cfg.get("maps") or {}
  overlay_cfg = (cfg.get("status") or {}).get("overlay")
  overlay = load_overlay(Path(cfg["_sources_dir"]) / overlay_cfg["file"]) if overlay_cfg else None
  version = version or cfg["version"]
  rows, fields, dropped = [], [], []
  seen_types: dict[str, str] = {}
  for src_cfg, res in zip(cfg["sources"], results):
    names = native_names(res.fields)
    for f in res.fields:
      col = names[f["name"]]
      if seen_types.setdefault(col, f["type"]) != f["type"]:
        raise ValueError(f"column {col} has type {seen_types[col]} and {f['type']} in different sources")
      if col not in [x["name"] for x in fields]:
        fields.append({"name": col, "type": f["type"], "native": f["name"]})
    keep = []
    for ft in res.features:
      g = clean_geometry(ft["geometry"])
      if g is None:
        dropped.append(f"{res.source_url}: dropped feature with no polygon (attributes: "
                       f"{ {k: v for k, v in ft['properties'].items() if v not in (None, '')} })")
        continue
      keep.append((ft["properties"], g))
    attrs = [p for p, _ in keep]
    pid_cfg = source_setting(cfg, src_cfg, "place_id")
    ids = build_place_ids(pid_cfg, attrs, maps)
    check_place_ids(ids, pid_cfg["pattern"])
    if overlay:
      unmatched_overlay(overlay, attrs, cfg["status"]["overlay"]["key"])
    ftypes = {f["name"]: f["type"] for f in res.fields}
    for (props, g), pid in zip(keep, ids):
      st = resolve_status(cfg["status"], props, res.data_last_edit, overlay,
                          cfg["status"]["overlay"]["key"] if overlay_cfg else None)
      row = {
        "place_id": pid, "authority": cfg["authority"],
        "source_id": render(source_setting(cfg, src_cfg, "source_id"), props, maps),
        "name": render(source_setting(cfg, src_cfg, "name"), props, maps),
        "place_type": cfg["place_type"], "geom_type": "MultiPolygon",
        "status": st[0], "status_source": st[1], "status_date": st[2],
        "source_url": res.source_url,
        "source_date": _iso_day(res.data_last_edit) or _iso_day(res.retrieved),
        "retrieved": dt.datetime.fromisoformat(res.retrieved.replace("Z", "+00:00")),
        "version": version, "license": cfg["license"], "attribution": " ".join(cfg["attribution"].split()),
        "_geom": g,
      }
      if src_cfg.get("component"):
        row["component"] = src_cfg["component"]
      for nat, col in names.items():
        row[col] = coerce(props.get(nat), ftypes[nat])
      rows.append(row)
  all_ids = [r["place_id"] for r in rows]
  if len(set(all_ids)) != len(all_ids):
    raise ValueError("place_id is not unique across the collection's sources")
  return rows, fields, dropped


def to_table(rows: list[dict], fields: list[dict]) -> pa.Table:
  """rows -> Arrow table: common columns, component, natives, bbox struct, WKB geometry (last)."""
  has_component = any("component" in r for r in rows)
  cols, arrays = [], []

  def add(name: str, typ: pa.DataType, values: list):
    cols.append(name)
    arrays.append(pa.array(values, type=typ))

  for c in COMMON:
    add(c, pa.date32() if c == "source_date" else TS if c == "retrieved" else pa.string(), [r[c] for r in rows])
  if has_component:
    add("component", pa.string(), [r.get("component") for r in rows])
  for f in fields:
    add(f["name"], arrow_type(f["type"]), [r.get(f["name"]) for r in rows])
  geoms = np.array([r["_geom"] for r in rows], dtype=object)
  b = shapely.bounds(geoms)
  cols.append("bbox")
  arrays.append(pa.StructArray.from_arrays([pa.array(b[:, i]) for i in range(4)], fields=list(BBOX)))
  cols.append("geometry")
  arrays.append(pa.array(shapely.to_wkb(geoms, output_dimension=2, byte_order=1), type=pa.binary()))
  return pa.Table.from_arrays(arrays, names=cols)


def geo_metadata(table: pa.Table) -> dict:
  """GeoParquet 1.1 `geo` metadata for the table: WKB MultiPolygon in EPSG:4326 with the bbox covering."""
  b = table.column("bbox").combine_chunks()
  mins = [min(b.field(k).to_pylist()) for k in ("xmin", "ymin")]
  maxs = [max(b.field(k).to_pylist()) for k in ("xmax", "ymax")]
  return {"version": "1.1.0", "primary_column": "geometry", "columns": {"geometry": {
    "encoding": "WKB", "geometry_types": ["MultiPolygon"], "crs": pyproj.CRS.from_epsg(4326).to_json_dict(),
    "edges": "planar", "orientation": "counterclockwise", "bbox": [mins[0], mins[1], maxs[0], maxs[1]],
    "covering": {"bbox": {k: ["bbox", k] for k in ("xmin", "ymin", "xmax", "ymax")}}}}}


def write_geoparquet(table: pa.Table, path: Path, provenance: dict, row_group_size: int = 2000) -> dict:
  """write GeoParquet 1.1 (zstd) with the geo metadata and the provenance record; returns the geo metadata."""
  geo = geo_metadata(table)
  meta = {b"geo": json.dumps(geo).encode(), b"gazetteer:provenance": json.dumps(provenance).encode()}
  path.parent.mkdir(parents=True, exist_ok=True)
  pq.write_table(table.replace_schema_metadata(meta), path, compression="zstd", row_group_size=row_group_size)
  return geo
