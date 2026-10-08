"""build one collection end to end (fetch -> normalise -> GeoParquet -> PMTiles -> STAC) and detect source changes."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

import pyarrow.parquet as pq
import requests

from . import fetch, stac, tiles
from .fetch import SourceResult
from .table import build_rows, to_table, write_geoparquet
from .validate import check_parquet, check_pmtiles

log = logging.getLogger(__name__)


def fetch_source(src: dict, cache: Path, delay: float = 0.5, s=None) -> SourceResult:
  """fetch one configured source (ArcGIS layer or zipped shapefile) into the cache directory."""
  if src["kind"] == "arcgis":
    return fetch.fetch_arcgis(src, delay=delay, raw_dir=cache / "raw" / (src.get("component") or "layer"), s=s)
  if src["kind"] == "shapefile_zip":
    return fetch.fetch_shapefile_zip(src, cache, s=s)
  raise ValueError(f"unknown source kind {src['kind']}")


def provenance_record(cfg: dict, results: list[SourceResult], rows: int, dropped: list[str], version: str, now: str) -> dict:
  """per-layer provenance: source url, item id, data last edit, retrieval time, record count, payload checksum."""
  return {
    "slug": cfg["slug"], "version": version, "built": now, "record_count": rows,
    "sources": [{"source_url": r.source_url, "source_item_id": r.item_id, "component": r.component,
                 "data_last_edit": r.data_last_edit, "retrieved": r.retrieved, "record_count": r.record_count,
                 "checksum": r.checksum, **{k: v for k, v in r.extra.items() if v not in (None, "")}} for r in results],
    "dropped": dropped,
  }


def build_layer(cfg: dict, staging: Path, cache: Path, version: str | None = None, delay: float = 0.5) -> dict:
  """fetch, normalise and write catalog/staging/<slug>/; returns a summary dict. raises on any failed check."""
  slug = cfg["slug"]
  version = version or cfg["version"]
  out = staging / slug
  if out.exists():
    shutil.rmtree(out)
  (out / "styles").mkdir(parents=True)
  s = fetch.session()
  results = [fetch_source(src, cache / slug, delay, s) for src in cfg["sources"]]
  now = fetch.now_iso()
  rows, fields, dropped = build_rows(cfg, results, version)
  table = to_table(rows, fields)
  prov = provenance_record(cfg, results, len(rows), dropped, version, now)
  geo = write_geoparquet(table, out / "places.parquet", prov)
  tiles.build_pmtiles(out / "places.parquet", out / "places.pmtiles", slug, cfg["title"],
                      cfg["description"], cfg["attribution"], cfg.get("tile_properties"))
  header, _ = tiles.read_pmtiles(out / "places.pmtiles")
  (out / "styles" / "default.json").write_text(json.dumps(stac.style_json(slug, header["max_zoom"]), indent=2) + "\n")
  (out / "provenance.json").write_text(json.dumps(prov, indent=2, default=str) + "\n")
  (out / "AGENTS.md").write_text(stac.agents(cfg))
  # the README lists the asset sizes, so write a placeholder first, build the collection, then fill it in
  (out / "README.md").write_text("")
  coll = stac.build_collection(cfg, table, geo, prov, out, header, now, {})
  (out / "README.md").write_text(stac.readme(cfg, table, prov, coll, version))
  coll = stac.build_collection(cfg, table, geo, prov, out, header, now, {})
  (out / "collection.json").write_text(json.dumps(coll, indent=2, default=str) + "\n")
  problems = check_parquet(out / "places.parquet", cfg) + check_pmtiles(out / "places.pmtiles", slug)
  if problems:
    raise RuntimeError(f"{slug}: " + "; ".join(problems))
  return {"slug": slug, "features": table.num_rows, "parquet_bytes": (out / "places.parquet").stat().st_size,
          "pmtiles_bytes": (out / "places.pmtiles").stat().st_size, "license": cfg["license"],
          "dropped": dropped, "max_zoom": header["max_zoom"]}


def published_provenance(base_url: str, slug: str, s=None) -> dict | None:
  """the provenance.json published for a collection, or None when it is not published (yet)."""
  s = s or fetch.session()
  r = s.get(f"{base_url.rstrip('/')}/{slug}/provenance.json", timeout=60)
  if r.status_code in (403, 404):
    return None
  r.raise_for_status()
  return r.json()


def changed_sources(cfg: dict, published: dict | None, probes: list[dict]) -> str | None:
  """None when every source matches the published record, else a short reason.

  per source: a served data_last_edit and the record count are compared; static downloads compare the HTTP
  validators (ETag / Last-Modified / Content-Length); a layer that serves no edit date is re-fetched (small) and
  compared on its payload checksum, which the caller puts in probe['checksum'].
  """
  if published is None:
    return "not published yet"
  old = published.get("sources", [])
  if len(old) != len(probes):
    return "source list changed"
  for o, p in zip(old, probes):
    if p.get("data_last_edit") is not None:
      if o.get("data_last_edit") != p["data_last_edit"]:
        return f"data_last_edit {o.get('data_last_edit')} -> {p['data_last_edit']}"
      if o.get("record_count") != p.get("record_count"):
        return f"record_count {o.get('record_count')} -> {p.get('record_count')}"
    elif "checksum" in p:
      if o.get("checksum") != p["checksum"]:
        return "payload checksum changed"
    else:
      oh = o.get("http") or {}
      for k in ("etag", "last_modified", "content_length"):
        if p.get(k) and oh.get(k) != p[k]:
          return f"download {k} {oh.get(k)} -> {p[k]}"
  return None


def detect(cfg: dict, base_url: str, s=None) -> dict:
  """{'slug', 'changed', 'reason'} by comparing the sources' change tokens with the published provenance."""
  s = s or fetch.session()
  published = published_provenance(base_url, cfg["slug"], s)
  probes = []
  for src in cfg["sources"]:
    if src["kind"] == "arcgis":
      p = fetch.probe_arcgis(s, src)
      if p["data_last_edit"] is None:               # no edit date served: compare the payload itself
        p["checksum"] = fetch.fetch_arcgis(src, s=s).checksum
      probes.append(p)
    else:
      probes.append(fetch.probe_shapefile_zip(s, src))
  reason = changed_sources(cfg, published, probes)
  return {"slug": cfg["slug"], "changed": reason is not None, "reason": reason or "unchanged"}


def bump_patch(version: str) -> str:
  """'1.0.3' -> '1.0.4' (the sync workflow's version for a rebuilt collection)."""
  major, minor, patch = (int(x) for x in version.split("."))
  return f"{major}.{minor}.{patch + 1}"


def next_version(cfg: dict, base_url: str, s=None) -> str:
  """the published current_version of the collection with its patch number bumped, or the config's version when
  the collection is not in the published versions.json yet."""
  s = s or fetch.session()
  r = s.get(f"{base_url.rstrip('/')}/versions.json", timeout=60)
  if r.status_code in (403, 404):
    return cfg["version"]
  r.raise_for_status()
  cur = (r.json().get("collections", {}).get(cfg["slug"]) or {}).get("current_version")
  return bump_patch(cur) if cur else cfg["version"]
