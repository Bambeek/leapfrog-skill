#!/usr/bin/env python3
"""Rank what users already asked for. Standard library only, no network.

    wish_rank.py leapfrog/wishes.csv --out leapfrog/wishes.md
    wish_rank.py a.csv b.csv --changelog leapfrog/sources/changelog.txt --app "AppName"

Input CSV columns: source,url,date,rating,votes,status,text (extra ignored).
Rows without url or text are dropped and counted, never guessed.

Keeps only sentences that ask for something (wish), describe a workaround,
or say why someone left (churn), using the patterns in phrases.json. Groups
them into clusters (themes first, then word overlap), and scores each:

    item weight = (1 + log2(1 + votes)) x kind (churn 1.5, workaround 1.3)
                  x 0.5 if older than --months
    cluster     = sum of item weights x (1 + 0.25 per extra source)

Flags: thin (under 3 mentions or one source), maybe-shipped (changelog line
shares its key words), stalled (open or planned on a board for 2+ years),
declined (closed as not planned). Every quote is a verbatim substring of a
row you supplied, printed with that row's URL.

Writes wishes.md (or --out) and the same data as JSON next to it. Prints a
short summary only.
"""

import argparse
import collections
import csv
import datetime as dt
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIND_WEIGHT = {"wish": 1.0, "workaround": 1.3, "churn": 1.5}
OPEN_STATUSES = {"open", "planned", "under review", "considering", "in review", "backlog", "future consideration"}
DECLINED_STATUSES = {"declined", "not planned", "closed", "won't do", "wont do", "rejected"}
QUOTE_MAX = 280
STOP = set("""
a about above after again against all also am an and any are as at be because been before being below between both but by
can could did do does doing down during each few for from further had has have having he her here hers herself him himself his
how i if in into is it its itself just let like me more most my myself no nor not now of off on once only or other our ours
out over own really same she should so some such than that the their theirs them then there these they this those through to
too under until up very was we were what when where which while who whom why will with would you your yours yourself
app apps thing things way lot get got use using used make want wish please would love need able feature features add
dont doesnt cant isnt im ive id its theyre youre one even still much many also every great good nice bad
""".split())


def load_phrases(path):
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    kinds = {k: [re.compile(p, re.I) for p in pats] for k, pats in cfg["kinds"].items()}
    themes = {t: [re.compile(r"\b" + re.escape(w), re.I) for w in words] for t, words in cfg.get("themes", {}).items()}
    return kinds, themes


def parse_date(s):
    s = (s or "").strip()
    for fmt, n in (("%Y-%m-%d", 10), ("%Y-%m", 7), ("%Y", 4)):
        try:
            return dt.datetime.strptime(s[:n], fmt).date()
        except ValueError:
            pass
    return None


def to_int(s):
    try:
        return max(0, int(float(str(s).strip())))
    except (TypeError, ValueError):
        return 0


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 12]


def stem(w):
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith("es") and w[-3] in "sxzh":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def words(s, extra_stop):
    out = []
    for w in re.findall(r"[a-z][a-z0-9'+-]{2,}", s.lower()):
        w = w.replace("'", "")
        if w in STOP or w in extra_stop:
            continue
        w = stem(w)
        if w not in STOP and w not in extra_stop:
            out.append(w)
    return out


def read_rows(paths):
    rows, dropped = [], 0
    for p in paths:
        with open(p, newline="", encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
                if not r.get("url") or not r.get("text"):
                    dropped += 1
                    continue
                rows.append(r)
    return rows, dropped


def extract(rows, kinds, today, months, extra_stop):
    items, seen = [], set()
    cutoff = today - dt.timedelta(days=int(months * 30.4))
    for r in rows:
        date = parse_date(r.get("date"))
        votes = to_int(r.get("votes"))
        for s in sentences(r["text"]):
            key = (r["url"], s.lower())
            if key in seen:
                continue
            found = [k for k, pats in kinds.items() if any(p.search(s) for p in pats)]
            if not found:
                continue
            seen.add(key)
            kind = max(found, key=lambda k: KIND_WEIGHT.get(k, 1.0))
            w = (1 + math.log2(1 + votes)) * KIND_WEIGHT.get(kind, 1.0)
            if date and date < cutoff:
                w *= 0.5
            items.append({
                "text": s, "url": r["url"], "source": r.get("source") or "unknown",
                "date": date.isoformat() if date else "", "votes": votes, "kind": kind,
                "status": (r.get("status") or "").lower(), "weight": w,
                "words": set(words(s, extra_stop)),
            })
    return items


def theme_of(text, themes):
    best, hits = None, 0
    for t, pats in themes.items():
        n = sum(1 for p in pats if p.search(text))
        if n > hits:
            best, hits = t, n
    return best


def cluster(items, themes, overlap=0.25):
    clusters = []
    by_theme = {}
    for it in sorted(items, key=lambda i: -i["weight"]):
        t = theme_of(it["text"], themes)
        if t:
            c = by_theme.get(t)
            if c is None:
                c = by_theme[t] = {"label": t, "theme": True, "items": [], "terms": collections.Counter()}
                clusters.append(c)
        else:
            c, best = None, 0.0
            for cand in clusters:
                if cand["theme"]:
                    continue
                top = {w for w, _ in cand["terms"].most_common(12)}
                if not it["words"] or not top:
                    continue
                j = len(it["words"] & top) / float(len(it["words"] | top))
                if j > best:
                    c, best = cand, j
            if c is None or best < overlap:
                c = {"label": None, "theme": False, "items": [], "terms": collections.Counter()}
                clusters.append(c)
        c["items"].append(it)
        c["terms"].update(it["words"])
    for c in clusters:
        if not c["label"]:
            c["label"] = " / ".join(w for w, _ in c["terms"].most_common(3)) or "misc"
    return clusters


def changelog_hit(c, lines):
    keys = [w for w, _ in c["terms"].most_common(6)]
    for line in lines:
        lw = set(words(line, set()))
        if len([k for k in keys if k in lw]) >= 2:
            return line.strip()[:160]
    return None


def score(clusters, today, changelog_lines):
    out = []
    stall_cut = today - dt.timedelta(days=730)
    for c in clusters:
        items = c["items"]
        sources = sorted({i["source"] for i in items})
        total = sum(i["weight"] for i in items) * (1 + 0.25 * (len(sources) - 1))
        flags = []
        if len(items) < 3 or len(sources) < 2:
            flags.append("thin")
        hit = changelog_hit(c, changelog_lines) if changelog_lines else None
        if hit:
            flags.append("maybe-shipped")
        if any(i["status"] in DECLINED_STATUSES for i in items):
            flags.append("declined")
        if any(i["status"] in OPEN_STATUSES and i["date"] and parse_date(i["date"]) < stall_cut for i in items):
            flags.append("stalled")
        quotes, used_src = [], set()
        for i in sorted(items, key=lambda i: -i["weight"]):
            if len(quotes) == 2:
                break
            if i["source"] in used_src and len({x["source"] for x in items}) > 1:
                continue
            used_src.add(i["source"])
            t = i["text"] if len(i["text"]) <= QUOTE_MAX else i["text"][:QUOTE_MAX].rstrip() + "..."
            quotes.append({"text": t, "url": i["url"], "source": i["source"], "date": i["date"]})
        out.append({
            "label": c["label"], "score": round(total, 2), "mentions": len(items), "sources": sources,
            "votes": sum(i["votes"] for i in items),
            "kinds": dict(collections.Counter(i["kind"] for i in items)),
            "flags": flags, "changelog": hit, "keywords": [w for w, _ in c["terms"].most_common(8)],
            "quotes": quotes,
        })
    out.sort(key=lambda c: -c["score"])
    for n, c in enumerate(out, 1):
        c["id"] = "W%02d" % n
    return out


def to_markdown(clusters, meta):
    o = ["# What users already asked for", "",
         "%(rows)d rows, %(dropped)d dropped (no url or text), %(items)d matching sentences, %(clusters)d clusters. "
         "Ranked by score. Quotes are verbatim." % meta, ""]
    for c in clusters:
        kinds = ", ".join("%s %d" % kv for kv in sorted(c["kinds"].items()))
        flags = (" **" + ", ".join(c["flags"]) + "**") if c["flags"] else ""
        o.append("## %s %s (score %.1f)%s" % (c["id"], c["label"], c["score"], flags))
        o.append("%d mentions, %d sources (%s), %d votes. %s" % (
            c["mentions"], len(c["sources"]), ", ".join(c["sources"]), c["votes"], kinds))
        if c["changelog"]:
            o.append("Changelog: \"%s\"" % c["changelog"])
        for q in c["quotes"]:
            o.append("> \"%s\" [%s%s](%s)" % (q["text"], q["source"], ", " + q["date"] if q["date"] else "", q["url"]))
        o.append("")
    return "\n".join(o)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Rank what users already asked for")
    ap.add_argument("csv", nargs="+")
    ap.add_argument("--out", default="leapfrog/wishes.md")
    ap.add_argument("--phrases", default=os.path.join(HERE, "phrases.json"))
    ap.add_argument("--changelog", help="plain text of the original's changelog")
    ap.add_argument("--app", default="", help="comma-separated names to ignore as words (the app, its company)")
    ap.add_argument("--months", type=float, default=18, help="older items count half (default 18)")
    ap.add_argument("--today", help="YYYY-MM-DD, for reproducible runs")
    ap.add_argument("--top", type=int, default=8, help="clusters shown in the summary")
    args = ap.parse_args(argv)

    today = parse_date(args.today) if args.today else dt.date.today()
    kinds, themes = load_phrases(args.phrases)
    extra_stop = {w.strip().lower() for n in args.app.split(",") for w in n.split() if w.strip()}
    rows, dropped = read_rows(args.csv)
    items = extract(rows, kinds, today, args.months, extra_stop)
    changelog = []
    if args.changelog:
        with open(args.changelog, encoding="utf-8", errors="replace") as f:
            changelog = [l for l in f if l.strip()]
    clusters = score(cluster(items, themes), today, changelog)
    meta = {"rows": len(rows), "dropped": dropped, "items": len(items), "clusters": len(clusters)}

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(to_markdown(clusters, meta))
    json_path = os.path.splitext(args.out)[0] + ".json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "clusters": clusters}, f, indent=1)

    print("%(rows)d rows (%(dropped)d dropped), %(items)d wish sentences, %(clusters)d clusters" % meta)
    for c in clusters[: args.top]:
        print("  %s %-34s %6.1f  %3d x %d src  %s" % (
            c["id"], c["label"][:34], c["score"], c["mentions"], len(c["sources"]), ",".join(c["flags"])))
    print("-> %s, %s" % (args.out, json_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
