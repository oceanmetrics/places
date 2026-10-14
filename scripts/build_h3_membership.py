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

  uv run scripts/build_h3_membership.py [--slug noaa_sanctuaries ...] [--out catalog/h3] [--workers N] [--upload]

--upload syncs each <out>/<slug>/h3/ to s3://oceanmetrics.io-public/gazetteer/<slug>/h3/ (no --delete), membership.json
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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import importlib.util

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gazetteer import membership as m  # noqa: E402

BASE_DIRECT = "https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/"
S3 = "s3://oceanmetrics.io-public/gazetteer"


def get(url: str) -> bytes:
  req = urllib.request.Request(url, headers={"User-Agent": "oceanmetrics-places/h3-membership"})
  with urllib.request.urlopen(req, timeout=300) as r:
    return r.read()


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
  tables = m.collection_membership(t, res_max, workers=workers)
  if not any(tb.num_rows for tb in tables.values()):
    return None
  extra = {"slug": row["slug"], "collection_version": row.get("version"), "places_sha256": row["parquet_sha256"],
           "built": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "seconds": round(time.time() - t0, 1),
           "places": len({p for tb in tables.values() for p in tb.column("place_id").to_pylist()})}
  return m.write_membership(tables, out / row["slug"], version=row.get("version") or "", extra=extra)


def attach_published(lj: dict, out: Path) -> dict:
  """the published layers.json with `h3` set from the local membership builds (nothing else changes)."""
  spec = importlib.util.spec_from_file_location("build_layers_json", ROOT / "scripts" / "build_layers_json.py")
  bl = importlib.util.module_from_spec(spec)
  spec.loader.exec_module(bl)
  mans = bl.h3_manifests([r["slug"] for r in lj["layers"]], out, lj.get("base", bl.BASE))
  return {**lj, "layers": bl.attach_h3(lj["layers"], mans, lj.get("base", bl.BASE))}


def upload(slug: str, out: Path) -> None:
  d = out / slug / "h3"
  subprocess.run(["aws", "s3", "sync", str(d), f"{S3}/{slug}/h3/", "--exclude", "membership.json"], check=True)
  subprocess.run(["aws", "s3", "cp", str(d / "membership.json"), f"{S3}/{slug}/h3/membership.json",
                  "--content-type", "application/json"], check=True)


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--slug", action="append", help="collection slug (repeatable); default every layer with a parquet")
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
    missing = set(a.slug) - {r["slug"] for r in rows}
    if missing:
      raise SystemExit(f"not in {a.layers} (or no parquet): {sorted(missing)}")
    rows = [r for r in rows if r["slug"] in a.slug]
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
      for key in ("index/layers.json", "layers.json"):
        subprocess.run(["aws", "s3", "cp", str(lo), f"{S3}/{key}", "--content-type", "application/json",
                        "--cache-control", "no-cache"], check=True)
  return 0


if __name__ == "__main__":
  sys.exit(main())
