import pytest

from gazetteer.fmt import normalize_lease_number, render
from gazetteer.ids import build_place_ids, check_place_ids, suffix_duplicates

LEASE = {"rule": "lease", "pattern": r"^BOEM:OCS-[A-Z] \d{4,5}(:[a-z0-9-]+)?$"}


@pytest.mark.parametrize("raw,expected", [
  ("OCS-P 0561", "OCS-P 0561"), ("P00202", "OCS-P 0202"), ("P00240", "OCS-P 0240"), ("OCS-A 0501", "OCS-A 0501"),
  ("OCS-G 37334 Provisional", "OCS-G 37334"), (" OCS-A  0482 ", "OCS-A 0482"), ("", ""), (None, ""),
])
def test_lease_number_normalisation(raw, expected):
  assert normalize_lease_number(raw) == expected


def test_commercial_polygon_keeps_the_bare_lease_id_and_easements_get_suffixes():
  attrs = [
    {"OBJECTID": 500, "LEASE_NUMBER": "OCS-A 0497", "LEASE_TYPE": "Easement"},
    {"OBJECTID": 477, "LEASE_NUMBER": "OCS-A 0497", "LEASE_TYPE": "Commercial"},
    {"OBJECTID": 502, "LEASE_NUMBER": "OCS-A 0501", "LEASE_TYPE": "Easement"},
    {"OBJECTID": 503, "LEASE_NUMBER": "OCS-A 0501", "LEASE_TYPE": "Easement"},
    {"OBJECTID": 481, "LEASE_NUMBER": "OCS-A 0501", "LEASE_TYPE": "Commercial"},
  ]
  ids = build_place_ids(LEASE, attrs)
  assert ids == ["BOEM:OCS-A 0497:easement", "BOEM:OCS-A 0497", "BOEM:OCS-A 0501:easement",
                 "BOEM:OCS-A 0501:easement-2", "BOEM:OCS-A 0501"]
  check_place_ids(ids, LEASE["pattern"])


def test_same_number_in_different_regions_is_not_a_duplicate():
  ids = build_place_ids(LEASE, [{"OBJECTID": 1, "LEASE_NUMBER": "OCS-P 0561", "LEASE_TYPE": "Commercial"},
                                {"OBJECTID": 2, "LEASE_NUMBER": "OCS-A 0561", "LEASE_TYPE": "Commercial"}])
  assert ids == ["BOEM:OCS-P 0561", "BOEM:OCS-A 0561"]


def test_template_ids_and_duplicates_are_an_error():
  cfg = {"template": "BOEM:PA:{PLANNING_AREA}"}
  assert build_place_ids(cfg, [{"PLANNING_AREA": "SOC"}, {"PLANNING_AREA": "CEC"}]) == ["BOEM:PA:SOC", "BOEM:PA:CEC"]
  with pytest.raises(ValueError, match="duplicate"):
    build_place_ids(cfg, [{"PLANNING_AREA": "SOC"}, {"PLANNING_AREA": "SOC"}])


def test_block_ids_strip_padding_and_skip_an_empty_sub_block():
  t = "BOEM:WPA-BLK:{PROTRACTION_NUMBER}-{BLOCK_NUMBER}{SUB_BLOCK|prefix:-}"
  assert render(t, {"PROTRACTION_NUMBER": "NI17-09", "BLOCK_NUMBER": " 6224", "SUB_BLOCK": " "}) == "BOEM:WPA-BLK:NI17-09-6224"
  assert render(t, {"PROTRACTION_NUMBER": "NI17-09", "BLOCK_NUMBER": " 6224", "SUB_BLOCK": "A"}) == "BOEM:WPA-BLK:NI17-09-6224-A"


def test_map_filter_and_whitespace_collapse():
  maps = {"names": {"SOC": "Southern California"}}
  assert render("{PA|map:names} Planning Area", {"PA": "SOC"}, maps) == "Southern California Planning Area"
  assert render("{PA|map:names}", {"PA": "XYZ"}, maps) == "XYZ"
  assert render("{A} {B}", {"A": "Ocean Wind LLC\r\n", "B": None}) == "Ocean Wind LLC"


def test_pattern_check_rejects_bad_and_duplicate_ids():
  with pytest.raises(ValueError, match="do not match"):
    check_place_ids(["BOEM:nope"], LEASE["pattern"])
  with pytest.raises(ValueError, match="duplicate"):
    check_place_ids(["BOEM:OCS-A 0001", "BOEM:OCS-A 0001"], LEASE["pattern"])


def test_suffix_duplicates_is_deterministic_in_the_given_order():
  assert suffix_duplicates(["a", "a", "b"], ["x", "x", "x"], [2, 1, 0]) == ["a:x", "a", "b"]
