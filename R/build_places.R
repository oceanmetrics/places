# NOTE: copied from oceanmetrics/erddap-places catalog/build_places.R (2026-10-08). it still RUNS FROM erddap-places
# (it uses here::here() paths such as catalog/cache and catalog/places there) until the move to this repo completes;
# edits made here are not picked up by the erddap-places release (publish_places.sh) until then.
# R stays in this repo only for what already works in R (onmsR, mregions2 for the long tail); see AGENTS.md.

# build a gazetteer of 20 marine places (18 noaa sanctuaries from the official onms boundary downloads
# + 1 marineregions eez + 1 protectedseas mpa), each with source_url and source_date
# run with: Rscript catalog/build_places.R

librarian::shelf(
  sf, dplyr, purrr, mregions2, sfarrow, jsonlite, glue, geojsonsf, here, fs, stringr, units, readr,
  quiet = TRUE)

sf::sf_use_s2(TRUE)

dir_repo   <- here::here()
dir_cache  <- fs::path(dir_repo, "catalog", "cache")
dir_places <- fs::path(dir_repo, "catalog", "places")
fs::dir_create(dir_cache)
fs::dir_create(dir_places)

# helper: pick the first available column (case-insensitive) from a set of candidate names ----
pick_col <- function(df, candidates) {
  nms <- names(df)
  hit <- candidates[tolower(candidates) %in% tolower(nms)]
  if (length(hit) == 0) return(NA_character_)
  nms[match(tolower(hit[1]), tolower(nms))]
}

# helper: finalize geometry per spec (valid, 4326, dateline-wrapped, multipolygon) ----
finalize_geom <- function(x) {
  x |>
    sf::st_make_valid() |>
    sf::st_transform(4326) |>
    sf::st_wrap_dateline(options = c("WRAPDATELINE=YES", "DATELINEOFFSET=180")) |>
    sf::st_cast("MULTIPOLYGON")
}

# 1. noaa sanctuaries (official onms boundary downloads) -----------------------------------

# official boundaries are the zipped shapefiles listed at
#   https://sanctuaries.noaa.gov/library/imast_gis.html
# sanctuaries.csv (onmsR) holds the authoritative name and the download url (url_zip) per nms code.
# zips are cached in catalog/cache/imast/<NMS>.zip (git-ignored); delete a zip to re-download it.
sanctuaries <- readr::read_csv(
  "~/Github/noaa-onms/onmsR/data-raw/sanctuaries.csv" |> path.expand(),
  show_col_types = FALSE)

dir_imast <- fs::path(dir_cache, "imast")
fs::dir_create(dir_imast)

read_sanctuary <- function(nms, sanctuary, url_zip) {
  f_zip <- fs::path(dir_imast, glue::glue("{nms}.zip"))
  if (!fs::file_exists(f_zip)) {
    download.file(url_zip, f_zip, mode = "wb", quiet = TRUE)
  }

  # pick the geographic shapefile; skip macos resource forks and the projected albers twin (pmnm)
  shp <- unzip(f_zip, list = TRUE)$Name |>
    stringr::str_subset("\\.shp$") |>
    stringr::str_subset("__MACOSX|Albers", negate = TRUE)
  stopifnot(length(shp) == 1)
  x <- sf::st_read(paste0("/vsizip/", f_zip, "/", shp), quiet = TRUE) |>
    sf::st_zm(drop = TRUE)

  # every zip ships a .prj (nad83, except fknms "GCS_Assumed_Geographic_1" = nad27), so
  # st_transform() below applies the right datum shift; fail loudly if one ever arrives without
  stopifnot(!is.na(sf::st_crs(x)))

  nm <- if (nms == "PMNM") {
    glue::glue("{sanctuary} Marine National Monument")
  } else {
    glue::glue("{sanctuary} National Marine Sanctuary")
  }

  # union all zones / polygons in the zip into one multipolygon per site
  geom <- x |>
    sf::st_make_valid() |>
    sf::st_transform(4326) |>
    sf::st_geometry() |>
    sf::st_union()

  sf::st_sf(
    place_id    = glue::glue("NMS:{nms}"),
    gazetteer   = "NMS",
    name        = nm,
    source_url  = url_zip,
    source_date = format(as.Date(fs::file_info(f_zip)$modification_time)),
    geometry    = geom)
}

places_nms <- purrr::pmap(
  sanctuaries |> select(nms, sanctuary, url_zip),
  read_sanctuary) |>
  bind_rows()

# 2. marineregions mrgid 8439 (pitcairn eez) ------------------------------------------------

mrgid <- 8439
geom_mrgid <- tryCatch(
  mregions2::gaz_geometry(mrgid),
  error = function(e) mregions2::gaz_search(mrgid) |> mregions2::gaz_geometry())
name_mrgid <- mregions2::gaz_search(mrgid)$preferredGazetteerName

place_mrgid <- sf::st_sf(
  place_id    = glue::glue("MRGID:{mrgid}"),
  gazetteer   = "MRGID",
  name        = name_mrgid,
  source_url  = glue::glue("https://marineregions.org/gazetteer.php?p=details&id={mrgid}"),
  source_date = format(Sys.Date()),
  geometry    = sf::st_geometry(geom_mrgid))

# 3. protectedseas psgid 939 (tortugas ecological reserve) --------------------------------

psgid    <- 939
# note: the site's api is actually served under /v2/ (the bare /api/ path 404s)
url_ps   <- glue::glue("https://map.navigatormap.org/v2/api/boundary/area/?gid={psgid}")
f_cache  <- fs::path(dir_cache, glue::glue("psgid_{psgid}.json"))

if (!fs::file_exists(f_cache)) {
  download.file(url_ps, f_cache, quiet = TRUE)
}

body_ps <- readLines(f_cache, warn = FALSE) |>
  paste(collapse = "") |>
  stringr::str_replace('\\{"bounds":(.*)\\}', '\\1')

x_ps <- geojsonsf::geojson_sf(body_ps) |>
  sf::st_zm(drop = TRUE)

col_name_ps <- pick_col(x_ps, c("site_name", "SITE_NAME", "name", "NAME"))
name_ps <- if (is.na(col_name_ps)) "Tortugas Ecological Reserve" else as.character(x_ps[[col_name_ps]][1])

place_psgid <- sf::st_sf(
  place_id    = glue::glue("PSGID:{psgid}"),
  gazetteer   = "PSGID",
  name        = name_ps,
  source_url  = as.character(url_ps),
  source_date = format(as.Date(fs::file_info(f_cache)$modification_time)),
  geometry    = sf::st_union(sf::st_geometry(x_ps)))

# combine, finalize geometry, compute area and bbox --------------------------------------

places <- bind_rows(places_nms, place_mrgid, place_psgid) |>
  mutate(geometry = finalize_geom(geometry))

places <- places |>
  mutate(
    area_km2 = sf::st_area(geometry) |>
      units::set_units(km^2) |>
      as.numeric() |>
      round(1)) |>
  select(place_id, gazetteer, name, area_km2, source_url, source_date, geometry) |>
  arrange(gazetteer, place_id)

# outputs ------------------------------------------------------------------------------

f_parquet <- fs::path(dir_places, "places.parquet")
f_geojson <- fs::path(dir_places, "places.geojson")
f_pmtiles <- fs::path(dir_places, "places.pmtiles")

# write geoparquet via duckdb's spatial extension rather than sfarrow: sfarrow's geo metadata
# (key "schema_version" instead of "version", no "geometry_types") is not readable by duckdb's
# geoparquet reader, so round-trip through a temp geojson and let duckdb write valid geoparquet.
f_tmp_geojson <- fs::path(dir_cache, "places_tmp.geojson")
if (fs::file_exists(f_tmp_geojson)) fs::file_delete(f_tmp_geojson)
sf::st_write(places, f_tmp_geojson, delete_dsn = TRUE, quiet = TRUE)

if (fs::file_exists(f_parquet)) fs::file_delete(f_parquet)
system(glue::glue(
  "duckdb -c \"",
  "INSTALL spatial; LOAD spatial; ",
  "COPY (SELECT place_id, gazetteer, name, area_km2, source_url, CAST(source_date AS DATE) AS source_date, ",
  # bbox is the geoparquet bbox-covering struct (for antimeridian-crossing places such as PMNM it
  # spans -180..180); written here so the output matches what portolan publishes
  "{{'xmin': ST_XMin(geom), 'ymin': ST_YMin(geom), 'xmax': ST_XMax(geom), 'ymax': ST_YMax(geom)}} AS bbox, ",
  "geom AS geometry FROM ST_Read('{f_tmp_geojson}')) ",
  "TO '{f_parquet}' (FORMAT PARQUET);\""))
fs::file_delete(f_tmp_geojson)

if (fs::file_exists(f_geojson)) fs::file_delete(f_geojson)
sf::st_write(places, f_geojson, delete_dsn = TRUE, quiet = TRUE)

# tile metadata: name, description and attribution (shown by maplibre's attribution control)
tile_name <- "places"
tile_desc <- paste(
  "Ocean Metrics gazetteer: 20 marine place polygons (18 NOAA National Marine Sanctuaries,",
  "1 MarineRegions EEZ, 1 ProtectedSeas MPA); layer 'places', keyed by place_id.")
tile_attr <- paste0(
  '<a href="https://sanctuaries.noaa.gov" target="_blank">NOAA ONMS</a> | ',
  '<a href="https://www.marineregions.org" target="_blank">MarineRegions.org</a> (CC-BY-4.0) | ',
  '<a href="https://protectedseas.net" target="_blank">ProtectedSeas</a>')

system2(
  "/opt/homebrew/bin/tippecanoe",
  c("-o", shQuote(f_pmtiles), "-l", "places", "-zg",
    "-n", shQuote(tile_name), "-N", shQuote(tile_desc), "--attribution", shQuote(tile_attr),
    "--drop-densest-as-needed", "--extend-zooms-if-still-dropping", "--force", shQuote(f_geojson)))

fs::file_delete(f_geojson)

# summary --------------------------------------------------------------------------------

summary_tbl <- places |>
  sf::st_drop_geometry() |>
  bind_cols(n_parts = sapply(sf::st_geometry(places), \(g) length(g))) |>
  select(place_id, name, n_parts, area_km2)

print(summary_tbl)
