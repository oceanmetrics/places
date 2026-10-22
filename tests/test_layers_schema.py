"""the layers.json that scripts/build_layers_json.py produces validates against the platform contract
(`@oceanmetrics/catalog` schemas/places-layers.schema.json, from oceanmetrics/platform packages/catalog): keys, types, the h3 rule, `access`."""
import copy
import json
import os
from pathlib import Path

import pytest

from test_layers_json import COLL, REF, RESCINDED, LEDGER, SHA_NEW, bl

jsonschema = pytest.importorskip("jsonschema")

NAME = "places-layers.schema.json"
ROOT = Path(__file__).resolve().parent.parent
# first hit wins: $OM_SCHEMAS_DIR, the npm package the web install brings (web/package.json devDependency), then a sibling
# checkout of oceanmetrics/platform
SCHEMAS_CANDIDATES = [
  *([Path(os.environ["OM_SCHEMAS_DIR"])] if os.environ.get("OM_SCHEMAS_DIR") else []),
  ROOT / "web/node_modules/@oceanmetrics/catalog/schemas",
  ROOT.parent / "platform/packages/catalog/schemas",
]
SCHEMAS_DIR = next((d for d in SCHEMAS_CANDIDATES if (d / NAME).exists()), SCHEMAS_CANDIDATES[0])


@pytest.fixture(scope="module")
def validator():
  f = SCHEMAS_DIR / NAME
  if not f.exists():
    pytest.skip(f"{f} not found: set OM_SCHEMAS_DIR or run `npm install` in web/")
  schema = json.loads(f.read_text())
  jsonschema.Draft202012Validator.check_schema(schema)
  return jsonschema.Draft202012Validator(schema)


def built_manifest():
  """the builder's own rows for a polygon layer (with a current membership), a public point, a line, an unlisted
  polygon (membership current too), a raster reference row and a derived one."""
  line = {**COLL, "id": "acme_lines", "geoparquet:geometry_type": "MultiLineString"}
  point = {**COLL, "id": "acme_points", "geoparquet:geometry_type": "Point"}
  hidden = {**RESCINDED, "id": "acme_hidden", "gazetteer:access": "unlisted"}
  derived = {**REF, "id": "acme_high_seas", "gazetteer:raster": None, "gazetteer:reference": True,
             "gazetteer:display": {"via": "acme_leases", "id_from": "fao_id"}}
  rows = [bl.layer_row(RESCINDED, ledger=LEDGER), bl.layer_row(line), bl.layer_row(point), bl.layer_row(hidden, ledger=LEDGER),
          bl.layer_row(REF), bl.layer_row(derived)]
  mans = {s: {"places_sha256": SHA_NEW} for s in ("boem_wind_planning_rescinded", "acme_hidden")}
  rows = bl.attach_h3(rows, mans)
  return bl.manifest(rows, generated="2026-10-22T12:00:00Z")


def test_the_builders_layers_json_validates(validator):
  doc = built_manifest()
  assert {r["kind"] for r in doc["layers"]} == {"vector", "raster", "derived"}
  assert [r["access"] for r in doc["layers"]].count("unlisted") == 1
  errors = sorted(validator.iter_errors(doc), key=lambda e: list(e.path))
  assert errors == [], [f"{list(e.path)}: {e.message}" for e in errors]


def test_a_polygon_vector_row_without_h3_is_rejected_regression(validator):
  # the invariant of the H3 job (--missing): a polygon vector layer always has its membership
  doc = built_manifest()
  doc["layers"][0]["h3"] = None
  assert not validator.is_valid(doc)


def test_missing_access_and_unknown_keys_are_rejected(validator):
  doc = built_manifest()
  no_access = copy.deepcopy(doc)
  del no_access["layers"][1]["access"]
  assert not validator.is_valid(no_access)
  extra = copy.deepcopy(doc)
  extra["layers"][1]["visibility"] = "public"
  assert not validator.is_valid(extra)
  bad = copy.deepcopy(doc)
  bad["layers"][1]["access"] = "private"
  assert not validator.is_valid(bad)
