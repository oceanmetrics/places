"""per-layer YAML config (sources/<authority>/<layer>.yml): load and validate."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

PLACE_TYPES = {"lease", "planning_area", "aoa", "station", "transect"}
KINDS = {"arcgis", "shapefile_zip", "calcofi_positions"}
GEOMETRY_TYPES = {"MultiPolygon", "Point", "LineString"}  # collection-level `geometry_type`, default MultiPolygon
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
  for i, src in enumerate(cfg.get("sources") or []):
    if src.get("kind") not in KINDS:
      errs.append(f"sources[{i}].kind must be one of {sorted(KINDS)}")
    if not src.get("url"):
      errs.append(f"sources[{i}].url missing")
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
