#!/usr/bin/env python3
"""build the gazetteer's geometry-free place index and id crosswalk (what the JS client searches and resolves).

  catalog/staging/index/places_index.parquet   one row per place, no geometry (range-read by hyparquet)
  catalog/staging/index/crosswalk.parquet      place_id <-> external ids (rows with at least one id)
  catalog/staging/index/collection.json        STAC collection `index` (CC0-1.0) + README.md

collections come from (a) catalog/staging/*/places.parquet (local, wins on a slug clash) and (b) the published
catalog's children that carry a places.parquet asset (erddap/stats/rasters/... children have none and are skipped).
rerunnable and deterministic: the same inputs give the same bytes. python: pyarrow + shapely (project deps).

  python scripts/build_index.py [--out DIR] [--staging DIR] [--base URL] [--no-remote] [--no-local]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin

import pyarrow as pa
import pyarrow.parquet as pq
import shapely

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://storage.oceanmetrics.io/gazetteer/"
ROW_GROUP = 5000
INDEX_VERSION = "1.0.0"

# schemas (plain utf8/double so hyparquet can range-read them) ----
BBOX_T = pa.struct([("xmin", pa.float64()), ("ymin", pa.float64()), ("xmax", pa.float64()), ("ymax", pa.float64())])
INDEX_SCHEMA = pa.schema([
  ("place_id", pa.string()), ("name", pa.string()), ("authority", pa.string()), ("place_type", pa.string()),
  ("geom_type", pa.string()), ("collection", pa.string()), ("bbox", BBOX_T),
  ("centroid_lon", pa.float64()), ("centroid_lat", pa.float64()), ("area_km2", pa.float64()),
  ("license", pa.string()), ("attribution", pa.string()), ("version", pa.string()), ("updated", pa.string()),
])
XW_COLS = ["mrgid", "psgid", "wdpa_id", "mpainv_site_id", "mpatlas_id", "wikidata_qid", "gers_id"]
XW_SCHEMA = pa.schema([("place_id", pa.string())] + [(c, pa.string()) for c in XW_COLS])

# crosswalk id columns found in a source layer (lower-cased column name -> crosswalk column) ----
XW_SOURCE_COLS = {
  "mrgid": "mrgid", "psgid": "psgid", "proseasid": "psgid", "wdpa_cd": "wdpa_id", "wdpa_id": "wdpa_id",
  "wdpaid": "wdpa_id", "mpainv_site_id": "mpainv_site_id", "mpatlas_id": "mpatlas_id",
  "wikidata_qid": "wikidata_qid", "gers_id": "gers_id",
}
# place_id prefix -> (crosswalk column, regex capturing the id); MPA: is the NOAA MPA Inventory's authority
XW_PREFIX = {
  "MRGID": ("mrgid", re.compile(r"^(\d+)")),
  "PSGID": ("psgid", re.compile(r"^(.+)$")),
  "MPAINV": ("mpainv_site_id", re.compile(r"^(.+)$")),
  "MPA": ("mpainv_site_id", re.compile(r"^(.+)$")),
}
NULL_IDS = {"", "0", "nan", "none", "null", "na", "n/a"}
GEOM_NAMES = {0: "Point", 1: "LineString", 2: "LinearRing", 3: "Polygon", 4: "MultiPoint", 5: "MultiLineString",
              6: "MultiPolygon", 7: "GeometryCollection"}


# helpers ----
def squash(s) -> str | None:
  s = " ".join(str(s).split()) if s is not None else ""
  return s or None


def clean_id(v) -> str | None:
  """a source id as a clean string: 1234.0 -> '1234', blanks and 0/nan/none -> None."""
  if v is None:
    return None
  if isinstance(v, float):
    if v != v:
      return None
    v = int(v) if v == int(v) else v
  s = re.sub(r"^(\d+)\.0+$", r"\1", str(v).strip())
  return None if s.lower() in NULL_IDS else s


def prefix_id(place_id: str | None) -> tuple[str, str] | None:
  """(crosswalk column, id) implied by a place_id prefix, e.g. MRGID:8439:part -> ('mrgid', '8439')."""
  if not place_id or ":" not in place_id:
    return None
  pre, rest = place_id.split(":", 1)
  hit = XW_PREFIX.get(pre.upper())
  if not hit:
    return None
  m = hit[1].match(rest.strip())
  return (hit[0], m.group(1)) if m else None


def attribution_of(coll: dict) -> str | None:
  txt = squash(coll.get("gazetteer:attribution"))
  if txt:
    return txt
  names = list(dict.fromkeys(
    p["name"] for p in coll.get("providers") or []
    if p.get("name") and ({"producer", "licensor"} & set(p.get("roles", [])))))
  return (", ".join(names) + ". " if names else "") + "Processed by Ocean Metrics."


def authority_of(place_id: str | None) -> str | None:
  return place_id.split(":", 1)[0] if place_id and ":" in place_id else None


# discovery ----
@dataclass
class Source:
  slug: str
  path: Path
  coll: dict
  origin: str  # local | published
  version: str | None = None


def get_json(url: str, timeout: int = 60):
  req = urllib.request.Request(url, headers={"User-Agent": "oceanmetrics-places/build-index"})
  with urllib.request.urlopen(req, timeout=timeout) as r:
    return json.load(r)


def download(url: str, dest: Path, timeout: int = 300) -> Path:
  dest.parent.mkdir(parents=True, exist_ok=True)
  req = urllib.request.Request(url, headers={"User-Agent": "oceanmetrics-places/build-index"})
  with urllib.request.urlopen(req, timeout=timeout) as r, open(dest, "wb") as f:
    while chunk := r.read(1 << 20):
      f.write(chunk)
  return dest


def parquet_href(coll: dict) -> str | None:
  """href of the collection's places.parquet asset (any asset whose file is places.parquet), else None."""
  for a in (coll.get("assets") or {}).values():
    h = a.get("href") or ""
    if h.split("?")[0].rsplit("/", 1)[-1] == "places.parquet":
      return h
  return None


def local_sources(staging: Path) -> list[Source]:
  out = []
  for f in sorted(staging.glob("*/places.parquet")):
    cj = f.parent / "collection.json"
    coll = json.loads(cj.read_text()) if cj.exists() else {}
    out.append(Source(f.parent.name, f, coll, "local", coll.get("version")
                      or (coll.get("gazetteer:provenance") or {}).get("version")))
  return out


def remote_sources(base: str, cache: Path, fetch=get_json, get_file=download) -> list[Source]:
  """published children with a places.parquet asset, downloaded into cache; [] (warned) when unreachable."""
  try:
    cat = fetch(urljoin(base, "catalog.json"))
  except (urllib.error.URLError, OSError, ValueError) as e:
    print(f"warning: published catalog unreachable ({e}); remote collections skipped", file=sys.stderr)
    return []
  try:
    versions = fetch(urljoin(base, "versions.json")).get("collections") or {}
  except (urllib.error.URLError, OSError, ValueError):
    versions = {}
  hrefs = [urljoin(base, l["href"]) for l in cat.get("links", []) if l.get("rel") == "child"]

  def one(href: str):
    try:
      coll = fetch(href)
      h = parquet_href(coll)
      if not h:
        return None
      slug = coll["id"]
      path = get_file(urljoin(href, h), cache / slug / "places.parquet")
    except (urllib.error.URLError, OSError, ValueError, KeyError) as e:
      print(f"warning: {href}: {e}", file=sys.stderr)
      return None
    ver = coll.get("version") or (versions.get(slug) or {}).get("current_version")
    return Source(slug, path, coll, "published", ver)

  with ThreadPoolExecutor(8) as ex:
    return [s for s in ex.map(one, hrefs) if s]


def merge_sources(published: list[Source], local: list[Source]) -> list[Source]:
  """one source per slug, a local staged build replacing the published one; sorted by slug."""
  by = {s.slug: s for s in published}
  by.update({s.slug: s for s in local})
  return [by[k] for k in sorted(by)]


# per-collection rows ----
def _col(batch: pa.RecordBatch, cols: dict[str, str], name: str):
  return batch.column(cols[name]) if name in cols else None


def _strs(arr, n: int) -> list:
  return [squash(v) for v in arr.to_pylist()] if arr is not None else [None] * n


def batch_rows(batch: pa.RecordBatch, src: Source) -> tuple[dict, list[dict]]:
  """(index columns, crosswalk rows) for one record batch of a source layer."""
  n = batch.num_rows
  cols = {c.lower(): c for c in batch.schema.names}
  coll = src.coll
  ids = [v for v in batch.column(cols["place_id"]).to_pylist()]

  # geometry-derived: bounds, centroid, type ----
  if "geometry" in cols:
    wkb = batch.column(cols["geometry"]).to_pylist()
    geoms = shapely.from_wkb(wkb, on_invalid="ignore")
    ok = ~shapely.is_missing(geoms) & ~shapely.is_empty(geoms)
    bounds = shapely.bounds(geoms)
    tids = shapely.get_type_id(geoms)
  else:
    geoms = ok = bounds = tids = None

  bb = [None] * n
  if "bbox" in cols:
    st = batch.column(cols["bbox"])
    f = {k: st.field(k).to_pylist() for k in ("xmin", "ymin", "xmax", "ymax")}
    bb = [(f["xmin"][i], f["ymin"][i], f["xmax"][i], f["ymax"][i]) if None not in (f["xmin"][i], f["ymin"][i], f["xmax"][i], f["ymax"][i]) else None for i in range(n)]
  bbox, clon, clat, gtype = [], [], [], []
  for i in range(n):
    b = bb[i]
    if b is None and geoms is not None and ok[i]:
      b = tuple(float(x) for x in bounds[i])
    c = None
    if geoms is not None and ok[i]:
      pt = shapely.centroid(geoms[i])
      c = (pt.x, pt.y)
    elif b is not None:
      c = ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    bbox.append(None if b is None else {"xmin": b[0], "ymin": b[1], "xmax": b[2], "ymax": b[3]})
    clon.append(None if c is None else c[0])
    clat.append(None if c is None else c[1])
    gtype.append(GEOM_NAMES.get(int(tids[i])) if tids is not None and ok[i] else None)

  # attributes: row column wins, then collection metadata, then the place_id prefix ----
  row_gt = _strs(_col(batch, cols, "geom_type"), n)
  coll_gt = squash(coll.get("geoparquet:geometry_type"))
  def pick_gt(row, computed):
    # the collection's declared type (Polygon rows of a MultiPolygon layer) unless the stored geometry is another kind
    fam = lambda t: "point" if "Point" in t else "line" if "Line" in t else "polygon"
    if row:
      return row
    return coll_gt if coll_gt and (not computed or fam(computed) == fam(coll_gt)) else computed or coll_gt
  geom_type = [pick_gt(row_gt[i], gtype[i]) for i in range(n)]
  row_auth = _strs(_col(batch, cols, "authority") if "authority" in cols else _col(batch, cols, "gazetteer"), n)
  authority = [row_auth[i] or squash(coll.get("gazetteer:authority")) or authority_of(ids[i]) for i in range(n)]
  row_pt = _strs(_col(batch, cols, "place_type"), n)
  place_type = [v or squash(coll.get("gazetteer:place_type")) for v in row_pt]
  row_lic = _strs(_col(batch, cols, "license"), n)
  lic = [v or squash(coll.get("license")) for v in row_lic]
  row_att = _strs(_col(batch, cols, "attribution"), n)
  att = [v or attribution_of(coll) for v in row_att]
  row_ver = _strs(_col(batch, cols, "version"), n)
  ver = [v or src.version for v in row_ver]
  updated = squash(coll.get("updated") or (coll.get("gazetteer:provenance") or {}).get("built"))
  area = _col(batch, cols, "area_km2")
  area = [None if v is None or v != v else float(v) for v in area.to_pylist()] if area is not None else [None] * n

  index = {
    "place_id": ids, "name": _strs(_col(batch, cols, "name"), n), "authority": authority, "place_type": place_type,
    "geom_type": geom_type, "collection": [src.slug] * n, "bbox": bbox, "centroid_lon": clon, "centroid_lat": clat,
    "area_km2": area, "license": lic, "attribution": att, "version": ver, "updated": [updated] * n,
  }

  # crosswalk: source columns, then the place_id prefix fills what is still unknown ----
  src_cols = {XW_SOURCE_COLS[k]: cols[k] for k in XW_SOURCE_COLS if k in cols}
  xw_vals = {c: [clean_id(v) for v in batch.column(src_cols[c]).to_pylist()] if c in src_cols else [None] * n
             for c in XW_COLS}
  xw = []
  for i in range(n):
    row = {c: xw_vals[c][i] for c in XW_COLS}
    p = prefix_id(ids[i])
    if p and not row[p[0]]:
      row[p[0]] = p[1]
    if any(row.values()):
      xw.append({"place_id": ids[i], **row})
  return index, xw


def source_batches(src: Source):
  """record batches of ROW_GROUP rows with only the columns the index needs (never both geometry twice)."""
  pf = pq.ParquetFile(src.path)
  low = {c.lower(): c for c in pf.schema_arrow.names}
  want = ["place_id", "name", "authority", "gazetteer", "place_type", "geom_type", "bbox", "geometry", "area_km2",
          "license", "attribution", "version"] + list(XW_SOURCE_COLS)
  cols = [low[w] for w in dict.fromkeys(want) if w in low]
  if "place_id" not in low:
    raise ValueError(f"{src.slug}: no place_id column")
  yield from pf.iter_batches(batch_size=ROW_GROUP, columns=cols)


# build ----
def _table(rows_by_col: dict[str, list], schema: pa.Schema) -> pa.Table:
  return pa.table({f.name: pa.array(rows_by_col[f.name], type=f.type) for f in schema}, schema=schema)


def build(sources: list[Source], out: Path) -> dict:
  """write places_index.parquet + crosswalk.parquet for the sources; returns {slug: n_rows} and crosswalk counts."""
  out.mkdir(parents=True, exist_ok=True)
  counts: dict[str, int] = {}
  seen: dict[str, str] = {}
  dups = 0
  xw_n = {c: 0 for c in XW_COLS}
  xw_rows = 0
  ext = [180.0, 90.0, -180.0, -90.0]
  updated = []
  opts = dict(compression="snappy", data_page_version="1.0", use_dictionary=False, write_statistics=True)
  with pq.ParquetWriter(out / "places_index.parquet", INDEX_SCHEMA, **opts) as iw, \
       pq.ParquetWriter(out / "crosswalk.parquet", XW_SCHEMA, **opts) as xw_w:
    pend_i: list[dict] = []
    pend_x: list[dict] = []

    def flush_index():
      nonlocal pend_i
      if pend_i:
        iw.write_table(_table({k: sum((p[k] for p in pend_i), []) for k in INDEX_SCHEMA.names}, INDEX_SCHEMA),
                       row_group_size=ROW_GROUP)
        pend_i = []

    for src in sources:
      counts[src.slug] = 0
      try:
        for batch in source_batches(src):
          index, xw = batch_rows(batch, src)
          for pid in index["place_id"]:
            if pid in seen and seen[pid] != src.slug:
              dups += 1
            seen.setdefault(pid, src.slug)
          for b in index["bbox"]:
            if b:
              ext = [min(ext[0], b["xmin"]), min(ext[1], b["ymin"]), max(ext[2], b["xmax"]), max(ext[3], b["ymax"])]
          counts[src.slug] += batch.num_rows
          pend_i.append(index)
          pend_x.extend(xw)
          if sum(len(p["place_id"]) for p in pend_i) >= ROW_GROUP:
            flush_index()
      except (ValueError, OSError, pa.ArrowException) as e:
        print(f"warning: {src.slug}: skipped ({e})", file=sys.stderr)
      if src.coll.get("updated"):
        updated.append(src.coll["updated"])
    flush_index()
    if pend_x:
      cols = {k: [r[k] for r in pend_x] for k in XW_SCHEMA.names}
      xw_w.write_table(_table(cols, XW_SCHEMA), row_group_size=ROW_GROUP)
      xw_rows = len(pend_x)
      for c in XW_COLS:
        xw_n[c] = sum(1 for r in pend_x if r[c])
  if dups:
    print(f"warning: {dups} place_id(s) occur in more than one collection", file=sys.stderr)
  return {"counts": counts, "crosswalk": xw_n, "crosswalk_rows": xw_rows, "bbox": ext,
          "updated": max(updated) if updated else None, "duplicates": dups}


def collection_json(stats: dict, out: Path) -> dict:
  total = sum(stats["counts"].values())
  asset = lambda name, desc, extra: {
    "href": f"./{name}", "type": "application/vnd.apache.parquet", "title": desc,
    "file:size": (out / name).stat().st_size, "roles": ["data", "index"], **extra}
  coll = {
    "type": "Collection", "id": "index", "stac_version": "1.1.0",
    "title": "Gazetteer index and crosswalk",
    "description": (
      "Geometry-free search index of every place in the Ocean Metrics gazetteer (one row per place: id, name, "
      "authority, type, collection, bbox, centroid, area, licence, attribution, version) and a crosswalk from "
      "place_id to external identifiers (MarineRegions MRGID, ProtectedSeas PSGID, WDPA, NOAA MPA Inventory, "
      "MPAtlas, Wikidata, Overture GERS). Read by the client with range requests to search and resolve places "
      "without loading any geometry. Rebuilt by scripts/build_index.py whenever a collection is published. The "
      "per-place licence and attribution of the underlying geometry are in the index rows and must be honoured "
      "when the geometry is used; the index itself is CC0-1.0."),
    "license": "CC0-1.0", "version": INDEX_VERSION,
    "extent": {"spatial": {"bbox": [stats["bbox"]]}, "temporal": {"interval": [[None, None]]}},
    "links": [
      {"rel": "root", "href": "../catalog.json", "type": "application/json"},
      {"rel": "parent", "href": "../catalog.json", "type": "application/json"},
      {"rel": "license", "href": "https://creativecommons.org/publicdomain/zero/1.0/", "type": "text/html"},
      {"rel": "describedby", "href": "./README.md", "type": "text/markdown"},
    ],
    "assets": {
      "places_index": asset("places_index.parquet", "Place index (no geometry)",
                            {"table:row_count": total}),
      "crosswalk": asset("crosswalk.parquet", "place_id to external ids",
                         {"table:row_count": stats["crosswalk_rows"]}),
      "documentation": {"href": "./README.md", "type": "text/markdown", "roles": ["documentation"]},
    },
    "gazetteer:collections": stats["counts"],
  }
  if stats["updated"]:
    coll["updated"] = stats["updated"]
  return coll


def readme(stats: dict, origins: dict[str, str]) -> str:
  rows = "\n".join(f"| {k} | {origins.get(k, '')} | {v} |" for k, v in stats["counts"].items())
  xw = "\n".join(f"| {c} | {n} |" for c, n in stats["crosswalk"].items())
  return f"""# Gazetteer index and crosswalk

Geometry-free companions to the gazetteer collections, for searching and resolving places in the browser.
Licence of the index itself: CC0-1.0. Each row carries the `license` and `attribution` of the geometry it
points to; honour them when you use that geometry.

## `places_index.parquet`

One row per place ({sum(stats["counts"].values())} rows, row groups of {ROW_GROUP}, snappy, plain columns).

| column | type | note |
|---|---|---|
| place_id | utf8 | `<authority>:<source_id>`, stable |
| name | utf8 | |
| authority | utf8 | |
| place_type | utf8 | |
| geom_type | utf8 | Point, LineString, Polygon, Multi* |
| collection | utf8 | slug; the PMTiles/GeoParquet live at `<base><collection>/` |
| bbox | struct | xmin, ymin, xmax, ymax (double); antimeridian geometries are split, so xmin may be -180 and xmax 180 |
| centroid_lon, centroid_lat | double | planar centroid of the stored geometry (bbox centre if absent) |
| area_km2 | double | null where the source has none |
| license, attribution, version, updated | utf8 | per row, from the collection |

## `crosswalk.parquet`

`place_id` plus `mrgid`, `psgid`, `wdpa_id`, `mpainv_site_id`, `mpatlas_id`, `wikidata_qid`, `gers_id` (all utf8,
null where unknown); only places with at least one external id have a row ({stats["crosswalk_rows"]} rows).
Sources: `MRGID:`, `PSGID:`, `MPAINV:` and `MPA:` (NOAA MPA Inventory) place_id prefixes; id columns in a source
layer (`mrgid`, `psgid`, `ProSeasID` as psgid, `WDPA_Cd` as wdpa_id). `mpatlas_id`, `wikidata_qid` and `gers_id`
are reserved for later.

| column | non-null |
|---|---|
{xw}

## Collections indexed

| collection | origin | places |
|---|---|---|
{rows}

Rebuild with `python scripts/build_index.py` (local `catalog/staging/*/places.parquet` wins over the published
catalog; `--no-remote` / `--no-local` restrict it).
"""


def table_text(stats: dict, origins: dict[str, str]) -> str:
  w = max([len(k) for k in stats["counts"]] + [10])
  lines = [f"{'collection':<{w}}  {'origin':<9}  {'rows':>8}"]
  lines += [f"{k:<{w}}  {origins.get(k, ''):<9}  {v:>8}" for k, v in stats["counts"].items()]
  lines.append(f"{'TOTAL':<{w}}  {'':<9}  {sum(stats['counts'].values()):>8}")
  return "\n".join(lines)


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--out", default=str(ROOT / "catalog" / "staging" / "index"))
  ap.add_argument("--staging", default=str(ROOT / "catalog" / "staging"))
  ap.add_argument("--base", default=BASE, help="published catalog base URL")
  ap.add_argument("--no-remote", action="store_true")
  ap.add_argument("--no-local", action="store_true")
  a = ap.parse_args(argv)
  staging, out = Path(a.staging), Path(a.out)
  loc = [] if a.no_local or not staging.is_dir() else local_sources(staging)
  with tempfile.TemporaryDirectory(prefix="places-index-") as tmp:
    rem = [] if a.no_remote else remote_sources(a.base, Path(tmp))
    sources = merge_sources(rem, loc)
    stats = build(sources, out)
  origins = {s.slug: s.origin for s in sources}
  (out / "collection.json").write_text(json.dumps(collection_json(stats, out), indent=2, ensure_ascii=False) + "\n")
  (out / "README.md").write_text(readme(stats, origins))
  print(table_text(stats, origins))
  print("crosswalk rows: " + str(stats["crosswalk_rows"]) + "; non-null: "
        + ", ".join(f"{c}={n}" for c, n in stats["crosswalk"].items()))
  print(f"wrote {out}")
  return 0


if __name__ == "__main__":
  sys.exit(main())
