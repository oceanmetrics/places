"""a collection's versions.json ledger for a metadata-only (reference) collection, in portolan's format.

`portolan add` refuses a collection without geospatial files ("No geospatial files found to add"), and a reference
collection (e.g. mr_*, whose data we do not republish) has none in the public tree, so publish_collections.sh records
its versions here instead: one entry per publish, every file in the folder with its sha256, size and href.

  python -m gazetteer.ledger <pub_dir> <slug> <version> [<message>]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

SKIP = {"versions.json"}


def asset_entries(coll_dir: Path, slug: str) -> dict:
  out = {}
  for f in sorted(p for p in coll_dir.rglob("*") if p.is_file()):
    rel = f.relative_to(coll_dir).as_posix()
    if rel in SKIP or rel.startswith(".portolan/"):
      continue
    b = f.read_bytes()
    out[rel] = {"sha256": hashlib.sha256(b).hexdigest(), "size_bytes": len(b), "href": f"{slug}/{rel}",
                "mtime": f.stat().st_mtime}
  return out


def append_version(coll_dir: Path, slug: str, version: str, message: str = "", now: str | None = None) -> dict:
  """add `version` to <coll_dir>/versions.json (created when absent) and make it current; refuses a version the
  ledger already has, and data files (a reference collection must not carry any)."""
  assets = asset_entries(coll_dir, slug)
  data = [k for k in assets if k.endswith((".parquet", ".pmtiles"))]
  if data:
    raise ValueError(f"{slug}: a reference collection must not carry data files: {data}")
  p = coll_dir / "versions.json"
  led = json.loads(p.read_text()) if p.exists() else {"spec_version": "1.0.0", "current_version": None, "versions": []}
  have = [v["version"] for v in led["versions"]]
  if version in have:
    raise ValueError(f"{slug}: the ledger already has {version} ({have})")
  prev = led["versions"][-1]["assets"] if led["versions"] else {}
  changes = sorted(k for k, a in assets.items() if (prev.get(k) or {}).get("sha256") != a["sha256"])
  led["versions"].append({
    "version": version, "created": now or dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
    "breaking": False, "assets": assets, "changes": changes,
    "schema": {"type": "unknown", "fingerprint": {"columns": [], "types": {}}}, "message": message or "reference collection: metadata only"})
  led["current_version"] = version
  p.write_text(json.dumps(led, indent=2) + "\n")
  return led


if __name__ == "__main__":
  d, slug, ver = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
  led = append_version(d / slug, slug, ver, sys.argv[4] if len(sys.argv) > 4 else "")
  print(f"ledger {slug}: {[v['version'] for v in led['versions']]}")
