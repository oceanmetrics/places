"""gazetteer/bbox.py: antimeridian-aware bboxes for the published metadata (RFC 7946: west > east crosses +/-180)."""
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import MultiPolygon, Point, Polygon

from gazetteer.bbox import geometries_bbox, join_extent, main, parquet_bbox, place_bbox, union_bbox, unwrap_bbox, wrap_bbox

CASES = json.loads((Path(__file__).parent / "fixtures" / "union_bbox_cases.json").read_text())["cases"]


def rect(x0, y0, x1, y1):
  return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)])


# PMNM as stored: split at +/-180, a sliver east of the cut and the main body west of it
PMNM = MultiPolygon([rect(177.8, 25, 180, 30), rect(-180, 19.2, -161, 31.8)])


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_union_bbox_shared_cases(case):
  assert union_bbox(case["boxes"]) == pytest.approx(case["want"])


def test_union_bbox_of_nothing_raises():
  with pytest.raises(ValueError):
    union_bbox([])


def test_place_cut_at_the_antimeridian_crosses_instead_of_spanning_the_globe():
  assert PMNM.bounds == (-180, 19.2, 180, 31.8)                       # what a plain min/max published
  assert place_bbox(PMNM) == pytest.approx([177.8, 19.2, -161, 31.8])


def test_place_bbox_plain_point_and_empty():
  assert place_bbox(rect(-125, 30, -117, 40)) == [-125, 30, -117, 40]
  assert place_bbox(Point(-120.5, 34.2)) == [-120.5, 34.2, -120.5, 34.2]
  assert place_bbox(shapely.from_wkt("MULTIPOLYGON EMPTY")) is None and place_bbox(None) is None


def test_place_with_parts_on_both_sides_not_touching_180_still_crosses():
  kiribati = MultiPolygon([rect(172, 0, 174, 2), rect(-158, 1, -157, 3)])
  assert place_bbox(kiribati) == pytest.approx([172, 0, -157, 3])


def test_collection_with_pmnm_and_the_mainland_crosses():
  assert geometries_bbox([PMNM, rect(-125, 30, -117, 40), rect(-82, 24, -80, 26)]) == pytest.approx([177.8, 19.2, -80, 40])


def test_wrap_and_unwrap():
  assert wrap_bbox([177, 10, 199, 14]) == [177, 10, -161, 14]          # index convention -> RFC 7946
  assert wrap_bbox([10, 10, 12, 12]) == [10, 10, 12, 12]
  assert wrap_bbox([-180, 0, 200, 1]) == [-180, 0, 180, 1]              # 380 degrees wide: the whole band
  assert unwrap_bbox([177, 10, -161, 14]) == [177, 10, 199, 14]         # RFC 7946 -> fitBounds
  assert unwrap_bbox([-125, 30, -117, 40]) == [-125, 30, -117, 40]


def write_geo(path: Path, geoms):
  pq.write_table(pa.table({"geometry": pa.array([shapely.to_wkb(g) for g in geoms], type=pa.binary())}), path)


def test_join_extent_joins_portolans_two_halves(tmp_path):
  """regression: portolan 0.8.0 `add` writes a crossing geo bbox as two halves; STAC reads the first as the extent."""
  c = tmp_path / "collection.json"
  c.write_text(json.dumps({"extent": {"spatial": {"bbox": [[-180, -15.4, -64.5, 48.5], [177.8, -15.4, 180, 48.5]]}}}))
  assert join_extent(c) == [[177.8, -15.4, -64.5, 48.5]]
  assert json.loads(c.read_text())["extent"]["spatial"]["bbox"] == [[177.8, -15.4, -64.5, 48.5]]


def test_join_extent_from_data_drops_an_old_globe_extent(tmp_path):
  """regression: on a republish portolan unions the new bbox with the old -180..180 extent; measure from the data."""
  c, d = tmp_path / "collection.json", tmp_path / "places.parquet"
  c.write_text(json.dumps({"extent": {"spatial": {"bbox": [[-180, 19.2, 180, 40]]}}}))
  write_geo(d, [PMNM, rect(-125, 30, -117, 40)])
  assert parquet_bbox(d) == pytest.approx([177.8, 19.2, -117, 40])
  assert main(["join-extent", str(c), "--data", str(d)]) == 0
  assert json.loads(c.read_text())["extent"]["spatial"]["bbox"][0] == pytest.approx([177.8, 19.2, -117, 40])


def test_join_extent_leaves_a_plain_extent_file_untouched(tmp_path):
  c = tmp_path / "collection.json"
  text = '{"extent": {"spatial": {"bbox": [[-125.0, 30.0, -117.0, 40.0]]}}}'
  c.write_text(text)
  assert join_extent(c) == [[-125.0, 30.0, -117.0, 40.0]] and c.read_text() == text
