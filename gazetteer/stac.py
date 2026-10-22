"""STAC collection.json, README.md, AGENTS.md and the default map style for one built collection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa

from .status import layer_status

STAC_EXTENSIONS = [
  "https://stac-extensions.github.io/table/v1.2.0/schema.json",
  "https://stac-extensions.github.io/file/v2.1.0/schema.json",
  "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json",
  "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json",
]
OCEAN_METRICS = {"name": "Ocean Metrics LLC", "roles": ["processor", "host"], "url": "https://oceanmetrics.io"}
COLUMN_DOCS = {
  "place_id": "prefixed, unique id (e.g. BOEM:OCS-P 0561, BOEM:PA:SOC, AOA:N1-A)",
  "authority": "organisation that publishes the boundary (BOEM, AOA = NOAA Aquaculture Opportunity Areas)",
  "source_id": "the source layer's own identifier for the feature (lease number, planning-area code, OBJECTID, AOA code)",
  "name": "human-readable name",
  "place_type": "kind of place: lease, planning_area or aoa",
  "geom_type": "geometry type after normalisation (MultiPolygon)",
  "status": "lifecycle status (e.g. active, cancelled, relinquished, settlement_pending, rescinded, draft_proposed, identified)",
  "status_source": "URL that documents the status",
  "status_date": "ISO date (or year) the status took effect or was last confirmed; may be empty",
  "status_upstream": "the source's own status code, verbatim (e.g. BOEM LEASE_STATUS_CD, AREA_STATUS); null when the source has none. may disagree with `status`",
  "status_history": "JSON array of dated status events [{date, value, source, note}], ascending; null when none is logged",
  "source_url": "the service endpoint or download the boundary was fetched from",
  "source_date": "date of the source's last data edit (retrieval date when the source serves none)",
  "retrieved": "UTC time the boundary was fetched",
  "version": "collection release version this row was built for",
  "license": "SPDX identifier of the licence (CC-PDDC = public-domain U.S. government work)",
  "attribution": "credit line to show with the data",
  "component": "which source layer of the collection the row comes from",
  "bbox": "GeoParquet bbox-covering column (xmin, ymin, xmax, ymax)",
  "geometry": "MULTIPOLYGON, EPSG:4326, split at +/-180 antimeridian",
}


def multihash(path: Path) -> str:
  """sha-256 as a multihash hex string (0x12 0x20 prefix), the form Portolan records in file:checksum."""
  h = hashlib.sha256()
  with open(path, "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
      h.update(chunk)
  return "1220" + h.hexdigest()


def size_label(n: int) -> str:
  return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{n / 1e3:.0f} kB"


def style_json(slug: str, max_zoom: int, geometry_type: str = "MultiPolygon", style: dict | None = None) -> dict:
  """the collection's default MapLibre style. `style` (config, polygon layers only) overrides the fill / outline paint:
  fill_color, fill_opacity, line_color, line_width (e.g. one colour per ProtectedSeas Navigator group)."""
  src = {"data": {"type": "vector", "url": "pmtiles://../places.pmtiles", "minzoom": 0, "maxzoom": max_zoom}}
  st = style or {}
  if geometry_type == "Mixed":   # points, lines and polygons share one tile layer: one style layer per geometry kind
    return {"version": 8, "name": "Default", "sources": src, "layers": [
      {"id": f"{slug}-fill", "type": "fill", "source": "data", "source-layer": slug, "filter": ["==", ["geometry-type"], "Polygon"],
       "paint": {"fill-color": "#0b6e99", "fill-opacity": 0.25}},
      {"id": f"{slug}-outline", "type": "line", "source": "data", "source-layer": slug, "filter": ["==", ["geometry-type"], "Polygon"],
       "paint": {"line-color": "#0b6e99", "line-width": 1}},
      {"id": f"{slug}-line", "type": "line", "source": "data", "source-layer": slug, "filter": ["==", ["geometry-type"], "LineString"],
       "paint": {"line-color": "#0b6e99", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1, 10, 2.5]}},
      {"id": f"{slug}-point", "type": "circle", "source": "data", "source-layer": slug, "filter": ["==", ["geometry-type"], "Point"],
       "paint": {"circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 2, 8, 4, 12, 6], "circle-color": "#0b6e99",
                 "circle-stroke-color": "#ffffff", "circle-stroke-width": 1, "circle-opacity": 0.9}}]}
  if geometry_type == "Point":
    return {"version": 8, "name": "Default", "sources": src, "layers": [
      {"id": f"{slug}-circle", "type": "circle", "source": "data", "source-layer": slug,
       "paint": {"circle-radius": ["interpolate", ["linear"], ["zoom"], 3, 2, 8, 5, 12, 7], "circle-color": "#0b6e99",
                 "circle-stroke-color": "#ffffff", "circle-stroke-width": 1, "circle-opacity": 0.9}}]}
  if geometry_type in ("LineString", "MultiLineString"):
    return {"version": 8, "name": "Default", "sources": src, "layers": [
      {"id": f"{slug}-line", "type": "line", "source": "data", "source-layer": slug,
       "paint": {"line-color": "#0b6e99", "line-width": ["interpolate", ["linear"], ["zoom"], 3, 1, 10, 2.5]}}]}
  return {"version": 8, "name": "Default",
          "sources": src,
          "layers": [
            {"id": f"{slug}-fill", "type": "fill", "source": "data", "source-layer": slug,
             "paint": {"fill-color": st.get("fill_color", "#e08a1e"), "fill-opacity": st.get("fill_opacity", 0.45)}},
            {"id": f"{slug}-line", "type": "line", "source": "data", "source-layer": slug,
             "paint": {"line-color": st.get("line_color", "#a85f00"), "line-width": st.get("line_width", 1)}}]}


def build_collection(cfg: dict, table: pa.Table, geo: dict, provenance: dict, dir: Path, header: dict, now: str,
                     descriptions: dict[str, str]) -> dict:
  """the STAC Collection (1.1.0) mirroring the catalog places collection, for files already in `dir`."""
  slug = cfg["slug"]
  bbox = geo["columns"]["geometry"]["bbox"]
  gt = cfg.get("geometry_type", "MultiPolygon")
  docs = {**COLUMN_DOCS, "geom_type": f"geometry type ({gt})", "geometry": f"{gt.upper()}, EPSG:4326, split at +/-180 antimeridian"}
  gts = geo["columns"]["geometry"]["geometry_types"]
  cols = []
  for f in table.schema:
    desc = descriptions.get(f.name) or docs.get(f.name) or f"native attribute of the source layer ({f.name})"
    cols.append({"name": f.name, "type": str(f.type).replace("timestamp[ms, tz=UTC]", "timestamp[ms, tz=UTC]"),
                 "description": desc})
  links = [
    {"rel": "root", "href": "../catalog.json", "type": "application/json", "title": "Ocean Metrics gazetteer"},
    {"rel": "parent", "href": "../catalog.json", "type": "application/json", "title": "Ocean Metrics gazetteer"},
    {"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown", "title": "Agent/LLM usage guide"},
    {"rel": "describedby", "href": "./README.md", "type": "text/markdown", "title": "Human-readable documentation"},
    {"rel": "pmtiles", "href": "./places.pmtiles", "type": "application/vnd.pmtiles", "pmtiles:layers": [slug]},
    {"rel": "license", "href": cfg["license_url"], "type": "text/html", "title": cfg.get("license_note", "").strip()[:200] or cfg["license"]},
    {"rel": "via", "href": cfg["source_page"], "type": "text/html", "title": "Upstream publisher page"},
  ]
  for s in provenance["sources"]:
    # rashid (PTL-PRO-001) wants every `via` link typed text/html; the ArcGIS REST layer page is an HTML page
    links.append({"rel": "via", "href": s["source_url"], "type": "text/html",
                  "title": "Source layer" + (f" ({s['component']})" if s.get("component") else "")})
  ref = reference_fields(cfg)
  if ref:
    # a reference collection: no parquet or pmtiles of ours in public (the publisher asked us not to republish), so no
    # pmtiles link; the map draws the publisher's tiles (`xyz`, STAC web-map-links)
    links = [l for l in links if l["rel"] != "pmtiles"]
    if "gazetteer:raster" in ref:
      links.append({"rel": "xyz", "href": ref["gazetteer:raster"]["tiles"][0], "type": "image/png",
                    "title": "Map tiles served by the publisher"})
    elif "gazetteer:display" in ref:
      links.append({"rel": "related", "href": f"../{ref['gazetteer:display']['via']}/collection.json", "type": "application/json",
                    "title": f"Drawn by the map tiles of {ref['gazetteer:display']['via']}"})
  def asset(name, href, typ, roles, title=None):
    p = dir / href
    a = {"href": f"./{href}", "type": typ}
    if title:
      a["title"] = title
    a.update({"file:size": p.stat().st_size, "file:checksum": multihash(p), "roles": roles})
    return name, a
  data = [] if ref else [
    asset("places", "places.parquet", "application/vnd.apache.parquet", ["data"]),
    asset("places-tiles", "places.pmtiles", "application/vnd.pmtiles", ["visual"], f"{slug} (vector tiles)"),
  ]
  assets = dict(data + [
    asset("styles/default", "styles/default.json", "application/vnd.mapbox.style+json", ["style", "default"], "Default"),
    asset("provenance", "provenance.json", "application/json", ["metadata"], "Source provenance and change-detection record"),
    asset("documentation", "README.md", "text/markdown", ["documentation"]),
  ])
  tiles = {} if ref else {"pmtiles:min_zoom": header["min_zoom"], "pmtiles:max_zoom": header["max_zoom"],
                          "pmtiles:tile_type": "mvt", "pmtiles:center": header["center"], "pmtiles:layers": [slug]}
  return {
    "type": "Collection", "id": slug, "stac_version": "1.1.0",
    "description": " ".join(cfg["description"].split()) + f" Built by build.py from {len(provenance['sources'])} source layer(s).",
    "links": links, "stac_extensions": STAC_EXTENSIONS,
    "geoparquet:geometry_type": (gts[0] if len(gts) == 1 else gts), "geoparquet:feature_count": table.num_rows,
    "table:row_count": table.num_rows, "table:primary_geometry": "geometry", "table:columns": cols,
    "updated": now, **tiles,
    "title": cfg["title"],
    "extent": {"spatial": {"bbox": [bbox]}, "temporal": {"interval": [[None, None]]}},
    "license": cfg.get("stac_license") or cfg["license"],   # SPDX id, or "other" (+ the license link) for a custom one
    "providers": [*cfg["providers"], OCEAN_METRICS],
    "gazetteer:authority": cfg["authority"], "gazetteer:place_type": cfg["place_type"],
    "gazetteer:cadence": cfg.get("cadence", "weekly"), "gazetteer:attribution": " ".join(cfg["attribution"].split()),
    "gazetteer:provenance": provenance,
    "gazetteer:source_link": source_link(cfg),
    **({"citation": " ".join(cfg["citation"].split())} if cfg.get("citation") else {}),
    **layer_status_fields(cfg),
    **access_fields(cfg),
    **ref,
    "assets": assets,
  }


def source_link(cfg: dict) -> dict:
  """the source gazetteer or publisher page every app links back to: {href, title}."""
  title = cfg.get("source_title") or next((p["name"] for p in cfg.get("providers") or [] if p.get("name")), None)
  return {"href": cfg.get("source_home") or cfg.get("source_page"), "title": title}


def is_reference(cfg: dict) -> bool:
  """a collection whose data files are never published: config `reference` (the publisher's tiles draw it) or
  `display` (another collection's tiles draw it, e.g. a derived piece of a reference collection)."""
  return bool(cfg.get("reference") or cfg.get("display"))


def reference_fields(cfg: dict) -> dict:
  """{'gazetteer:reference', 'gazetteer:raster'} for a reference collection (config `reference`), {'gazetteer:reference',
  'gazetteer:display'} for a `display` one, else {}. the raster block is what build_layers_json.py turns into a
  `kind: "raster"` row, the display block into a `kind: "derived"` row."""
  ref = cfg.get("reference")
  if not ref and cfg.get("display"):
    return {"gazetteer:reference": True, "gazetteer:display": {"via": cfg["display"]["via"], "id_from": cfg["display"]["id_from"]}}
  if not ref:
    return {}
  raster = {"tiles": [ref["tiles"]], "tile_size": ref.get("tile_size", 256), "minzoom": ref.get("minzoom", 0),
            "maxzoom": ref.get("maxzoom", 22), "link": ref.get("link") or cfg.get("source_page"),
            "feature_url": ref.get("feature_url"), "info_url": ref.get("info_url"), "info_id": ref.get("info_id")}
  return {"gazetteer:reference": True, "gazetteer:raster": raster}


def layer_status_fields(cfg: dict) -> dict:
  """{'gazetteer:status', 'gazetteer:status_history'} for a config that documents a layer-level status; {} otherwise."""
  st, hist = layer_status(cfg)
  return {"gazetteer:status": st, "gazetteer:status_history": hist} if st else {}


def access_fields(cfg: dict) -> dict:
  """{'gazetteer:access'}: `public` (default) or `unlisted` from the config's `access`. an unlisted collection is
  published and reachable by link but never listed: build_index.py leaves it out of search, the client's layers() drops
  its layers.json row unless asked."""
  return {"gazetteer:access": cfg.get("access") or "public"}


def readme(cfg: dict, table: pa.Table, provenance: dict, collection: dict, version: str) -> str:
  slug = cfg["slug"]
  rows = [f"| {c['name']} | {c['type']} | {c['description']} |" for c in collection["table:columns"]]
  srcs = []
  for s in provenance["sources"]:
    srcs.append(f"| {s.get('component') or '-'} | {s['source_url']} | {s.get('source_item_id') or '-'} | "
                f"{s.get('data_last_edit') or 'not served'} | {s['retrieved']} | {s['record_count']} | `{s['checksum'][:16]}...` |")
  files = [f"| {k} | {size_label(a['file:size'])} | `{a['file:checksum'][:16]}...` |"
           for k, a in collection["assets"].items()]
  overlay = ""
  ev = cfg["status"].get("events")
  if ev:
    overlay = (f"\n## Status event log\n\nThe source layer has no status field. `status`, `status_source` and `status_date` "
               f"are the latest event in the hand-maintained, dated event log `sources/{ev['file']}` (one row per event, each "
               f"with its source URL), joined on the exact `{ev['key']}`; `status_history` holds every event of the place as "
               f"JSON. Places with no event are `{cfg['status']['value']}` as of the layer's last edit. The log is the place "
               f"to record BOEM's changes until the layer catches up.\n")
  if cfg["status"].get("upstream"):
    overlay += (f"\n`status_upstream` is the source's own `{cfg['status']['upstream']}`, verbatim; where it disagrees with "
                f"`status`, `status` is ours and documented by `status_source`.\n")
  st, hist = layer_status(cfg)
  if st:
    events = "\n".join(f"- {e['date']}: {e['value']} ({e['source']}){' - ' + e['note'] if e.get('note') else ''}" for e in hist)
    overlay += f"\n## Layer status\n\n**{st['value'].replace('_', ' ')} {st['date']}** ({st['source']}).\n\n{events}\n"
  ref = is_reference(cfg)
  link = source_link(cfg)
  if ref and cfg.get("display"):
    what = (f"`{slug}` v{version}, {table.num_rows} features: a **derived reference collection**. It is computed from a "
            f"collection whose publisher asked that its products not be republished, so there is no parquet or PMTiles "
            f"copy here; this folder holds metadata only")
    quick = reference_quick_start(cfg)
  elif ref:
    what = (f"`{slug}` v{version}, {table.num_rows} features: a **reference collection**. The publisher asked that its "
            f"products not be republished, so there is no parquet or PMTiles copy here; this folder holds metadata only")
    quick = reference_quick_start(cfg)
  else:
    what = (f"`{slug}` v{version}, {table.num_rows} features, GeoParquet 1.1 (`places.parquet`) and PMTiles "
            f"(`places.pmtiles`, layer `{slug}`)")
    quick = f"""```sql
SELECT place_id, name, status, status_date
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/{slug}/places.parquet')
ORDER BY place_id;
```"""
  place_link = (f"\n- **Each place at the source**: `{cfg['place_url']}` (the `url` column of the gazetteer index)"
                if cfg.get("place_url") else "")
  return f"""# {cfg['title']}

{' '.join(cfg['description'].split())}

- **Collection**: {what}
- **Source**: [{link['title']}]({link['href']}){place_link}
- **Licence**: {cfg['license']} - {' '.join(cfg.get('license_note', '').split())} {cfg['license_url']}
- **Attribution**: {' '.join(cfg['attribution'].split())}
- **Refresh**: {cfg.get('cadence', 'weekly')}, by `.github/workflows/sync.yml` (re-fetched only when the source's `editingInfo.dataLastEditDate` or record count changed)
{overlay}
## Sources and provenance

| Component | Source | Item | Data last edit | Retrieved | Records | Checksum (sha-256 of payload) |
|---|---|---|---|---|---|---|
{chr(10).join(srcs)}

Machine-readable copy: [`provenance.json`](./provenance.json) (also in `collection.json` and the Parquet footer).

## Schema

| Column | Type | Description |
|---|---|---|
{chr(10).join(rows)}

Native attributes keep the source layer's names; a native name equal to a gazetteer column ignoring case
(`NAME` vs `name`) is suffixed `_src`.

## Files

| File | Size | Checksum |
|---|---|---|
{chr(10).join(files)}

## Quick start

{quick}

## Changes

- **{version}**: first release.
"""


def display_text(cfg: dict) -> str:
  """how a `display` collection is drawn (README / AGENTS), for outside readers: no geometry here, draw `via`."""
  d, slug = cfg["display"], cfg["slug"]
  return f"""Search it in the gazetteer index (names, ids, extents, areas; no geometry):

```sql
SELECT place_id, source_id, name, area_km2
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/index/places_index.parquet')
WHERE collection = '{slug}'
ORDER BY name;
```

**Drawing it.** `{slug}` has no map tiles of its own. In `layers.json` its row has `kind: "derived"` and
`display: {{"via": "{d['via']}", "id_from": "{d['id_from']}"}}`: draw the PMTiles of the `{d['via']}` collection (layer
`{d['via']}`) and show each `{slug}` place in the `{d['via']}` feature whose `place_id` equals the place's `{d['id_from']}`
value. That value is the parquet column `{d['id_from']}` and also the index row's `source_id`, so a reader of the public
index needs no parquet (e.g. place `FAOHS:21` has `source_id` `FAO:21`: draw feature `FAO:21`). The `{d['via']}` feature
is the whole parent area, not the piece itself: highlight or label it, and say that the piece is only the part of it
that this collection covers. Do not mirror or redistribute the pieces."""


def reference_quick_start(cfg: dict) -> str:
  if cfg.get("display") and not cfg.get("reference"):
    return display_text(cfg)
  ref = cfg["reference"]
  wfs =(f"\nOne place's boundary, from the publisher (replace `{{source_id}}` with the index row's `source_id`):\n\n"
         f"```\n{ref['feature_url']}\n```\n") if ref.get("feature_url") else ""
  return f"""Search it in the gazetteer index (names, ids, extents, areas and links back; no geometry):

```sql
SELECT place_id, source_id, name, area_km2, url
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/index/places_index.parquet')
WHERE collection = '{cfg['slug']}'
ORDER BY name;
```

Map tiles, served by the publisher (XYZ, {ref.get('tile_size', 256)} px PNG; `layers.json` row `kind: "raster"`):

```
{ref['tiles']}
```
{wfs}"""


def agents(cfg: dict) -> str:
  slug = cfg["slug"]
  if is_reference(cfg):
    why = ("The collection is computed from a collection whose publisher asked that its products not be republished"
           if cfg.get("display") else "The publisher asked that its products not be republished")
    return f"""# AGENTS.md - {cfg['title']}

Guidance for AI agents and LLMs working with this collection.

## Overview

{' '.join(cfg['description'].split())}

Licence {cfg['license']}; credit: {' '.join(cfg['attribution'].split())}

## This is a reference collection

{why}, so there is **no parquet or PMTiles here**. Do not mirror
or redistribute its boundaries; link to the publisher ({source_link(cfg)['href']}) and each place's own page (the
index `url` column).

{reference_quick_start(cfg)}"""
  return f"""# AGENTS.md - {cfg['title']}

Guidance for AI agents and LLMs working with this collection.

## Overview

{' '.join(cfg['description'].split())}

Licence {cfg['license']}; credit: {' '.join(cfg['attribution'].split())}

## Find a place

```sql
SELECT * FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/{slug}/places.parquet')
WHERE name ILIKE '%california%';
```

`place_id` is unique and prefixed; `status` / `status_source` / `status_date` say whether the place is current and
where that is documented. Check `status` before treating a lease or area as live.

## Render on a map

Load `places.pmtiles` (layer `{slug}`) into MapLibre GL via the PMTiles protocol; `styles/default.json` is a starting style.
"""
