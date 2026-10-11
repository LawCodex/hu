#!/usr/bin/env python3
"""Convert cached NJT pages (_raw/hu/docs/*.html.gz) to LawCodex Markdown.

Usage: hu_convert.py CATALOGUE.jsonl [...]   (uses _raw/hu/docs/index.jsonl for eli->id)
"""
import argparse
import datetime
import gzip
import html as htmlmod
import json
import os
import re
import sys
import unicodedata

from lxml import html as lh

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hu_common import BASE, RAW, ROOT  # noqa: E402

DOCDIR = os.path.join(RAW, "docs")
TODAY = os.environ.get("HU_TODAY") or datetime.date.today().isoformat()
RETRIEVED = os.environ.get("HU_RETRIEVED") or TODAY

MONTHS = {"január": 1, "február": 2, "március": 3, "április": 4, "május": 5, "június": 6,
          "július": 7, "augusztus": 8, "szeptember": 9, "október": 10, "november": 11,
          "december": 12}
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9,
         "X": 10, "XI": 11, "XII": 12}

# Structural slice classes, from the highest level down. Each entry: (label class,
# title class). Title slices follow their label slice.
STRUCT = [
    ("konyv", "konyvcim"),
    ("resz", "reszcim"),
    ("focim", "focimCim"),
    ("alaptorvenyFejezet", None),
    ("fejezet", "fejezetCim"),
    ("alcim", None),
    ("tagolo", None),
    ("tagoloCim", None),
]
MAIN_STRUCT = {"konyv", "resz", "focim", "alaptorvenyFejezet", "fejezet"}
TITLE_CLASSES = {t for _, t in STRUCT if t}
STRUCT_CLASSES = [s for s, _ in STRUCT]
ARTICLE_CLASSES = {"szakasz", "cikkArab", "cikkRomai", "cikkBetu"}

TYPE_INFO = {
    "alaptorveny": ("constitution", "alaptorveny"),
    "torveny": ("act", "torvenyek"),
    "tvr": ("law-decree", "torvenyereju-rendeletek"),
    "korm": ("government-decree", "kormanyrendeletek"),
    "mt": ("government-decree", "kormanyrendeletek"),
    "min": ("ministerial-decree", "miniszteri-rendeletek"),
}


def slugify(s, maxlen=80):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    if len(s) > maxlen:
        s = s[:maxlen].rsplit("-", 1)[0]
    return s


def norm_ws(s):
    s = s.replace(" ", " ")
    return re.sub(r"[ \t\r\n]+", " ", s)


def md_escape_line(s):
    s = s.strip()
    if re.match(r"^\d+\.\s", s):
        s = re.sub(r"^(\d+)\.", r"\1\\.", s, count=1)
    elif re.match(r"^[#>+*-]\s", s) or s.startswith("#"):
        s = "\\" + s
    return s


class Conv:
    def __init__(self, docid):
        self.docid = docid
        self.fn_used = []

    def inline(self, el, skip_jel=False):
        """Render inline content of an element as Markdown text."""
        out = []
        if el.text:
            out.append(el.text)
        for ch in el:
            if not isinstance(ch.tag, str):  # comments
                if ch.tail:
                    out.append(ch.tail)
                continue
            tag = ch.tag.lower()
            cls = ch.get("class") or ""
            if tag == "sup" and "fnSup" in cls:
                n = (ch.text_content() or "").strip()
                if n:
                    out.append("[^%s]" % n)
                    self.fn_used.append(n)
            elif tag == "br":
                out.append("\n")
            elif tag in ("i", "em"):
                t = self.inline(ch)
                out.append(wrap(t, "*"))
            elif tag in ("b", "strong"):
                t = self.inline(ch)
                out.append(wrap(t, "**"))
            elif tag == "img":
                src = ch.get("src") or ""
                if src:
                    if src.startswith("/"):
                        src = BASE + src
                    out.append("![](%s)" % src)
            elif tag == "sup":
                out.append("<sup>%s</sup>" % self.inline(ch).strip())
            elif tag == "sub":
                out.append("<sub>%s</sub>" % self.inline(ch).strip())
            elif tag == "span" and "jhId" in cls:
                pass
            elif tag == "table":
                out.append("\n\n" + self.table(ch) + "\n\n")
            elif tag in ("div", "p"):
                out.append("\n\n" + self.inline(ch) + "\n\n")
            else:
                out.append(self.inline(ch))
            if ch.tail:
                out.append(ch.tail)
        return "".join(out)

    def para(self, el):
        """Block-level rendering: returns list of paragraph strings."""
        txt = self.inline(el)
        paras = []
        for block in re.split(r"\n\s*\n", txt):
            lines = [norm_ws(x).strip() for x in block.split("\n")]
            lines = [x for x in lines if x]
            if not lines:
                continue
            if any(x.startswith("<table") or x.startswith("|") for x in lines):
                paras.append("\n".join(lines))
                continue
            paras.append("\\\n".join(md_escape_line(x) for x in lines))
        return paras

    def table(self, t):
        rows = t.xpath(".//tr")
        simple = True
        grid = []
        for r in rows:
            cells = r.xpath("./td|./th")
            row = []
            for c in cells:
                if int(c.get("colspan") or 1) != 1 or int(c.get("rowspan") or 1) != 1:
                    simple = False
                if c.xpath(".//table"):
                    simple = False
                txt = norm_ws(self.inline(c).replace("\n", " ")).strip()
                row.append(txt.replace("|", "\\|"))
            grid.append(row)
        if simple and grid and len({len(r) for r in grid}) == 1 and len(grid[0]) > 0:
            w = len(grid[0])
            lines = ["| " + " | ".join(grid[0]) + " |", "|" + "---|" * w]
            for r in grid[1:]:
                lines.append("| " + " | ".join(r) + " |")
            return "\n".join(lines)
        return self.html_table(t)

    def html_table(self, t):
        def rec(el):
            tag = el.tag.lower()
            if tag in ("table", "thead", "tbody", "tr"):
                inner = "".join(rec(c) for c in el if isinstance(c.tag, str)
                                and c.tag.lower() in ("thead", "tbody", "tr", "td", "th"))
                return "<%s>%s</%s>" % (tag, inner, tag)
            if tag in ("td", "th"):
                attrs = ""
                for a in ("colspan", "rowspan"):
                    v = el.get(a)
                    if v and v != "1":
                        attrs += ' %s="%s"' % (a, v)
                parts = [norm_ws(p) for p in re.split(r"\n\s*\n", self.inline(el))]
                txt = "<br>".join(x.strip().replace("\n", "<br>") for x in parts if x.strip())
                return "<%s%s>%s</%s>" % (tag, attrs, txt, tag)
            return ""
        return "<table>" + "".join(rec(c) for c in t if isinstance(c.tag, str)
                                    and c.tag.lower() in ("thead", "tbody", "tr")) + "</table>"


def wrap(t, m):
    if not t.strip():
        return t
    lead = t[:len(t) - len(t.lstrip())]
    trail = t[len(t.rstrip()):]
    inner = t.strip()
    if "\n" in inner:
        return t
    return "%s%s%s%s%s" % (lead, m, inner, m, trail)


def parse_date_hu(s):
    m = re.search(r"(\d{4})\.\s*(%s)\s*(\d{1,2})\." % "|".join(MONTHS), s)
    if m:
        try:
            return datetime.date(int(m.group(1)), MONTHS[m.group(2)], int(m.group(3))).isoformat()
        except ValueError:
            return None
    return None


def label_date(label, year):
    """'403/2016. (XII. 5.) Korm. rendelet' -> 2016-12-05"""
    m = re.search(r"\((\w+)\.\s*(\d{1,2})\.\)", label)
    if m and m.group(1) in ROMAN:
        try:
            return datetime.date(int(year), ROMAN[m.group(1)], int(m.group(2))).isoformat()
        except ValueError:
            return None
    return None


def yaml_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def convert(page, item, docid):
    m = re.search(r"openDocument\('jogszabaly','[^']*','((?:[^'\\]|\\.)*)','((?:[^'\\]|\\.)*)'", page)
    label = htmlmod.unescape(m.group(1)) if m else item.get("label", docid)
    fulltitle = htmlmod.unescape(m.group(2)) if m else label
    doc = lh.fromstring(page)
    root = doc.xpath('//div[@id="jogszab"]')
    if not root:
        raise ValueError("no #jogszab in %s" % docid)
    root = root[0]
    c = Conv(docid)

    slices = [el for el in root if isinstance(el.tag, str) and el.tag.lower() in ("div", "h1", "h2", "h3")]
    classes = set()
    for el in slices:
        classes.update((el.get("class") or "").split())
    present = [s for s in STRUCT_CLASSES if s in classes]
    level_of = {s: 2 + i for i, s in enumerate(present)}
    art_level = min(6, 2 + len(present))
    for s_ in present:
        if s_ not in MAIN_STRUCT and level_of[s_] >= art_level:
            level_of[s_] = 99  # rendered as bold paragraph

    hataly = None
    out = []
    pending_struct = None  # (level, label) awaiting its title slice
    pending_art = None  # (level, label) szakasz without own title

    def heading(level, text):
        text = norm_ws(text).strip()
        text = re.sub(r"(?<!\\)\*+", "", text).strip()
        if not text:
            return
        if level <= 6:
            out.append("#" * level + " " + text)
        else:
            out.append("**" + text + "**")

    def flush_struct():
        nonlocal pending_struct
        if pending_struct:
            heading(*pending_struct)
            pending_struct = None

    in_annex = False
    for el in slices:
        cls = (el.get("class") or "").split()
        tag = el.tag.lower()
        if "footnote" in cls:
            continue
        if tag == "h1" or "jogszabalyMainTitle" in cls or "jogszabalySubtitle" in cls:
            continue
        if "hataly" in cls:
            hataly = el.text_content().strip()
            continue
        if "changeVersionParent" in cls:
            continue
        cl0 = cls[0] if cls else ""
        if cl0 in TITLE_CLASSES and pending_struct:
            t = norm_ws(c.inline(el).replace("\n", " ")).strip()
            lvl, lab = pending_struct
            pending_struct = None
            heading(lvl, (lab + " — " + t) if t else lab)
            continue
        flush_struct()
        if cl0 in level_of:
            lab = norm_ws(c.inline(el).replace("\n", " ")).strip()
            lvl = level_of[cl0] + (1 if in_annex else 0)
            if cl0 in ("konyv", "resz", "fejezet", "focim"):
                pending_struct = (lvl, lab)
            else:
                heading(lvl, lab)
            continue
        if cl0 == "mellekletCimke":
            in_annex = True
            heading(2, norm_ws(c.inline(el).replace("\n", " ")).strip())
            continue
        if cl0 == "mellekletTitle":
            t = norm_ws(c.inline(el).replace("\n", " ")).strip()
            if t:
                out.append("**" + t + "**")
            continue
        if cl0 == "mellekletTagolo":
            t = norm_ws(c.inline(el).replace("\n", " ")).strip()
            if t:
                out.append("**" + t + "**")
            continue
        if cl0 in ARTICLE_CLASSES:
            if cl0 == "szakasz":
                cim = el.xpath('.//p[contains(@class,"szakaszCim")]')
                if cim:
                    t = norm_ws(c.inline(cim[0]).replace("\n", " ")).strip()
                    heading(art_level, t)
                else:
                    pending_art = art_level
                    # heading emitted from the szakasz-jel of the next slice
                continue
            heading(art_level, norm_ws(c.inline(el).replace("\n", " ")).strip())
            continue
        # ordinary text slice
        if pending_art is not None:
            sj = el.xpath('.//span[@class="szakasz-jel"]')
            if sj:
                heading(pending_art, sj[0].text_content().strip())
                s = sj[0]
                parent = s.getparent()
                # drop the label from the paragraph (keep its tail)
                tail = s.tail or ""
                prev = s.getprevious()
                if prev is not None:
                    prev.tail = (prev.tail or "") + tail
                else:
                    parent.text = (parent.text or "") + tail
                parent.remove(s)
            pending_art = None
        if "tablazat" in cls or el.xpath("./div[@class='TABLE']"):
            for t in el.xpath(".//table"):
                if t.xpath("ancestor::table"):
                    continue
                out.append(c.table(t))
            continue
        out.extend(c.para(el))
    flush_struct()

    # footnotes
    notes = []
    for fn in root.xpath('.//div[@class="footnote"]') or doc.xpath('//div[@class="footnote"]'):
        sup = fn.xpath("./sup")
        if not sup:
            continue
        n = sup[0].text_content().strip()
        sup[0].getparent().remove(sup[0])
        t = " ".join(p for p in c.para(fn))
        t = norm_ws(t.replace("\\\n", " ")).strip()
        notes.append((n, t))
    used = set(c.fn_used)
    fn_lines = ["[^%s]: %s" % (n, t) for n, t in notes if n in used]
    first_note = notes[0][1] if notes else ""

    # metadata
    cat = item.get("category")
    typ, folder = TYPE_INFO[cat]
    year = docid.split("-")[0]
    num = docid.split("-")[1]
    date = parse_date_hu(first_note.split("kihirdetés napja:")[-1]) if "kihirdetés napja" in first_note else None
    if not date:
        date = label_date(label, year)
    consolidated = None
    if hataly:
        mm = re.match(r"(\d{4})\.(\d\d)\.(\d\d)", hataly)
        if mm:
            consolidated = "%s-%s-%s" % mm.groups()
    status = "in_force"
    if item.get("from") and item["from"] > TODAY:
        status = "not_yet_in_force"

    fm = ["---",
          "title: " + yaml_str(fulltitle),
          "identifier: " + yaml_str(label),
          "njt_id: " + yaml_str(docid),
          "eli: " + yaml_str(BASE + item["eli"]) if item.get("eli") else None,
          "type: " + typ,
          "jurisdiction: hu",
          "language: hu",
          ("date: " + date) if date else None,
          ("in_force_from: " + item["from"]) if item.get("from") else None,
          ("last_amended: " + consolidated) if consolidated else None,
          "status: " + status,
          "source: " + yaml_str(BASE + "/jogszabaly/" + docid),
          "retrieved: " + RETRIEVED,
          "---", ""]
    fm = [x for x in fm if x is not None]
    body = ["# " + norm_ws(fulltitle).strip(), ""]
    for p in out:
        body.append(p)
        body.append("")
    if fn_lines:
        body.append("---")
        body.append("")
        body.extend(fn_lines)
        body.append("")
    text = "\n".join(fm + body)
    text = re.sub(r"\n{3,}", "\n\n", text)

    # path
    if cat == "alaptorveny":
        rel = os.path.join(folder, "magyarorszag-alaptorvenye.md")
    else:
        sub = fulltitle[len(label):].strip() if fulltitle.startswith(label) else fulltitle
        issuer = ""
        if cat in ("korm",):
            issuer = "korm-"
        elif cat == "mt":
            issuer = "mt-"
        elif cat == "min":
            issuer = slugify(item["eli"].split("/")[4]) + "-"
        slug = slugify(sub, 70) or "jogszabaly"
        rel = os.path.join(folder, year, "%s-%s-%s%s.md" % (year, num, issuer, slug))
    return rel, text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("catalogues", nargs="+")
    ap.add_argument("--out", default=ROOT)
    a = ap.parse_args()
    idx = {}
    for line in open(os.path.join(DOCDIR, "index.jsonl"), encoding="utf-8"):
        d = json.loads(line)
        if "id" in d:
            idx[d["eli"]] = d["id"]
    n = err = 0
    written = {}
    for c in a.catalogues:
        for line in open(c, encoding="utf-8"):
            it = json.loads(line)
            docid = idx.get(it["eli"])
            if not docid:
                continue
            if it.get("to"):
                continue
            fn = os.path.join(DOCDIR, docid + ".html.gz")
            if not os.path.exists(fn):
                continue
            try:
                page = gzip.open(fn, "rt", encoding="utf-8").read()
                rel, text = convert(page, it, docid)
            except Exception as e:
                print("ERR", docid, e, file=sys.stderr)
                err += 1
                continue
            if rel in written and written[rel] != docid:
                base, ext = os.path.splitext(rel)
                rel = base + "-" + docid.lower() + ext
            written[rel] = docid
            path = os.path.join(a.out, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            n += 1
    print("converted %d, errors %d" % (n, err))


if __name__ == "__main__":
    main()
