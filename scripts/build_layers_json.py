#!/usr/bin/env python3
"""build layers.json, the manifest the apps read (CalCOFI explore spatial_layers, atlas boot.json units).

standalone (stdlib only): merges two sources of truth, local staged builds win over published ones.
  (a) catalog/staging/*/collection.json   (fresh, not yet published builds)
  (b) <base>/catalog.json -> each child collection.json, plus versions.json for the current version
a collection is a map layer when it carries a PMTiles asset (`kind: "vector"`) or a `gazetteer:raster` tile source
(`kind: "raster"`: a reference layer drawn from its publisher's own tile service, e.g. Marine Regions' WMTS, with no
parquet or PMTiles of ours; `raster` = {tiles, tile_size, minzoom, maxzoom, link, feature_url, info_url, info_id}: `info_url` (a WMS GetFeatureInfo
template taking `{bbox}`) names the place under a click, `info_id` is its response field; `feature_url` fetches one
place's boundary from the publisher, with the index row's `{source_id}`). either source may be absent.
every row has `source_link` ({href, title}: the source gazetteer or publisher page apps link back to).

URLs: every layer's `pmtiles` is CANONICAL, on the storage host (`base`, https://storage.oceanmetrics.io/gazetteer/):
each request there costs one 302 to the bucket. apps MAY rewrite a `pmtiles` URL onto `base_direct` (the bucket's own
host, https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/, no redirect) by replacing the `base` prefix, until a
redirect-free host lands. the manifest itself is published at <base>index/layers.json (the client falls back to
<base>layers.json).

status and versions (all null when unknown, so an older collection still makes a valid row):
  status / status_history  the layer-level status ({value, date, source, note}) and its ascending events, from the
                           collection's `gazetteer:status` / `gazetteer:status_history` (the source YAML's `layer_status`)
  status_label             "rescinded 2025-07-30": status value ('_' -> ' ') then its date; apps show `title (status_label)`
  created                  date of the collection's FIRST published version (<slug>/versions.json versions[0].created)
  updated                  the current build's timestamp (collection.json `updated`)
  source_date              latest upstream data edit date across the collection's sources (provenance data_last_edit)
  parquet / parquet_sha256 absolute URL of places.parquet and its sha256 at `version` (the ledger entry for that version,
                           else the collection's own file:checksum); consumers pin `version` + `parquet_sha256`
  h3                       absolute URL of <slug>/h3/membership.json, the place x H3 membership (res 1-7, share of each
                           cell inside; scripts/build_h3_membership.py), only while it was built from this row's
                           parquet_sha256; else null

  python scripts/build_layers_json.py [--out catalog/staging/layers.json] [--h3 catalog/h3] [--no-remote] [--no-local]
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
sys.path.insert(0, str(ROOT))
from gazetteer.dedup import search_rank  # noqa: E402
from gazetteer.legacy import legacy_title  # noqa: E402

BASE = "https://storage.oceanmetrics.io/gazetteer/"
BASE_DIRECT = "https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/gazetteer/"   # path-style: the dotted bucket name breaks tls on the virtual-hosted form
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
  "raster": {
    "raster": {"raster-opacity": 0.8},
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


def parquet_asset(coll: dict) -> dict | None:
  """the collection's places.parquet asset (the `places` key, else the first parquet data asset)."""
  assets = coll.get("assets") or {}
  if (assets.get("places") or {}).get("type") == "application/vnd.apache.parquet":
    return assets["places"]
  return next((a for a in assets.values() if a.get("type") == "application/vnd.apache.parquet"
               and str(a.get("href", "")).endswith("places.parquet")), None)


def layer_bbox(coll: dict) -> list[float] | None:
  """the collection extent for fitting a map: a crossing extent (west > east, RFC 7946) is UNWRAPPED, east + 360, so
  [177.8, s, -64.5, n] becomes [177.8, s, 295.5, n]; the same convention as the index bbox."""
  b = (((coll.get("extent") or {}).get("spatial") or {}).get("bbox") or [None])[0]
  if not b:
    return None
  return [b[0], b[1], b[2] + 360, b[3]] if b[0] > b[2] else b


def status_label(status: dict | None) -> str | None:
  """'rescinded 2025-07-30': the value with '_' as space, then the date; None without a status."""
  if not status or not status.get("value"):
    return None
  return " ".join(x for x in (str(status["value"]).replace("_", " "), str(status.get("date") or "")) if x)


def created_date(ledger: dict | None) -> str | None:
  """ISO date of the first published version in a collection's versions.json ledger."""
  vs = (ledger or {}).get("versions") or []
  if not vs:
    return None
  return str(vs[0].get("created") or "")[:10] or None


def parquet_sha256(coll: dict, version: str | None, ledger: dict | None) -> str | None:
  """sha256 (hex) of places.parquet at `version`: the ledger's entry for that version, else the collection's
  file:checksum (a sha2-256 multihash, '1220' + hex)."""
  for v in (ledger or {}).get("versions") or []:
    if version and v.get("version") == version:
      sha = ((v.get("assets") or {}).get("places.parquet") or {}).get("sha256")
      if sha:
        return sha
  mh = str((parquet_asset(coll) or {}).get("file:checksum") or "")
  return mh[4:] if mh.startswith("1220") and len(mh) == 68 else None


def source_date(coll: dict) -> str | None:
  """latest upstream data edit date (ISO date) across the provenance sources; None when no source serves one."""
  days = [str(s.get("data_last_edit"))[:10] for s in (coll.get("gazetteer:provenance") or {}).get("sources") or []
          if s.get("data_last_edit")]
  return max(days) if days else None


def raster_source(coll: dict) -> dict | None:
  """a reference collection's tile source (`gazetteer:raster`), normalised: {tiles, tile_size, minzoom, maxzoom, link}."""
  r = coll.get("gazetteer:raster")
  if not r or not r.get("tiles"):
    return None
  tiles = r["tiles"] if isinstance(r["tiles"], list) else [r["tiles"]]
  return {"tiles": tiles, "tile_size": r.get("tile_size", 256), "minzoom": r.get("minzoom", 0),
          "maxzoom": r.get("maxzoom", 22), "link": r.get("link"), "feature_url": r.get("feature_url"),
          "info_url": r.get("info_url"), "info_id": r.get("info_id")}


def source_link(coll: dict) -> dict | None:
  """the source gazetteer or publisher page to link back to: {href, title}. `gazetteer:source_link` (written since
  2026-10-19), else the collection's 'Upstream publisher page' link titled by its first producer."""
  sl = coll.get("gazetteer:source_link") or {}
  if sl.get("href"):
    return {"href": sl["href"], "title": sl.get("title") or sl["href"]}
  href = next((l["href"] for l in coll.get("links") or [] if l.get("rel") == "via"
               and l.get("title") == "Upstream publisher page" and l.get("href")), None)
  if not href:
    return None
  title = next((p["name"] for p in providers_of(coll) if "producer" in p.get("roles", [])), None)
  return {"href": href, "title": title or href}


def is_map_layer(coll: dict) -> bool:
  return has_pmtiles(coll) or raster_source(coll) is not None


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
    if t in ("fill", "line", "circle", "raster") and isinstance(lyr.get("paint"), dict):
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
  return f"{attribution_text(coll)} {legacy_title(slug, coll.get('title')) or slug}{v}. Ocean Metrics gazetteer, {year}. {base.rstrip('/')}/{slug}/"


def layer_row(coll: dict, style: dict | None = None, version: str | None = None, base: str = BASE,
              ledger: dict | None = None) -> dict:
  """the manifest row for one STAC collection (pure: no I/O). `ledger` is the collection's versions.json."""
  slug = coll["id"]
  geom_type = coll.get("geoparquet:geometry_type") or "MultiPolygon"
  n = coll.get("geoparquet:feature_count", coll.get("table:row_count"))
  ver = coll.get("version") or (coll.get("gazetteer:provenance") or {}).get("version") or version
  layers = coll.get("pmtiles:layers") or []
  updated = coll.get("updated")
  status = coll.get("gazetteer:status") or None
  raster = raster_source(coll)
  return {
    "slug"            : slug,
    "title"           : legacy_title(slug, coll.get("title")) or slug,
    "collection"      : slug,
    "kind"            : "raster" if raster else "vector",
    "raster"          : raster,
    "pmtiles"         : None if raster else pmtiles_url(slug, base),
    "source_layer"    : None if raster else layers[0] if layers else slug,
    "geom_type"       : geom_type if isinstance(geom_type, str) else geom_type[0] if len(geom_type) == 1 else "Mixed",
    "n"               : n,
    "updated"         : updated,
    "version"         : ver,
    "paint"           : default_paint("raster" if raster else geom_kind(geom_type), style),
    "authority"       : coll.get("gazetteer:authority"),
    "place_type"      : coll.get("gazetteer:place_type"),
    "bbox"            : layer_bbox(coll),
    "attribution"     : attribution_text(coll),
    "attribution_html": attribution_html(coll),
    "license"         : coll.get("license"),
    "license_url"     : license_url(coll),
    "citation"        : citation(coll, slug, ver, updated, base),
    "source_link"     : source_link(coll),
    "status"          : status,
    "status_history"  : coll.get("gazetteer:status_history") or None,
    "status_label"    : status_label(status),
    "search_rank"     : search_rank(slug),
    "created"         : created_date(ledger),
    "source_date"     : source_date(coll),
    "parquet"         : f"{base.rstrip('/')}/{slug}/places.parquet" if parquet_asset(coll) else None,
    "parquet_sha256"  : parquet_sha256(coll, ver, ledger) if parquet_asset(coll) else None,
    "h3"              : None,
  }


def h3_url(slug: str, base: str = BASE) -> str:
  return f"{base.rstrip('/')}/{slug}/h3/membership.json"


def attach_h3(rows: list[dict], manifests: dict[str, dict], base: str = BASE) -> list[dict]:
  """set each row's `h3` to its membership.json URL when that membership was built from the row's own places.parquet
  (places_sha256 == parquet_sha256); a stale or missing one leaves it null."""
  out = []
  for r in rows:
    man = manifests.get(r["slug"]) or {}
    ok = r.get("parquet_sha256") and man.get("places_sha256") == r["parquet_sha256"]
    out.append({**r, "h3": h3_url(r["slug"], base) if ok else None})
  return out


def h3_manifests(slugs: list[str], local_dir: Path | None, base: str = BASE, fetch=None) -> dict[str, dict]:
  """membership.json per slug: the local build (<local_dir>/<slug>/h3/membership.json) first, else the published one."""
  got = {}
  for s in slugs:
    f = local_dir / s / "h3" / "membership.json" if local_dir else None
    if f is not None and f.exists():
      got[s] = json.loads(f.read_text())
    elif fetch is not None:
      try:
        got[s] = fetch(h3_url(s, base))
      except (urllib.error.URLError, OSError, ValueError):
        pass
  return got


def merge_rows(published: list[dict], local: list[dict]) -> list[dict]:
  """one row per slug, a local staged build replacing the published one; sorted by slug."""
  by = {r["slug"]: r for r in published}
  by.update({r["slug"]: r for r in local})
  return [by[k] for k in sorted(by)]


def manifest(rows: list[dict], base: str = BASE, generated: str | None = None) -> dict:
  return {"schema": SCHEMA, "generated": generated or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
          "base": base, "base_direct": BASE_DIRECT, "layers": rows}


# sources ----
def local_rows(staging: Path, base: str = BASE, fetch=None) -> list[dict]:
  """rows for staged builds. the ledger (for `created`) is the staged <slug>/versions.json, else the published one
  (fetched when `fetch` is given), else none: a never-published collection has `created` null."""
  rows = []
  for f in sorted(staging.glob("*/collection.json")):
    coll = json.loads(f.read_text())
    if not is_map_layer(coll):
      continue
    style_f = f.parent / "styles" / "default.json"
    style = json.loads(style_f.read_text()) if style_f.exists() else None
    ledger_f = f.parent / "versions.json"
    ledger = json.loads(ledger_f.read_text()) if ledger_f.exists() else None
    if ledger is None and fetch is not None:
      try:
        ledger = fetch(urljoin(base, f"{coll['id']}/versions.json"))
      except (urllib.error.URLError, OSError, ValueError):
        ledger = None
    rows.append(layer_row(coll, style, base=base, ledger=ledger))
  return rows


# reads go to the S3 origin, not the CDN: storage.oceanmetrics.io caches the catalog's JSON for a day (max-age=86400), so
# right after a publish it still serves the old versions.json and ledgers (2026-10-16). URLs written out keep `base`
def origin(url: str) -> str:
  return BASE_DIRECT + url[len(BASE):] if url.startswith(BASE) else url


def get_json(url: str, timeout: int = 60):
  req = urllib.request.Request(origin(url), headers={"User-Agent": "oceanmetrics-places/layers-json"})
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
    if not is_map_layer(coll):
      return None
    style = None
    ref = (coll.get("assets") or {}).get("styles/default")
    if ref and ref.get("href"):
      try:
        style = fetch(urljoin(href, ref["href"]))
      except (urllib.error.URLError, OSError, ValueError):
        pass
    try:
      ledger = fetch(urljoin(href, "versions.json"))
    except (urllib.error.URLError, OSError, ValueError):
      ledger = None
    return layer_row(coll, style, version=(versions.get(coll["id"]) or {}).get("current_version"), base=base,
                     ledger=ledger)

  with ThreadPoolExecutor(8) as ex:
    return [r for r in ex.map(one, hrefs) if r]


def main(argv=None) -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--out", default=str(ROOT / "catalog" / "staging" / "layers.json"))
  ap.add_argument("--staging", default=str(ROOT / "catalog" / "staging"))
  ap.add_argument("--base", default=BASE, help="published catalog base URL")
  ap.add_argument("--h3", default=str(ROOT / "catalog" / "h3"), help="local membership builds (build_h3_membership.py)")
  ap.add_argument("--no-remote", action="store_true")
  ap.add_argument("--no-local", action="store_true")
  a = ap.parse_args(argv)
  staging = Path(a.staging)
  loc = [] if a.no_local or not staging.is_dir() else local_rows(staging, a.base, None if a.no_remote else get_json)
  rem = [] if a.no_remote else remote_rows(a.base)
  rows = merge_rows(rem, loc)
  rows = attach_h3(rows, h3_manifests([r["slug"] for r in rows], Path(a.h3), a.base, None if a.no_remote else get_json),
                   a.base)
  out = Path(a.out)
  out.parent.mkdir(parents=True, exist_ok=True)
  out.write_text(json.dumps(manifest(rows, a.base), indent=2, ensure_ascii=False) + "\n")
  print(f"wrote {out}: {len(rows)} layers ({len(rem)} published, {len(loc)} local staged, "
        f"{sum(1 for r in rows if r['h3'])} with h3 membership)")
  return 0


if __name__ == "__main__":
  sys.exit(main())
