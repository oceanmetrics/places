import pytest
import shapely
from shapely.geometry import MultiPolygon, Polygon

from conftest import square
from gazetteer.geom import clean_geometry, esri_json_to_geojson, max_edge_span, split_antimeridian


def lon_range(g):
  b = g.bounds
  return b[0], b[2]


def test_polygon_inside_the_world_is_unchanged():
  g = square(10, 10)
  out = split_antimeridian(g)
  assert out.geom_type == "MultiPolygon" and len(out.geoms) == 1
  assert out.equals(g)


def test_unwrapped_polygon_past_180_is_split_in_two_halves():
  g = Polygon([(170, 50), (190, 50), (190, 60), (170, 60), (170, 50)])   # lon 190 = -170
  out = split_antimeridian(g)
  assert lon_range(out) == (-180.0, 180.0)
  assert len(out.geoms) == 2
  assert out.area == pytest.approx(g.area)
  east = [p for p in out.geoms if p.bounds[0] >= 0][0]
  west = [p for p in out.geoms if p.bounds[2] <= 0][0]
  assert east.bounds == (170.0, 50.0, 180.0, 60.0)
  assert west.bounds == (-180.0, 50.0, -170.0, 60.0)


def test_wrapped_ring_that_jumps_the_dateline_is_split():
  # the same box written the way a lon/lat dataset does: 170 -> -170 in one edge (a 340 degree step)
  g = Polygon([(170, 50), (-170, 50), (-170, 60), (170, 60), (170, 50)])
  assert max_edge_span(g) == 340
  out = clean_geometry(g)
  assert out.is_valid and len(out.geoms) == 2
  assert lon_range(out) == (-180.0, 180.0)
  assert out.area == pytest.approx(20 * 10)
  assert max_edge_span(out) <= 180


def test_vertices_a_hair_short_of_the_meridian_snap_onto_it():
  east = Polygon([(170, 0), (179.99999, 0), (179.99999, 10), (170, 10), (170, 0)])
  west = Polygon([(-179.99999, 0), (-170, 0), (-170, 10), (-179.99999, 10), (-179.99999, 0)])
  out = clean_geometry(MultiPolygon([east, west]))
  assert out.is_valid and lon_range(out) == (-180.0, 180.0)
  assert clean_geometry(square(179.0, 0, 0.5)).bounds == (179.0, 0.0, 179.5, 0.5)    # far from 180: untouched


def test_polygon_west_of_minus_180_is_split():
  g = Polygon([(-190, 0), (-170, 0), (-170, 5), (-190, 5), (-190, 0)])
  out = split_antimeridian(g)
  assert lon_range(out) == (-180.0, 180.0) and out.area == pytest.approx(g.area)


def test_hole_stays_with_its_half():
  shell = [(170, 0), (190, 0), (190, 10), (170, 10), (170, 0)]
  hole = [(172, 2), (176, 2), (176, 4), (172, 4), (172, 2)]
  out = split_antimeridian(Polygon(shell, [hole]))
  assert out.area == pytest.approx(200 - 8)
  assert len(out.geoms) == 2


def test_already_split_input_is_idempotent():
  east = Polygon([(170, 0), (180, 0), (180, 10), (170, 10), (170, 0)])
  west = Polygon([(-180, 0), (-170, 0), (-170, 10), (-180, 10), (-180, 0)])
  out = clean_geometry(MultiPolygon([east, west]))
  assert out.area == pytest.approx(200) and lon_range(out) == (-180.0, 180.0)


def test_ring_that_encircles_a_pole_is_refused():
  wrap = [(170, 80), (-100, 80), (-10, 80), (80, 80), (170, 80)]   # four 90 degree steps: a full turn that does not close
  with pytest.raises(NotImplementedError):
    split_antimeridian(Polygon(wrap))


def test_invalid_bowtie_is_made_valid():
  bow = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])
  assert not bow.is_valid
  out = clean_geometry(bow)
  assert out.is_valid and out.geom_type == "MultiPolygon" and out.area == pytest.approx(2.0)


def test_empty_or_non_polygon_gives_none():
  assert clean_geometry(None) is None
  assert clean_geometry(shapely.geometry.Point(1, 1)) is None
  assert clean_geometry(Polygon()) is None


def test_exterior_is_counter_clockwise():
  cw = Polygon([(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)])
  assert not cw.exterior.is_ccw
  out = clean_geometry(cw)
  assert out.geoms[0].exterior.is_ccw


def test_esri_rings_clockwise_outer_ccw_hole():
  outer = [[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]            # clockwise
  hole = [[2, 2], [8, 2], [8, 8], [2, 8], [2, 2]]                  # counter-clockwise
  other = [[20, 0], [20, 5], [25, 5], [25, 0], [20, 0]]            # a second outer
  gj = esri_json_to_geojson({"rings": [outer, hole, other]})
  assert gj["type"] == "MultiPolygon"
  g = shapely.geometry.shape(gj)
  assert g.area == pytest.approx(100 - 36 + 25)
  assert esri_json_to_geojson({"rings": []}) is None and esri_json_to_geojson(None) is None
