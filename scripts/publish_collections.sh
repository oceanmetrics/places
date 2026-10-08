#!/usr/bin/env bash
# publish staged collections into the live gazetteer catalog:
# copy -> portolan add -> restore shared files -> fix sizes/checksums/roles -> rashid gate -> upload -> verify
#
# usage: scripts/publish_collections.sh [--no-upload] [--republish [--version V] [--note TEXT]] <slug> [<slug> ...]
#
#   (default)     FIRST publish: a fresh catalog/pub/<slug>/ per run, portolan add records 1.0.0 itself.
#   --republish   a new version of collections that are already published (the pulled catalog/pub/<slug>/ and its
#                 versions.json ledger must exist). the slug dir is NOT removed: the staged assets are copied over it,
#                 the pulled ledger is kept (restored after `portolan add`), then
#                     portolan version bump <slug> V -m "<note>" -y
#                 makes the ledger end at V exactly once. defaults: V=1.0.1, note="row-group layout for range reads".
#                 build the staged slug with the same version first: uv run build.py build --slug <slug> --version V
#   env PLACES_PUB / PLACES_STAGING override catalog/pub and catalog/staging (tests, scratch copies).
#
# prerequisites (see catalog/staging/RUNBOOK_PUBLISH.md):
#   - catalog/staging/<slug>/ built and green (uv run build.py check)
#   - catalog/pub/ holds the published metadata tree:
#     aws s3 sync s3://oceanmetrics.io-public/gazetteer/ catalog/pub/ \
#       --exclude '*.parquet' --exclude '*.pmtiles' --exclude '*.tif' --exclude '*.nc'
#
# guards the portolan 0.8.0 quirks (collateral rewrites, stale checksums, pmtiles role flip,
# root versions.json), per erddap-places/catalog/publish_places.sh and integrate_erin_layers.sh:
#   - `add` rewrites OTHER collections' collection.json and the root catalog.json: snapshot, restore.
#   - `add` auto-creates a PATCH version in the collection ledger when files changed against it, so a later `version bump`
#     reports "no changes" (or the ledger would end at the auto version, not the requested one). first publish: add's own
#     1.0.0 is the ledger. republish: snapshot the ledger, let add run, restore the snapshot, THEN bump to the requested
#     version, so the ledger gains exactly one new entry (V) on top of the pulled history.
#   - `bump` leaves the root versions.json summary at the old version: rewritten from the ledger below.
#   - `add` leaves stale file:size / file:checksum on some assets and re-extracts the PMTiles role as `data`: recomputed.

set -euo pipefail

do_upload=1
republish=0
version="1.0.1"
note="row-group layout for range reads"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-upload) do_upload=0; shift ;;
    --republish) republish=1; shift ;;
    --version)   version="${2:?--version needs a value}"; shift 2 ;;
    --note)      note="${2:?--note needs a value}"; shift 2 ;;
    --*)         echo "unknown option $1" >&2; exit 1 ;;
    *)           break ;;
  esac
done
[[ $# -ge 1 ]] || { echo "usage: $0 [--no-upload] [--republish [--version V] [--note TEXT]] <slug> ..." >&2; exit 1; }
slugs="$*"
# the version the ledger must end at
if [[ $republish -eq 1 ]]; then want="$version"; else want="1.0.0"; fi

dir_repo="$(cd "$(dirname "$0")/.." && pwd)"
dir_pub="${PLACES_PUB:-$dir_repo/catalog/pub}"
dir_staging="${PLACES_STAGING:-$dir_repo/catalog/staging}"
s3_dest="s3://oceanmetrics.io-public/gazetteer"

# 1. snapshot every shared file portolan add may rewrite ----
snap="$(mktemp -d)"
trap 'rm -rf "$snap"' EXIT
shared=$(cd "$dir_pub" && find . \( -name collection.json -o -name versions.json \) -not -path '*/items/*' | sort)
for f in $shared catalog.json; do
  mkdir -p "$snap/$(dirname "$f")"
  cp "$dir_pub/$f" "$snap/$f" 2>/dev/null || true
done

# 2. copy staging into the pub tree. first publish: a fresh dir, so a re-run gets a fresh 1.0.0 ledger rather than
#    portolan auto-bumping a leftover one. republish: keep the dir (and its pulled ledger), copy over it ----
for s in $slugs; do
  [[ -d "$dir_staging/$s" ]] || { echo "not staged: $s" >&2; exit 1; }
  if [[ $republish -eq 1 ]]; then
    [[ -f "$dir_pub/$s/versions.json" ]] || { echo "--republish: no pulled ledger at $dir_pub/$s/versions.json (pull the published tree first)" >&2; exit 1; }
    python3 - "$dir_pub/$s/versions.json" "$version" "$s" <<'PYEOF'
import json, sys
led = json.load(open(sys.argv[1]))
have = [v["version"] for v in led["versions"]]
if sys.argv[2] in have:
    sys.exit(f"{sys.argv[3]}: the pulled ledger already has {sys.argv[2]} ({have}); nothing to republish")
PYEOF
  else
    rm -rf "$dir_pub/$s"
  fi
  mkdir -p "$dir_pub/$s"
  cp -R "$dir_staging/$s/." "$dir_pub/$s/"
done

# 3. portolan add (records 1.0.0 itself on a first add, an auto patch version on a republish; renders thumbnails) ----
cd "$dir_pub"
# shellcheck disable=SC2046
portolan add $(for s in $slugs; do echo "$s/"; done) --force --force-thumbnails

# 4. restore the snapshotted shared files. first publish: keep the target slugs' fresh ledgers (add's 1.0.0).
#    republish: restore the target slugs' PULLED ledger too, then bump to the requested version ----
for f in $shared catalog.json; do
  case "$f" in *"/items/"*) continue ;; esac
  keep=0
  for s in $slugs; do [[ "$f" == "./$s/"* ]] && keep=1; done
  if [[ $republish -eq 1 && "$f" == */versions.json && $keep -eq 1 ]]; then keep=0; fi
  [[ $keep -eq 0 ]] && [[ -f "$snap/$f" ]] && cp "$snap/$f" "$dir_pub/$f"
done
if [[ $republish -eq 1 ]]; then
  for s in $slugs; do
    portolan version bump "$s" "$version" -m "$note" -y
  done
fi

# 5. fixups: child links, asset sizes/checksums, pmtiles role, root versions entries ----
python3 - "$dir_pub" "$slugs" "$want" <<'PYEOF'
import datetime, hashlib, json, os, sys
d, slugs, want = sys.argv[1], sys.argv[2].split(), sys.argv[3]
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
    hist = [v["version"] for v in led["versions"]]
    assert led["current_version"] == want, f"{s}: ledger at {led['current_version']}, expected {want}"
    assert hist.count(want) == 1 and hist[-1] == want, f"{s}: ledger history {hist} must end at {want} exactly once"
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

# 6. gate: fail only on ERROR findings in the collections being published; the pulled tree carries
#    pre-existing findings in other collections (e.g. the stats item links), which are reported, not fatal ----
rashid check "$dir_pub" --data-scope local --all > /tmp/rashid_gate.txt 2>&1 || true
python3 - "$slugs" <<'PYEOF'
import re, sys
slugs = set(sys.argv[1].split())
sev = None
mine, elsewhere = [], 0
for line in open("/tmp/rashid_gate.txt"):
    m = re.match(r"^(error|warning|info)\s", line)
    if m:
        sev = m.group(1)
        continue
    fm = re.match(r"^\s+(\S+?)/", line)
    if fm and sev == "error":
        if fm.group(1) in slugs:
            mine.append(line.rstrip())
        else:
            elsewhere += 1
if mine:
    print("GATE FAILED: error findings in the publish set:")
    print("\n".join(mine))
    sys.exit(1)
print(f"gate ok: no errors in the publish set ({elsewhere} pre-existing error lines elsewhere in the pulled tree)")
PYEOF

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
