"""gazetteer/retire.py: unlink a published collection from the root catalog.json and versions.json."""
import pytest

from gazetteer.retire import unlink_collection

CAT = {"type": "Catalog", "links": [{"rel": "root", "href": "./catalog.json"},
                                   {"rel": "child", "href": "./a/collection.json"},
                                   {"rel": "child", "href": "./protectedseas_navigator/collection.json"}]}
VER = {"schema_version": "1", "collections": {"a": {"current_version": "1.0.0"},
                                              "protectedseas_navigator": {"current_version": "1.0.0"}}}


def test_unlink_drops_the_child_link_and_the_versions_entry_only():
  """retiring protectedseas_navigator (split into six layers, 2026-10-20) takes it out of what the index and
  layers.json read; nothing else changes."""
  cat, ver = unlink_collection(CAT, VER, "protectedseas_navigator")
  assert [l["href"] for l in cat["links"]] == ["./catalog.json", "./a/collection.json"]
  assert ver == {"schema_version": "1", "collections": {"a": {"current_version": "1.0.0"}}}
  assert len(CAT["links"]) == 3 and "protectedseas_navigator" in VER["collections"]      # inputs untouched


def test_an_unknown_slug_raises():
  with pytest.raises(KeyError, match="no child link"):
    unlink_collection(CAT, VER, "protectedseas_navigatr")
