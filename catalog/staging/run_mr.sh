#!/usr/bin/env bash
# SOURCES=sources_mr limits the configs loaded to a private copy of sources/marineregions (other agents share the dir).
# build the Marine Regions collections serially (the mini); per-slug stamps and the build output go to logs/mrprod.log,
# logs/mrprod.done marks the end. usage: catalog/staging/run_mr.sh mr_eez mr_territorial_seas ...
set -u
cd "$(dirname "$0")/../.."          # repo root
mkdir -p logs cache/mr
rm -f logs/mrprod.done
for slug in "$@"; do
  echo "[$(date -u +%FT%TZ)] START $slug" >> logs/mrprod.log
  t0=$(date +%s)
  uv run build.py build --sources "${SOURCES:-sources}" --slug "$slug" --cache cache/mr --delay 1.0 >> logs/mrprod.log 2>&1
  rc=$?
  echo "[$(date -u +%FT%TZ)] END $slug rc=$rc seconds=$(( $(date +%s) - t0 ))" >> logs/mrprod.log
done
touch logs/mrprod.done
