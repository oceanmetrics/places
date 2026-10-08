"""CalCOFI station positions -> point (stations) and linestring (lines) features.

source: the two files CalCOFI publishes on https://calcofi.org/sampling-info/station-positions/
  - CalCOFIStationOrder.csv           the 113 stations of the extended pattern (line, station, lat, lon, depth, type)
  - CalCOFI_75StandardStations.kml    the 75-station standard pattern (placemark names are "LLL.L SSS.S")
a station is `in_core_75` when its key is a placemark of the 75-station KML; the other 38 form the extended grid.
a line is the polyline through its stations in nearshore -> offshore order; a line with a single listed position
(the SCCOOS inshore stations that sit on their own line numbers) cannot form a linestring and is reported as dropped.
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path

import pyproj
import requests
import shapely
from shapely.geometry import LineString, Point

from .fetch import SourceResult, download, head_info, now_iso, session

GEOD = pyproj.Geod(ellps="WGS84")

STATION_FIELDS = [
  {"name": "line_id", "type": "string"}, {"name": "station_id", "type": "string"},
  {"name": "station_key", "type": "string"}, {"name": "line", "type": "float"}, {"name": "station", "type": "float"},
  {"name": "order_occ", "type": "int"}, {"name": "depth_est_m", "type": "int"}, {"name": "sta_type", "type": "string"},
  {"name": "in_core_75", "type": "bool"}, {"name": "sampling_pattern", "type": "string"},
]
LINE_FIELDS = [
  {"name": "line_id", "type": "string"}, {"name": "line", "type": "float"}, {"name": "n_stations", "type": "int"},
  {"name": "n_core_75", "type": "int"}, {"name": "in_core_75", "type": "bool"},
  {"name": "station_min", "type": "float"}, {"name": "station_max", "type": "float"}, {"name": "length_km", "type": "float"},
]


def pad(value: float) -> str:
  """CalCOFI's fixed-width number: 93.3 -> '093.3', 30 -> '030.0', 120 -> '120.0'."""
  return f"{float(value):05.1f}"


def station_key(line: float, station: float) -> str:
  """'093.3 030.0', the form of the CalCOFI database's site_key."""
  return f"{pad(line)} {pad(station)}"


def parse_station_order(text: str) -> list[dict]:
  """CalCOFIStationOrder.csv -> one dict per station (line, station, lat, lon, order_occ, depth_est_m, sta_type)."""
  out = []
  for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
    line, sta = float(r["Line"]), float(r["Sta"])
    depth = (r.get("Est Depth") or "").strip()
    out.append({"line": line, "station": sta, "lat": float(r["Lat (dec)"]), "lon": float(r["Lon (dec)"]),
                "order_occ": int(r["Order Occ"]), "depth_est_m": int(float(depth)) if depth else None,
                "sta_type": (r.get("Sta Type") or "").strip()})
  return out


def parse_core_keys(kml: str) -> set[str]:
  """the station keys ('093.3 026.7') among the placemark names of the 75-station KML (folders and facilities ignored)."""
  names = re.findall(r"<Placemark>\s*<name>([^<]*)</name>", kml)
  return {n.strip() for n in names if re.fullmatch(r"\d{3}\.\d \d{3}\.\d", n.strip())}


def station_features(rows: list[dict], core_keys: set[str]) -> tuple[list[dict], list[dict], list[str]]:
  """station rows -> (features, fields, notes); notes list core keys with no position in the table."""
  feats = []
  for r in rows:
    key = station_key(r["line"], r["station"])
    core = key in core_keys
    feats.append({"properties": {
      "line_id": pad(r["line"]), "station_id": pad(r["station"]), "station_key": key, "line": r["line"],
      "station": r["station"], "order_occ": r["order_occ"], "depth_est_m": r["depth_est_m"], "sta_type": r["sta_type"],
      "in_core_75": core, "sampling_pattern": "core_75" if core else "extended"},
      "geometry": Point(r["lon"], r["lat"])})
  missing = sorted(core_keys - {f["properties"]["station_key"] for f in feats})
  notes = [f"core-75 station {k} has no position in the station table" for k in missing]
  return feats, STATION_FIELDS, notes


def line_features(rows: list[dict], core_keys: set[str]) -> tuple[list[dict], list[dict], list[str]]:
  """station rows -> (features, fields, notes): one LineString per line with two or more stations, vertices in
  station-number order (nearshore -> offshore); single-station lines are dropped and reported."""
  by_line: dict[float, list[dict]] = {}
  for r in rows:
    by_line.setdefault(r["line"], []).append(r)
  feats, notes = [], []
  for line in sorted(by_line):
    sts = sorted(by_line[line], key=lambda r: r["station"])
    if len(sts) < 2:
      notes.append(f"line {pad(line)} has one listed station ({station_key(line, sts[0]['station'])}, "
                   f"{sts[0]['sta_type']}): no linestring")
      continue
    geom = LineString([(r["lon"], r["lat"]) for r in sts])
    n_core = sum(station_key(line, r["station"]) in core_keys for r in sts)
    length_km = GEOD.geometry_length(geom) / 1000
    feats.append({"properties": {
      "line_id": pad(line), "line": line, "n_stations": len(sts), "n_core_75": n_core, "in_core_75": n_core > 0,
      "station_min": sts[0]["station"], "station_max": sts[-1]["station"], "length_km": round(length_km, 1)},
      "geometry": geom})
  return feats, LINE_FIELDS, notes


def build_features(product: str, rows: list[dict], core_keys: set[str]):
  if product == "stations":
    return station_features(rows, core_keys)
  if product == "lines":
    return line_features(rows, core_keys)
  raise ValueError(f"unknown calcofi product {product!r} (stations | lines)")


def clean_simple_geometry(geom, geom_type: str):
  """a valid 2-D Point or LineString (the collection's `geometry_type`), or None; no antimeridian handling is
  needed (CalCOFI is at 117-127 W) but longitudes outside [-180, 180] are rejected."""
  if geom is None or geom.is_empty:
    return None
  geom = shapely.force_2d(geom)
  if geom.geom_type != geom_type or not geom.is_valid:
    return None
  x0, y0, x1, y1 = geom.bounds
  if x0 < -180 or x1 > 180 or y0 < -90 or y1 > 90:
    return None
  return geom


def fetch_calcofi(src: dict, cache_dir: Path, s: requests.Session | None = None) -> SourceResult:
  """download the station-order CSV and the 75-station KML (own cache directory) and build the product's features.

  `data_last_edit` is the CSV's Last-Modified date; the checksum covers both downloads.
  """
  s = s or session()
  csv_path = download(src["url"], cache_dir / "calcofi", s)
  kml_path = download(src["core_url"], cache_dir / "calcofi", s)
  head = head_info(src["url"], s)
  rows = parse_station_order(csv_path.read_text(encoding="utf-8", errors="replace"))
  core = parse_core_keys(kml_path.read_text(encoding="utf-8", errors="replace"))
  feats, fields, notes = build_features(src["product"], rows, core)
  expected = src.get("expected_count")
  if expected and expected != len(feats):
    raise RuntimeError(f"{src['url']}: expected {expected} {src['product']}, built {len(feats)}")
  if src.get("expected_core") and len(core & {station_key(r["line"], r["station"]) for r in rows}) != src["expected_core"]:
    raise RuntimeError(f"the 75-station KML matches {len(core)} keys, expected {src['expected_core']} core stations")
  h = hashlib.sha256()
  for p in (csv_path, kml_path):
    h.update(p.read_bytes())
  edit = None
  if head.get("last_modified"):
    from email.utils import parsedate_to_datetime
    edit = parsedate_to_datetime(head["last_modified"]).strftime("%Y-%m-%dT%H:%M:%SZ")
  return SourceResult(
    features=feats, fields=fields, source_url=src["url"], item_id=src.get("item_id", ""), component=src.get("component"),
    data_last_edit=edit, retrieved=now_iso(), record_count=len(feats), checksum=h.hexdigest(),
    extra={"http": head, "core_75_source": src["core_url"], "core_75_stations": len(core), "dropped": notes})
