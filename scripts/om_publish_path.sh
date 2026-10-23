#!/usr/bin/env bash
# sourced by the publish scripts: sets P to the one publisher of the bucket, oceanmetrics/platform scripts/om-publish.sh
# (both stores, R2 then S3; never deletes; dry run unless --really). OM_PUBLISH wins (the workflows check platform out
# and set it); else a platform checkout next to this repo; else ~/Github/oceanmetrics/platform. a missing one stops.
P="${OM_PUBLISH:-}"
if [ -z "$P" ]; then
  for c in "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/platform/scripts/om-publish.sh" \
           "$HOME/Github/oceanmetrics/platform/scripts/om-publish.sh"; do
    if [ -x "$c" ]; then P="$c"; break; fi
  done
fi
[ -n "$P" ] && [ -x "$P" ] || { echo "om-publish.sh not found (set OM_PUBLISH to oceanmetrics/platform scripts/om-publish.sh)" >&2; exit 1; }
