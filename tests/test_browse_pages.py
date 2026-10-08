"""scripts/build_browse_pages.py: the generated folder pages for the public bucket."""
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "build_browse_pages", Path(__file__).resolve().parent.parent / "scripts" / "build_browse_pages.py")
bp = importlib.util.module_from_spec(_spec)
sys.modules["build_browse_pages"] = bp  # dataclasses resolves annotations via sys.modules
_spec.loader.exec_module(bp)

SITE, FILES = "https://storage.oceanmetrics.io", "https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public"

README_TOP = """# Ocean Metrics gazetteer

Published at `https://storage.oceanmetrics.io/gazetteer/`.

## Collections

- [`places/`](places/collection.json) -- 20 polygons
  as GeoParquet.
- **bold** and *italic* and a <script>alert(1)</script> tag.

See [`stats/README.md`](stats/README.md) and [the site](https://example.org/a_b_c).
"""
README_STATS = """# stats

| Column | Type |
|---|---|
| place_id | string |
| value | double |

```sql
SELECT * FROM read_parquet('x.parquet')
```
"""

TREE = {  # key -> (bytes, modified)
    "gazetteer/README.md": (README_TOP, "2026-10-08T13:11:09+00:00"),
    "gazetteer/catalog.json": ("x" * 2048, "2026-10-08T18:41:17+00:00"),
    "gazetteer/places/places.parquet": ("x" * 3 * 1024 * 1024, "2026-10-01T10:00:00+00:00"),
    "gazetteer/places/collection.json": ("{}", "2026-10-02T10:00:00+00:00"),
    "gazetteer/stats/README.md": (README_STATS, "2026-10-05T10:00:00+00:00"),
    "gazetteer/stats/dhw_5km/CRW_SST/NMS:HIHWNMS.parquet": ("x" * 1500, "2026-10-07T10:00:00+00:00"),
    "gazetteer/stats/dhw_5km/CRW_SST/NMS:FKNMS.parquet": ("x" * 500, "2026-10-08T10:00:00+00:00"),
    "gazetteer/index.html": ("<html>stale page</html>", "2026-10-01T00:00:00+00:00"),  # never listed
    "gazetteer/empty/": ("", "2026-10-01T00:00:00+00:00"),  # 0-byte directory marker, never listed
    "marine-atlas/latest.txt": ("v7", "2026-10-03T00:00:00+00:00"),
    "marine-atlas/v7/manifest.json": ("x" * 100, "2026-10-04T00:00:00+00:00"),
    "backups/dump.sql": ("x" * 10, "2026-10-04T00:00:00+00:00"),
}


def _objs(tree=TREE):
    return [bp.Obj(k, len(v), m) for k, (v, m) in tree.items()]


def _readmes():
    return {k: v for k, (v, _) in TREE.items() if k.endswith("README.md")}


@pytest.fixture(scope="module")
def pages():
    return bp.build_pages(_objs(), _readmes(), ["gazetteer/"])


def test_one_page_per_directory_below_the_prefix(pages):
    assert sorted(pages) == [
        "gazetteer/index.html",
        "gazetteer/places/index.html",
        "gazetteer/stats/dhw_5km/CRW_SST/index.html",
        "gazetteer/stats/dhw_5km/index.html",
        "gazetteer/stats/index.html",
    ]  # no marine-atlas/ or backups/ pages, no page for the empty directory marker


def test_listing_dirs_first_with_links_sizes_and_modified(pages):
    h = pages["gazetteer/index.html"]
    rows = re.findall(r"<tr><td>(.*?)</td><td class='num'>(.*?)</td><td class='num'[^>]*>(.*?)</td></tr>", h)
    names = [re.sub(r"\s+\d+$", "", re.sub(r"<[^>]+>", "", r[0]).strip()) for r in rows]
    assert names == ["places/", "stats/", "README.md", "catalog.json"]
    # directories link to the storage host (trailing slash) with an object-count chip
    assert f"<a href='{SITE}/gazetteer/places/'>places/</a> <span class='chip'>2</span>" in h
    assert f"<a href='{SITE}/gazetteer/stats/'>stats/</a> <span class='chip'>3</span>" in h
    # files link straight to the bucket
    assert f"<a href='{FILES}/gazetteer/catalog.json'>catalog.json</a>" in h
    assert f"<a href='{FILES}/gazetteer/README.md'>README.md</a>" in h
    sizes = {n: r[1] for n, r in zip(names, rows)}
    assert sizes["catalog.json"] == "2 KB"            # 2048 B, trailing .0 dropped
    assert sizes["places/"] == "3 MB"                 # 3 MiB + 2 B, summed over the directory
    assert sizes["README.md"].endswith(" B")
    mods = {n: r[2] for n, r in zip(names, rows)}
    assert mods["catalog.json"] == "2026-10-08 18:41Z"
    assert mods["stats/"] == "2026-10-08 10:00Z"      # newest object under the directory
    assert "<th>name</th>" in h and "<th class='num'>size</th>" in h and "<th class='num'>modified</th>" in h


def test_subtitle_counts_listed_objects_only(pages):
    # index.html and the 0-byte directory marker are not counted; marine-atlas/ is outside the prefix
    assert "7 object(s)" in pages["gazetteer/index.html"]
    assert "3 object(s)" in pages["gazetteer/stats/index.html"]


def test_colon_in_key_is_kept_in_the_link(pages):
    h = pages["gazetteer/stats/dhw_5km/CRW_SST/index.html"]
    assert f"<a href='{FILES}/gazetteer/stats/dhw_5km/CRW_SST/NMS:FKNMS.parquet'>NMS:FKNMS.parquet</a>" in h
    assert h.index("NMS:FKNMS") < h.index("NMS:HIHWNMS")  # sorted by name


def test_breadcrumbs_run_to_the_root(pages):
    h = pages["gazetteer/stats/dhw_5km/CRW_SST/index.html"]
    assert (f"<div class='crumb'><a href='{SITE}/'>root</a> / <a href='{SITE}/gazetteer/'>gazetteer</a>"
            f" / <a href='{SITE}/gazetteer/stats/'>stats</a> / <a href='{SITE}/gazetteer/stats/dhw_5km/'>dhw_5km</a>"
            f" / CRW_SST</div>") in h
    assert "<div class='crumb'><a href='%s/'>root</a> / gazetteer</div>" % SITE in pages["gazetteer/index.html"]


def test_readme_rendered_inline_on_its_own_directory_page(pages):
    h = pages["gazetteer/index.html"]
    assert "<div class='readme'><h1>Ocean Metrics gazetteer</h1>" in h
    assert "<h2>Collections</h2>" in h
    assert "<code>https://storage.oceanmetrics.io/gazetteer/</code>" in h
    assert "<strong>bold</strong> and <em>italic</em>" in h
    # the list item continued on the next line is one item
    assert re.search(r"<li><a href=\"[^\"]+\"><code>places/</code></a> -- 20 polygons as GeoParquet\.</li>", h)
    # the readme sits above the table
    assert h.index("class='readme'") < h.index("<table><thead><tr><th>name")
    # a child's README is shown on the child's page, not the parent's
    assert "<th>Column</th>" not in h
    s = pages["gazetteer/stats/index.html"]
    assert ("<table><thead><tr><th>Column</th><th>Type</th></tr></thead><tbody>"
            "<tr><td>place_id</td><td>string</td></tr><tr><td>value</td><td>double</td></tr></tbody></table>") in s
    assert "<pre><code>SELECT * FROM read_parquet(&#x27;x.parquet&#x27;)</code></pre>" in s
    assert "class='readme'" not in pages["gazetteer/places/index.html"]  # no README there


def test_readme_html_is_escaped(pages):
    h = pages["gazetteer/index.html"]
    assert "<script>alert(1)</script>" not in h
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in h


def test_readme_relative_links_resolve(pages):
    h = pages["gazetteer/index.html"]
    assert f'<a href="{FILES}/gazetteer/places/collection.json">' in h        # a file -> the bucket
    assert f'<a href="{SITE}/gazetteer/stats/">' in h                         # X/README.md -> X's page
    assert '<a href="https://example.org/a_b_c">the site</a>' in h            # absolute, underscores kept
    assert "<em>b</em>" not in h


def test_deepest_page_exists_for_every_directory_with_objects():
    keys = {o.key for o in _objs() if not o.key.endswith("/") and o.key.startswith("gazetteer/")}
    pg = bp.build_pages(_objs(), {}, ["gazetteer/"])
    for k in keys:
        if k.endswith("index.html"):
            continue
        for a in bp.ancestors(k):
            assert f"{a}/index.html" in pg


def test_deterministic_and_idempotent(tmp_path):
    a = bp.build_pages(_objs(), _readmes(), ["gazetteer/"])
    b = bp.build_pages(list(reversed(_objs())), _readmes(), ["gazetteer/"])
    assert a == b
    n1 = bp.write_pages(a, tmp_path, ["gazetteer/"], False)
    stamp = {p: p.stat().st_mtime_ns for p in tmp_path.rglob("index.html")}
    n2 = bp.write_pages(a, tmp_path, ["gazetteer/"], False)
    assert n1 == n2 and n1[0] == 5
    assert stamp == {p: p.stat().st_mtime_ns for p in tmp_path.rglob("index.html")}  # untouched on rerun


def test_stale_pages_are_removed(tmp_path):
    bp.write_pages(bp.build_pages(_objs(), {}, ["gazetteer/"]), tmp_path, ["gazetteer/"], False)
    assert (tmp_path / "gazetteer/stats/index.html").exists()
    fewer = [o for o in _objs() if "/stats/" not in o.key]
    bp.write_pages(bp.build_pages(fewer, {}, ["gazetteer/"]), tmp_path, ["gazetteer/"], False)
    assert not (tmp_path / "gazetteer/stats/index.html").exists()
    assert (tmp_path / "gazetteer/places/index.html").exists()


def test_root_page_lists_only_the_allowlisted_prefixes():
    pg = bp.build_pages(_objs(), {}, ["gazetteer/"], root=True)
    h = pg["index.html"]
    assert f"<a href='{SITE}/marine-atlas/'>marine-atlas/</a></td><td class='num'>2</td>" in h
    assert f"<a href='{SITE}/gazetteer/'>gazetteer/</a></td><td class='num'>7</td>" in h
    assert "backups" not in h
    assert "<div class='crumb'>root</div>" in h


def test_parse_list_objects_json():
    doc = {"Contents": [{"Key": "gazetteer/a.json", "Size": 5, "LastModified": "2026-10-08T13:11:08+00:00"}]}
    assert bp.parse_listing(doc) == [bp.Obj("gazetteer/a.json", 5, "2026-10-08T13:11:08+00:00")]
    assert bp.parse_listing({}) == []  # an empty prefix has no Contents


def test_local_mode_cli(tmp_path):
    src = tmp_path / "pub"
    (src / "stats").mkdir(parents=True)
    (src / "README.md").write_text("# top\n\nhello\n")
    (src / "stats" / "a.parquet").write_bytes(b"x" * 10)
    out = tmp_path / "out"
    assert bp.main(["--prefix", "gazetteer/", "--local", str(src), "--out", str(out)]) == 0
    top = (out / "gazetteer/index.html").read_text()
    assert "<h1>top</h1>" in top and "<p>hello</p>" in top
    assert f"<a href='{SITE}/gazetteer/stats/'>stats/</a>" in top
    assert "a.parquet" in (out / "gazetteer/stats/index.html").read_text()
    before = (out / "gazetteer/index.html").read_bytes()
    assert bp.main(["--prefix", "gazetteer/", "--local", str(src), "--out", str(out)]) == 0
    assert (out / "gazetteer/index.html").read_bytes() == before


@pytest.mark.parametrize("n,s", [(0, "0 B"), (3, "3 B"), (2048, "2 KB"), (4300000, "4.1 MB"), (int(21.3 * 1024 ** 3), "21.3 GB")])
def test_fmt_size(n, s):
    assert bp.fmt_size(n) == s
