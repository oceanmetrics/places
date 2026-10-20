"""gazetteer/pipeline.restac_layer: metadata from the YAML over staged files, no fetch (needs a staged mr_goas)."""
import json
import shutil

import pytest

from conftest import ROOT
from gazetteer.config import load_all
from gazetteer.pipeline import restac_layer

STAGED = ROOT / "catalog" / "staging" / "mr_goas"


@pytest.mark.skipif(not (STAGED / "places.parquet").exists(), reason="mr_goas not staged")
def test_restac_version_bumps_the_metadata_and_writes_the_identify_template(tmp_path):
  """mr_* 1.0.1 for `info_url` (2026-10-20) without re-downloading the layers from VLIZ: a new collection version,
  the rows untouched."""
  shutil.copytree(STAGED, tmp_path / "mr_goas")
  before = (tmp_path / "mr_goas" / "places.parquet").read_bytes()
  res = restac_layer(load_all(ROOT / "sources")["mr_goas"], tmp_path, version="9.9.9")
  assert res["reference"] is True
  coll = json.loads((tmp_path / "mr_goas" / "collection.json").read_text())
  prov = json.loads((tmp_path / "mr_goas" / "provenance.json").read_text())
  assert prov["version"] == "9.9.9" and coll["gazetteer:provenance"]["version"] == "9.9.9"
  r = coll["gazetteer:raster"]
  assert "REQUEST=GetFeatureInfo" in r["info_url"] and "{bbox}" in r["info_url"] and r["info_id"] == "name"
  assert (tmp_path / "mr_goas" / "places.parquet").read_bytes() == before
