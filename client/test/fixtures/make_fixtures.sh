#!/usr/bin/env bash
# regenerate the tiny offline fixtures the tests read (needs the duckdb CLI with the spatial extension):
#   bash test/fixtures/make_fixtures.sh
set -euo pipefail
cd "$(dirname "$0")"
duckdb <<'SQL'
LOAD spatial;

-- two collections, WKB geometry split at +/-180, sorted by place_id, 2 rows per row group so a lookup reads one group
CREATE TEMP TABLE leases AS
SELECT * FROM (VALUES
  ('FX:A-1',  'FX', 'A-1', 'Alpha lease',          'lease', 'active',    'POLYGON((-124 33,-123 33,-123 34,-124 34,-124 33))'),
  ('FX:B-2',  'FX', 'B-2', 'Bravo lease',          'lease', 'cancelled', 'POLYGON((-122 35,-121 35,-121 36,-122 36,-122 35))'),
  ('FX:C-3',  'FX', 'C-3', 'Charlie lease',        'lease', 'active',    'POLYGON((-120 37,-119 37,-119 38,-120 38,-120 37))'),
  ('FX:D-4',  'FX', 'D-4', 'Delta easement',       'easement', 'active', 'POLYGON((-118 39,-117 39,-117 40,-118 40,-118 39))'),
  ('FX:PM',   'FX', 'PM',  'Pacific Meridian Mon', 'lease', 'active',
     'MULTIPOLYGON(((170 20,180 20,180 22,170 22,170 20)),((-180 20,-170 20,-170 22,-180 22,-180 20)),((-165 21,-164 21,-164 22,-165 22,-165 21)))'),
  ('FX:Z-9',  'FX', 'Z-9',  'Zulu lease',          'lease', 'active',    'POLYGON((-100 25,-99 25,-99 26,-100 26,-100 25))')
) t(place_id, authority, source_id, name, place_type, status, wkt);
COPY (
  SELECT place_id, authority, source_id, name, place_type, status,
         round(ST_Area_Spheroid(ST_FlipCoordinates(g)) / 1e6, 1) AS area_km2,
         {'xmin': ST_XMin(g), 'ymin': ST_YMin(g), 'xmax': ST_XMax(g), 'ymax': ST_YMax(g)} AS bbox,
         ST_AsWKB(g) AS geometry
  FROM (SELECT *, ST_GeomFromText(wkt) AS g FROM leases)
  ORDER BY place_id
) TO 'fx_leases/places.parquet' (FORMAT parquet, ROW_GROUP_SIZE 2, COMPRESSION snappy);

CREATE TEMP TABLE aoa AS
SELECT * FROM (VALUES
  ('AOA:N1', 'AOA', 'N1', 'Northern aquaculture area', 'aoa', 'identified', 'POLYGON((-123 36,-122 36,-122 37,-123 37,-123 36))'),
  ('AOA:S2', 'AOA', 'S2', 'Southern aquaculture area', 'aoa', 'identified', 'POLYGON((-119 32,-118 32,-118 33,-119 33,-119 32))'),
  -- the same place_id as in fx_leases, in another collection (BOEM:OCS-P 0562 is in two live collections)
  ('FX:C-3', 'AOA', 'C-3', 'Charlie lease (AOA copy)', 'lease', 'identified', 'POLYGON((-90 28,-89 28,-89 29,-90 29,-90 28))')
) t(place_id, authority, source_id, name, place_type, status, wkt);
COPY (
  SELECT place_id, authority, source_id, name, place_type, status,
         round(ST_Area_Spheroid(ST_FlipCoordinates(g)) / 1e6, 1) AS area_km2,
         {'xmin': ST_XMin(g), 'ymin': ST_YMin(g), 'xmax': ST_XMax(g), 'ymax': ST_YMax(g)} AS bbox,
         ST_AsWKB(g) AS geometry
  FROM (SELECT *, ST_GeomFromText(wkt) AS g FROM aoa)
  ORDER BY place_id
) TO 'fx_aoa/places.parquet' (FORMAT parquet, ROW_GROUP_SIZE 2, COMPRESSION snappy);

-- the index: no geometry, zstd (exercises hyparquet-compressors).
-- THIS MUST MIRROR the output of scripts/build_index.py (INDEX_SCHEMA): same columns, order and types as the LIVE
-- https://storage.oceanmetrics.io/gazetteer/index/places_index.parquet. (the old fixture had `centroid DOUBLE[]` and
-- TIMESTAMPTZ `updated`, which the live index never had, so the tests passed while production read null centroids.)
-- check against the live schema with:
--   duckdb -c "DESCRIBE SELECT * FROM read_parquet('https://storage.oceanmetrics.io/gazetteer/index/places_index.parquet')"
-- place_id varchar, name varchar, authority varchar, place_type varchar, geom_type varchar, collection varchar,
-- bbox struct(xmin double, ymin double, xmax double, ymax double), centroid_lon double, centroid_lat double,
-- area_km2 double, license varchar, attribution varchar, version varchar, updated varchar.
-- a place cut at the antimeridian (FX:PM) carries the UNWRAPPED bbox (xmax beyond 180), as build_index.py writes it.
COPY (
  SELECT place_id::VARCHAR AS place_id, name::VARCHAR AS name, authority::VARCHAR AS authority, place_type::VARCHAR AS place_type,
         CASE WHEN place_id = 'FX:PM' THEN 'MultiPolygon' ELSE 'Polygon' END::VARCHAR AS geom_type,
         collection::VARCHAR AS collection,
         CASE WHEN place_id = 'FX:PM' THEN {'xmin': 170.0, 'ymin': 20.0, 'xmax': 196.0, 'ymax': 22.0}
              ELSE {'xmin': bbox.xmin, 'ymin': bbox.ymin, 'xmax': bbox.xmax, 'ymax': bbox.ymax} END AS bbox,
         (CASE WHEN place_id = 'FX:PM' THEN -179.8 ELSE (bbox.xmin + bbox.xmax) / 2 END)::DOUBLE AS centroid_lon, ((bbox.ymin + bbox.ymax) / 2)::DOUBLE AS centroid_lat,
         area_km2::DOUBLE AS area_km2,
         'CC-PDDC'::VARCHAR AS license,
         (CASE collection WHEN 'fx_leases' THEN 'Fixture Agency, via MarineCadastre. Processed by Ocean Metrics.'
                          ELSE 'NOAA AOA program. Processed by Ocean Metrics.' END)::VARCHAR AS attribution,
         (CASE collection WHEN 'fx_leases' THEN '1.0.3' ELSE '2.0.0' END)::VARCHAR AS version,
         '2026-10-01T12:00:00Z'::VARCHAR AS updated
  FROM (SELECT 'fx_leases' AS collection, * FROM read_parquet('fx_leases/places.parquet')
        UNION ALL BY NAME SELECT 'fx_aoa' AS collection, * FROM read_parquet('fx_aoa/places.parquet'))
  ORDER BY collection, place_id
) TO 'index/places_index.parquet' (FORMAT parquet, ROW_GROUP_SIZE 4, COMPRESSION zstd);

-- a larger collection (600 small polygons) so a lookup by id can be shown to read a fraction of the file
COPY (
  SELECT 'BIG:' || lpad(i::varchar, 4, '0') AS place_id, 'BIG' AS authority, i::varchar AS source_id,
         'Big place ' || i AS name, 'station' AS place_type, 'active' AS status, 1.0 AS area_km2,
         {'xmin': ST_XMin(g), 'ymin': ST_YMin(g), 'xmax': ST_XMax(g), 'ymax': ST_YMax(g)} AS bbox,
         ST_AsWKB(g) AS geometry
  FROM (SELECT i, ST_Buffer(ST_Point(-130 + (i % 60) * 0.5, 20 + (i // 60) * 0.5), 0.1, 6) AS g FROM range(600) t(i))
  ORDER BY place_id
) TO 'fx_big/places.parquet' (FORMAT parquet, COMPRESSION snappy);
SQL

# duckdb cannot write row groups smaller than 2048 rows: rewrite the large one with 50 rows per group, so a lookup
# by id reads one row group (the stats prune the rest)
uv run --project ../../.. python - <<'PY'
import pyarrow.parquet as pq
t = pq.read_table("fx_big/places.parquet")
pq.write_table(t, "fx_big/places.parquet", row_group_size=50, compression="snappy")
print("fx_big row groups:", pq.ParquetFile("fx_big/places.parquet").num_row_groups)
PY

# layers.json also at the root of the fixture base: the client falls back to it when index/layers.json is 404/403
cp index/layers.json layers.json
