#!/usr/bin/env python3
"""build each polygon collection's place x H3 membership (gazetteer/membership.py) from its PUBLISHED places.parquet.

for every layer in the published layers.json that has a places.parquet (or the --slug ones): download it from the
bucket host, check its sha256 against the manifest's parquet_sha256, and write

  <out>/<slug>/h3/res=<1..5>/membership.parquet
  <out>/<slug>/h3/res=<6|7>/p=<parent>/membership.parquet     (split by the res-2 / res-3 parent)
  <out>/<slug>/h3/membership.json                              (files, rows, bytes, and what it was built from)

membership.json carries `places_sha256` and `collection_version`: build_layers_json.py advertises a layer's `h3` only
while that sha256 is the layer's parquet_sha256, so a collection rebuilt without its membership is never matched to
stale cells. the membership is a derived sidecar, not a STAC asset (adding it changes no collection version).
a collection without polygons (points, lines) gets no membership.

  uv run scripts/build_h3_membership.py [--slug noaa_sanctuaries ...] [--missing] [--out catalog/h3] [--workers N] [--upload]

--missing adds every polygon vector layer (kind vector, geom_type Polygon / MultiPolygon, with a parquet) whose
<slug>/h3/membership.json is absent from the bucket or was built from another parquet than the row's parquet_sha256
(`missing_slugs`), so the invariant "a polygon vector row has h3" holds after each sync, not only for the slugs it rebuilt.
With --missing and no --slug only those are built; with neither, every layer with a parquet is.

--upload publishes each <out>/<slug>/h3/ to gazetteer/<slug>/h3/ of the bucket through oceanmetrics/platform
scripts/om-publish.sh (both stores, R2 then S3; never deletes; OM_PUBLISH or a platform checkout beside this repo), membership.json
last. --layers-out writes the PUBLISHED layers.json unchanged but for each row's `h3` (build_layers_json.attach_h3,
from every <out>/*/h3/membership.json), so advertising the membership rebuilds nothing else; with --upload it goes to
index/layers.json and the root layers.json, after the collections' h3/ files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import importlib.util

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gazetteer import membership as m  # noqa: E402

BASE_DIRECT = "https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/"
PREFIX = "gazetteer"     # the prefix in the public bucket (both stores, through om-publish.sh)


def get(url: str) -> bytes:
  req = urllib.request.Request(url, headers={"User-Agent": "oceanmetrics-places/h3-membership"})
  with urllib.request.urlopen(req, timeout=300) as r:
    return r.read()


POLYGONS = ("Polygon", "MultiPolygon")


def is_polygon_layer(row: dict) -> bool:
  """a vector layer of polygons with a published parquet: the rows that must carry an `h3` membership."""
  return (row.get("kind") == "vector" and row.get("geom_type") in POLYGONS
          and bool(row.get("parquet") and row.get("parquet_sha256")))


def missing_slugs(lj: dict, manifests: dict[str, dict | None]) -> list[str]:
  """slugs of the polygon vector layers of a layers.json whose membership is absent (no manifest) or stale
  (its places_sha256 is not the row's parquet_sha256), sorted. `manifests` maps slug -> membership.json (or None)."""
  return sorted(r["slug"] for r in lj["layers"]
                if is_polygon_layer(r) and (manifests.get(r["slug"]) or {}).get("places_sha256") != r["parquet_sha256"])


def published_membership(row: dict, base: str, base_direct: str, fetch=None) -> dict | None:
  """the layer's published h3/membership.json (read from the bucket host), None when there is none (404 / 403)."""
  url = direct(f"{base.rstrip('/')}/{row['slug']}/h3/membership.json", base, base_direct)
  try:
    return json.loads((fetch or get)(url))
  except urllib.error.HTTPError as e:
    if e.code in (403, 404):
      return None
    raise


def direct(url: str, row_base: str, base_direct: str) -> str:
  """the bucket-host form of a storage-host URL (the storage host answers with a 302)."""
  return base_direct + url[len(row_base):] if url.startswith(row_base) else url


def source_parquet(row: dict, base: str, base_direct: str, cache: Path) -> Path:
  """the published places.parquet of a layers.json row, cached by sha256 and checked against it."""
  sha = row["parquet_sha256"]
  f = cache / f"{row['slug']}-{sha[:16]}.parquet"
  if not f.exists():
    cache.mkdir(parents=True, exist_ok=True)
    b = get(direct(row["parquet"], base, base_direct))
    got = hashlib.sha256(b).hexdigest()
    if got != sha:
      raise SystemExit(f"{row['slug']}: places.parquet sha256 {got} != layers.json parquet_sha256 {sha}")
    f.write_bytes(b)
  return f


def build_one(row: dict, src: Path, out: Path, res_max: int = m.RES_MAX, workers: int = 1) -> dict | None:
  t = pq.read_table(src, columns=["place_id", "geometry"])
  t0 = time.time()
  warnings: list = []
  mem = m.compute_membership(t, res_max, workers=workers, warnings=warnings)  # compact: written a partition at a time
  del t
  if not any(mem.rows(r) for r in mem.res):
    return None
  extra = {"slug": row["slug"], "collection_version": row.get("version"), "places_sha256": row["parquet_sha256"],
           "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - t0, 1),
           "places": mem.places(),
           "warnings": warnings}
  return m.write_membership(mem, out / row["slug"], version=row.get("version") or "", extra=extra)


def attach_published(lj: dict, out: Path) -> dict:
  """the published layers.json with `h3` set from the local membership builds (nothing else changes)."""
  spec = importlib.util.spec_from_file_location("build_layers_json", ROOT / "scripts" / "build_layers_json.py")
  bl = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(bl)
  mans = bl.h3_manifests([r["slug"] for r in lj["layers"]], out, lj.get("base", bl.BASE))
  return {**lj, "layers": bl.attach_h3(lj["layers"], mans, lj.get("base", bl.BASE))}


def om_publish_path() -> str:
  """the one publisher of the bucket, oceanmetrics/platform scripts/om-publish.sh: OM_PUBLISH, else a platform checkout
  beside this repo, else ~/Github/oceanmetrics/platform (scripts/om_publish_path.sh is the shell twin)"""
  env = os.environ.get("OM_PUBLISH")
  cands = [Path(env)] if env else [ROOT.parent / "platform" / "scripts" / "om-publish.sh",
                                   Path.home() / "Github" / "oceanmetrics" / "platform" / "scripts" / "om-publish.sh"]
  for c in cands:
    if c.is_file() and os.access(c, os.X_OK):
      return str(c)
  raise SystemExit("om-publish.sh not found (set OM_PUBLISH to oceanmetrics/platform scripts/om-publish.sh)")


def upload(slug: str, out: Path, run=subprocess.run, publisher: str | None = None) -> None:
  """<out>/<slug>/h3/ to gazetteer/<slug>/h3/ on both stores, membership.json last (content types by extension)"""
  run([publisher or om_publish_path(), "--really", "--last", "membership.json", str(out / slug / "h3"),
       f"{PREFIX}/{slug}/h3"], check=True)


def upload_layers(lo: Path, run=subprocess.run, publisher: str | None = None) -> None:
  """the layers.json with `h3` attached to gazetteer/index/ (its previous R2 copy kept under _history/) and gazetteer/"""
  p = publisher or om_publish_path()
  run([p, "--really", "--keep-history", "--cache-control", "no-cache", str(lo), f"{PREFIX}/index", "--as", "layers.json"],
      check=True)
  run([p, "--really", "--cache-control", "no-cache", str(lo), PREFIX, "--as", "layers.json"], check=True)


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--slug", action="append", help="collection slug (repeatable); default every layer with a parquet")
  ap.add_argument("--missing", action="store_true",
                  help="also build every polygon vector layer whose published membership is absent or stale")
  ap.add_argument("--layers", default=BASE_DIRECT + "index/layers.json", help="the published layers.json")
  ap.add_argument("--out", default=str(ROOT / "catalog" / "h3"))
  ap.add_argument("--cache", default=str(ROOT / "cache" / "h3src"))
  ap.add_argument("--res-max", type=int, default=m.RES_MAX)
  ap.add_argument("--workers", type=int, default=os.cpu_count() or 1, help="processes (default: every core)")
  ap.add_argument("--layers-out", help="write the published layers.json with `h3` attached here")
  ap.add_argument("--upload", action="store_true")
  a = ap.parse_args(argv)
  lj = json.loads(get(a.layers))
  base, base_direct = lj.get("base", ""), lj.get("base_direct", BASE_DIRECT)
  rows = [r for r in lj["layers"] if r.get("parquet") and r.get("parquet_sha256")]
  if a.slug:
    absent = set(a.slug) - {r["slug"] for r in rows}
    if absent:
      raise SystemExit(f"not in {a.layers} (or no parquet): {sorted(absent)}")
  if a.slug or a.missing:
    want = set(a.slug or [])
    if a.missing:
      cand = [r for r in rows if is_polygon_layer(r)]
      with ThreadPoolExecutor(8) as ex:
        mans = dict(zip([r["slug"] for r in cand], ex.map(lambda r: published_membership(r, base, base_direct), cand)))
      todo = missing_slugs(lj, mans)
      print(f"--missing: {len(todo)} of {len(cand)} polygon layers: {', '.join(todo) or 'none'}", flush=True)
      want |= set(todo)
    rows = [r for r in rows if r["slug"] in want]
  out = Path(a.out)
  for r in rows:
    src = source_parquet(r, base, base_direct, Path(a.cache))
    man = build_one(r, src, out, a.res_max, a.workers)
    if man is None:
      print(f"{r['slug']}: no polygons, no membership", flush=True)
      continue
    print(f"{r['slug']}: {man['places']} places, {man['rows']:,} rows, {len(man['files'])} files, "
          f"{man['bytes'] / 1e6:.1f} MB, {man['seconds']}s", flush=True)
    if a.upload:
      upload(r["slug"], out)
  if a.layers_out:
    lo = Path(a.layers_out)
    new = attach_published(lj, out)
    lo.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {lo}: {sum(1 for r in new['layers'] if r.get('h3'))} of {len(new['layers'])} layers with h3", flush=True)
    if a.upload:
      upload_layers(lo)
  return 0


if __name__ == "__main__":
  sys.exit(main())
