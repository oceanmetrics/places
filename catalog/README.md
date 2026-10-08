# catalog/

The Portolan STAC tree (`catalog.json`, `versions.json`, one directory per collection) is built here and published
to `s3://oceanmetrics.io-public/gazetteer/` (https://storage.oceanmetrics.io/gazetteer/).

- `catalog/staging/<slug>/` holds a fresh build before it is integrated (`uv run build.py build`); `uv run build.py check`
  reports "not built" when it is absent.
- Built artifacts are git-ignored (`*.parquet`, `*.pmtiles`, `*.thumb.jpg`, `collection.json`); `collection.json` stays
  out of git for now. The sync workflow pulls the published copy of a collection before rebuilding it.
- Integrate a staged build with `portolan add <slug>/` from inside this directory, then `rashid check catalog` from the
  repo root before publishing.
