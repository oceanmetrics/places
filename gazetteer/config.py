"""per-layer YAML config (sources/<authority>/<layer>.yml): load and validate."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .status import layer_status

PLACE_TYPES = {"lease", "planning_area", "aoa", "station", "transect"}
# MarineCadastre first-15 layers (sources/*/mc_*.yml): protected areas, jurisdictions, habitat, navigation, ...
PLACE_TYPES |= {"protected_area", "jurisdiction", "maritime_limit", "habitat", "restricted_area", "navigation_measure",
                "infrastructure"}
KINDS = {"arcgis", "shapefile_zip", "calcofi_positions"}
GEOMETRY_TYPES = {"MultiPolygon", "Point", "LineString", "MultiLineString"}  # collection-level `geometry_type`, default MultiPolygon
PLACE_TYPES |= {"eez", "territorial_sea", "contiguous_zone", "high_seas", "ecs", "ocean_sea", "world_heritage"}  # mr_* (Marine Regions)
KINDS |= {"wfs"}                                                      # OGC WFS 2.0 GeoJSON (gazetteer/fetch_wfs.py)
PLACE_TYPES |= {"mpa", "undersea_feature"}   # mpa_inventory, gebco_undersea
PLACE_TYPES |= {"managed_area"}              # protectedseas_navigator: MPAs and other area-based management measures
PLACE_TYPES |= {"internal_waters", "archipelagic_waters", "sea_area", "marine_region"}  # mr_* additions (2026-10-20)
KINDS |= {"navigator_export"}                # ProtectedSeas Navigator Direct Data Export (gazetteer/navigator.py)
PLACE_TYPES |= {"disposal_site", "military_area"}   # MarineCadastre scan 2026-10-20: EPA ocean disposal sites; Navy OPAREAs, SUA
FILTER_KINDS = {"arcgis", "navigator_export"}   # source kinds that take `exclude` / `include` ({native field: [values]})
STYLE_KEYS = {"fill_color", "fill_opacity", "line_color", "line_width"}   # config `style:` (polygon layers)

REQUIRED = ["slug", "title", "description", "authority", "place_type", "version", "license", "attribution",
            "providers", "status", "sources"]


def load_layer_config(path: str | Path) -> dict:
  """read and validate one layer config; the filename is not significant, `slug` is."""
  path = Path(path)
  cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
  if cfg.get("extends"):
    cfg = extend_config(cfg, path)
  validate_config(cfg, path.name)
  cfg["_path"] = str(path)
  cfg["_sources_dir"] = str(path.parent.parent)
  return cfg


def extend_config(cfg: dict, path: Path) -> dict:
  """`extends: _base.yml` (a file next to `path`): the base's keys, then this config's on top (top-level keys replace,
  `sources` included). bases start with `_`, so `load_all` never builds one on its own. e.g. the ProtectedSeas Navigator
  groups share `sources/protectedseas/_navigator_base.yml` (licence, attribution, ids) and differ in slug, title, style
  and their source's `include`."""
  base_path = path.parent / cfg["extends"]
  if not base_path.name.startswith("_"):
    raise ValueError(f"{path.name}: extends {base_path.name}, but a base config's file name must start with '_'")
  base = yaml.safe_load(base_path.read_text(encoding="utf-8"))
  if base.get("extends"):
    raise ValueError(f"{base_path.name}: a base config cannot extend another")
  return {**base, **{k: v for k, v in cfg.items() if k != "extends"}, "_extends": str(base_path)}


def validate_config(cfg: dict, label: str = "config") -> None:
  """raise ValueError with every problem found (license and attribution are mandatory)."""
  errs = [f"missing {k}" for k in REQUIRED if not cfg.get(k)]
  if cfg.get("slug") and not re.fullmatch(r"[a-z][a-z0-9_]*", cfg["slug"]):
    errs.append("slug must be snake_case")
  if cfg.get("place_type") and cfg["place_type"] not in PLACE_TYPES:
    errs.append(f"place_type must be one of {sorted(PLACE_TYPES)}")
  if cfg.get("geometry_type", "MultiPolygon") not in GEOMETRY_TYPES:
    errs.append(f"geometry_type must be one of {sorted(GEOMETRY_TYPES)}")
  st = cfg.get("status") or {}
  errs += [f"status.{k} missing" for k in ("value", "source", "date") if not st.get(k)]
  if st.get("overlay"):
    errs.append("status.overlay is retired: use status.events (a dated event log, see status.py)")
  ev = st.get("events")
  if ev is not None and not (isinstance(ev, dict) and ev.get("file") and ev.get("key")):
    errs.append("status.events needs file and key")
  if st.get("upstream") is not None and not isinstance(st["upstream"], str):
    errs.append("status.upstream must be a native field name")
  try:
    layer_status(cfg)
  except ValueError as e:
    errs.append(str(e))
  errs += reference_problems(cfg)
  if cfg.get("spatial_sort") and cfg.get("id_sort"):
    errs.append("spatial_sort and id_sort are exclusive (one row order)")
  sf = cfg.get("search_fields")
  if sf is not None and not (isinstance(sf, list) and sf and all(isinstance(f, str) and f for f in sf)):
    errs.append("search_fields must be a non-empty list of native column names")
  targs = cfg.get("tile_args")
  if targs is not None and not (isinstance(targs, list) and all(isinstance(a, str) and a.startswith("--") for a in targs)):
    errs.append("tile_args must be a list of tippecanoe long options (e.g. --simplification=4)")
  style = cfg.get("style")
  if style is not None and not (isinstance(style, dict) and style and set(style) <= STYLE_KEYS):
    errs.append(f"style takes only {sorted(STYLE_KEYS)}")
  for i, src in enumerate(cfg.get("sources") or []):
    if src.get("kind") not in KINDS:
      errs.append(f"sources[{i}].kind must be one of {sorted(KINDS)}")
    if not src.get("url"):
      errs.append(f"sources[{i}].url missing")
    for key in ("exclude", "include"):
      rule = src.get(key)
      if rule is None:
        continue
      if src.get("kind") not in FILTER_KINDS:
        errs.append(f"sources[{i}].{key} is only supported for {' and '.join(sorted(FILTER_KINDS))} sources")
      if key == "include" and src.get("kind") == "arcgis":
        errs.append(f"sources[{i}].include is not supported for arcgis sources (use exclude)")
      if not (isinstance(rule, dict) and rule and all(isinstance(v, list) and v for v in rule.values())):
        errs.append(f"sources[{i}].{key} must map a native field to a non-empty list of values")
    for key in ("place_id", "name", "source_id"):
      if not (src.get(key) or cfg.get(key)):
        errs.append(f"sources[{i}]: no {key} (set it on the source or the collection)")
    pid = src.get("place_id") or cfg.get("place_id") or {}
    if not pid.get("pattern"):
      errs.append(f"sources[{i}]: place_id.pattern missing")
    elif not (pid.get("rule") or pid.get("template")):
      errs.append(f"sources[{i}]: place_id needs a rule or a template")
    else:
      try:
        re.compile(pid["pattern"])
      except re.error as e:
        errs.append(f"sources[{i}]: bad place_id.pattern: {e}")
  if errs:
    raise ValueError(f"{label}: " + "; ".join(errs))


def reference_problems(cfg: dict) -> list[str]:
  """checks of the optional link-back keys: `place_url` (a template of the place's page at its source, rendered per
  index row) and `reference` (a collection whose data we do not republish: drawn from the publisher's own XYZ tiles,
  `tiles`, one boundary at a time from `feature_url`, which takes the row's `{source_id}`)."""
  errs = []
  pu = cfg.get("place_url")
  if pu is not None and not (isinstance(pu, str) and "{" in pu and (pu.startswith("http") or pu.startswith("{"))):
    errs.append("place_url must be a template with at least one {FIELD}: an http(s) URL, or a field holding one")
  ref = cfg.get("reference")
  if ref is None:
    return errs
  if not isinstance(ref, dict) or not ref.get("tiles"):
    return errs + ["reference.tiles missing (an XYZ tile URL template)"]
  if not all(k in ref["tiles"] for k in ("{z}", "{x}", "{y}")):
    errs.append("reference.tiles needs {z}, {x} and {y}")
  if ref.get("feature_url") and "{source_id}" not in ref["feature_url"]:
    errs.append("reference.feature_url needs {source_id}")
  if ref.get("info_url"):                      # identify on click: the publisher's WMS GetFeatureInfo, no geometry
    if "{bbox}" not in ref["info_url"]:
      errs.append("reference.info_url needs {bbox} (west,south,east,north around the clicked point)")
    if not ref.get("info_id"):
      errs.append("reference.info_url needs reference.info_id (the response field holding the place's source_id or name)")
  for k in ("minzoom", "maxzoom", "tile_size"):
    if k in ref and not isinstance(ref[k], int):
      errs.append(f"reference.{k} must be an integer")
  return errs


def source_setting(cfg: dict, src: dict, key: str):
  """a per-source setting falling back to the collection-level one."""
  return src.get(key) if src.get(key) is not None else cfg.get(key)


def load_all(sources_dir: str | Path) -> dict[str, dict]:
  """every layer config under sources_dir/*/*.yml, keyed by slug (duplicate slugs are an error); `_*.yml` files are
  bases for `extends`, not layers."""
  out: dict[str, dict] = {}
  for p in sorted(q for q in Path(sources_dir).glob("*/*.yml") if not q.name.startswith("_")):
    cfg = load_layer_config(p)
    if cfg["slug"] in out:
      raise ValueError(f"duplicate slug {cfg['slug']} in {p}")
    out[cfg["slug"]] = cfg
  return out
