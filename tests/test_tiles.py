import shutil

import pytest

from conftest import STAGING, lease_cfg, lease_result, square
from gazetteer.table import build_rows, to_table, write_geoparquet
from gazetteer.tiles import build_pmtiles, read_pmtiles, tippecanoe_cmd
from gazetteer.validate import check_pmtiles

needs_tippecanoe = pytest.mark.skipif(not shutil.which("tippecanoe"), reason="tippecanoe not installed")


def test_tippecanoe_command_names_layer_and_carries_attribution():
  cmd = tippecanoe_cmd("in.ndjson", "out.pmtiles", "boem_wind_leases", "Wind leases", "desc", "BOEM credit")
  assert "-zg" in cmd and cmd[cmd.index("-l") + 1] == "boem_wind_leases"
  assert cmd[cmd.index("-n") + 1] == "Wind leases" and cmd[cmd.index("-N") + 1] == "desc"
  assert cmd[cmd.index("--attribution") + 1] == "BOEM credit"


@needs_tippecanoe
def test_pmtiles_metadata_has_attribution_name_description_and_layer(tmp_path):
  cfg = lease_cfg(tmp_path)
  rows, fields, _ = build_rows(cfg, [lease_result([(1, "OCS-A 0001", "Commercial", "X", square(-70, 40, 0.5)),
                                                    (2, "OCS-A 0002", "Commercial", "Y", square(-69, 40, 0.5))])])
  pq_path = tmp_path / "places.parquet"
  write_geoparquet(to_table(rows, fields), pq_path, {"sources": []})
  out = tmp_path / "places.pmtiles"
  assert build_pmtiles(pq_path, out, "t_leases", "Test leases", "Two test leases", "BOEM test credit") == 2
  header, meta = read_pmtiles(out)
  assert meta["attribution"] == "BOEM test credit"
  assert meta["name"] == "Test leases" and meta["description"] == "Two test leases"
  assert [lyr["id"] for lyr in meta["vector_layers"]] == ["t_leases"]
  assert header["tile_type"] == 1 and header["max_zoom"] >= 0
  assert -70.1 < header["bounds"][0] < -69.9
  assert check_pmtiles(out, "t_leases") == []
  assert check_pmtiles(out, "other_slug") != []          # wrong layer name is caught


@needs_tippecanoe
def test_pmtiles_without_attribution_fails_the_check(tmp_path):
  import subprocess
  nd = tmp_path / "a.ndjson"
  nd.write_text('{"type":"Feature","properties":{},"geometry":{"type":"Polygon","coordinates":[[[1,1],[2,1],[2,2],[1,2],[1,1]]]}}\n')
  out = tmp_path / "a.pmtiles"
  subprocess.run(["tippecanoe", "-o", str(out), "-zg", "-l", "x", "--force", "--quiet", str(nd)], check=True)
  problems = check_pmtiles(out, "x")
  assert "PMTiles metadata has no attribution" in problems


def test_pmtiles_reader_agrees_with_the_reference_implementation():
  """our dependency-free header / metadata reader against the `pmtiles` package, on a staged archive."""
  pm = pytest.importorskip("pmtiles.reader")
  path = STAGING / "boem_ocs_planning" / "places.pmtiles"
  if not path.exists():
    pytest.skip("boem_ocs_planning not built")
  header, meta = read_pmtiles(path)
  with open(path, "rb") as fh:
    ref = pm.Reader(pm.MmapSource(fh))
    rh, rm = ref.header(), ref.metadata()
    assert rm == meta
    assert (rh["min_zoom"], rh["max_zoom"]) == (header["min_zoom"], header["max_zoom"])
    assert rh["min_lon_e7"] / 1e7 == pytest.approx(header["bounds"][0])
    assert rh["max_lat_e7"] / 1e7 == pytest.approx(header["bounds"][3])


def test_keep_all_turns_off_low_zoom_thinning():
  thin = tippecanoe_cmd("in", "out", "s", "n", "d", "a")
  keep = tippecanoe_cmd("in", "out", "s", "n", "d", "a", maxzoom=10, keep_all=True)
  assert "--drop-densest-as-needed" in thin and "-r1" not in thin
  assert "-r1" in keep and "--drop-densest-as-needed" not in keep and "-z10" in keep


@needs_tippecanoe
@pytest.mark.skipif(not shutil.which("tippecanoe-decode"), reason="tippecanoe-decode not installed")
def test_keep_all_draws_every_point_at_low_zoom_regression(tmp_path):
  """regression: calcofi_stations (113 points) kept ~1 station per tile below z10 under default thinning."""
  import subprocess
  import numpy as np
  import pyarrow as pa
  import shapely
  from gazetteer.table import BBOX
  rng = np.random.default_rng(1)
  pts = [shapely.Point(-124 + float(a), 32 + float(b)) for a, b in rng.random((60, 2)) * 6]
  b = shapely.bounds(np.array(pts, dtype=object))
  t = pa.table({"place_id": [f"T:{i}" for i in range(60)], "geom_type": ["Point"] * 60,
                "bbox": pa.StructArray.from_arrays([pa.array(b[:, i]) for i in range(4)], fields=list(BBOX)),
                "geometry": pa.array(shapely.to_wkb(np.array(pts, dtype=object)), type=pa.binary())})
  write_geoparquet(t, tmp_path / "p.parquet", {})

  def at_z3(keep_all):
    out = tmp_path / f"k{keep_all}.pmtiles"
    build_pmtiles(tmp_path / "p.parquet", out, "t", "t", "t", "credit", ["place_id"], 10, keep_all)
    txt = subprocess.run(["tippecanoe-decode", str(out), "3", "1", "3"], capture_output=True, text=True).stdout
    return txt.count('"type": "Feature",')

  assert at_z3(True) == 60
  assert at_z3(False) < 60
