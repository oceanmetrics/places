"""the 12 layers added from the MarineCadastre scan (2026-10-20, notes om/plans_todo/2026-10-20_marinecadastre-scan.md
section 3a): config rules, one test per id / name / status rule with a synthetic fixture, and checks on the staged
outputs (skipped for a collection that was not built)."""
import json
import re

import pyarrow.parquet as pq
import pytest
import shapely

from conftest import ROOT, STAGING, square
from gazetteer.config import PLACE_TYPES, load_all, validate_config
from gazetteer.fetch import SourceResult
from gazetteer.fmt import render
from gazetteer.ids import build_place_ids, check_place_ids
from gazetteer.status import resolve_status, upstream_status
from gazetteer.table import build_rows, to_table
from gazetteer.validate import check_parquet, check_pmtiles

CFGS = load_all(ROOT / "sources")

# slug -> (features served 2026-10-20, place_type, authority, a valid example id, an id that must not match)
SCAN = {
  "noaa_efh": (782, "habitat", "NMFS", "NMFS:EFH:834", "NMFS:EFH:x"),
  "epa_ocean_disposal_sites": (96, "disposal_site", "EPA", "EPA:US193", "EPA:193"),
  "uscg_anchorages": (679, "navigation_measure", "USCG", "USCG:ANCH:110-182-a-1:anchorage-a", "USCG:ANCH:110.182(a)(1)"),
  "boem_ocs_withdrawals": (28, "restricted_area", "BOEM", "BOEM:WD:GRNMS", "BOEM:WD:grnms"),
  "noaa_coral_protection_areas": (19, "managed_area", "NMFS", "NMFS:CPA:block-canyon", "NMFS:CPA:Block Canyon"),
  "noaa_narw_sma": (10, "managed_area", "NMFS", "NMFS:SMA:cape-cod-bay", "NMFS:SMA:"),
  "noaa_cetacean_bia": (131, "habitat", "NMFS", "NMFS:BIA:3", "NMFS:BIA:three"),
  "boem_marine_minerals_leases": (78, "lease", "BOEM", "BOEM:OCS-G 23707:part", "BOEM:OCS-G-23707"),
  "noaa_pilot_boarding_areas": (168, "navigation_measure", "MC", "MC:pilot:saint-thomas-island:part-3", "MC:pilot:"),
  "noaa_lightering_zones": (122, "navigation_measure", "MC", "MC:lightering:southtex", "USCG:lightering:southtex"),
  "navy_operating_areas": (35, "military_area", "NAVY", "NAVY:OPAREA:vacapes-oparea", "NAVY:OPAREA:VACAPES"),
  "navy_special_use_airspace": (769, "military_area", "NAVY", "NAVY:SUA:warning:key-west-fl:part-2", "NAVY:SUA:key-west-fl"),
}
BIA_CITATION = "Van Parijs, S. M., Curtice, C., & Ferguson, M. C. (Eds.). (2015)"


def staged(slug):
  d = STAGING / slug
  if not (d / "places.parquet").exists():
    pytest.skip(f"{slug} not built")
  return d


def ids_for(slug, attrs):
  """place ids for synthetic native attributes, checked against the collection's pattern."""
  pid = CFGS[slug]["place_id"]
  ids = build_place_ids(pid, attrs, CFGS[slug].get("maps"))
  check_place_ids(ids, pid["pattern"])
  return ids


def name(slug, attrs):
  return render(CFGS[slug]["name"], attrs)


def source_id(slug, attrs):
  return render(CFGS[slug]["source_id"], attrs)


# config rules --------------------------------------------------------------------------------------------------------

def test_all_twelve_configs_are_present():
  assert len(SCAN) == 12 and set(SCAN) <= set(CFGS)


def test_the_two_new_place_types_are_accepted_and_an_unknown_one_is_not():
  assert {"disposal_site", "military_area"} <= PLACE_TYPES
  base = {**CFGS["epa_ocean_disposal_sites"]}
  validate_config(base)
  with pytest.raises(ValueError, match="place_type"):
    validate_config({**base, "place_type": "dump"})


@pytest.mark.parametrize("slug", sorted(SCAN))
def test_licence_attribution_place_type_and_authority(slug):
  c = CFGS[slug]
  n, place_type, authority, _, _ = SCAN[slug]
  assert c["license"] == "CC-PDDC" and c["license_url"].startswith("https://")
  assert "Processed by Ocean Metrics" in c["attribution"] and ("Public domain" in c["attribution"])
  assert len(c["license_note"].split()) > 5
  assert c["place_type"] == place_type and c["authority"] == authority
  assert c["source_page"] == f"https://www.arcgis.com/home/item.html?id={c['sources'][0]['item_id']}"


@pytest.mark.parametrize("slug", sorted(SCAN))
def test_one_arcgis_source_pointing_at_its_item_and_expecting_the_served_count(slug):
  srcs = CFGS[slug]["sources"]
  assert len(srcs) == 1 and srcs[0]["kind"] == "arcgis" and srcs[0]["url"].startswith("https://")
  assert re.fullmatch(r"[0-9a-f]{32}", srcs[0]["item_id"])
  assert srcs[0]["expected_count"] == SCAN[slug][0]


@pytest.mark.parametrize("slug", sorted(SCAN))
def test_id_pattern_takes_the_example_and_rejects_the_bad_one(slug):
  _, _, authority, good, bad = SCAN[slug]
  pat = CFGS[slug]["place_id"]["pattern"]
  assert good.startswith(authority + ":") and re.fullmatch(pat, good)
  assert not re.fullmatch(pat, bad)


def test_id_prefixes_do_not_collide_between_the_new_collections_or_with_existing_ones():
  # each new collection has its own '<authority>:<segment>:' namespace, except the BOEM leases (one serial series)
  heads = {s: CFGS[s]["place_id"]["template"].split("{")[0] for s in SCAN}
  assert len(set(heads.values())) == len(heads)
  others = {s: (c.get("place_id") or {}).get("template", "").split("{")[0] for s, c in CFGS.items() if s not in SCAN}
  assert not {h for h in heads.values() if h.count(":") > 1} & set(others.values())


def test_bia_citation_is_carried_in_attribution_and_citation():
  c = CFGS["noaa_cetacean_bia"]
  assert BIA_CITATION in " ".join(c["attribution"].split()) and BIA_CITATION in " ".join(c["citation"].split())
  assert "citation required" in c["attribution"]


# id, name and status rules (synthetic fixtures) ----------------------------------------------------------------------

def test_efh_id_is_the_fid_and_the_name_joins_species_and_life_stage():
  attrs = [{"FID": 1, "OBJECTID": 0, "SITENAME_L": "Pacific cod (Gulf of Alaska)", "LIFESTAGE": "Adult (Summer)"},
           {"FID": 834, "OBJECTID": 0, "SITENAME_L": "Krill - Euphausia Pacifica", "LIFESTAGE": "ALL"}]
  assert ids_for("noaa_efh", attrs) == ["NMFS:EFH:1", "NMFS:EFH:834"]      # OBJECTID repeats in the source: not the id
  assert name("noaa_efh", attrs[0]) == "Pacific cod (Gulf of Alaska) EFH - Adult (Summer)"


def test_efh_tiles_keep_a_small_payload_and_low_zoom_detail_is_capped():
  c = CFGS["noaa_efh"]
  assert "DATACAVEAT" not in c["tile_properties"] and c["tile_args"] == ["--low-detail=10"]


def test_epa_id_is_the_dump_site_code_and_the_placeholder_code_is_accepted():
  attrs = [{"DumpSiteCo": "US193", "OfficialNa": "San Francisco Deepwater Ocean Site (SF-DODS)"},
           {"DumpSiteCo": "USXXX", "OfficialNa": "Isle of Shoals North Dredged Material Disposal Site (IOSN)"}]
  assert ids_for("epa_ocean_disposal_sites", attrs) == ["EPA:US193", "EPA:USXXX"]
  assert name("epa_ocean_disposal_sites", attrs[0]) == "San Francisco Deepwater Ocean Site (SF-DODS)"
  assert source_id("epa_ocean_disposal_sites", attrs[1]) == "USXXX"


def test_anchorage_id_is_cfr_section_plus_name_and_a_section_lists_several_anchorages():
  attrs = [{"objectid": 442, "codefederalregulations": "110.182(a)(1)", "anchoragename": "Anchorage A",
            "location": "Fort George Inlet, Mayport, FL"},
           {"objectid": 443, "codefederalregulations": "110.182(a)(1)", "anchoragename": "Anchorage B",
            "location": "Fort George Inlet, Mayport, FL"}]
  assert ids_for("uscg_anchorages", attrs) == ["USCG:ANCH:110-182-a-1:anchorage-a", "USCG:ANCH:110-182-a-1:anchorage-b"]
  assert name("uscg_anchorages", attrs[0]) == "Anchorage A - Fort George Inlet, Mayport, FL"
  assert source_id("uscg_anchorages", attrs[0]) == "33 CFR 110.182(a)(1) Anchorage A"


def test_regression_anchorage_without_a_cfr_section_falls_back_to_its_location():
  attrs = [{"objectid": 676, "codefederalregulations": None, "anchoragename": "Anchorage Area", "location": "Duck Island, NY"}]
  assert ids_for("uscg_anchorages", attrs) == ["USCG:ANCH:duck-island-ny:anchorage-area"]
  assert source_id("uscg_anchorages", attrs[0]) == "Duck Island, NY Anchorage Area"


def test_regression_anchorage_repeats_of_section_and_name_are_suffixed_in_objectid_order():
  attrs = [{"objectid": 647, "codefederalregulations": "166.200(d)(2)", "anchoragename": "Brazos Santiago Pass", "location": "x"},
           {"objectid": 646, "codefederalregulations": "166.200(d)(2)", "anchoragename": "Brazos Santiago Pass", "location": "x"}]
  assert ids_for("uscg_anchorages", attrs) == ["USCG:ANCH:166-200-d-2:brazos-santiago-pass:part",
                                               "USCG:ANCH:166-200-d-2:brazos-santiago-pass"]


def test_anchorage_status_date_is_the_effective_date():
  st = CFGS["uscg_anchorages"]["status"]
  assert resolve_status(st, {"effectivedate": 1459382400000}, None) == ("in_force", st["source"], "2016-03-31")
  assert resolve_status(st, {"effectivedate": None}, None)[2] == ""


def test_withdrawal_id_is_the_acronym_and_the_name_says_withdrawal():
  attrs = [{"ACRONYM": "GRNMS", "NAME": "Gray's Reef National Marine Sanctuary"}, {"ACRONYM": "NAL", "NAME": "North Aleutian Basin"}]
  assert ids_for("boem_ocs_withdrawals", attrs) == ["BOEM:WD:GRNMS", "BOEM:WD:NAL"]
  assert name("boem_ocs_withdrawals", attrs[0]) == "Gray's Reef National Marine Sanctuary (OCS leasing withdrawal)"
  assert resolve_status(CFGS["boem_ocs_withdrawals"]["status"], attrs[0], "2026-07-15T00:00:00Z")[::2] == ("withdrawn", "2026-07-15")


def test_coral_zone_id_is_the_zone_name_not_the_cfr_section():
  attrs = [{"objectid": 1, "zonename": "Block Canyon", "cfrsection": "50 CFR Part 648.372.c.1"},
           {"objectid": 19, "zonename": "Georges Bank Deep-Sea Coral Protection Area", "cfrsection": "50 CFR Part 648.373.a"}]
  assert ids_for("noaa_coral_protection_areas", attrs) == ["NMFS:CPA:block-canyon",
                                                           "NMFS:CPA:georges-bank-deep-sea-coral-protection-area"]
  assert name("noaa_coral_protection_areas", attrs[0]) == "Block Canyon (50 CFR Part 648.372.c.1)"


def test_regression_right_whale_areas_sharing_a_cfr_paragraph_get_distinct_ids_from_location():
  attrs = [{"objectid": 8, "cfrsection": "50 CFR 224.105(a) 2ii", "location": "Ports of New York and New Jersey",
            "restrictedperiod": "November 15 to April 30"},
           {"objectid": 9, "cfrsection": "50 CFR 224.105(a) 2ii", "location": "Delaware Bay",
            "restrictedperiod": "November 15 to April 30"}]
  assert ids_for("noaa_narw_sma", attrs) == ["NMFS:SMA:ports-of-new-york-and-new-jersey", "NMFS:SMA:delaware-bay"]
  assert name("noaa_narw_sma", attrs[1]) == "Delaware Bay Seasonal Management Area (November 15 to April 30)"


def test_bia_id_is_bia_id_and_the_name_carries_species_and_type():
  attrs = [{"BIA_ID": 3, "BIA_name": "Hawaii Island", "cmn_name": "Bottlenose dolphin", "BIA_type": "Small and resident"}]
  assert ids_for("noaa_cetacean_bia", attrs) == ["NMFS:BIA:3"]
  assert name("noaa_cetacean_bia", attrs[0]) == "Hawaii Island (Bottlenose dolphin, Small and resident)"
  assert resolve_status(CFGS["noaa_cetacean_bia"]["status"], attrs[0], "2024-06-12T00:00:00Z")[::2] == ("identified", "2015")


def test_marine_minerals_lease_ids_use_the_formal_lease_number():
  attrs = [{"LeaseNo": "OCS-A-0505", "ProjectID": "Sandbridge 2013", "EffectiveDate": 1}, {"LeaseNo": "OCS-A-00467", "EffectiveDate": 2},
           {"LeaseNo": "OCS-FL-2000", "EffectiveDate": 3}, {"LeaseNo": "OCS-A-XXXX", "EffectiveDate": None}]
  assert ids_for("boem_marine_minerals_leases", attrs) == ["BOEM:OCS-A 0505", "BOEM:OCS-A 0467", "BOEM:OCS-FL-2000",
                                                           "BOEM:OCS-A-XXXX"]
  assert name("boem_marine_minerals_leases", attrs[0]) == "OCS-A 0505 marine minerals lease - Sandbridge 2013"
  assert source_id("boem_marine_minerals_leases", attrs[0]) == "OCS-A-0505"        # the lease number as served


def test_regression_marine_minerals_repeated_lease_number_the_earlier_effective_date_keeps_the_bare_id():
  attrs = [{"OBJECTID": 4143, "LeaseNo": "OCS-G-23707", "ProjectID": "Collier County 2006", "EffectiveDate": 1134518400000},
           {"OBJECTID": 4144, "LeaseNo": "OCS-G-23707", "ProjectID": "Holly Beach 2002", "EffectiveDate": 1020384000000}]
  assert ids_for("boem_marine_minerals_leases", attrs) == ["BOEM:OCS-G 23707:part", "BOEM:OCS-G 23707"]


def test_marine_minerals_status_is_the_lease_status_lower_cased_and_copied_verbatim_upstream():
  st = CFGS["boem_marine_minerals_leases"]["status"]
  assert resolve_status(st, {"LeaseStatus": "Complete"}, None)[0] == "complete"
  assert resolve_status(st, {"LeaseStatus": None}, None)[0] == "unknown"
  assert upstream_status(st, {"LeaseStatus": "Proposed"}) == "Proposed"


def test_regression_pilot_stations_with_several_boarding_areas_are_suffixed_in_objectid_order():
  attrs = [{"objectid": o, "stationname": "Saint Thomas Island"} for o in (146, 143, 145, 144)]
  assert ids_for("noaa_pilot_boarding_areas", attrs) == [
    "MC:pilot:saint-thomas-island:part-3", "MC:pilot:saint-thomas-island", "MC:pilot:saint-thomas-island:part-2",
    "MC:pilot:saint-thomas-island:part"]
  assert name("noaa_pilot_boarding_areas", attrs[0]) == "Saint Thomas Island pilot boarding area"


def test_lightering_zone_id_is_the_site_name_and_the_name_carries_the_area_type():
  attrs = [{"objectid": 52, "sitename": "Penobscot Bay", "areatype": "Designated"},
           {"objectid": 53, "sitename": "Penobscot Bay", "areatype": "Designated"},
           {"objectid": 2, "sitename": "Gulfmex 2", "areatype": "Designated"}]
  assert ids_for("noaa_lightering_zones", attrs) == ["MC:lightering:penobscot-bay", "MC:lightering:penobscot-bay:part",
                                                     "MC:lightering:gulfmex-2"]
  assert name("noaa_lightering_zones", attrs[2]) == "Gulfmex 2 lightering zone (Designated)"


def test_navy_oparea_id_is_the_short_name_the_name_the_long_form_and_status_upstream_is_copied():
  attrs = [{"featurename": "VACAPES OPAREA", "featuredescription": "VIRGINIA CAPES OPERATING AREA  (VCOA)",
            "operationalstatus": "In Service"}]
  assert ids_for("navy_operating_areas", attrs) == ["NAVY:OPAREA:vacapes-oparea"]
  assert name("navy_operating_areas", attrs[0]) == "VIRGINIA CAPES OPERATING AREA (VCOA)"     # whitespace collapsed
  st = CFGS["navy_operating_areas"]["status"]
  assert resolve_status(st, attrs[0], None)[0] == "active" and upstream_status(st, attrs[0]) == "In Service"


def test_regression_special_use_airspace_id_is_type_plus_name_and_repeats_are_suffixed_in_objectid_order():
  attrs = [{"objectid": 183, "specialuseairspacetype": "Warning", "featurename": "KEY WEST, FL", "featuredescription": "Warning Area"},
           {"objectid": 182, "specialuseairspacetype": "Warning", "featurename": "KEY WEST, FL", "featuredescription": "Warning Area"},
           {"objectid": 9, "specialuseairspacetype": "Restricted", "featurename": "KEY WEST, FL", "featuredescription": "Restricted Area"}]
  assert ids_for("navy_special_use_airspace", attrs) == ["NAVY:SUA:warning:key-west-fl:part", "NAVY:SUA:warning:key-west-fl",
                                                         "NAVY:SUA:restricted:key-west-fl"]
  assert name("navy_special_use_airspace", attrs[0]) == "KEY WEST, FL (Warning Area)"
  assert source_id("navy_special_use_airspace", attrs[0]) == "Warning KEY WEST, FL"


def test_marine_minerals_rows_carry_status_upstream_licence_and_the_formal_id(tmp_path):
  cfg = {**CFGS["boem_marine_minerals_leases"], "_sources_dir": str(tmp_path)}
  feats = [{"properties": {"OBJECTID": 4135, "LeaseNo": "OCS-A-0505", "ProjectID": "Sandbridge 2013", "LeaseStatus": "Active",
                           "EffectiveDate": 1373587200000}, "geometry": square(-75.9, 36.7, 0.05)}]
  fields = [{"name": "OBJECTID", "type": "int"}, {"name": "LeaseNo", "type": "string"}, {"name": "ProjectID", "type": "string"},
            {"name": "LeaseStatus", "type": "string"}, {"name": "EffectiveDate", "type": "date"}]
  res = SourceResult(features=feats, fields=fields, source_url=cfg["sources"][0]["url"], data_last_edit="2026-09-02T00:00:00Z",
                     retrieved="2026-10-20T12:00:00Z", record_count=1, checksum="x")
  rows, flds, dropped = build_rows(cfg, [res])
  t = to_table(rows, flds)
  assert not dropped and t.num_rows == 1
  r = t.to_pylist()[0]
  assert (r["place_id"], r["source_id"], r["status"], r["status_upstream"], r["status_date"]) == (
    "BOEM:OCS-A 0505", "OCS-A-0505", "active", "Active", "2026-09-02")
  assert (r["license"], r["authority"], r["place_type"]) == ("CC-PDDC", "BOEM", "lease")


# staged outputs ------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("slug", sorted(SCAN))
def test_staged_parquet_and_pmtiles_pass_every_check(slug):
  d = staged(slug)
  assert check_parquet(d / "places.parquet", CFGS[slug]) == []
  assert check_pmtiles(d / "places.pmtiles", slug) == []


@pytest.mark.parametrize("slug", sorted(SCAN))
def test_staged_count_polygons_licence_and_ids_on_every_row(slug):
  d = staged(slug)
  t = pq.read_table(d / "places.parquet")
  n = SCAN[slug][0]
  assert abs(t.num_rows - n) <= max(1, n // 50)                         # served count, minus any geometry-less feature
  assert set(shapely.get_type_id(shapely.from_wkb(t.column("geometry").to_pylist()))) == {6}
  assert set(t.column("license").to_pylist()) == {"CC-PDDC"}
  assert set(t.column("authority").to_pylist()) == {SCAN[slug][2]}
  assert set(t.column("place_type").to_pylist()) == {SCAN[slug][1]}
  pat = CFGS[slug]["place_id"]["pattern"]
  assert all(re.fullmatch(pat, i) for i in t.column("place_id").to_pylist())
  assert all(v for v in t.column("name").to_pylist())


@pytest.mark.parametrize("slug", sorted(SCAN))
def test_staged_provenance_names_the_item(slug):
  d = staged(slug)
  prov = json.loads((d / "provenance.json").read_text())
  for s in prov["sources"]:
    assert all(s.get(k) not in (None, "") for k in ("source_url", "source_item_id", "retrieved", "record_count", "checksum"))


def test_staged_bia_collection_carries_the_citation():
  d = staged("noaa_cetacean_bia")
  assert BIA_CITATION in json.loads((d / "collection.json").read_text())["citation"]
