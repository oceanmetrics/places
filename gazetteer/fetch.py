"""fetch a source layer: ArcGIS REST (FeatureServer / MapServer) or a zipped shapefile -> shapely features in EPSG:4326."""
from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import logging
import time
import zipfile
from pathlib import Path

import numpy as np
import requests
import shapely
from shapely.geometry import shape

from .geom import esri_json_to_geojson

log = logging.getLogger(__name__)

UA = "oceanmetrics-gazetteer/1.0 (+https://oceanmetrics.io; contact: bdbest@gmail.com)"
ESRI_TYPES = {
  "esriFieldTypeOID": "int", "esriFieldTypeInteger": "int", "esriFieldTypeSmallInteger": "int",
  "esriFieldTypeBigInteger": "int", "esriFieldTypeDouble": "float", "esriFieldTypeSingle": "float",
  "esriFieldTypeString": "string", "esriFieldTypeDate": "date", "esriFieldTypeGUID": "string",
  "esriFieldTypeGlobalID": "string", "esriFieldTypeDateOnly": "string", "esriFieldTypeTimeOnly": "string",
}
SHP_SIDECARS = {".shp", ".shx", ".dbf", ".prj", ".cpg"}


@dataclasses.dataclass
class SourceResult:
  """one fetched source: features (properties + shapely geometry in EPSG:4326), field types and provenance."""
  features: list[dict]
  fields: list[dict]                 # [{"name", "type"}], type in int | float | string | date
  source_url: str
  item_id: str = ""
  component: str | None = None
  data_last_edit: str | None = None  # ISO 8601 UTC, or None when the source serves no edit date
  retrieved: str = ""
  record_count: int = 0
  checksum: str = ""                 # sha256 of the raw payload
  extra: dict = dataclasses.field(default_factory=dict)  # source license / attribution text, item dates


def now_iso() -> str:
  return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ms_to_iso(ms) -> str | None:
  """epoch milliseconds -> ISO 8601 UTC string (None stays None)."""
  if ms in (None, ""):
    return None
  return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def session() -> requests.Session:
  s = requests.Session()
  s.headers.update({"User-Agent": UA, "Accept-Encoding": "gzip"})
  return s


def get(s: requests.Session, url: str, params: dict | None = None, verify: bool = True, tries: int = 4) -> requests.Response:
  """GET with retries and backoff (the shared BOEM / NOAA servers throttle and hiccup)."""
  last = None
  for k in range(tries):
    try:
      if not verify:
        requests.packages.urllib3.disable_warnings()
      r = s.get(url, params=params, timeout=120, verify=verify)
      if r.status_code in (429, 500, 502, 503, 504):
        raise requests.HTTPError(f"HTTP {r.status_code}", response=r)
      r.raise_for_status()
      return r
    except (requests.RequestException, OSError) as e:
      last = e
      time.sleep(2 ** k)
  raise RuntimeError(f"GET {url} failed after {tries} tries: {last}")


def arcgis_json(s, url: str, params: dict, verify: bool = True) -> dict:
  """GET an ArcGIS REST endpoint as JSON; ArcGIS reports many errors as HTTP 200 with an `error` body."""
  r = get(s, url, {**params, "f": "json"}, verify)
  d = r.json()
  if isinstance(d, dict) and d.get("error"):
    raise RuntimeError(f"ArcGIS error from {url}: {d['error']}")
  return d


def item_meta(s, item_id: str) -> dict:
  """AGOL item JSON -> the fields worth keeping as provenance (license text, credits, dates)."""
  if not item_id:
    return {}
  d = arcgis_json(s, f"https://www.arcgis.com/sharing/rest/content/items/{item_id}", {})
  return {"item_title": d.get("title"), "item_owner": d.get("owner"), "item_modified": ms_to_iso(d.get("modified")),
          "source_license": d.get("licenseInfo"), "source_attribution": d.get("accessInformation")}


def probe_arcgis(s, src: dict) -> dict:
  """cheap change token for an ArcGIS layer: {data_last_edit, record_count} (two small requests)."""
  url, verify = src["url"], src.get("tls_verify", True)
  meta = arcgis_json(s, url, {}, verify)
  count = arcgis_json(s, f"{url}/query", {"where": "1=1", "returnCountOnly": "true"}, verify)["count"]
  return {"data_last_edit": ms_to_iso((meta.get("editingInfo") or {}).get("dataLastEditDate")), "record_count": count}


def fetch_arcgis(src: dict, delay: float = 0.5, raw_dir: Path | None = None, s: requests.Session | None = None) -> SourceResult:
  """page through a layer with resultOffset (ordered by its object id) as GeoJSON in EPSG:4326, or Esri JSON when
  the server cannot do GeoJSON (src.format: esrijson, or chosen automatically from supportedQueryFormats)."""
  s = s or session()
  url, verify = src["url"], src.get("tls_verify", True)
  meta = arcgis_json(s, url, {}, verify)
  fields = [{"name": f["name"], "type": ESRI_TYPES.get(f["type"], "string")}
            for f in meta.get("fields", []) if f["type"] != "esriFieldTypeGeometry"]
  oid = meta.get("objectIdField") or next((f["name"] for f in meta["fields"] if f["type"] == "esriFieldTypeOID"), None)
  fmt = src.get("format") or ("geojson" if "geojson" in (meta.get("supportedQueryFormats") or "geojson").lower() else "esrijson")
  total = arcgis_json(s, f"{url}/query", {"where": "1=1", "returnCountOnly": "true"}, verify)["count"]
  page = int(src.get("page_size") or min(1000, meta.get("maxRecordCount") or 1000))
  feats, offset, h = [], 0, hashlib.sha256()
  while True:
    params = {"where": "1=1", "outFields": "*", "outSR": 4326, "returnGeometry": "true", "resultOffset": offset,
              "resultRecordCount": page, "f": "geojson" if fmt == "geojson" else "json"}
    if oid:
      params["orderByFields"] = oid
    r = get(s, f"{url}/query", params, verify)
    h.update(r.content)
    if raw_dir:
      raw_dir.mkdir(parents=True, exist_ok=True)
      (raw_dir / f"page_{offset:07d}.{'geojson' if fmt == 'geojson' else 'json'}").write_bytes(r.content)
    d = r.json()
    if isinstance(d, dict) and d.get("error"):
      raise RuntimeError(f"ArcGIS error from {url}: {d['error']}")
    got = d.get("features", [])
    exceeded = bool(d.get("exceededTransferLimit") or (d.get("properties") or {}).get("exceededTransferLimit"))
    for f in got:
      if fmt == "geojson":
        gj, props = f.get("geometry"), f.get("properties") or {}
      else:
        gj, props = esri_json_to_geojson(f.get("geometry")), f.get("attributes") or {}
      feats.append({"properties": props, "geometry": shape(gj) if gj else None})
    offset += len(got)
    if not got or (len(got) < page and not exceeded):
      break
    time.sleep(delay)
  if len(feats) != total:
    raise RuntimeError(f"{url}: paged {len(feats)} features but the layer counts {total}")
  expected = src.get("expected_count")
  if expected and expected != total:
    log.warning("%s: expected %s features, the layer now has %s", url, expected, total)
  return SourceResult(
    features=feats, fields=fields, source_url=url, item_id=src.get("item_id", ""), component=src.get("component"),
    data_last_edit=ms_to_iso((meta.get("editingInfo") or {}).get("dataLastEditDate")), retrieved=now_iso(),
    record_count=total, checksum=h.hexdigest(),
    extra={**item_meta(s, src.get("item_id", "")), "copyright_text": meta.get("copyrightText") or None})


# shapefile in a zip ------------------------------------------------------------------------------------------------

def head_info(url: str, s: requests.Session | None = None) -> dict:
  """HTTP validators of a static download: {etag, last_modified, content_length} (any may be None).

  a streamed GET that is closed before the body is read, not HEAD: NOAA redirects to a pre-signed S3 URL that is
  valid for GET only (HEAD on it returns 403).
  """
  s = s or session()
  with s.get(url, stream=True, allow_redirects=True, timeout=60) as r:
    r.raise_for_status()
    h = r.headers
    return {"etag": h.get("ETag"), "last_modified": h.get("Last-Modified"),
            "content_length": int(h["Content-Length"]) if h.get("Content-Length") else None}


def download(url: str, dest_dir: Path, s: requests.Session | None = None) -> Path:
  """stream a file into dest_dir (a directory made for this one download); skip when the size already matches."""
  s = s or session()
  dest_dir.mkdir(parents=True, exist_ok=True)
  dest = dest_dir / Path(url).name
  info = head_info(url, s)
  if dest.exists() and info["content_length"] and dest.stat().st_size == info["content_length"]:
    return dest
  with s.get(url, stream=True, timeout=300) as r:
    r.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as fh:
      for chunk in r.iter_content(1 << 20):
        fh.write(chunk)
    tmp.replace(dest)
  return dest


def extract_stem(zip_path: Path, out_dir: Path, stem: str) -> tuple[Path, dt.date]:
  """extract only <stem>.shp/.shx/.dbf/.prj/.cpg from a zip into out_dir (member paths are ignored: no zip-slip).

  returns the .shp path and the newest member date (the shapefile's own date, since the zip has no edit date).
  """
  out_dir.mkdir(parents=True, exist_ok=True)
  newest = dt.datetime(1980, 1, 1)
  with zipfile.ZipFile(zip_path) as z:
    for info in z.infolist():
      p = Path(info.filename)
      if info.is_dir() or p.stem.lower() != stem.lower() or p.suffix.lower() not in SHP_SIDECARS:
        continue
      (out_dir / f"{stem}{p.suffix.lower()}").write_bytes(z.read(info))
      newest = max(newest, dt.datetime(*info.date_time))
  shp = out_dir / f"{stem}.shp"
  if not shp.exists():
    raise FileNotFoundError(f"{zip_path} has no {stem}.shp")
  return shp, newest.date()


def read_shapefile(shp: Path, segmentize_m: float | None = None) -> tuple[list[dict], list[dict]]:
  """shapefile -> (features, fields); geometries reprojected to EPSG:4326 (densified first when segmentize_m is set,
  so straight projected edges stay faithful)."""
  import pyogrio.raw
  import pyproj

  meta, _, geoms, field_data = pyogrio.raw.read(str(shp))
  if not meta.get("crs"):
    raise ValueError(f"{shp}: no CRS (.prj missing)")
  src_crs = pyproj.CRS.from_user_input(meta["crs"])
  tr = pyproj.Transformer.from_crs(src_crs, 4326, always_xy=True)
  g = shapely.from_wkb(geoms)
  g = shapely.force_2d(g)
  if segmentize_m and src_crs.is_projected:
    g = shapely.segmentize(g, segmentize_m)
  g = shapely.transform(g, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))
  fields, cols = [], {}
  for name, arr in zip(meta["fields"], field_data):
    kind = arr.dtype.kind
    typ = "int" if kind in "iu" else "float" if kind == "f" else "date" if kind == "M" else "string"
    fields.append({"name": name, "type": typ})
    cols[name] = arr
  feats = []
  for i, geom in enumerate(g):
    props = {}
    for name, arr in cols.items():
      v = arr[i]
      if isinstance(v, np.generic):
        v = v.item()
      if isinstance(v, float) and np.isnan(v):
        v = None
      if isinstance(v, np.datetime64):
        v = None
      props[name] = v
    feats.append({"properties": props, "geometry": geom})
  return feats, fields


def fetch_shapefile_zip(src: dict, cache_dir: Path, s: requests.Session | None = None) -> SourceResult:
  """download the zip into <cache_dir>/zip (its own directory), extract only <member_stem>.* into <cache_dir>/shp."""
  s = s or session()
  url, stem = src["url"], src["member_stem"]
  head = head_info(url, s)
  zip_path = download(url, cache_dir / "zip", s)
  shp, shp_date = extract_stem(zip_path, cache_dir / "shp", stem)
  feats, fields = read_shapefile(shp, src.get("segmentize_m"))
  h = hashlib.sha256()
  for ext in sorted(SHP_SIDECARS):
    f = shp.with_suffix(ext)
    if f.exists():
      h.update(f.read_bytes())
  return SourceResult(
    features=feats, fields=fields, source_url=url, item_id=src.get("item_id", ""), component=src.get("component"),
    data_last_edit=shp_date.isoformat() + "T00:00:00Z", retrieved=now_iso(), record_count=len(feats),
    checksum=h.hexdigest(), extra={"http": head, "zip_bytes": zip_path.stat().st_size})


def probe_shapefile_zip(s, src: dict) -> dict:
  """change token for a static download: the HTTP validators (no edit date is served)."""
  return {"data_last_edit": None, "record_count": None, **head_info(src["url"], s)}


def raw_signature(obj) -> str:
  return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()
