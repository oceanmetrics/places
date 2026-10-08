#!/usr/bin/env python3
"""build layers.json, the manifest the apps read (CalCOFI explore spatial_layers, atlas boot.json units).

standalone (stdlib only): merges two sources of truth, local staged builds win over published ones.
  (a) catalog/staging/*/collection.json   (fresh, not yet published builds)
  (b) <base>/catalog.json -> each child collection.json, plus versions.json for the current version
a collection is a map layer when it carries a PMTiles asset. either source may be absent.

  python scripts/build_layers_json.py [--out catalog/staging/layers.json] [--no-remote] [--no-local]
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://storage.oceanmetrics.io/gazetteer/"
SCHEMA = 1

# default paint per geometry kind (MapLibre paint properties), overridden by a collection's styles/default.json ----
PAINT = {
  "polygon": {
    "fill": {"fill-color": "#e08a1e", "fill-opacity": 0.45},
    "line": {"line-color": "#a85f00", "line-width": 1},
  },
  "line": {
    "line": {"line-color": "#a85f00", "line-width": 1.5},
  },
  "point": {
    "circle": {"circle-color": "#e08a1e", "circle-radius": 4, "circle-stroke-color": "#ffffff", "circle-stroke-width": 1},
  },
}
LICENSE_URLS = {
  "CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/",
  "CC-BY-SA-4.0": "https://creativecommons.org/licenses/by-sa/4.0/",
  "CC0-1.0": "https://creativecommons.org/publicdomain/zero/1.0/",
  "CC-PDDC": "https://www.usa.gov/publicdomain/label/1.0/",
}


# helpers ----
def geom_kind(geom_type: str | list | None) -> str:
  """point | line | polygon, or `mixed` for a collection holding several kinds (geoparquet:geometry_type is then a list)."""
  kinds = {geom_kind(g) for g in geom_type} if isinstance(geom_type, (list, tuple)) else None
  if kinds is not None:
    return kinds.pop() if len(kinds) == 1 else "mixed" if kinds else "polygon"
  g = (geom_type or "").lower()
  return "point" if "point" in g else "line" if "line" in g else "polygon"


def pmtiles_url(slug: str, base: str = BASE) -> str:
  return f"{base.rstrip('/')}/{slug}/places.pmtiles"


def has_pmtiles(coll: dict) -> bool:
  if any(a.get("type") == "application/vnd.pmtiles" for a in (coll.get("assets") or {}).values()):
    return True
  return any(l.get("rel") == "pmtiles" for l in coll.get("links") or [])


def squash(s: str | None) -> str:
  return " ".join((s or "").split())


def default_paint(kind: str, style: dict | None = None) -> dict:
  """per-geometry defaults, with the paint of any fill/line/circle layer in the collection's default style on top."""
  kinds = ["polygon", "line", "point"] if kind == "mixed" else [kind]
  paint = {k: dict(v) for knd in kinds for k, v in PAINT[knd].items()}
  if kind == "mixed":  # one entry per drawn layer type; the polygon outline wins over the line default
    paint["line"] = dict(PAINT["polygon"]["line"])
  for lyr in (style or {}).get("layers", []):
    t = lyr.get("type")
    if t in ("fill", "line", "circle") and isinstance(lyr.get("paint"), dict):
      paint.setdefault(t, {}).update(lyr["paint"])
  return paint


def providers_of(coll: dict) -> list[dict]:
  return [p for p in coll.get("providers") or [] if p.get("name")]


def attribution_text(coll: dict) -> str:
  txt = squash(coll.get("gazetteer:attribution"))
  if txt:
    return txt
  names = [p["name"] for p in providers_of(coll) if "producer" in p.get("roles", []) or "licensor" in p.get("roles", [])]
  names = list(dict.fromkeys(names))
  return (", ".join(names) + ". " if names else "") + "Processed by Ocean Metrics."


def attribution_html(coll: dict) -> str:
  """the attribution line as safe HTML, each provider name found in the text linked to its url."""
  txt = html.escape(attribution_text(coll), quote=False)
  for p in sorted(providers_of(coll), key=lambda p: -len(p["name"])):
    if not p.get("url"):
      continue
    name = html.escape(p["name"], quote=False)
    if name in txt and f">{name}<" not in txt:
      txt = txt.replace(name, f'<a href="{html.escape(p["url"], quote=True)}">{name}</a>', 1)
  return txt


def license_url(coll: dict) -> str | None:
  for l in coll.get("links") or []:
    if l.get("rel") == "license" and l.get("href"):
      return l["href"]
  return LICENSE_URLS.get(coll.get("license") or "")


def citation(coll: dict, slug: str, version: str | None, updated: str | None, base: str) -> str:
  if coll.get("citation"):
    return squash(coll["citation"])
  year = (updated or "")[:4] or str(datetime.now(timezone.utc).year)
  v = f", v{version}" if version else ""
  return f"{attribution_text(coll)} {coll.get('title') or slug}{v}. Ocean Metrics gazetteer, {year}. {base.rstrip('/')}/{slug}/"


def layer_row(coll: dict, style: dict | None = None, version: str | None = None, base: str = BASE) -> dict:
  """the manifest row for one STAC collection (pure: no I/O)."""
  slug = coll["id"]
  geom_type = coll.get("geoparquet:geometry_type") or "MultiPolygon"
  n = coll.get("geoparquet:feature_count", coll.get("table:row_count"))
  ver = coll.get("version") or (coll.get("gazetteer:provenance") or {}).get("version") or version
  layers = coll.get("pmtiles:layers") or []
  updated = coll.get("updated")
  return {
    "slug"            : slug,
    "title"           : coll.get("title") or slug,
    "collection"      : slug,
    "pmtiles"         : pmtiles_url(slug, base),
    "source_layer"    : layers[0] if layers else slug,
    "geom_type"       : geom_type if isinstance(geom_type, str) else geom_type[0] if len(geom_type) == 1 else "Mixed",
    "n"               : n,
    "updated"         : updated,
    "version"         : ver,
    "paint"           : default_paint(geom_kind(geom_type), style),
    "authority"       : coll.get("gazetteer:authority"),
    "place_type"      : coll.get("gazetteer:place_type"),
    "bbox"            : (((coll.get("extent") or {}).get("spatial") or {}).get("bbox") or [None])[0],
    "attribution"     : attribution_text(coll),
    "attribution_html": attribution_html(coll),
    "license"         : coll.get("license"),
    "license_url"     : license_url(coll),
    "citation"        : citation(coll, slug, ver, updated, base),
  }


def merge_rows(published: list[dict], local: list[dict]) -> list[dict]:
  """one row per slug, a local staged build replacing the published one; sorted by slug."""
  by = {r["slug"]: r for r in published}
  by.update({r["slug"]: r for r in local})
  return [by[k] for k in sorted(by)]


def manifest(rows: list[dict], base: str = BASE, generated: str | None = None) -> dict:
  return {"schema": SCHEMA, "generated": generated or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
          "base": base, "layers": rows}


# sources ----
def local_rows(staging: Path, base: str = BASE) -> list[dict]:
  rows = []
  for f in sorted(staging.glob("*/collection.json")):
    coll = json.loads(f.read_text())
    if not has_pmtiles(coll):
      continue
    style_f = f.parent / "styles" / "default.json"
    style = json.loads(style_f.read_text()) if style_f.exists() else None
    rows.append(layer_row(coll, style, base=base))
  return rows


def get_json(url: str, timeout: int = 60):
  req = urllib.request.Request(url, headers={"User-Agent": "oceanmetrics-places/layers-json"})
  with urllib.request.urlopen(req, timeout=timeout) as r:
    return json.load(r)


def remote_rows(base: str = BASE, fetch=get_json) -> list[dict]:
  """rows for the collections in the published catalog; [] (with a warning) when it is unreachable."""
  try:
    cat = fetch(urljoin(base, "catalog.json"))
  except (urllib.error.URLError, OSError, ValueError) as e:
    print(f"warning: published catalog unreachable ({e}); remote layers skipped", file=sys.stderr)
    return []
  try:
    versions = (fetch(urljoin(base, "versions.json")).get("collections") or {})
  except (urllib.error.URLError, OSError, ValueError):
    versions = {}
  hrefs = [urljoin(base, l["href"]) for l in cat.get("links", []) if l.get("rel") == "child"]

  def one(href: str):
    try:
      coll = fetch(href)
    except (urllib.error.URLError, OSError, ValueError) as e:
      print(f"warning: {href}: {e}", file=sys.stderr)
      return None
    if not has_pmtiles(coll):
      return None
    style = None
    ref = (coll.get("assets") or {}).get("styles/default")
    if ref and ref.get("href"):
      try:
        style = fetch(urljoin(href, ref["href"]))
      except (urllib.error.URLError, OSError, ValueError):
        pass
    return layer_row(coll, style, version=(versions.get(coll["id"]) or {}).get("current_version"), base=base)

  with ThreadPoolExecutor(8) as ex:
    return [r for r in ex.map(one, hrefs) if r]


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--out", default=str(ROOT / "catalog" / "staging" / "layers.json"))
  ap.add_argument("--staging", default=str(ROOT / "catalog" / "staging"))
  ap.add_argument("--base", default=BASE, help="published catalog base URL")
  ap.add_argument("--no-remote", action="store_true")
  ap.add_argument("--no-local", action="store_true")
  a = ap.parse_args(argv)
  staging = Path(a.staging)
  loc = [] if a.no_local or not staging.is_dir() else local_rows(staging, a.base)
  rem = [] if a.no_remote else remote_rows(a.base)
  rows = merge_rows(rem, loc)
  out = Path(a.out)
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(json.dumps(manifest(rows, a.base), indent=2, ensure_ascii=False) + "\n")
  print(f"wrote {out}: {len(rows)} layers ({len(rem)} published, {len(loc)} local staged)")
  return 0


if __name__ == "__main__":
  sys.exit(main())
