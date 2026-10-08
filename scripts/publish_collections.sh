#!/usr/bin/env bash
# publish staged collections into the live gazetteer catalog:
# copy -> portolan add -> restore shared files -> fix sizes/checksums/roles -> rashid gate -> upload -> verify
#
# usage: scripts/publish_collections.sh [--no-upload] <slug> [<slug> ...]
#
# prerequisites (see catalog/staging/RUNBOOK_PUBLISH.md):
#   - catalog/staging/<slug>/ built and green (uv run build.py check)
#   - catalog/pub/ holds the published metadata tree:
#     aws s3 sync s3://oceanmetrics.io-public/gazetteer/ catalog/pub/ \
#       --exclude '*.parquet' --exclude '*.pmtiles' --exclude '*.tif' --exclude '*.nc'
#
# guards the portolan 0.8.0 quirks (collateral rewrites, stale checksums, pmtiles role flip,
# root versions.json), per erddap-places/catalog/publish_places.sh and integrate_erin_layers.sh.

set -euo pipefail

do_upload=1
[[ "${1:-}" == "--no-upload" ]] && { do_upload=0; shift; }
[[ $# -ge 1 ]] || { echo "usage: $0 [--no-upload] <slug> ..." >&2; exit 1; }
slugs="$*"

dir_repo="$(cd "$(dirname "$0")/.." && pwd)"
dir_pub="$dir_repo/catalog/pub"
dir_staging="$dir_repo/catalog/staging"
s3_dest="s3://oceanmetrics.io-public/gazetteer"

# 1. snapshot every shared file portolan add may rewrite ----
snap="$(mktemp -d)"
trap 'rm -rf "$snap"' EXIT
shared=$(cd "$dir_pub" && find . \( -name collection.json -o -name versions.json \) -not -path '*/items/*' | sort)
for f in $shared catalog.json; do
  mkdir -p "$snap/$(dirname "$f")"
  cp "$dir_pub/$f" "$snap/$f" 2>/dev/null || true
done

# 2. copy staging into the pub tree ----
for s in $slugs; do
  [[ -d "$dir_staging/$s" ]] || { echo "not staged: $s" >&2; exit 1; }
  mkdir -p "$dir_pub/$s"
  cp -R "$dir_staging/$s/." "$dir_pub/$s/"
done

# 3. portolan add (records 1.0.0 itself on a first add; renders thumbnails) ----
cd "$dir_pub"
# shellcheck disable=SC2046
portolan add $(for s in $slugs; do echo "$s/"; done) --force --force-thumbnails

# 4. restore the snapshotted shared files (keep the target slugs' fresh ledgers) ----
for f in $shared catalog.json; do
  case "$f" in *"/items/"*) continue ;; esac
  keep=0
  for s in $slugs; do [[ "$f" == "./$s/"* ]] && keep=1; done
  [[ $keep -eq 0 ]] && [[ -f "$snap/$f" ]] && cp "$snap/$f" "$dir_pub/$f"
done

# 5. fixups: child links, asset sizes/checksums, pmtiles role, root versions entries ----
python3 - "$dir_pub" "$slugs" <<'PYEOF'
import datetime, hashlib, json, os, sys
d, slugs = sys.argv[1], sys.argv[2].split()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
p = os.path.join(d, "catalog.json")
cat = json.load(open(p))
have = {l.get("href") for l in cat["links"]}
for s in slugs:
    href = f"./{s}/collection.json"
    if href not in have:
        cat["links"].append({"rel": "child", "href": href, "type": "application/json", "title": s})
with open(p, "w") as f:
    json.dump(cat, f, indent=2, ensure_ascii=False); f.write("\n")
rp = os.path.join(d, "versions.json")
root = json.load(open(rp))
for s in slugs:
    cp_ = os.path.join(d, s, "collection.json")
    c = json.load(open(cp_))
    for a in c["assets"].values():
        fp = os.path.join(d, s, a["href"])
        if os.path.exists(fp):
            b = open(fp, "rb").read()
            a["file:size"] = len(b)
            a["file:checksum"] = "1220" + hashlib.sha256(b).hexdigest()
        if a["href"].endswith(".pmtiles"):
            a["roles"] = ["visual"]
    with open(cp_, "w") as f:
        json.dump(c, f, indent=2, ensure_ascii=False); f.write("\n")
    led = json.load(open(os.path.join(d, s, "versions.json")))
    assert led["current_version"] == "1.0.0", f"{s}: ledger at {led['current_version']}, expected 1.0.0"
    cur = next(v for v in led["versions"] if v["version"] == led["current_version"])
    root["collections"][s] = {
        "current_version": led["current_version"],
        "updated": now,
        "asset_count": len(cur["assets"]),
        "total_size_bytes": sum(a["size_bytes"] for a in cur["assets"].values())}
root["updated"] = now
with open(rp, "w") as f:
    json.dump(root, f, indent=2); f.write("\n")
print("fixups ok:", " ".join(slugs))
PYEOF

# 6. gate ----
rashid check "$dir_pub" --data-scope local

# 7. upload (no --delete anywhere; root files last) ----
if [[ $do_upload -eq 1 ]]; then
  for s in $slugs; do
    aws s3 sync "$dir_pub/$s/" "$s3_dest/$s/" --exclude '.portolan/*'
  done
  aws s3 cp "$dir_pub/versions.json" "$s3_dest/versions.json" --content-type application/json
  aws s3 cp "$dir_pub/catalog.json"  "$s3_dest/catalog.json"  --content-type application/json
  for s in $slugs; do
    code=$(curl -s -o /dev/null -w "%{http_code}" -L "https://storage.oceanmetrics.io/gazetteer/$s/collection.json")
    echo "verify $s collection.json: $code"
  done
fi
