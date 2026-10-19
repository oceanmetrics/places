"""gazetteer/ledger.py: versions.json for a metadata-only (reference) collection."""
import json

import pytest

from gazetteer.ledger import append_version


def test_first_and_next_version_record_metadata_files_and_changes(tmp_path):
  d = tmp_path / "mr_eez"
  (d / "styles").mkdir(parents=True)
  (d / "collection.json").write_text("{}")
  (d / "README.md").write_text("a")
  (d / "styles" / "default.json").write_text("{}")
  led = append_version(d, "mr_eez", "1.0.0", now="2026-10-19T00:00:00Z")
  assert led["current_version"] == "1.0.0"
  assert sorted(led["versions"][0]["assets"]) == ["README.md", "collection.json", "styles/default.json"]
  assert led["versions"][0]["assets"]["README.md"]["href"] == "mr_eez/README.md"
  (d / "README.md").write_text("b")
  led = append_version(d, "mr_eez", "1.0.1", "new readme")
  assert [v["version"] for v in led["versions"]] == ["1.0.0", "1.0.1"] and led["versions"][1]["changes"] == ["README.md"]
  assert json.loads((d / "versions.json").read_text())["current_version"] == "1.0.1"
  with pytest.raises(ValueError, match="already has 1.0.1"):
    append_version(d, "mr_eez", "1.0.1")


def test_a_reference_collection_with_data_files_is_refused(tmp_path):
  # marine regions asked us not to republish their products (2026-10-16): never ledger, so never upload, a parquet
  d = tmp_path / "mr_eez"
  d.mkdir()
  (d / "places.parquet").write_bytes(b"PAR1")
  with pytest.raises(ValueError, match="must not carry data files"):
    append_version(d, "mr_eez", "1.0.0")
