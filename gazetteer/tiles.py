"""PMTiles from a staged GeoParquet via tippecanoe (-zg, layer name = collection slug, attribution in the metadata)."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pyarrow.parquet as pq
import shapely


def _json_value(v):
  if isinstance(v, (dt.datetime, dt.date)):
    return v.isoformat()
  return v


# tile properties: just enough to label, filter and look a place up (the full record is in the GeoParquet, joined on
# place_id); every property is repeated in each tile a polygon touches, so a full set made 52 leases a 19 MB archive
TILE_PROPERTIES = ["place_id", "name", "place_type", "status", "status_date", "source_id", "component"]


def table_to_ndjson(parquet: Path, out: Path, keep: list[str] | None = None) -> int:
  """write newline-delimited GeoJSON features (the `keep` columns as properties); returns the count."""
  t = pq.read_table(parquet)
  names = [n for n in (keep or TILE_PROPERTIES) if n in t.column_names]
  data = {n: t.column(n).to_pylist() for n in names}
  geoms = shapely.from_wkb(t.column("geometry").to_pylist())
  with open(out, "w", encoding="utf-8") as fh:
    for i, g in enumerate(geoms):
      props = {n: _json_value(data[n][i]) for n in names if data[n][i] is not None}
      fh.write(json.dumps({"type": "Feature", "properties": props, "geometry": shapely.geometry.mapping(g)}) + "\n")
  return len(geoms)


def tippecanoe_cmd(src: Path, dest: Path, slug: str, name: str, description: str, attribution: str) -> list[str]:
  """the tippecanoe invocation: guessed max zoom, layer = slug, -n / -N name and description, --attribution."""
  return ["tippecanoe", "-o", str(dest), "-zg", "-l", slug, "-n", name, "-N", description,
          "--attribution", attribution, "--drop-densest-as-needed", "--extend-zooms-if-still-dropping",
          "--read-parallel", "--force", "--quiet", str(src)]


def build_pmtiles(parquet: Path, dest: Path, slug: str, name: str, description: str, attribution: str,
                  keep: list[str] | None = None) -> int:
  """GeoParquet -> PMTiles; returns the feature count. raises if tippecanoe is missing or fails."""
  if not shutil.which("tippecanoe"):
    raise RuntimeError("tippecanoe not found on PATH (brew install tippecanoe, or build felt/tippecanoe)")
  with tempfile.TemporaryDirectory() as tmp:
    nd = Path(tmp) / f"{slug}.geojsonl"
    n = table_to_ndjson(parquet, nd, keep)
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(tippecanoe_cmd(nd, dest, slug, name, " ".join(description.split()), " ".join(attribution.split())),
                   check=True)
  return n


def read_pmtiles(path: Path) -> tuple[dict, dict]:
  """(header, metadata) of a PMTiles v3 file, read without extra dependencies.

  header: min_zoom, max_zoom, center, bounds, tile_type; metadata: the JSON tippecanoe wrote (name, description,
  attribution, vector_layers, ...).
  """
  import gzip
  import struct

  raw = Path(path).read_bytes()
  if raw[:7] != b"PMTiles" or raw[7] != 3:
    raise ValueError(f"{path}: not a PMTiles v3 file")
  off_meta, len_meta = struct.unpack_from("<QQ", raw, 24)
  compression = raw[97]                      # internal compression: 1 none, 2 gzip
  min_zoom, max_zoom = raw[100], raw[101]
  e7 = struct.unpack_from("<iiii", raw, 102)  # min lon, min lat, max lon, max lat (1e-7 degrees)
  center = struct.unpack_from("<ii", raw, 119)
  blob = raw[off_meta:off_meta + len_meta]
  if compression == 2:
    blob = gzip.decompress(blob)
  header = {"min_zoom": min_zoom, "max_zoom": max_zoom, "tile_type": raw[99],
            "bounds": [v / 1e7 for v in e7], "center": [center[0] / 1e7, center[1] / 1e7, raw[118]]}
  return header, json.loads(blob)
