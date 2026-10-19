"""build the prototype's data/: values.json (public derived table) and eez.pmtiles (INTERNAL vector tiles, local only).

  uv run proto/eez_sdg/build.py            # then: uv run proto/eez_sdg/serve.py  ->  http://localhost:5190/

the EEZ vector tiles are the internal mr_eez copy (env PLACES_INTERNAL, default ~/data/oceanmetrics/places-internal),
linked, not copied; data/ is git-ignored and must never be uploaded until VLIZ agrees how these tiles may be served.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from sdg import SERIES, eez_values, fetch_series  # noqa: E402

INTERNAL = Path(os.environ.get("PLACES_INTERNAL", Path.home() / "data/oceanmetrics/places-internal"))


def main() -> int:
  data = HERE / "data"
  data.mkdir(exist_ok=True)
  eez_dir = INTERNAL / "mr_eez"
  cols = ["source_id", "name", "pol_type", "un_ter1", "un_sov1"]
  eezs = pq.read_table(eez_dir / "places.parquet", columns=cols).to_pylist()
  raw = {code: fetch_series(code, data / "sdg_cache") for code in SERIES}
  values = eez_values(eezs, {code: d["data"] for code, d in raw.items()})
  meta = {code: {**SERIES[code], "description": raw[code]["data"][0]["seriesDescription"],
                 "source": raw[code]["data"][0]["source"],
                 "link": f"https://unstats.un.org/sdgs/dataportal/database?series={code}"} for code in SERIES}
  coll = json.loads((eez_dir / "collection.json").read_text())
  out = {"series": meta, "eez": values, "eez_attribution": coll.get("gazetteer:attribution") or coll.get("description")}
  (data / "values.json").write_text(json.dumps(out, indent=1))
  link = data / "eez.pmtiles"
  if link.is_symlink() or link.exists():
    link.unlink()
  link.symlink_to(eez_dir / "places.pmtiles")
  for code in SERIES:
    n = sum(1 for v in values.values() if v[code])
    print(f"{code}: {n} of {len(values)} EEZs with a value")
  return 0


if __name__ == "__main__":
  sys.exit(main())
