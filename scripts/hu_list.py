#!/usr/bin/env python3
"""Build the catalogue of Hungarian legislation from the NJT ELI list pages.

https://njt.jog.gov.hu/eli/TV/<year>            acts (törvények)
https://njt.jog.gov.hu/eli/TVR/<year>           law-decrees (törvényerejű rendeletek)
https://njt.jog.gov.hu/eli/R/<year>/<issuer>    decrees (Korm = government, ministers ...)

Each list page shows 10 items with their validity interval ("Hatályos: from - to").
Output: _raw/hu/catalogue.jsonl (one JSON object per item, all items, in force or not).

Usage: hu_list.py [tv|tvr|korm|min|all] [--from YEAR] [--to YEAR]
"""
import argparse
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hu_common import BASE, RAW, get  # noqa: E402

LISTDIR = os.path.join(RAW, "lists")

ITEM_RE = re.compile(
    r'<h4>\s*<a[^>]*href="(/eli/[^"]+)"[^>]*>(.*?)</a>\s*</h4>\s*'
    r'<p>(.*?)</p>\s*<p class="small">(.*?)</p>', re.S)
BADGE_RE = re.compile(r'<span class="badge">(\d+)</span>')
LAST_RE = re.compile(r"eliListPagerLink\((\d+), '[^']*'\)\">\s*<button[^>]*ri-skip-right")


def clean(t):
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()


def fetch_list(path, page):
    """Return HTML of a list page (cached)."""
    fn = os.path.join(LISTDIR, path.strip("/").replace("/", "_") + "_p%d.html" % page)
    if os.path.exists(fn):
        with open(fn, encoding="utf-8") as f:
            return f.read()
    url = BASE + path + ("?page=%d" % page if page > 1 else "")
    r = get(url, allow_redirects=False)
    if r.status_code in (301, 302):
        txt = ""  # no such list (redirect to search form)
    else:
        r.raise_for_status()
        txt = r.text
    os.makedirs(LISTDIR, exist_ok=True)
    with open(fn + ".tmp", "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(fn + ".tmp", fn)
    return txt


def parse(txt):
    items = []
    for href, label, title, small in ITEM_RE.findall(txt):
        m = re.search(r"Hatályos:\s*(\d{4}-\d\d-\d\d)?\s*-\s*(\d{4}-\d\d-\d\d)?", clean(small))
        items.append({
            "eli": href,
            "label": clean(label),
            "title": clean(title),
            "from": m.group(1) if m else None,
            "to": m.group(2) if m else None,
        })
    return items


def crawl(path, category, check_year=True):
    txt = fetch_list(path, 1)
    if not txt:
        return []
    m = BADGE_RE.search(txt)
    total = int(m.group(1)) if m else 0
    if total == 0:
        return []
    pages = (total + 9) // 10
    out = parse(txt)
    # An unknown year makes the server fall back to an unfiltered list: detect it.
    year = path.split("/")[3]
    if check_year and out and any(it["eli"].split("/")[3] != year for it in out):
        print("SKIP %s: unfiltered fallback list" % path, file=sys.stderr)
        return []
    for p in range(2, pages + 1):
        out += parse(fetch_list(path, p))
    for it in out:
        it["category"] = category
        it["list"] = path
    if len(out) != total:
        print("WARN %s: expected %d got %d" % (path, total, len(out)), file=sys.stderr)
    return out


def ministers():
    """Issuer codes for ministerial decrees, from the ELI issuer table."""
    fn = os.path.join(RAW, "eli_kibocsatokodok.html")
    if not os.path.exists(fn):
        r = get(BASE + "/eli/kibocsatokodok")
        with open(fn, "w", encoding="utf-8") as f:
            f.write(r.text)
    s = open(fn, encoding="utf-8").read()
    rows = re.findall(r"<tr>\s*<td>(.*?)</td>\s*<td>(.*?)</td>", s, re.S)
    out = []
    for code, name in rows:
        code, name = clean(code), clean(name)
        if not code:
            continue
        if ("miniszter" in name.lower() and "államtitkár" not in name.lower()) or code == "ME":
            out.append((code, name))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("what", nargs="?", default="all")
    ap.add_argument("--from", dest="y0", type=int, default=None)
    ap.add_argument("--to", dest="y1", type=int, default=2026)
    ap.add_argument("--workers", type=int, default=3)
    a = ap.parse_args()

    jobs = []  # (path, category)
    if a.what in ("tv", "all"):
        jobs += [("/eli/TV/%d" % y, "torveny") for y in range(a.y0 or 1800, a.y1 + 1)]
    if a.what in ("tvr", "all"):
        jobs += [("/eli/TVR/%d" % y, "tvr") for y in range(a.y0 or 1945, min(a.y1, 1990) + 1)]
    if a.what in ("korm", "all"):
        jobs += [("/eli/R/%d/Korm" % y, "korm") for y in range(a.y0 or 1945, a.y1 + 1)]
        jobs += [("/eli/R/%d/MT" % y, "mt") for y in range(a.y0 or 1945, min(a.y1, 1990) + 1)]
    if a.what in ("min", "all"):
        # An invalid year (1800) makes the server return the unfiltered list of all
        # decrees of the issuer, which saves one request per issuer and year.
        for code, _ in ministers():
            jobs.append(("/eli/R/1800/%s" % code.replace(" ", "%20"), "min", False))

    out_fn = os.path.join(RAW, "catalogue_%s.jsonl" % a.what)
    n = 0
    with ThreadPoolExecutor(a.workers) as ex, open(out_fn, "w", encoding="utf-8") as f:
        for items in ex.map(lambda j: crawl(*j), jobs):
            for it in items:
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
                n += 1
    print("wrote %d items to %s" % (n, out_fn))


if __name__ == "__main__":
    main()
