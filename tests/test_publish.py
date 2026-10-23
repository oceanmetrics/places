"""the uploads go through oceanmetrics/platform scripts/om-publish.sh (both stores, R2 then S3; never deletes), with the
prefixes, order and headers the aws calls had: scripts/publish_collections.sh run end to end against fakes (portolan,
rashid, aws for the reads of the live root files, curl, and an om-publish that records each call), and
build_h3_membership.py's upload() and upload_layers() with a recording runner."""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "build_h3_membership.py"
spec = importlib.util.spec_from_file_location("build_h3_membership_pub", SCRIPT)
bh = importlib.util.module_from_spec(spec)
sys.modules["build_h3_membership_pub"] = bh
spec.loader.exec_module(bh)

FAKES = {
  # portolan add <slug>/ ...: the fresh 1.0.0 ledger a first publish gets; portolan version bump: nothing
  "portolan": """import json, os, sys
if sys.argv[1] == "add":
    for a in sys.argv[2:]:
        if a.endswith("/") and not a.startswith("-"):
            json.dump({"current_version": "1.0.0", "versions": [{"version": "1.0.0", "assets": {}}]},
                      open(os.path.join(a, "versions.json"), "w"))
""",
  "rashid": "",
  # aws: only the two reads of the live root files are expected; anything else is logged as a write
  "aws": """import json, os, sys
a = sys.argv[1:]
if a[:2] == ["s3", "cp"] and a[2].startswith("s3://") and not a[3].startswith("s3://"):
    live = {"versions.json": {"collections": {"other": {"current_version": "2.0.0"}}, "updated": "2026-01-01"},
            "catalog.json": {"links": [{"rel": "child", "href": "./other/collection.json"}]}}
    json.dump(live[a[2].rsplit("/", 1)[1]], open(a[3], "w"))
else:
    open(os.environ["AWS_WRITES"], "a").write(json.dumps(a) + "\\n")
""",
  "curl": "print('200', end='')",
  "om-publish": """import json, os, sys
open(os.environ["OM_PUBLISH_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\\n")
""",
}


def fakes(d: Path) -> Path:
  d.mkdir()
  for name, body in FAKES.items():
    (d / name).write_text(f"#!{sys.executable}\n{body}")
    (d / name).chmod(0o755)
  return d


def tree(tmp_path: Path, slug: str) -> tuple[Path, Path]:
  pub, staging = tmp_path / "pub", tmp_path / "staging"
  (pub / ".portolan").mkdir(parents=True)
  (pub / "catalog.json").write_text(json.dumps({"links": []}))
  (pub / "versions.json").write_text(json.dumps({"collections": {}}))
  (staging / slug).mkdir(parents=True)
  (staging / slug / "collection.json").write_text(json.dumps({"id": slug, "assets": {"readme": {"href": "./README.md"}}}))
  (staging / slug / "README.md").write_text("# x\n")
  return pub, staging


def test_publish_collections_uploads_each_slug_then_the_merged_root_files_through_om_publish(tmp_path):
  bin_ = fakes(tmp_path / "bin")
  pub, staging = tree(tmp_path, "toy")
  log, writes = tmp_path / "calls.jsonl", tmp_path / "aws_writes.jsonl"
  env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "OM_PUBLISH": str(bin_ / "om-publish"),
         "OM_PUBLISH_LOG": str(log), "AWS_WRITES": str(writes), "PLACES_PUB": str(pub), "PLACES_STAGING": str(staging),
         "PLACES_INTERNAL": str(tmp_path / "internal")}
  r = subprocess.run(["bash", str(ROOT / "scripts" / "publish_collections.sh"), "toy"], env=env, capture_output=True,
                     text=True)
  assert r.returncode == 0, r.stderr + r.stdout
  calls = [json.loads(l) for l in log.read_text().splitlines()]
  assert calls[0] == ["--really", "--exclude", ".portolan/*", "--last", "collection.json", str(pub / "toy"), "gazetteer/toy"]
  assert [(c[:2], c[-3:]) for c in calls[1:]] == [(["--really", "--keep-history"], ["gazetteer", "--as", "versions.json"]),
                                                  (["--really", "--keep-history"], ["gazetteer", "--as", "catalog.json"])]
  assert not writes.exists(), "no aws write: only the two reads of the live root files"
  # the merged root files kept in the pub tree: the live entries plus this slug's
  root_v = json.loads((pub / "versions.json").read_text())
  assert set(root_v["collections"]) == {"other", "toy"} and root_v["collections"]["toy"]["current_version"] == "1.0.0"
  hrefs = [l["href"] for l in json.loads((pub / "catalog.json").read_text())["links"]]
  assert hrefs == ["./other/collection.json", "./toy/collection.json"]


def test_no_upload_runs_no_publisher(tmp_path):
  bin_ = fakes(tmp_path / "bin")
  pub, staging = tree(tmp_path, "toy")
  log = tmp_path / "calls.jsonl"
  env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "OM_PUBLISH": str(tmp_path / "missing"),
         "OM_PUBLISH_LOG": str(log), "AWS_WRITES": str(tmp_path / "w"), "PLACES_PUB": str(pub),
         "PLACES_STAGING": str(staging)}
  r = subprocess.run(["bash", str(ROOT / "scripts" / "publish_collections.sh"), "--no-upload", "toy"], env=env,
                     capture_output=True, text=True)
  assert r.returncode == 0, r.stderr
  assert not log.exists()


def test_the_script_has_no_aws_write_and_no_delete():
  sh = (ROOT / "scripts" / "publish_collections.sh").read_text()
  code = [l for l in sh.splitlines() if not l.lstrip().startswith("#")]
  assert not [l for l in code if "aws s3 sync" in l or ("aws s3 cp" in l and '"$s3_dest/' in l.split("aws s3 cp", 1)[1].split()[1])]
  assert "--delete" not in "\n".join(code)


def test_membership_upload_is_one_om_publish_call_with_membership_json_last(tmp_path):
  calls = []
  bh.upload("noaa_sanctuaries", tmp_path, run=lambda cmd, check: calls.append(cmd), publisher="om-publish.sh")
  assert calls == [["om-publish.sh", "--really", "--last", "membership.json", str(tmp_path / "noaa_sanctuaries" / "h3"),
                    "gazetteer/noaa_sanctuaries/h3"]]


def test_layers_json_goes_to_index_with_history_then_to_the_root_both_no_cache(tmp_path):
  calls = []
  bh.upload_layers(tmp_path / "layers.json", run=lambda cmd, check: calls.append(cmd), publisher="om-publish.sh")
  assert [c[-3:] for c in calls] == [["gazetteer/index", "--as", "layers.json"], ["gazetteer", "--as", "layers.json"]]
  assert "--keep-history" in calls[0] and "--keep-history" not in calls[1]
  assert all(c[c.index("--cache-control") + 1] == "no-cache" for c in calls)


def test_a_missing_publisher_stops(monkeypatch, tmp_path):
  monkeypatch.setenv("OM_PUBLISH", str(tmp_path / "missing"))
  with pytest.raises(SystemExit, match="om-publish.sh not found"):
    bh.om_publish_path()
