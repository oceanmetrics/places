"""fetch a layer from an OGC WFS 2.0 GeoServer (Marine Regions product layers at geo.vliz.be) as GeoJSON in EPSG:4326.

kind `wfs` in a source config. one request per page (startIndex / count, sorted by a stable key), serial and polite.
the layer carries no edit date, so change detection uses the layer title in GetCapabilities (it names the product
version, e.g. "Exclusive Economic Zones (200 NM) (v12, world, 2023)") plus the feature count, stored as the `http.etag`
token the shapefile kind already uses. every feature also gets the Marine Regions provenance columns (`mrgid`,
`mrgid_uri`, `mr_product`, `mr_product_version`, `mr_product_doi`, `mr_license`, `mr_modified`) and, when two features
share an MRGID, a deterministic `mr_part` suffix so place_id stays unique.
"""
from __future__ import annotations

import hashlib
import logging
import re
import time
from pathlib import Path

import requests
from shapely.geometry import shape

from . import fetch
from .fetch import SourceResult, now_iso
from .ids import suffix_duplicates

log = logging.getLogger(__name__)

WFS_URL = "https://geo.vliz.be/geoserver/MarineRegions/wfs"
MR_FIELDS = [("mrgid", "int"), ("mrgid_uri", "string"), ("mr_product", "string"), ("mr_product_version", "string"),
             ("mr_product_doi", "string"), ("mr_license", "string"), ("mr_modified", "date"), ("mr_part", "string")]


def mrgid_uri(mrgid) -> str:
  """the canonical Marine Regions URI of a record."""
  return f"http://marineregions.org/mrgid/{int(mrgid)}"


def wfs_params(src: dict, **extra) -> dict:
  return {"service": "WFS", "version": "2.0.0", "typeNames": src["type_name"], **extra}


def wfs_hits(s: requests.Session, src: dict) -> int:
  """number of features the layer holds now (resultType=hits)."""
  r = fetch.get(s, src.get("wfs_url", WFS_URL), wfs_params(src, request="GetFeature", resultType="hits"))
  m = re.search(r'numberMatched="(\d+)"', r.text)
  if not m:
    raise RuntimeError(f"{src['type_name']}: no numberMatched in the WFS hits response")
  return int(m.group(1))


def layer_title(s: requests.Session, src: dict) -> str | None:
  """the layer's <Title> from GetCapabilities (it names the product version); None when it is not listed."""
  r = fetch.get(s, src.get("wfs_url", WFS_URL), {"service": "WFS", "version": "2.0.0", "request": "GetCapabilities"})
  for block in re.findall(r"<FeatureType[ >].*?</FeatureType>", r.text, re.S):
    if re.search(rf"<Name>{re.escape(src['type_name'])}</Name>", block):
      m = re.search(r"<Title>(.*?)</Title>", block, re.S)
      return m.group(1).strip() if m else None
  return None


def probe_wfs(s: requests.Session, src: dict) -> dict:
  """cheap change token: the layer title (product version) and feature count, in the `etag` slot of the http record."""
  n = wfs_hits(s, src)
  return {"data_last_edit": None, "record_count": n, "etag": f"{layer_title(s, src)}|{n}"}


def infer_type(values: list) -> str:
  """int | float | string from the non-null values of one native attribute (all-null stays string)."""
  vals = [v for v in values if v is not None]
  if vals and all(isinstance(v, int) and not isinstance(v, bool) for v in vals):
    return "int"
  if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
    return "float"
  return "string"


def assign_parts(mrgids: list[int], labels: list[str]) -> list[str]:
  """'' for the first feature of an MRGID (in source order), ':<label>[-n]' for the others, from ids.suffix_duplicates."""
  base = [f"MRGID:{m}" for m in mrgids]
  full = suffix_duplicates(base, labels, list(range(len(base))))
  return [f[len(b):] for f, b in zip(full, base)]


def resolve_mrgid(props: dict, spec: dict) -> int:
  """the feature's MRGID from a native field (`field`, maybe a string) or, for a layer without one, a name lookup (`map`)."""
  v = props.get(spec.get("field", "mrgid"))
  if spec.get("map"):
    key = props.get(spec["lookup_field"])
    if key not in spec["map"]:
      raise ValueError(f"no MRGID configured for {spec['lookup_field']}={key!r}")
    v = spec["map"][key]
  if v in (None, ""):
    raise ValueError(f"feature without an MRGID: {props}")
  return int(v)


def annotate(features: list[dict], src: dict) -> list[dict]:
  """add mrgid + the mr_* provenance attributes to every feature's properties (in place); returns the field defs."""
  prod = src["mr"]
  spec = src.get("mrgid") or {"field": "mrgid"}
  ids = [resolve_mrgid(f["properties"], spec) for f in features]
  label_field = src.get("part_label_field")
  labels = [("buffer" if str(f["properties"].get(label_field)).lower() == "true" else "part") if label_field else "part"
            for f in features]
  parts = assign_parts(ids, labels)
  modified = f"{prod['released']}T00:00:00Z"
  mr_names = {n for n, _ in MR_FIELDS}
  natives = [k for k in (features[0]["properties"] if features else {}) if k not in mr_names]
  fields = [{"name": k, "type": infer_type([f["properties"].get(k) for f in features])} for k in natives]
  for f, m, part in zip(features, ids, parts):
    f["properties"].update({
      "mrgid": m, "mrgid_uri": mrgid_uri(m), "mr_product": prod["product"], "mr_product_version": prod["version"],
      "mr_product_doi": prod["doi"], "mr_license": prod["license"], "mr_modified": modified, "mr_part": part})
  # a native `mrgid` (int or string) is replaced by the integer one, which leads the mr fields
  return [{"name": n, "type": t} for n, t in MR_FIELDS] + fields


def fetch_wfs(src: dict, delay: float = 1.0, raw_dir: Path | None = None, s: requests.Session | None = None) -> SourceResult:
  """page through a WFS layer as GeoJSON (EPSG:4326, lon/lat) and annotate it; fails when the paged count is off."""
  s = s or fetch.session()
  url = src.get("wfs_url", WFS_URL)
  total = wfs_hits(s, src)
  title = layer_title(s, src)
  page = int(src.get("page_size") or 25)
  feats, start, h = [], 0, hashlib.sha256()
  while start < total:
    params = wfs_params(src, request="GetFeature", outputFormat="application/json", srsName="EPSG:4326",
                        sortBy=src.get("sort_by", "mrgid"), startIndex=start, count=page)
    r = fetch.get(s, url, params, tries=5)
    h.update(r.content)
    got = r.json().get("features", [])
    if not got:
      break
    for f in got:
      feats.append({"properties": f.get("properties") or {}, "geometry": shape(f["geometry"]) if f.get("geometry") else None})
    start += len(got)
    log.info("%s: %d / %d", src["type_name"], len(feats), total)
    time.sleep(delay)
  if len(feats) != total:
    raise RuntimeError(f"{src['type_name']}: paged {len(feats)} features but the layer counts {total}")
  expected = src.get("expected_count")
  if expected and expected != total:
    log.warning("%s: expected %s features, the layer now has %s", src["type_name"], expected, total)
  fields = annotate(feats, src)
  return SourceResult(
    features=feats, fields=fields, source_url=url + f"?typeNames={src['type_name']}", item_id=src["type_name"],
    component=src.get("component"), data_last_edit=f"{src['mr']['released']}T00:00:00Z", retrieved=now_iso(),
    record_count=total, checksum=h.hexdigest(),
    extra={"http": {"etag": f"{title}|{total}", "last_modified": None, "content_length": None}, "wfs_layer_title": title})
