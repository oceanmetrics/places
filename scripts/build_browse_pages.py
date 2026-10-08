#!/usr/bin/env python3
"""Generate browsable index.html pages for the public bucket (storage.oceanmetrics.io).

S3 serves objects, not directories, and anonymous ListBucket is denied, so a folder URL has
nothing to show. This writes one real `index.html` per prefix (file table, breadcrumbs, the
prefix's README.md rendered inline); the Caddy vhost (MarineSensitivity/server caddy/Caddyfile)
rewrites a folder URL to that object. Same conventions as the sibling generators:
  * CalCOFI/workflows scripts/build_storage_index.R   (storage.calcofi.io: name/size/modified, chips)
  * MarineSensitivity/msens R/storage.R               (same bucket and vhost: look, README block,
    dirs link to the storage host, files link straight to S3 so no bytes transit the VM)

It only WRITES local files. Uploading is a separate, deliberate step (see docs/browse_pages.md):
    aws s3 sync OUT s3://oceanmetrics.io-public/ --exclude '*' --include '*index.html' \
        --cache-control no-cache

Usage:
    scripts/build_browse_pages.py --prefix gazetteer/ --out OUT            # live bucket listing
    scripts/build_browse_pages.py --prefix gazetteer/ --local catalog/pub --out OUT   # local tree
    scripts/build_browse_pages.py --prefix gazetteer/ --root --out OUT     # + the root page

Idempotent: no timestamps in the pages, so the same listing yields byte-identical output; pages
under the generated prefixes that the new listing no longer needs are removed from OUT.
"""
from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

BUCKET = "oceanmetrics.io-public"
SITE_URL = "https://storage.oceanmetrics.io"
FILE_BASE = f"https://s3.us-east-1.amazonaws.com/{BUCKET}"
GA4_ID = "G-9HW6L751XG"  # the property every page on this host already reports to
# prefixes the Caddy vhost serves (@atlas); the root page lists exactly these, never backups/ etc.
ROOT_PREFIXES = ("marine-atlas", "gazetteer")
MAX_ROWS = 2000


@dataclass(frozen=True)
class Obj:
    key: str
    size: int
    modified: str  # ISO 8601, UTC


# ---- listing ----------------------------------------------------------------------------------


def list_bucket(bucket: str, prefix: str, region: str = "us-east-1") -> list[Obj]:
    """All objects under prefix (aws cli follows pagination)."""
    out = subprocess.run(
        ["aws", "s3api", "list-objects-v2", "--bucket", bucket, "--prefix", prefix,
         "--region", region, "--output", "json"],
        check=True, capture_output=True, text=True).stdout
    return parse_listing(json.loads(out) if out.strip() else {})


def parse_listing(doc: dict) -> list[Obj]:
    return [Obj(c["Key"], int(c["Size"]), c["LastModified"]) for c in doc.get("Contents") or []]


def list_local(root: Path, prefix: str) -> list[Obj]:
    """A local mirror of ONE prefix: keys are prefix + path relative to root."""
    objs = []
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            objs.append(Obj(prefix + p.relative_to(root).as_posix(), st.st_size,
                            datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat()))
    return objs


# ---- markdown (tiny, deterministic, HTML-safe: everything is escaped) -------------------------

_SCHEME = re.compile(r"^(https?:|mailto:|ftp:|//|#)", re.I)


class Md:
    """Just enough markdown for the gazetteer READMEs: headings, paragraphs, (nested) lists,
    pipe tables, fenced code, blockquotes, rules; inline code, bold, italic, links, bare URLs.
    Relative links are resolved against the README's directory: README.md -> that directory's page,
    a known directory -> its page, anything else -> the object on the bucket."""

    def __init__(self, dirkey: str, dirs: set[str], site_url: str, file_base: str):
        self.dirkey, self.dirs, self.site, self.files = dirkey, dirs, site_url, file_base
        self._stash: list[str] = []

    # inline
    def _hold(self, s: str) -> str:
        self._stash.append(s)
        return f"\x00{len(self._stash) - 1}\x00"

    def href(self, h: str) -> str:
        if _SCHEME.match(h):
            return h
        path, sep, frag = h.partition("#")
        path, qsep, query = path.partition("?")
        tail = (qsep + query if qsep else "") + (sep + frag if sep else "")
        if not path:
            return h
        key = posixpath.normpath(posixpath.join(self.dirkey, path))
        if key.startswith(".."):
            return h
        if posixpath.basename(key) == "README.md":  # the directory's page renders it
            d = posixpath.dirname(key)
            return (f"{self.site}/{quote(d, safe='/:')}/" if d else f"{self.site}/") + tail
        if key in self.dirs or path.endswith("/"):
            return f"{self.site}/{quote(key, safe='/:')}/" + tail
        return f"{self.files}/{quote(key, safe='/:')}" + tail

    def inline(self, s: str) -> str:
        s = re.sub(r"`([^`]+)`", lambda m: self._hold(f"<code>{html.escape(m[1])}</code>"), s)
        s = html.escape(s, quote=False)

        def link(m):
            return self._hold(f'<a href="{html.escape(self.href(html.unescape(m[2])), quote=True)}">'
                              f"{self.inline_text(m[1])}</a>")

        s = re.sub(r'\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)', link, s)

        def bare(m):
            u = m[0].rstrip(".,;:")
            return self._hold(f'<a href="{u}">{u}</a>') + m[0][len(u):]

        s = re.sub(r"https?://[^\s<>\x00]+", bare, s)
        return self._finish(s)

    def inline_text(self, s: str) -> str:
        """link text: code spans are already stashed by the caller; emphasis only."""
        return self._emphasis(s)

    @staticmethod
    def _emphasis(s: str) -> str:
        s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])", r"<em>\1</em>", s)
        s = re.sub(r"(?<![\w])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w])", r"<em>\1</em>", s)
        return s

    def _finish(self, s: str) -> str:
        s = self._emphasis(s)
        while "\x00" in s:
            s = re.sub(r"\x00(\d+)\x00", lambda m: self._stash[int(m[1])], s)
        return s

    # blocks
    def render(self, md: str) -> str:
        lines = md.replace("\r\n", "\n").replace("\t", "    ").split("\n")
        return "\n".join(self._blocks(lines))

    def _blocks(self, lines: list[str]) -> list[str]:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            ln = lines[i]
            if not ln.strip():
                i += 1
            elif ln.lstrip().startswith("```"):
                j = i + 1
                while j < n and not lines[j].lstrip().startswith("```"):
                    j += 1
                out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
                i = j + 1
            elif m := re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", ln):
                lvl = len(m[1])
                out.append(f"<h{lvl}>{self.inline(m[2])}</h{lvl}>")
                i += 1
            elif re.match(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$", ln):
                out.append("<hr>")
                i += 1
            elif ln.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$", lines[i + 1]):
                j = i + 2
                while j < n and lines[j].lstrip().startswith("|"):
                    j += 1
                out.append(self._table(lines[i], lines[i + 2:j]))
                i = j
            elif ln.lstrip().startswith(">"):
                j = i
                while j < n and lines[j].lstrip().startswith(">"):
                    j += 1
                inner = [re.sub(r"^\s*>\s?", "", x) for x in lines[i:j]]
                out.append("<blockquote>" + "\n".join(self._blocks(inner)) + "</blockquote>")
                i = j
            elif re.match(r"^\s*([-*+]|\d+[.)])\s+", ln):
                html_, i = self._list(lines, i)
                out.append(html_)
            else:
                j = i
                while j < n and lines[j].strip() and not self._starts_block(lines[j]):
                    j += 1
                j = max(j, i + 1)
                out.append("<p>" + self.inline(" ".join(x.strip() for x in lines[i:j])) + "</p>")
                i = j
        return out

    @staticmethod
    def _starts_block(ln: str) -> bool:
        s = ln.lstrip()
        return bool(s.startswith(("```", "#", ">", "|")) or re.match(r"^([-*+]|\d+[.)])\s+", s))

    def _cells(self, row: str) -> list[str]:
        r = row.strip()
        r = r[1:] if r.startswith("|") else r
        r = r[:-1] if r.endswith("|") and not r.endswith("\\|") else r
        return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", r)]

    def _table(self, head: str, body: list[str]) -> str:
        th = "".join(f"<th>{self.inline(c)}</th>" for c in self._cells(head))
        trs = "".join("<tr>" + "".join(f"<td>{self.inline(c)}</td>" for c in self._cells(b)) + "</tr>"
                      for b in body)
        return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"

    def _list(self, lines: list[str], i: int) -> tuple[str, int]:
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+", lines[i])
        base, ordered = len(m[1]), m[2][0].isdigit()
        tag = "ol" if ordered else "ul"
        items: list[str] = []
        n = len(lines)
        while i < n:
            m = re.match(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$", lines[i])
            if not m or len(m[1]) != base:
                break
            text, i = [m[3]], i + 1
            nested = ""
            while i < n and lines[i].strip():
                mm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+", lines[i])
                if mm and len(mm[1]) > base:
                    nested, i = self._list(lines, i)
                elif mm and len(mm[1]) <= base:
                    break
                elif lines[i].startswith(" ") or not self._starts_block(lines[i]):
                    text.append(lines[i].strip())
                    i += 1
                else:
                    break
            items.append(f"<li>{self.inline(' '.join(text))}{nested}</li>")
            # a single blank line between items of the same list does not end it
            if i < n and not lines[i].strip() and i + 1 < n:
                mm = re.match(r"^(\s*)([-*+]|\d+[.)])\s+", lines[i + 1])
                if mm and len(mm[1]) == base:
                    i += 1
        return f"<{tag}>{''.join(items)}</{tag}>", i


# ---- pages ------------------------------------------------------------------------------------


def fmt_size(n: int) -> str:
    v, units = float(n), ["B", "KB", "MB", "GB", "TB"]
    k = 0
    while v >= 1024 and k < len(units) - 1:
        v, k = v / 1024, k + 1
    s = f"{v:.1f}" if k else f"{int(v)}"
    return f"{s.removesuffix('.0')} {units[k]}"


def fmt_time(iso: str) -> str:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc).strftime("%Y-%m-%d %H:%MZ")


CSS = (
    ":root{--fg:#1a1a1a;--muted:#6b7280;--bd:#e5e7eb;--bg:#fff;--acc:#0b6bcb}"
    "@media(prefers-color-scheme:dark){:root{--fg:#e5e7eb;--muted:#9ca3af;--bd:#374151;--bg:#111827;--acc:#60a5fa}}"
    "body{margin:0;padding:2rem 1rem;background:var(--bg);color:var(--fg);"
    "font:15px/1.5 -apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif}"
    "main{max-width:60rem;margin:0 auto}h1{font-size:1.4rem;margin:0 0 .25rem}"
    ".sub,.crumb{color:var(--muted);font-size:.9rem}.crumb{margin-bottom:1rem}"
    "a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}"
    ".scroll{overflow-x:auto}table{border-collapse:collapse;width:100%;margin-top:1rem}"
    "th,td{text-align:left;padding:.4rem .6rem;border-bottom:1px solid var(--bd);white-space:nowrap}"
    "th{font-size:.8rem;text-transform:uppercase;color:var(--muted)}"
    "td.num{text-align:right;font-variant-numeric:tabular-nums}"
    ".chip{background:var(--bd);border-radius:999px;padding:.05rem .5rem;font-size:.8rem;color:var(--muted)}"
    "footer{margin-top:2rem;color:var(--muted);font-size:.85rem}"
    ".readme{margin:1rem 0 .5rem;padding:.75rem 1rem;border:1px solid var(--bd);border-radius:8px;"
    "background:color-mix(in srgb,var(--bd) 25%,transparent)}"
    ".readme h1,.readme h2,.readme h3{font-size:1rem;margin:.4rem 0}.readme p{margin:.4rem 0}"
    ".readme code{font-size:.85em;background:var(--bd);padding:.05rem .3rem;border-radius:4px}"
    ".readme pre{overflow-x:auto;background:var(--bd);padding:.5rem;border-radius:6px}"
    ".readme pre code{background:none;padding:0}.readme ul,.readme ol{margin:.4rem 0 .4rem 1.1rem}"
    ".readme table{display:block;overflow-x:auto;margin:.5rem 0;font-size:.9em}"
    ".readme th,.readme td{white-space:normal;vertical-align:top}"
    ".readme blockquote{margin:.4rem 0;padding-left:.8rem;border-left:3px solid var(--bd);color:var(--muted)}"
)


def page(title: str, sub: str, body: str, crumbs: str, ga4_id: str = GA4_ID) -> str:
    ga = (f"<script async src='https://www.googletagmanager.com/gtag/js?id={ga4_id}'></script><script>"
          f"window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
          f"gtag('js',new Date());gtag('config','{ga4_id}',{{content_group:'storage'}});</script>") if ga4_id else ""
    t = html.escape(title)
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>{ga}"
            f"<title>{t}</title><style>{CSS}</style></head><body><main><h1>{t}</h1>"
            f"<div class='sub'>{html.escape(sub)}</div><div class='crumb'>{crumbs}</div>"
            f"<div class='scroll'>{body}</div>"
            f"<footer>Ocean Metrics public storage &middot; generated by <code>scripts/build_browse_pages.py</code> in "
            f"<a href='https://github.com/oceanmetrics/places'>oceanmetrics/places</a>. "
            f"Folders are browsed here; every file link downloads straight from Amazon S3.</footer>"
            f"</main></body></html>\n")


def crumbs_for(d: str, site_url: str) -> str:
    if not d:
        return "root"
    seg = d.split("/")
    parts = [f"<a href='{site_url}/'>root</a>"]
    for i, s in enumerate(seg):
        href = f"{site_url}/{quote('/'.join(seg[:i + 1]), safe='/:')}/"
        parts.append(f"<a href='{href}'>{html.escape(s)}</a>" if i < len(seg) - 1 else html.escape(s))
    return " / ".join(parts)


def _is_page(key: str) -> bool:
    return key == "index.html" or key.endswith("/index.html") or key.endswith("/")


def ancestors(key: str) -> list[str]:
    seg = key.split("/")[:-1]
    return ["/".join(seg[:i]) for i in range(1, len(seg) + 1)]


def build_pages(objs: list[Obj], readmes: dict[str, str], prefixes: list[str], *,
                site_url: str = SITE_URL, file_base: str = FILE_BASE,
                ga4_id: str = GA4_ID, root: bool = False,
                root_prefixes: tuple[str, ...] = ROOT_PREFIXES) -> dict[str, str]:
    """{page key: html}. One page per directory at/below each prefix (prefix 'gazetteer/' -> the
    'gazetteer' page and every descendant); with root=True also the bucket root page, which lists
    root_prefixes only. `readmes` maps a README.md object key to its text."""
    objs = sorted((o for o in objs if not _is_page(o.key)), key=lambda o: o.key)
    dirs = {a for o in objs for a in ancestors(o.key)}
    pages: dict[str, str] = {}
    pfx = [p.strip("/") for p in prefixes]

    def under(d: str) -> bool:
        return any(d == p or d.startswith(p + "/") for p in pfx)

    def listing(d: str) -> tuple[str, str]:
        pre = f"{d}/" if d else ""
        here = [o for o in objs if o.key.startswith(pre)]
        groups: dict[str, list[Obj]] = {}
        for o in here:
            groups.setdefault(o.key[len(pre):].split("/")[0], []).append(o)
        rows, shown = [], 0
        entries = sorted(groups.items(), key=lambda kv: (not any("/" in o.key[len(pre):] for o in kv[1]), kv[0]))
        for name, items in entries:
            if shown >= MAX_ROWS:
                break
            shown += 1
            if any("/" in o.key[len(pre):] for o in items):  # a directory
                mods = sorted(o.modified for o in items)
                href = f"{site_url}/{quote(pre + name, safe='/:')}/"
                rows.append(
                    f"<tr><td><a href='{href}'>{html.escape(name)}/</a> <span class='chip'>{len(items):,}</span></td>"
                    f"<td class='num'>{fmt_size(sum(o.size for o in items))}</td>"
                    f"<td class='num' title='oldest {mods[0]} · newest {mods[-1]}'>{fmt_time(mods[-1])}</td></tr>")
            else:
                o = items[0]
                rows.append(
                    f"<tr><td><a href='{file_base}/{quote(o.key, safe='/:')}'>{html.escape(name)}</a></td>"
                    f"<td class='num'>{fmt_size(o.size)}</td><td class='num'>{fmt_time(o.modified)}</td></tr>")
        if len(entries) > shown:
            rows.append(f"<tr><td colspan='3' class='chip'>showing {shown:,} of {len(entries):,} entries</td></tr>")
        table = ("<table><thead><tr><th>name</th><th class='num'>size</th><th class='num'>modified</th></tr></thead>"
                 f"<tbody>{''.join(rows)}</tbody></table>")
        return table, f"{len(here):,} object(s), {fmt_size(sum(o.size for o in here))}"

    def intro(d: str) -> str:
        md = readmes.get(f"{d}/README.md" if d else "README.md")
        if not md or not md.strip():
            return ""
        return "<div class='readme'>" + Md(d, dirs, site_url, file_base).render(md) + "</div>"

    for d in sorted(x for x in dirs if under(x)):
        table, sub = listing(d)
        pages[f"{d}/index.html"] = page(d, sub, intro(d) + table, crumbs_for(d, site_url), ga4_id)

    if root:
        rows = []
        for top in root_prefixes:
            items = [o for o in objs if o.key.startswith(top + "/")]
            href = f"{site_url}/{quote(top, safe='/:')}/"
            if items:
                rows.append(f"<tr><td><a href='{href}'>{html.escape(top)}/</a></td>"
                            f"<td class='num'>{len(items):,}</td><td class='num'>{fmt_size(sum(o.size for o in items))}</td></tr>")
            else:  # not walked in this run: still linked, no totals
                rows.append(f"<tr><td><a href='{href}'>{html.escape(top)}/</a></td><td class='num'></td><td class='num'></td></tr>")
        table = ("<table><thead><tr><th>name</th><th class='num'>items</th><th class='num'>size</th></tr></thead>"
                 f"<tbody>{''.join(rows)}</tbody></table>")
        pages["index.html"] = page("oceanmetrics.io-public", "public storage", intro("") + table, "root", ga4_id)
    return pages


# ---- readme fetching, output ------------------------------------------------------------------


def fetch_readmes(objs: list[Obj], file_base: str, local: Path | None, prefix: str) -> dict[str, str]:
    keys = [o.key for o in objs if o.key == "README.md" or o.key.endswith("/README.md")]
    if local is not None:
        return {k: (local / k[len(prefix):]).read_text(encoding="utf-8") for k in keys}

    def get(k: str) -> tuple[str, str]:
        with urlopen(f"{file_base}/{quote(k, safe='/:')}", timeout=30) as r:
            return k, r.read().decode("utf-8")

    with ThreadPoolExecutor(8) as ex:
        return dict(ex.map(get, keys))


def write_pages(pages: dict[str, str], out: Path, prefixes: list[str], root: bool) -> tuple[int, int]:
    """Write pages; drop index.html files under the generated prefixes that are no longer wanted."""
    out.mkdir(parents=True, exist_ok=True)
    for key, doc in pages.items():
        f = out / key
        f.parent.mkdir(parents=True, exist_ok=True)
        if not f.exists() or f.read_text(encoding="utf-8") != doc:
            f.write_text(doc, encoding="utf-8")
    roots = [out / p.strip("/") for p in prefixes] + ([out / "index.html"] if root else [])
    for r in roots:
        for f in ([r] if r.is_file() else sorted(r.rglob("index.html")) if r.is_dir() else []):
            if f.relative_to(out).as_posix() not in pages:
                f.unlink()
    return len(pages), sum(len(d.encode("utf-8")) for d in pages.values())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--prefix", action="append", help="bucket prefix to generate pages for (repeatable); default gazetteer/")
    ap.add_argument("--out", required=True, type=Path, help="local output dir (mirrors the bucket layout)")
    ap.add_argument("--bucket", default=BUCKET)
    ap.add_argument("--local", type=Path, help="a local mirror of the single --prefix (e.g. catalog/pub) instead of the bucket listing")
    ap.add_argument("--site-url", default=SITE_URL, help="host that serves the folder pages")
    ap.add_argument("--file-base", default=FILE_BASE, help="where file links point (default: the S3 endpoint)")
    ap.add_argument("--ga4-id", default=GA4_ID, help="GA4 measurement id ('' for none)")
    ap.add_argument("--root", action="store_true", help="also write the root index.html (marine-atlas/ and gazetteer/ only)")
    a = ap.parse_args(argv)

    prefixes = [p if p.endswith("/") else p + "/" for p in (a.prefix or ["gazetteer/"])]
    if a.local and len(prefixes) != 1:
        ap.error("--local mirrors exactly one --prefix")
    objs = [o for p in prefixes for o in (list_local(a.local, p) if a.local else list_bucket(a.bucket, p))]
    readmes = fetch_readmes(objs, a.file_base, a.local, prefixes[0])
    if a.root:  # the root README sits beside the pages; not part of any prefix listing
        try:
            with urlopen(f"{a.file_base}/README.md", timeout=30) as r:
                readmes["README.md"] = r.read().decode("utf-8")
        except OSError:
            pass
    pages = build_pages(objs, readmes, prefixes, site_url=a.site_url.rstrip("/"), file_base=a.file_base.rstrip("/"),
                        ga4_id=a.ga4_id, root=a.root)
    n, size = write_pages(pages, a.out, prefixes, a.root)
    print(f"{len(objs):,} objects -> {n} page(s), {size:,} bytes in {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
