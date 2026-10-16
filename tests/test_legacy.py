"""gazetteer/legacy.py: metadata for collections published outside this pipeline (erddap-places' `places`)."""
from gazetteer.legacy import legacy_place_type, legacy_title


def test_legacy_title_replaces_the_slug_default_only():
  t = legacy_title("places", "Places")
  assert t.startswith("erddap-places statistics places")
  assert legacy_title("places", None) == t
  assert legacy_title("places", "places") == t
  assert legacy_title("places", "Sanctuaries for erddap-places") == "Sanctuaries for erddap-places"


def test_legacy_title_leaves_other_collections_alone():
  assert legacy_title("noaa_sanctuaries", "NOAA National Marine Sanctuaries") == "NOAA National Marine Sanctuaries"
  assert legacy_title("noaa_sanctuaries", None) is None


def test_legacy_place_type_by_place_id_prefix():
  assert legacy_place_type("places", "NMS:MBNMS") == "protected_area"
  assert legacy_place_type("places", "PSGID:939") == "protected_area"
  assert legacy_place_type("places", "MRGID:8439") == "eez"
  assert legacy_place_type("places", "XYZ:1") is None
  assert legacy_place_type("places", None) is None
  assert legacy_place_type("noaa_sanctuaries", "NMS:MBNMS") is None
