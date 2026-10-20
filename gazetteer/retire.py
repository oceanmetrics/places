"""retire a published collection from the catalog: drop its child link from the root catalog.json and its entry from
the root versions.json, so the index, layers.json and the apps stop listing it. its files stay in the bucket (old links
keep working) until they are deleted on purpose. e.g. protectedseas_navigator, split into six layers (2026-10-20).

  python -m gazetteer.retire <pub_dir> <slug> [<slug> ...]     # edits <pub_dir>/catalog.json and versions.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def unlink_collection(catalog: dict, versions: dict, slug: str) -> tuple[dict, dict]:
  """(catalog, versions) without `slug`: its rel=child link (href ./<slug>/collection.json) and its versions entry.
  raises KeyError when the catalog has no such child (a typo must not pass silently)."""
  href = f"./{slug}/collection.json"
  links = [l for l in catalog.get("links", []) if not (l.get("rel") == "child" and l.get("href") == href)]
  if len(links) == len(catalog.get("links", [])):
    raise KeyError(f"{slug}: no child link {href} in the catalog")
  cols = {k: v for k, v in (versions.get("collections") or {}).items() if k != slug}
  return {**catalog, "links": links}, {**versions, "collections": cols}


def main(argv: list[str]) -> int:
  pub, slugs = Path(argv[0]), argv[1:]
  cat = json.loads((pub / "catalog.json").read_text())
  ver = json.loads((pub / "versions.json").read_text())
  for s in slugs:
    cat, ver = unlink_collection(cat, ver, s)
    print(f"retired {s} from catalog.json and versions.json (files left in place)")
  (pub / "catalog.json").write_text(json.dumps(cat, indent=2) + "\n")
  (pub / "versions.json").write_text(json.dumps(ver, indent=2) + "\n")
  return 0


if __name__ == "__main__":
  sys.exit(main(sys.argv[1:]))
