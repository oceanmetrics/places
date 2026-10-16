"""gazetteer/dedup.py: which index rows are the same place (group_id)."""
from gazetteer.dedup import bbox_iou, norm_name, same_place, same_place_groups


def row(pid, name, coll, box, gt="MultiPolygon"):
  return {"place_id": pid, "name": name, "collection": coll, "geom_type": gt,
          "bbox": dict(zip(("xmin", "ymin", "xmax", "ymax"), box))}


FKNMS = (-83.15, 24.3, -80.07, 25.65)


def test_norm_name_drops_case_accents_and_extra_spaces():
  assert norm_name("  Papahānaumokuākea   Marine NM ") == "papahanaumokuakea marine nm"
  assert norm_name(None) == ""


def test_bbox_iou():
  assert bbox_iou((0, 0, 2, 2), (0, 0, 2, 2)) == 1.0
  assert bbox_iou((0, 0, 2, 2), (1, 0, 3, 2)) == 1 / 3
  assert bbox_iou((0, 0, 1, 1), (5, 5, 6, 6)) == 0.0


def test_the_same_sanctuary_in_four_collections_is_one_group_regression():
  # "florida keys" listed FKNMS five times (2026-10-16): noaa_sanctuaries, mpa_inventory, two noaa_hapc, places
  rows = [
    row("ONMS:florida-keys-national-marine-sanctuary", "Florida Keys National Marine Sanctuary", "noaa_sanctuaries", (-83.17, 24.3, -80.05, 25.72)),
    row("MPAINV:NMS4", "Florida Keys National Marine Sanctuary", "mpa_inventory", FKNMS),
    row("NMFS:HAPC:20", "Florida Keys National Marine Sanctuary", "noaa_hapc", (-83.15, 24.3, -80.07, 25.64)),
    row("NMFS:HAPC:181", "Florida Keys National Marine Sanctuary", "noaa_hapc", FKNMS),
    row("NMS:FKNMS", "Florida Keys National Marine Sanctuary", "places", FKNMS),
    row("MPAINV:FL1", "Florida Keys Wildlife and Environmental Area", "mpa_inventory", (-81.6, 24.5, -81.0, 25.0)),
  ]
  g = same_place_groups(rows)
  assert g[:5] == ["mpa_inventory/MPAINV:NMS4"] * 5
  assert g[5] is None


def test_iou_threshold_admits_monitor_nms_at_0_81():
  a = row("ONMS:monitor", "Monitor National Marine Sanctuary", "noaa_sanctuaries", (0, 0, 1.0, 1.0))
  b = row("NMS:MNMS", "Monitor National Marine Sanctuary", "places", (0, 0, 0.9, 0.9))   # iou 0.81
  assert same_place(a, b)
  assert not same_place(a, row("x", "Monitor National Marine Sanctuary", "y", (0, 0, 0.85, 0.85)))   # iou 0.72


def test_homonyms_split_zones_and_a_seamount_beside_its_hapc_stay_apart():
  rows = [
    row("GEBCO:1", "Bear Seamount", "gebco_undersea", (-67.4, 39.9, -67.4, 39.9), "Point"),
    row("NMFS:HAPC:7", "Bear Seamount", "noaa_hapc", (-67.6, 39.8, -67.2, 40.1)),          # point vs polygon
    row("GEBCO:2", "Rio Grande Rise", "gebco_undersea", (-35.0, -31.0, -35.0, -31.0), "Point"),
    row("GEBCO:3", "Rio Grande Rise", "gebco_undersea", (-95.0, 27.0, -95.0, 27.0), "Point"),   # same name, other ocean
    row("USACE:1", "Monterey Bay - firing range", "usace_danger_zones", (-122.0, 36.6, -121.9, 36.7)),
    row("USACE:2", "Monterey Bay - firing range", "usace_danger_zones", (-121.95, 36.65, -121.8, 36.75)),   # part, iou < 0.8
  ]
  assert same_place_groups(rows) == [None] * 6


def test_identical_points_and_identical_polygons_within_one_collection_group():
  rows = [
    row("GEBCO:9", "Hudson Canyon", "gebco_undersea", (-72.0, 39.5, -72.0, 39.5), "Point"),
    row("GEBCO:10", "Hudson  canyon", "gebco_undersea", (-72.0005, 39.5, -72.0005, 39.5), "Point"),
  ]
  assert same_place_groups(rows) == ["gebco_undersea/GEBCO:10"] * 2


def test_placeholder_names_never_group_regression():
  # FWS: overlapping habitats of different Mariana plants, all named "No common name critical habitat (proposed)"
  rows = [row("FWS:CHP:10723", "No common name critical habitat (proposed)", "fws", (144.66, 13.331, 145.255, 14.164)),
          row("FWS:CHP:10728", "No common name critical habitat (proposed)", "fws", (144.66, 13.259, 145.255, 14.164)),
          row("X:1", "Unnamed", "x", (0, 0, 1, 1)), row("X:2", "Unnamed", "x", (0, 0, 1, 1))]
  assert same_place_groups(rows) == [None] * 4


def test_unnamed_or_boxless_rows_never_group():
  rows = [row("A:1", None, "a", (0, 0, 1, 1)), row("B:1", None, "b", (0, 0, 1, 1)),
          {"place_id": "C:1", "name": "X", "collection": "c", "geom_type": "Polygon", "bbox": None},
          {"place_id": "D:1", "name": "X", "collection": "d", "geom_type": "Polygon", "bbox": None}]
  assert same_place_groups(rows) == [None] * 4
