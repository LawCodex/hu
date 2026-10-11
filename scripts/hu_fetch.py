#!/usr/bin/env python3
"""Download the current consolidated text of every in-force item of the catalogue.

For each item: GET the ELI URL (redirects to /jogszabaly/<njt-id>), then load all
lazily-loaded blocks through /ajax/njtGetBlock.json and splice them into the page.
Result cached as gzip under _raw/hu/docs/<njt-id>.html.gz; an index line
(eli -> njt id) is appended to _raw/hu/docs/index.jsonl.

Usage: hu_fetch.py CATALOGUE.jsonl [...] [--workers N] [--all]
"""
import argparse
import gzip
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hu_common import BASE, RAW, get, post_json, in_force  # noqa: E402

DOCDIR = os.path.join(RAW, "docs")
INDEX = os.path.join(DOCDIR, "index.jsonl")
TODAY = os.environ.get("HU_TODAY")
lock = threading.Lock()

BORDER_RE = re.compile(r'<div id="([^"]+)" class="pH borderStart" data-show-order="(\d+)"(?: data-last-show-order="(\d+)")? data-b-n="(\d+)"[^>]*>')
PH_RE = re.compile(r'<div id="([^"]+)" class="pH(?: borderStart)?"[^>]*data-b-n="(\d+)"')


def load_index():
    done = {}
    if os.path.exists(INDEX):
        for line in open(INDEX, encoding="utf-8"):
            try:
                d = json.loads(line)
                done[d["eli"]] = d
            except ValueError:
                pass
    return done


def splice_blocks(page, docid):
    """Replace the placeholder blocks by their content fetched from the AJAX endpoint.

    Large documents are served with an initial prefix and a contiguous run of empty
    placeholder divs (class "pH"); each block starts with a "pH borderStart" div.
    """
    borders = BORDER_RE.findall(page)
    if not borders:
        return page
    block_ids = {}
    for pid, bn in PH_RE.findall(page):
        block_ids.setdefault(bn, []).append(pid)
    parts = []
    for i in range(0, len(borders), 25):
        part = borders[i:i + 25]
        req = []
        for _, so, last, _ in part:
            d = {"start": int(so)}
            if last:
                d["last"] = int(last)
            req.append(d)
        for attempt in range(8):
            r = post_json(BASE + "/ajax/njtGetBlock.json", {"documentId": docid, "data": req})
            missing = [bn for _, _, _, bn in part
                       if not any(('id="%s"' % x) in r.text for x in block_ids.get(bn, []))]
            if r.status_code == 200 and not missing and RATE_MSG not in r.text:
                break
            wait = 30 * (attempt + 1)
            print("block request failed for %s (HTTP %d, %d missing), sleeping %ds"
                  % (docid, r.status_code, len(missing), wait), flush=True)
            time.sleep(wait)
        else:
            raise RuntimeError("blocks missing for %s" % docid)
        parts.append(r.text)
    leaf_re = re.compile(r'<div id="[^"]+" class="pH( borderStart)?"[^>]*>\s*(?:<span id="[^"]*"></span>\s*)*</div>')
    open_re = re.compile(r'<div id="[^"]+" class="pH borderStart"[^>]*>\s*(?:<span id="[^"]*"></span>\s*)*')
    start = page.index('class="pH')
    start = page.rindex("<div", 0, start)
    ms = list(leaf_re.finditer(page))
    end = ms[-1].end()
    # placeholders are nested in their block's borderStart div: consume closing tags
    rest = leaf_re.sub("", page[start:end])
    opened = len(open_re.findall(rest))
    closed = rest.count("</div>")
    if open_re.sub("", rest).replace("</div>", "").strip():
        raise RuntimeError("non-contiguous placeholders in %s" % docid)
    need = opened - closed
    while need > 0:
        m = re.match(r"\s*</div>", page[end:])
        if not m:
            raise RuntimeError("unbalanced placeholders in %s" % docid)
        end += m.end()
        need -= 1
    res = page[:start] + "".join(parts) + page[end:]
    if 'class="pH' in res:
        raise RuntimeError("unresolved placeholders in %s" % docid)
    return res


RATE_MSG = 'id="dntCache"'  # "Túl sok lekérdezés, adott idő alatt!" (too many requests)


def get_page(url):
    """GET a document page; back off while the server answers with its rate-limit notice."""
    for attempt in range(8):
        r = get(url)
        if RATE_MSG not in r.text:
            return r
        wait = 30 * (attempt + 1)
        print("rate-limited on %s, sleeping %ds" % (url, wait), flush=True)
        time.sleep(wait)
    raise RuntimeError("rate-limited: %s" % url)


def direct_id(eli):
    """NJT document id for ELI paths with a known id pattern (saves the ELI redirect)."""
    p = eli.strip("/").split("/")
    if p[1] == "TV" and len(p) == 4:
        return "%s-%s-00-00" % (p[2], p[3])
    if p[1] == "TVR" and len(p) == 4:
        return "%s-%s-10-00" % (p[2], p[3])
    if p[1] == "R" and len(p) == 5 and p[3] == "Korm":
        return "%s-%s-20-22" % (p[2], p[4])
    return None


def fetch_one(it):
    did = direct_id(it["eli"])
    r = None
    if did:
        fn = os.path.join(DOCDIR, did + ".html.gz")
        if os.path.exists(fn):
            return {"eli": it["eli"], "id": did}
        r = get_page(BASE + "/jogszabaly/" + did)
        if r.status_code != 200 or ("openDocument('jogszabaly','%s'" % did) not in r.text:
            r = None
    if r is None:
        r = get_page(BASE + it["eli"])
    if r.status_code != 200 or "/jogszabaly/" not in r.url:
        return {"eli": it["eli"], "error": "HTTP %d %s" % (r.status_code, r.url)}
    docid = r.url.rstrip("/").split("/jogszabaly/")[1].split("?")[0]
    fn = os.path.join(DOCDIR, docid + ".html.gz")
    if not os.path.exists(fn):
        page = r.text
        m = re.search(r"openDocument\('jogszabaly','([^']+)'", page)
        did = m.group(1) if m else docid
        page = splice_blocks(page, did)
        with gzip.open(fn + ".tmp", "wt", encoding="utf-8") as f:
            f.write(page)
        os.replace(fn + ".tmp", fn)
    return {"eli": it["eli"], "id": docid}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("catalogues", nargs="+")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--all", action="store_true", help="also fetch items no longer in force")
    a = ap.parse_args()
    os.makedirs(DOCDIR, exist_ok=True)
    done = load_index()
    items = []
    seen = set()
    for c in a.catalogues:
        for line in open(c, encoding="utf-8"):
            it = json.loads(line)
            if it["eli"] in seen:
                continue
            seen.add(it["eli"])
            if (a.all or in_force(it)) and not (
                    it["eli"] in done and "id" in done[it["eli"]] and
                    os.path.exists(os.path.join(DOCDIR, done[it["eli"]]["id"] + ".html.gz"))):
                items.append(it)
    print("to fetch: %d" % len(items), flush=True)
    n = 0

    def job(it):
        try:
            return fetch_one(it)
        except Exception as e:  # keep going, record the error
            return {"eli": it["eli"], "error": str(e)[:300]}

    with ThreadPoolExecutor(a.workers) as ex, open(INDEX, "a", encoding="utf-8") as idx:
        for res in ex.map(job, items):
            with lock:
                idx.write(json.dumps(res, ensure_ascii=False) + "\n")
                idx.flush()
            n += 1
            if "error" in res:
                print("ERR", res, flush=True)
            if n % 100 == 0:
                print("%d/%d" % (n, len(items)), flush=True)
    print("done", n)


if __name__ == "__main__":
    main()
