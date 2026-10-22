-- the synthetic coverage.parquet of indicators.test.ts (the columns of indicators' schema/coverage.schema.json that the
-- cards read, plus spark): duckdb < make_coverage.sql, run in this folder
copy (select place_id, coll, indicator, time_grain, n_periods::integer n_periods, last_time, last_value::double last_value,
             last_class, status_method, status, trend, why, sentence, spark from (values
 ('NMS:A','places','erddap:sst','year',30,'2025-01-01',15.6605,null,'iea-sd','within','flat',null,'SST in A over the last 5 years (2021–2025) was within 1 SD of its 1996–2025 mean, and changed by less than 1 SD.','[]'),
 ('NMS:A','places','erddap:sst','month',360,'2025-07-01',17.2,null,null,null,null,null,null,'[]'),
 ('NMS:A','places','cmems:chl','year',33,'2025-01-01',1.2685,null,'iea-sd','above','up',null,'Chlorophyll-a in A over the last 5 years (2021–2025) was more than 1 SD above its 1993–2025 mean, and rose by more than 1 SD.','[]'),
 ('NMS:A','places','erddap:baa','year',10,'2025-01-01',0.8184,'0','values',null,null,'categorical: shown as class shares, with no status','Bleaching alert in A: No Stress over 82% of the area in 2025.','[]'),
 ('NMS:A','places','erddap:short','year',1,'2023-01-01',9.2444,null,'iea-sd',null,null,'1 year of record, fewer than the 10 a status needs','Bottom temperature in A: 9.24 °C in 2023; no status relative to its own record (1 year of record, fewer than the 10 a status needs).','[]'),
 ('NMS:A','places','erddap:unlisted','year',5,'2025-01-01',1.0,null,'values',null,null,null,'not in the manifest','[]'),
 ('MRGID:1','mr_eez','obis:species','year',50,'2024-01-01',1234.0,null,'values',null,null,null,'Species in Z: 1234 species in 2024.','[]'),
 ('MRGID:1','mr_eez','obis:species','all',1,null,5000.0,null,null,null,null,null,null,'[]'),
 ('MRGID:1','mr_eez','obis:es50','year',40,'2024-01-01',45.31,null,'values',null,null,null,'ES(50) in Z: 45.3 species in 2024.','[]'),
 ('MRGID:1','mr_eez','obis:density:fish','year',0,null,null,null,'values',null,null,null,null,'[]'),
 ('MRGID:1','mr_eez','obis:density:fish','decade',3,'2020-01-01',0.5,null,null,null,null,null,null,'[]'),
 ('MRGID:1','mr_eez','sdg:mpa','year',20,'2023-01-01',12.345,null,'values',null,null,null,'MPA cover in Z: 12.3% in 2023.','[]'),
 ('NMS:EMPTY','places','erddap:sst','year',0,null,null,null,'iea-sd',null,null,'no values',null,'[]')
) t(place_id, coll, indicator, time_grain, n_periods, last_time, last_value, last_class, status_method, status, trend, why, sentence, spark))
to 'coverage.parquet' (format parquet, compression snappy);
