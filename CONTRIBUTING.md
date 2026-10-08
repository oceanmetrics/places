# Contributing a place to the gazetteer

You can add a place (a reef, a survey area, a mooring, a transect) to the oceanmetrics places gazetteer with a pull
request. One contribution is one place: one geometry and a few lines of metadata. This is the Phase-0 path:
a documented pull request, automatically checked. Building and publishing the merged places is a maintainer step
(see [After merge](#after-merge)).

## 1. Make an id

Every contributed place gets an id `OM:<ulid>`, where `<ulid>` is a 26-character
[ULID](https://github.com/ulid/spec) (Crockford base32: digits and capitals without I, L, O, U; the first character
is 0-7). A colon is not safe in file names, so the directory spells the id with a hyphen:

| place id (in the gazetteer) | directory (in `contrib/`)             |
|-----------------------------|---------------------------------------|
| `OM:01M4DYNT7A321BTARZ0B61B9JQ` | `contrib/OM-01M4DYNT7A321BTARZ0B61B9JQ/` |

Make a fresh one for each place (it is a timestamp plus random bits, so two people never collide):

```sh
python3 -c "import time,secrets;A='0123456789ABCDEFGHJKMNPQRSTVWXYZ';n=(int(time.time()*1000)<<80)|secrets.randbits(80);print(''.join(A[(n>>5*i)&31] for i in range(25,-1,-1)))"
```

The id never changes, even if you later correct the geometry or the name (the geometry is versioned, the id is not).

## 2. Add two files

```
contrib/OM-<ulid>/place.geojson
contrib/OM-<ulid>/meta.json
```

### `place.geojson`

- A single GeoJSON `Feature`, or a `FeatureCollection` holding exactly one Feature.
- Geometry: `Polygon`, `MultiPolygon`, `Point`, `MultiPoint`, `LineString` or `MultiLineString`
  (no `GeometryCollection`). Properties are ignored; put the metadata in `meta.json`.
- **EPSG:4326** longitude/latitude in degrees (GeoJSON RFC 7946). Files in a projected CRS are rejected: reproject
  first (`ogr2ogr -t_srs EPSG:4326 out.geojson in.shp`, or `sf::st_transform(x, 4326)` in R).
- At most **5 MB** and **100,000 vertices**. Simplify if you need to (`ogr2ogr -simplify 0.0001`).
- Ring winding does not matter: the checker corrects it (exterior rings counter-clockwise). A self-intersecting
  polygon is repaired when it can be; one that cannot be repaired is rejected with the reason.
- A polygon that crosses the antimeridian may be drawn either as a ring that jumps (`179` to `-179`) or with
  longitudes past 180; it is split at +/-180 exactly as the build pipeline does. Points and lines must already sit
  inside [-180, 180].

### `meta.json`

```json
{
  "name": "Example Reef",
  "place_type": "habitat",
  "license": "CC-BY-4.0",
  "attribution": "Jane Doe, Example Institute (2026)",
  "contributor_orcid": "0000-0002-1825-0097",
  "source_url": "https://example.org/example-reef",
  "description": "One sentence on what this is and how the boundary was drawn."
}
```

| field               | required | rule |
|---------------------|----------|------|
| `name`              | yes      | non-empty text; shown in search |
| `place_type`        | yes      | one of the controlled list below |
| `license`           | **yes**  | SPDX id, exactly one of `CC0-1.0`, `CC-BY-4.0`, `ODbL-1.0` |
| `attribution`       | yes      | the credit line displayed with the place (CC-BY and ODbL require it) |
| `contributor_orcid` | no       | `0000-0000-0000-000X` (four groups of four digits, the last character a digit or `X`) |
| `source_url`        | no       | `http(s)://` link to the data's origin or documentation |
| `description`       | no       | text |

`place_type` is one of the types the gazetteer already uses (the list lives in `gazetteer/config.py`, `PLACE_TYPES`;
if none fits, ask in the pull request and a maintainer will add one):
`aoa`, `contiguous_zone`, `ecs`, `eez`, `habitat`, `high_seas`, `infrastructure`, `jurisdiction`, `lease`,
`maritime_limit`, `navigation_measure`, `ocean_sea`, `planning_area`, `protected_area`, `restricted_area`,
`station`, `territorial_sea`, `transect`, `world_heritage`.

### Licence: why unlicensed is rejected

The gazetteer redistributes every geometry (GeoParquet, vector tiles, search index) and writes the licence and
attribution onto every row. Data with no stated licence is "all rights reserved" by default, so we may not
redistribute it; a missing or unlisted `license` is therefore an error, never a default. Pick one of:

- `CC0-1.0`: public-domain dedication; no conditions.
- `CC-BY-4.0`: free to reuse with credit to your `attribution`.
- `ODbL-1.0`: free to reuse with credit; adaptations of the database stay open under the same licence.

Only contribute data you created or are licensed to relicense under one of these. Data scraped from a source with
other terms (for example non-commercial licences, or "contact us" terms) cannot be contributed; if it is worth
having, a maintainer may be able to onboard it as a licensed source instead (see `AGENTS.md`, licence tiers).

## 3. Open the pull request

Add only your `contrib/OM-<ulid>/` directory. One place per directory; several places can share a pull request.
Check it locally first:

```sh
uv run --group dev python scripts/validate_contribution.py contrib/OM-<ulid>
```

Exit code 0 means clean (warnings are printed); exit code 1 prints a readable list of what to fix.

### What CI checks

The `validate-contribution` workflow runs that same script on each contribution directory a pull request touches,
and fails the check if any is rejected. It checks:

1. directory name is `OM-<ulid>` and contains `place.geojson` and `meta.json`;
2. `place.geojson` parses as JSON, is one Feature (or a FeatureCollection of one), is within 5 MB and 100,000 vertices;
3. CRS is EPSG:4326 (a different `crs` member, or coordinates that are not degrees, are rejected);
4. the geometry is valid: winding is corrected, repairable polygons are repaired (warning), unfixable ones are
   rejected; polygons are split at the antimeridian;
5. `meta.json` has `name`, a known `place_type`, a `license` from the three above, and `attribution`; an ORCID and
   `source_url`, when given, are well formed;
6. **warning only:** the same `name` already exists with the same `place_type` among the staged or published
   collections or other contributions. Check that it is not a duplicate; a deliberate re-use is fine.

A warning does not fail the check. CI does not comment on the pull request; open the failed check's log for the list.

## After merge

Merging puts your files in `contrib/` on `main`; it does not publish them. A maintainer then runs the build, which
reads every merged contribution, normalises the geometry (valid, counter-clockwise, split at +/-180), stamps each
place with its `OM:<ulid>` id, licence and attribution, and writes them into a `contributions` collection
(GeoParquet, PMTiles, STAC) that is published with the rest of the gazetteer and appears in search and the map.

**That build step is future work**: today, merged contributions are validated and stored, and are not yet published.
Contributions marked `"example": true` in `meta.json` (below) are documentation and will always be skipped by it.

## Worked example

[`contrib/OM-01EXAMPE000000000000000000/`](contrib/OM-01EXAMPE000000000000000000) is a complete, valid contribution
(a made-up box off Point Conception). It is **documentation only**: `meta.json` carries `"example": true`, so the
publish build skips it, but the test suite validates it (`tests/test_contribution.py`) so it can never drift from the
rules. Copy it as a starting point, give your copy a new id, and drop the `example` key.

## Updating or removing a place

To correct a geometry or the metadata, open a pull request editing the files under the same directory; the id stays.
To withdraw a place, open a pull request deleting its directory (or ask a maintainer); published copies are removed
at the next build.
