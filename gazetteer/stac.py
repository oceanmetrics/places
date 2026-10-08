"""STAC collection.json, README.md, AGENTS.md and the default map style for one built collection."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa

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


def style_json(slug: str, max_zoom: int) -> dict:
  return {"version": 8, "name": "Default",
          "sources": {"data": {"type": "vector", "url": "pmtiles://../places.pmtiles", "minzoom": 0, "maxzoom": max_zoom}},
          "layers": [
            {"id": f"{slug}-fill", "type": "fill", "source": "data", "source-layer": slug,
             "paint": {"fill-color": "#e08a1e", "fill-opacity": 0.45}},
            {"id": f"{slug}-line", "type": "line", "source": "data", "source-layer": slug,
             "paint": {"line-color": "#a85f00", "line-width": 1}}]}


def build_collection(cfg: dict, table: pa.Table, geo: dict, provenance: dict, dir: Path, header: dict, now: str,
                     descriptions: dict[str, str]) -> dict:
  """the STAC Collection (1.1.0) mirroring the catalog places collection, for files already in `dir`."""
  slug = cfg["slug"]
  bbox = geo["columns"]["geometry"]["bbox"]
  cols = []
  for f in table.schema:
    desc = COLUMN_DOCS.get(f.name) or descriptions.get(f.name) or f"native attribute of the source layer ({f.name})"
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
  def asset(name, href, typ, roles, title=None):
    p = dir / href
    a = {"href": f"./{href}", "type": typ}
    if title:
      a["title"] = title
    a.update({"file:size": p.stat().st_size, "file:checksum": multihash(p), "roles": roles})
    return name, a
  assets = dict([
    asset("places", "places.parquet", "application/vnd.apache.parquet", ["data"]),
    asset("places-tiles", "places.pmtiles", "application/vnd.pmtiles", ["visual"], f"{slug} (vector tiles)"),
    asset("styles/default", "styles/default.json", "application/vnd.mapbox.style+json", ["style", "default"], "Default"),
    asset("provenance", "provenance.json", "application/json", ["metadata"], "Source provenance and change-detection record"),
    asset("documentation", "README.md", "text/markdown", ["documentation"]),
  ])
  return {
    "type": "Collection", "id": slug, "stac_version": "1.1.0",
    "description": " ".join(cfg["description"].split()) + f" Built by build.py from {len(provenance['sources'])} source layer(s).",
    "links": links, "stac_extensions": STAC_EXTENSIONS,
    "geoparquet:geometry_type": "MultiPolygon", "geoparquet:feature_count": table.num_rows,
    "table:row_count": table.num_rows, "table:primary_geometry": "geometry", "table:columns": cols,
    "updated": now, "pmtiles:min_zoom": header["min_zoom"], "pmtiles:max_zoom": header["max_zoom"],
    "pmtiles:tile_type": "mvt", "pmtiles:center": header["center"], "pmtiles:layers": [slug],
    "title": cfg["title"],
    "extent": {"spatial": {"bbox": [bbox]}, "temporal": {"interval": [[None, None]]}},
    "license": cfg["license"],
    "providers": [*cfg["providers"], OCEAN_METRICS],
    "gazetteer:authority": cfg["authority"], "gazetteer:place_type": cfg["place_type"],
    "gazetteer:cadence": cfg.get("cadence", "weekly"), "gazetteer:attribution": " ".join(cfg["attribution"].split()),
    "gazetteer:provenance": provenance,
    "assets": assets,
  }


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
  if (cfg["status"].get("overlay")):
    overlay = (f"\n## Status overlay\n\nThe source layer has no status field. `status`, `status_source` and `status_date` come "
               f"from the hand-maintained `sources/{cfg['status']['overlay']['file']}`, joined on the exact "
               f"`{cfg['status']['overlay']['key']}`; leases not in the overlay are `{cfg['status']['value']}` as of the "
               f"layer's last edit. The overlay is the place to record BOEM's changes until the layer catches up.\n")
  return f"""# {cfg['title']}

{' '.join(cfg['description'].split())}

- **Collection**: `{slug}` v{version}, {table.num_rows} features, GeoParquet 1.1 (`places.parquet`) and PMTiles (`places.pmtiles`, layer `{slug}`)
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

```sql
SELECT place_id, name, status, status_date
FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/{slug}/places.parquet')
ORDER BY place_id;
```

## Changes

- **{version}**: first release.
"""


def agents(cfg: dict) -> str:
  slug = cfg["slug"]
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
