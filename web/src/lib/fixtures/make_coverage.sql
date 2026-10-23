-- the synthetic coverage.parquet of indicators.test.ts, a copy of oceanmetrics/platform
-- packages/catalog/fixtures/indicators/ (change both together): the columns of the indicators coverage table, with
-- n_periods an int64 as the builder writes it. run in this folder: duckdb < make_coverage.sql
copy (select place_id, place_name, coll, place_coll, indicator, time_grain, t0, t1, n_periods::bigint n_periods, last_time,
             last_value::double last_value, last_class, status_method, status, trend, why, sentence, spark from (values
 ('NMS:A','A','places','noaa_sanctuaries','erddap:sst','year','1996-01-01','2025-01-01',30,'2025-01-01',15.6605,null,'iea-sd','within','flat',null,'SST in A over the last 5 years (2021–2025) was within 1 SD of its 1996–2025 mean, and changed by less than 1 SD.','[]'),
 ('NMS:A','A','places','noaa_sanctuaries','erddap:sst','month','1996-01-01','2025-07-01',360,'2025-07-01',17.2,null,null,null,null,null,null,'[]'),
 ('NMS:A','A','places','noaa_sanctuaries','cmems:chl','year','1993-01-01','2025-01-01',33,'2025-01-01',1.2685,null,'iea-sd','above','up',null,'Chlorophyll-a in A over the last 5 years (2021–2025) was more than 1 SD above its 1993–2025 mean, and rose by more than 1 SD.','[]'),
 ('NMS:A','A','places','noaa_sanctuaries','erddap:baa','year','2016-01-01','2025-01-01',10,'2025-01-01',0.8184,'0','values',null,null,'categorical: shown as class shares, with no status','Bleaching alert in A: No Stress over 82% of the area in 2025.','[]'),
 ('NMS:A','A','places','noaa_sanctuaries','erddap:short','year','2023-01-01','2023-01-01',1,'2023-01-01',9.2444,null,'iea-sd',null,null,'1 year of record, fewer than the 10 a status needs','Bottom temperature in A: 9.24 °C in 2023; no status relative to its own record (1 year of record, fewer than the 10 a status needs).','[]'),
 ('NMS:A','A','places','noaa_sanctuaries','erddap:unlisted','year','2021-01-01','2025-01-01',5,'2025-01-01',1.0,null,'values',null,null,null,'not in the manifest','[]'),
 ('MRGID:1','Z','mr_eez','mr_eez','obis:species','year','1975-01-01','2024-01-01',50,'2024-01-01',1234.0,null,'values',null,null,null,'Species in Z: 1234 species in 2024.','[]'),
 ('MRGID:1','Z','mr_eez','mr_eez','obis:species','all',null,null,1,null,5000.0,null,null,null,null,null,null,'[]'),
 ('MRGID:1','Z','mr_eez','mr_eez','obis:es50','year','1985-01-01','2024-01-01',40,'2024-01-01',45.31,null,'values',null,null,null,'ES(50) in Z: 45.3 species in 2024.','[]'),
 ('MRGID:1','Z','mr_eez','mr_eez','obis:density:fish','year',null,null,0,null,null,null,'values',null,null,null,null,'[]'),
 ('MRGID:1','Z','mr_eez','mr_eez','obis:density:fish','decade','2000-01-01','2020-01-01',3,'2020-01-01',0.5,null,null,null,null,null,null,'[]'),
 ('MRGID:1','Z','mr_eez','mr_eez','sdg:mpa','year','2004-01-01','2023-01-01',20,'2023-01-01',12.345,null,'values',null,null,null,'MPA cover in Z: 12.3% in 2023.','[]'),
 ('NMS:EMPTY','Empty','places','noaa_sanctuaries','erddap:sst','year',null,null,0,null,null,null,'iea-sd',null,null,'no values',null,'[]')
) t(place_id, place_name, coll, place_coll, indicator, time_grain, t0, t1, n_periods, last_time, last_value, last_class, status_method, status, trend, why, sentence, spark))
to 'coverage.parquet' (format parquet, compression snappy);
