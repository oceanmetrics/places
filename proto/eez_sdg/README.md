# EEZ × SDG 14 prototype (local only)

A global choropleth of UN SDG 14 indicators on true EEZ vector tiles. It is the case we are discussing with VLIZ:
summary values drawn on Marine Regions boundaries, which the publisher's PNG map tiles cannot do.

```sh
uv run proto/eez_sdg/build.py    # data/values.json + data/eez.pmtiles (a link to the internal mr_eez tiles)
uv run proto/eez_sdg/serve.py    # http://localhost:5190/ (127.0.0.1 only, with HTTP Range for PMTiles)
```

- **Boundaries:** `mr_eez` vector tiles from the internal store (`~/data/oceanmetrics/places-internal/mr_eez/`,
  env `PLACES_INTERNAL`). They are a reference collection, so `data/` is git-ignored and is **never uploaded**. That
  holds until VLIZ agrees how such tiles may be served; see the hold table in `catalog/staging/RUNBOOK_PUBLISH.md`.
- **Values:** the UN SDG Global Database API (`unstats.un.org/sdgapi`), latest year per M49 area. Series:
  - 14.5.1 `ER_MRN_MPA`
  - 14.1.1 `EN_MAR_CHLDEV`
  - 14.6.1 `ER_REG_UNFCIM`

  An EEZ takes the value of its territory (`un_ter1`), else of its sovereign (`un_sov1`). Joint regimes and
  overlapping claims get no value (`sdg.py`, tested in `tests/test_eez_sdg.py`). `values.json` is a public
  derived table: values keyed by MRGID, with no geometry.
- **Credit:**
  - The page carries the Marine Regions citation and DOI.
  - Each EEZ links to its Marine Regions page.
  - A toggle overlays the official Marine Regions map tiles (VLIZ GeoWebCache) for comparison.
