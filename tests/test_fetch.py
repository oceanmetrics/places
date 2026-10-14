import io
import json
import zipfile

import pytest

from gazetteer import fetch
from gazetteer.fetch import extract_stem, fetch_arcgis


class Resp:
  def __init__(self, payload):
    self.content = json.dumps(payload).encode()
    self._p = payload
    self.status_code = 200

  def json(self):
    return self._p

  def raise_for_status(self):
    pass


class FakeSession:
  """answers an ArcGIS layer with n point-less polygon features, `page` per request."""
  def __init__(self, n, page_flag="properties"):
    self.n, self.calls, self.flag = n, [], page_flag
    self.headers = {}

  def get(self, url, params=None, timeout=None, verify=True, **kw):
    params = dict(params or {})
    self.calls.append(params)
    if url.endswith("/query") and params.get("returnCountOnly"):
      return Resp({"count": self.n})
    if url.endswith("/query"):
      off, size = int(params["resultOffset"]), int(params["resultRecordCount"])
      ids = range(off, min(off + size, self.n))
      feats = [{"type": "Feature", "properties": {"OBJECTID": i + 1},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}} for i in ids]
      d = {"type": "FeatureCollection", "features": feats}
      if off + size < self.n:
        d["properties"] = {"exceededTransferLimit": True}
      return Resp(d)
    return Resp({"name": "t", "objectIdField": "OBJECTID", "fields": [{"name": "OBJECTID", "type": "esriFieldTypeOID"}],
                 "editingInfo": {"dataLastEditDate": 1741116701412}, "supportedQueryFormats": "JSON, geoJSON, PBF"})


def test_paging_collects_every_feature_in_object_id_order():
  s = FakeSession(25)
  res = fetch_arcgis({"url": "https://x/FeatureServer/0", "page_size": 10}, delay=0, s=s)
  assert res.record_count == 25 and [f["properties"]["OBJECTID"] for f in res.features] == list(range(1, 26))
  paged = [c for c in s.calls if "resultOffset" in c]
  assert [c["resultOffset"] for c in paged] == [0, 10, 20]
  assert all(c["orderByFields"] == "OBJECTID" and c["outSR"] == 4326 for c in paged)
  assert res.data_last_edit == "2025-03-04T19:31:41Z"


def test_count_mismatch_is_an_error():
  class Short(FakeSession):
    def get(self, url, params=None, **kw):
      r = super().get(url, params, **kw)
      if url.endswith("/query") and not (params or {}).get("returnCountOnly"):
        r._p["features"] = r._p["features"][:-1]
        r._p.pop("properties", None)
      return r
  with pytest.raises(RuntimeError, match="counts"):
    fetch_arcgis({"url": "https://x/FeatureServer/0", "page_size": 100}, delay=0, s=Short(5))


def test_exclude_drops_renacv_leases_and_records_them_pacific_og_regression(caplog):
  # boem_pacific_og_leases: BOEM's POC_Layers/7 lists 4 renewable leases (LEASE_STATUS_CD = RENACV) among the
  # 34 "oil and gas" leases; the config excludes them at fetch, the layer's own count stays the change token
  class Codes(FakeSession):
    def get(self, url, params=None, **kw):
      r = super().get(url, params, **kw)
      for f in r._p.get("features", []):
        oid = f["properties"]["OBJECTID"]
        f["properties"]["LEASE_STATUS_CD"] = "RENACV" if oid in (2, 4) else "UNIT" if oid == 5 else "PROD"
      return r
  src = {"url": "https://x/FeatureServer/7", "page_size": 100, "expected_count": 3,
         "exclude": {"LEASE_STATUS_CD": ["RENACV"]}}
  res = fetch_arcgis(src, delay=0, s=Codes(5))
  assert [f["properties"]["OBJECTID"] for f in res.features] == [1, 3, 5]
  assert res.record_count == 5
  assert res.extra["excluded"] == ["LEASE_STATUS_CD=RENACV: 2 feature(s)"]
  assert "expected" not in caplog.text            # expected_count is the count after the exclusion
  res = fetch_arcgis({k: v for k, v in src.items() if k != "exclude"}, delay=0, s=Codes(5))
  assert len(res.features) == 5 and res.extra["excluded"] is None


def test_exclude_features_rules():
  feats = [{"properties": {"A": "x", "B": 1}}, {"properties": {"A": "y", "B": 2}}, {"properties": {"A": None, "B": 3}}]
  kept, notes = fetch.exclude_features(feats, {"A": ["y"], "B": [3]})
  assert kept == feats[:1] and notes == ["A=y: 1 feature(s)", "B=3: 1 feature(s)"]
  assert fetch.exclude_features(feats, None) == (feats, [])


def test_arcgis_error_body_raises():
  class Err(FakeSession):
    def get(self, url, params=None, **kw):
      return Resp({"error": {"code": 400, "message": "bad"}})
  with pytest.raises(RuntimeError, match="ArcGIS error"):
    fetch_arcgis({"url": "https://x/FeatureServer/0"}, delay=0, s=Err(1))


def make_zip(path, names):
  with zipfile.ZipFile(path, "w") as z:
    for n in names:
      z.writestr(n, b"x-" + n.encode())


def test_only_the_named_shapefile_is_extracted_and_member_paths_are_ignored(tmp_path):
  z = tmp_path / "a.zip"
  make_zip(z, ["AOA_SOCAL.shp", "AOA_SOCAL.dbf", "AOA_SOCAL.shx", "AOA_SOCAL.prj", "AOA_SOCAL.shp.xml",
               "Other.shp", "report.pdf", "../evil/AOA_SOCAL.dbf2", "sub/dir/AOA_SOCAL.cpg"])
  shp, date = extract_stem(z, tmp_path / "out", "AOA_SOCAL")
  names = sorted(p.name for p in (tmp_path / "out").iterdir())
  assert names == ["AOA_SOCAL.cpg", "AOA_SOCAL.dbf", "AOA_SOCAL.prj", "AOA_SOCAL.shp", "AOA_SOCAL.shx"]
  assert shp.name == "AOA_SOCAL.shp" and not (tmp_path / "evil").exists()


def test_missing_shapefile_in_zip_is_an_error(tmp_path):
  z = tmp_path / "a.zip"
  make_zip(z, ["readme.txt"])
  with pytest.raises(FileNotFoundError):
    extract_stem(z, tmp_path / "out", "AOA_SOCAL")


def test_shapefile_reprojection_to_wgs84_with_densified_edges(tmp_path):
  import numpy as np
  import pyogrio.raw
  import shapely
  from gazetteer.fetch import read_shapefile

  # a 10 km square in California Albers (EPSG:3310) around (0, -400000): x -5000..5000
  sq = shapely.box(-5000, -405000, 5000, -395000)
  pyogrio.raw.write(str(tmp_path / "t.shp"), geometry=shapely.to_wkb(np.array([sq])), field_data=[np.array([7])],
                    fields=["AOA_N"], geometry_type="Polygon", crs="EPSG:3310", driver="ESRI Shapefile")
  feats, fields = read_shapefile(tmp_path / "t.shp", segmentize_m=1000)
  assert fields == [{"name": "AOA_N", "type": "int"}] and feats[0]["properties"] == {"AOA_N": 7}
  b = feats[0]["geometry"].bounds
  assert -121.0 < b[0] < -119.0 and 33.0 < b[1] < 36.0           # lon/lat near the Albers origin (-120, 0 -> ~34N)
  assert len(feats[0]["geometry"].exterior.coords) > 30        # 40 km of edge at 1 km spacing
