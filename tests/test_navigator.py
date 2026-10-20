"""gazetteer/navigator.py: the ProtectedSeas Navigator export (CSV attributes + PS_ID shapefiles) -> features."""
import numpy as np
import pyogrio
import pytest
import shapely
from shapely.geometry import Polygon

from gazetteer.config import load_all
from gazetteer.navigator import fetch_navigator_export, is_marine, probe_navigator_export

CSV = '''ogc_fid,ps_id,site_name,url,location_type,percent_marine_area,total_area,display_simplified,lfp,last_update,purpose
1,CA1,Reserve One,https://agency.example/ca1,0,100,12.5,false,5,2026-08-01,"Protects kelp.
Two lines of purpose text."
2,CA2,Lake Park,,3,0,4.0,false,1,2026-07-01,inland
3,CA3,Island Park,,2,40,8.0,true,3,2026-06-01,island
4,CA4,No Boundary Area,,0,100,1.0,,2,2026-05-01,boundary withheld
'''


def square(x0, y0):
  return Polygon([(x0, y0), (x0 + 1, y0), (x0 + 1, y0 + 1), (x0, y0 + 1)])


@pytest.fixture
def export(tmp_path):
  d = tmp_path / "export"
  (d / "csv").mkdir(parents=True)
  (d / "csv" / "Navigator_API_LFP5Sites_GlobalEEZs_082726.csv").write_text(CSV)
  shp = d / "shp" / "Navigator_API_LFP5Sites_GlobalEEZs_082726"
  shp.mkdir(parents=True)
  geoms = [square(0, 0), square(5, 5), square(10, 10)]
  pyogrio.raw.write(str(shp / "s.shp"), geometry=shapely.to_wkb(geoms), field_data=[np.array(["CA1", "CA2", "CA3"], dtype=object)],
                    fields=["PS_ID"], geometry_type="Polygon", crs="EPSG:4326", driver="ESRI Shapefile")
  return d


def test_export_joins_csv_and_shapefile_on_ps_id_and_keeps_marine_sites(export, tmp_path):
  r = fetch_navigator_export({"url": "https://navigatormap.org/data-request", "path": str(export)}, tmp_path)
  got = {f["properties"]["ps_id"]: f for f in r.features}
  assert sorted(got) == ["CA1", "CA3"]                                    # CA2 inland only, CA4 has no boundary
  assert r.extra["dropped_inland"] == 1 and r.extra["dropped_no_boundary"] == 1 and r.extra["sites_in_export"] == 4
  assert got["CA1"]["properties"]["purpose"] == "Protects kelp.\nTwo lines of purpose text."   # quoted newline
  assert got["CA1"]["properties"]["total_area"] == 12.5
  assert got["CA1"]["geometry"].equals(square(0, 0))
  assert r.data_last_edit == "2026-08-01T00:00:00Z"
  assert {"name": "display_simplified", "type": "bool"} in r.fields
  assert len(r.checksum) == 64


def test_marine_rule():
  assert is_marine(0, 100) and is_marine(2, 0) and is_marine(None, None)
  assert is_marine(1, 15.0)                                                 # inland water with a marine part
  assert not is_marine(3, 0) and not is_marine(1, None)


def test_probe_without_an_export_reports_the_published_checksum(tmp_path):
  # the sync runner has no export: detect must call it unchanged, not rebuild an empty collection
  pub = {"sources": [{"checksum": "abc"}]}
  assert probe_navigator_export({"path": str(tmp_path / "none")}, tmp_path, pub) == {"checksum": "abc"}


NAVIGATOR_CATEGORIES = {"Marine Protected Area", "Fisheries Management Area", "Other", "Water Quality/Human Health Area",
                        "Vessel Restricted Area", "Recreational Area", "Marine Spatial Planning Area",
                        "Jurisdictional Authority Area", "Other Effective Area-Based Conservation Area", "To Be Determined",
                        "Vessel Reporting Area", "Voluntary Conservation Measure Area", "Local Marine Managed Area"}


def navigator_groups():
  return {s: c for s, c in load_all("sources").items() if s.startswith("protectedseas_") and not c.get("superseded_by")}


def test_the_published_single_layer_is_kept_only_as_superseded():
  """its config stays until the groups are published, so an index rebuild keeps its links back, areas and keywords."""
  cfg = load_all("sources")["protectedseas_navigator"]
  assert sorted(cfg["superseded_by"]) == sorted(navigator_groups())
  assert cfg["place_url"] == "{url}" and cfg["area_field"] == "total_area" and cfg["search_fields"] == ["country", "state"]
  assert "include" not in cfg["sources"][0]


def test_navigator_groups_key_on_ps_id_and_use_the_supplied_area():
  groups = navigator_groups()
  assert sorted(groups) == ["protectedseas_fisheries", "protectedseas_human_use", "protectedseas_jurisdiction",
                            "protectedseas_mpa", "protectedseas_other", "protectedseas_vessel"]
  for cfg in groups.values():
    assert cfg["place_id"]["template"] == "PSGID:{ps_id}" and cfg["area_field"] == "total_area"
    assert cfg["license"] == "CC-BY-4.0" and "Zetterlind" in cfg["attribution"] and "navigatormap.org/data-request" in cfg["attribution"]
    assert cfg["id_sort"] and not cfg.get("spatial_sort")
    assert cfg["sources"][0]["path"] == "cache/protectedseas_navigator/export"


def test_navigator_groups_partition_the_13_categories():
  """every Navigator category is in exactly one group, so every site is in exactly one collection (the 30,111-site
  single collection crashed the place page and over-filled low-zoom tiles, 2026-10-20)."""
  cats = [c for cfg in navigator_groups().values() for c in cfg["sources"][0]["include"]["category_name"]]
  assert len(cats) == len(set(cats)) and set(cats) == NAVIGATOR_CATEGORIES


def test_include_keeps_only_listed_category_values(export, tmp_path):
  r = fetch_navigator_export({"url": "u", "path": str(export), "include": {"lfp": [5]}}, tmp_path)
  assert [f["properties"]["ps_id"] for f in r.features] == ["CA1"]        # CA3 is lfp 3
  assert r.extra["not_included"] == 1 and r.extra["excluded"] is None
  r = fetch_navigator_export({"url": "u", "path": str(export), "exclude": {"lfp": [5]}}, tmp_path)
  assert [f["properties"]["ps_id"] for f in r.features] == ["CA3"] and r.extra["excluded"] == ["lfp=5: 1 feature(s)"]
