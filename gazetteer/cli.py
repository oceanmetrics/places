"""command line: build | detect | check."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .config import load_all
from .pipeline import build_layer, detect, next_version
from .validate import check_parquet, check_pmtiles

ROOT = Path(__file__).resolve().parent.parent  # the repo root
PUBLISHED = "https://storage.oceanmetrics.io/gazetteer"


def main(argv: list[str] | None = None) -> int:
  ap = argparse.ArgumentParser(prog="build_gazetteer", description=__doc__)
  sub = ap.add_subparsers(dest="cmd", required=True)
  for name in ("build", "detect", "check", "next-version"):
    p = sub.add_parser(name)
    p.add_argument("--slug", action="append", help="only this collection (repeatable); default every one")
    p.add_argument("--sources", type=Path, default=ROOT / "sources")
    p.add_argument("--staging", type=Path, default=ROOT / "catalog" / "staging")
    if name == "build":
      p.add_argument("--cache", type=Path, default=ROOT / "cache")
      p.add_argument("--version", help="release version written into every row (default: the config's)")
      p.add_argument("--delay", type=float, default=0.5, help="seconds between page requests")
    if name in ("detect", "next-version"):
      p.add_argument("--published-base", default=PUBLISHED)
    if name == "detect":
      p.add_argument("--json-out", type=Path, help="write [{slug, changed, reason}] here")
  a = ap.parse_args(argv)
  logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
  cfgs = load_all(a.sources)
  slugs = a.slug or list(cfgs)
  unknown = [s for s in slugs if s not in cfgs]
  if unknown:
    ap.error(f"unknown slug(s) {unknown}; have {list(cfgs)}")
  if a.cmd == "build":
    for slug in slugs:
      print(json.dumps(build_layer(cfgs[slug], a.staging, a.cache, a.version, a.delay)))
    return 0
  if a.cmd == "detect":
    res = [detect(cfgs[s], a.published_base) for s in slugs]
    for r in res:
      print(json.dumps(r))
    if a.json_out:
      a.json_out.write_text(json.dumps(res, indent=2))
    return 0
  if a.cmd == "next-version":
    for slug in slugs:
      print(next_version(cfgs[slug], a.published_base))
    return 0
  bad = 0
  for slug in slugs:
    d = a.staging / slug
    if not (d / "places.parquet").exists() and not (d / "places.pmtiles").exists():
      # nothing staged for this collection: fine for a bare checkout, an error when it was asked for by name
      print(slug, f"not built (no {d}); run `uv run build.py build --slug {slug}`")
      bad += bool(a.slug)
      continue
    problems = check_parquet(d / "places.parquet", cfgs[slug]) + check_pmtiles(d / "places.pmtiles", slug)
    print(slug, "OK" if not problems else problems)
    bad += bool(problems)
  return 1 if bad else 0


if __name__ == "__main__":
  sys.exit(main())
