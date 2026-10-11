# Hungary — legislation as Markdown (LawCodex)

Hungarian legislation in force, in its current consolidated (*hatályos*) form, converted
to Markdown: Magyarország Alaptörvénye (the Fundamental Law), every act (*törvény*) and
law-decree (*törvényerejű rendelet*) in force, every government decree
(*kormányrendelet*, including the Council of Ministers' *MT rendelet*s still in force),
and every ministerial decree (*miniszteri rendelet*) in force. The texts are in Hungarian,
the only official language.

Part of [LawCodex](https://github.com/LawCodex), which publishes one repository per
jurisdiction.

## Coverage

Counts as of the retrieval date (2026-10-12):

<!-- COUNTS -->

"In force" means that the [NJT ELI list](https://njt.jog.gov.hu/eli/urisemak) gives the
item no end of validity, or an end of validity later than the retrieval date. This
includes:

- acts already promulgated but not yet in force (`status: not_yet_in_force`, with
  `in_force_from`);
- amending acts that are still in force today but will lapse automatically
  (`in_force_until` in the front matter).

Some items in force have an empty body, because all their operative provisions have been
repealed or merged into other acts (common for old acts and amending acts). They are kept
because NJT still lists them as in force; their footnotes explain what happened to the
text.

### Not covered

- Repealed legislation and historical versions (NJT has every *időállapot*; only the
  current one is collected).
- Decrees of autonomous regulatory bodies and other issuers (Magyar Nemzeti Bank, NMHH,
  MEKH, SZTFH, etc.), decrees of the Prime Minister's state secretaries, *határozat*s,
  *utasítás*ok, *közlemény*ek, Constitutional Court decisions.
- Local government decrees (*önkormányzati rendeletek*, tens of thousands).
- Explanatory memoranda (*indokolások*) and translations.
- Pictures embedded in the texts are not copied: they are linked to their NJT URL.

## Source

- **Nemzeti Jogszabálytár (NJT)**, <https://njt.jog.gov.hu>, the official, free
  database of consolidated Hungarian legislation (operated by MKIFK Magyar Közlönykiadó és
  Igazságügyi Fordítóközpont Zrt. under Government Decree 338/2011. (XII. 29.)).
- The catalogue comes from the ELI list pages
  (`https://njt.jog.gov.hu/eli/TV/<year>`, `/eli/TVR/<year>`, `/eli/R/<year>/Korm`,
  `/eli/R/<year>/MT`, and per-minister `/eli/R/…/<issuer>` lists).
- Each text is the current version of `https://njt.jog.gov.hu/jogszabaly/<njt-id>`. Large
  documents are loaded in blocks through the site's own `/ajax/njtGetBlock.json` endpoint,
  exactly as the web page does.
- NJT has no bulk download or documented API. The older host `njt.hu` refused connections
  from the machine used for this extraction; `njt.jog.gov.hu` (the current official host)
  was used instead.

### Copyright / licence

Under Section 1(4) of the Hungarian Copyright Act (1999. évi LXXVI. törvény), legislation
and other official texts are not protected by copyright. NJT states that MKIFK reserves
all rights in the texts as presented on its site; this repository contains only the
legislative texts themselves (with the official amendment footnotes), converted to plain
Markdown.

## Structure

```
alaptorveny/magyarorszag-alaptorvenye.md
torvenyek/<year>/<year>-<number>-<slug>.md                  acts
torvenyereju-rendeletek/<year>/<year>-<number>-<slug>.md    law-decrees (1949–1989)
kormanyrendeletek/<year>/<year>-<number>-korm-<slug>.md     government decrees
kormanyrendeletek/<year>/<year>-<number>-mt-<slug>.md       Council of Ministers decrees
miniszteri-rendeletek/<year>/<year>-<number>-<issuer>-<slug>.md   ministerial decrees
```

`<number>` is the official serial number in Arabic numerals (e.g. 2013. évi V. törvény →
`2013-5-…`), `<issuer>` is the NJT/ELI issuer code (`im`, `pm`, `bm`, `ekm`...), and `<slug>` is
the ASCII-transliterated title.

Each file has YAML front matter:

```yaml
title: "2013. évi V. törvény a Polgári Törvénykönyvről"
identifier: "2013. évi V. törvény"
njt_id: "2013-5-00-00"
eli: "https://njt.jog.gov.hu/eli/TV/2013/5"
type: act            # constitution | act | law-decree | government-decree | ministerial-decree
jurisdiction: hu
language: hu
date: 2013-02-26     # promulgation date
in_force_from: 2014-03-15
last_amended: 2026-10-01   # start of the consolidated time state (időállapot) retrieved
status: in_force     # or not_yet_in_force
source: "https://njt.jog.gov.hu/jogszabaly/2013-5-00-00"
retrieved: 2026-10-12
```

The body follows the structure of the act: books (*könyv*), parts (*rész*), titles (*cím*),
chapters (*fejezet*) and sub-headings become Markdown headings, sections (`§`) and articles
(*cikk*) are headings at the deepest level (`######` at most; unnumbered sub-headings
that would go deeper become **bold** lines). Annexes (*mellékletek*) are level-2 headings.
NJT's footnotes (promulgation date, amendment history) are kept as Markdown footnotes.
Tables become Markdown tables when simple, HTML tables otherwise.

## Regenerating

```sh
pip install -r scripts/requirements.txt
cd scripts
python hu_list.py tv; python hu_list.py tvr; python hu_list.py korm; python hu_list.py min
echo '{"eli": "/eli/Alaptv", "label": "Magyarország Alaptörvénye", "from": "2012-01-01", "to": null, "category": "alaptorveny"}' > ../../_raw/hu/catalogue_alaptorveny.jsonl
cd ../../_raw/hu
python ../../hu/scripts/hu_fetch.py catalogue_alaptorveny.jsonl catalogue_tv.jsonl catalogue_tvr.jsonl catalogue_korm.jsonl catalogue_min.jsonl
python ../../hu/scripts/hu_convert.py catalogue_alaptorveny.jsonl catalogue_tv.jsonl catalogue_tvr.jsonl catalogue_korm.jsonl catalogue_min.jsonl
python ../../hu/scripts/hu_counts.py
```

Raw pages are cached (gzip) in `../_raw/hu/` (override with `HU_RAW`). The scripts send
the User-Agent `LawCodex/1.0 (+https://github.com/LawCodex)`, use at most 2–3 parallel
connections with a delay between requests, and back off whenever NJT answers with its
"Túl sok lekérdezés" (too many requests) notice. `robots.txt` of njt.jog.gov.hu sets
no crawl delay and only disallows `/search/`, which is not used.
