# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyarrow>=17",
#   "shapely>=2.1",
#   "pyproj>=3.6",
#   "pyyaml>=6",
#   "requests>=2.31",
#   "pyogrio>=0.9",
#   "numpy>=1.26",
# ]
# ///
"""build the "Erin's layers" gazetteer collections: BOEM wind leases / planning areas / oil and gas, NOAA SoCal AOAs.

  uv run build.py build  [--slug boem_wind_leases ...] [--version 1.0.0]
  uv run build.py detect [--published-base https://storage.oceanmetrics.io/gazetteer]
  uv run build.py check

fetch -> normalise -> GeoParquet 1.1 (EPSG:4326, WKB, bbox struct, antimeridian split) -> PMTiles (tippecanoe)
-> STAC collection, staged in catalog/staging/<slug>/. per-layer settings live in sources/<authority>/<layer>.yml;
the code is the package gazetteer/ (tests: `uv run --group dev pytest -q`). needs `tippecanoe` on PATH.
"""
import sys

from gazetteer.cli import main

if __name__ == "__main__":
  sys.exit(main())
