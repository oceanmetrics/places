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
KINDS |= {"navigator_export"}                # ProtectedSeas Navigator Direct Data Export (gazetteer/navigator.py)
REQUIRED = ["slug", "title", "description", "authority", "place_type", "version", "license", "attribution",
            "providers", "status", "sources"]


def load_layer_config(path: str | Path) -> dict:
  """read and validate one layer config; the filename is not significant, `slug` is."""
  path = Path(path)
  cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
  validate_config(cfg, path.name)
  cfg["_path"] = str(path)
  cfg["_sources_dir"] = str(path.parent.parent)
  return cfg


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
  for i, src in enumerate(cfg.get("sources") or []):
    if src.get("kind") not in KINDS:
      errs.append(f"sources[{i}].kind must be one of {sorted(KINDS)}")
    if not src.get("url"):
      errs.append(f"sources[{i}].url missing")
    exc = src.get("exclude")
    if exc is not None:
      if src.get("kind") != "arcgis":
        errs.append(f"sources[{i}].exclude is only supported for arcgis sources")
      if not (isinstance(exc, dict) and exc and all(isinstance(v, list) and v for v in exc.values())):
        errs.append(f"sources[{i}].exclude must map a native field to a non-empty list of values")
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
  for k in ("minzoom", "maxzoom", "tile_size"):
    if k in ref and not isinstance(ref[k], int):
      errs.append(f"reference.{k} must be an integer")
  return errs


def source_setting(cfg: dict, src: dict, key: str):
  """a per-source setting falling back to the collection-level one."""
  return src.get(key) if src.get(key) is not None else cfg.get(key)


def load_all(sources_dir: str | Path) -> dict[str, dict]:
  """every layer config under sources_dir/*/*.yml, keyed by slug (duplicate slugs are an error)."""
  out: dict[str, dict] = {}
  for p in sorted(Path(sources_dir).glob("*/*.yml")):
    cfg = load_layer_config(p)
    if cfg["slug"] in out:
      raise ValueError(f"duplicate slug {cfg['slug']} in {p}")
    out[cfg["slug"]] = cfg
  return out
