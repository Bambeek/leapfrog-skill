#!/usr/bin/env python3
"""Pick the leaps: which user wishes and competitor gaps to build first.

    opportunity.py draft leapfrog/wishes.json --gaps leapfrog/gaps.csv --out leapfrog/candidates.csv
    # fill size (S/M/L) and fit (0-2) in candidates.csv, optionally rename feature
    opportunity.py score leapfrog/candidates.csv --top 8 --apply leapfrog/features.csv

gaps.csv: feature,original,<competitor>,<competitor>... with yes/no/partial.
A feature the original lacks and a competitor has is a gap candidate. A gap
that matches a wish cluster's words is merged into that wish.

Score = (0.2 + demand / max demand) x size (S 1, M 0.6, L 0.3)
        x (1 + 0.5 x fit) x (1 + 0.3 x competitors that have it, max 3)
        x 0.3 if maybe-shipped, x 1.2 if declined or stalled.
"""

import argparse
import csv
import json
import os
import re
import sys

SIZE = {"S": 1.0, "M": 0.6, "L": 0.3}
YES = {"yes", "y", "partial", "1", "true"}
FIELDS = ["id", "feature", "kind", "demand", "mentions", "sources", "competitors", "flags", "evidence", "size", "fit"]


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


def terms(s):
    return {stem(w) for w in re.findall(r"[a-z][a-z0-9]{2,}", s.lower())}


def read_gaps(path):
    gaps = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        comps = [c for c in reader.fieldnames if c and c.strip().lower() not in ("feature", "original", "notes")]
        for r in reader:
            if (r.get("original") or "").strip().lower() in YES:
                continue
            have = [c for c in comps if (r.get(c) or "").strip().lower() in YES]
            if have:
                gaps.append({"feature": r["feature"].strip(), "have": have})
    return gaps


def draft(wishes_path, gaps_path=None):
    with open(wishes_path, encoding="utf-8") as f:
        clusters = json.load(f)["clusters"]
    rows = []
    for c in clusters:
        rows.append({
            "id": c["id"], "feature": c["label"], "kind": "wish", "demand": c["score"],
            "mentions": c["mentions"], "sources": len(c["sources"]), "competitors": "",
            "flags": " ".join(c["flags"]), "evidence": c["quotes"][0]["url"] if c["quotes"] else "",
            "size": "", "fit": "", "_terms": set(c.get("keywords", [])) | terms(c["label"]),
        })
    if gaps_path:
        n = 0
        for g in read_gaps(gaps_path):
            gt = terms(g["feature"])
            match, best = None, 0.5  # at least half the gap's words must appear in the wish
            for r in rows:
                if r["kind"] == "wish" and gt:
                    share = len(gt & r["_terms"]) / float(len(gt))
                    if share >= best and (match is None or share > best):
                        match, best = r, share
            if match:
                have = set(filter(None, match["competitors"].split(";"))) | set(g["have"])
                match["competitors"] = ";".join(sorted(have))
                if g["feature"].lower() not in match["feature"].lower():
                    match["feature"] += " (%s)" % g["feature"]
            else:
                n += 1
                rows.append({
                    "id": "G%02d" % n, "feature": g["feature"], "kind": "gap", "demand": 0, "mentions": 0,
                    "sources": 0, "competitors": ";".join(g["have"]), "flags": "", "evidence": "",
                    "size": "", "fit": "", "_terms": gt,
                })
    for r in rows:
        r.pop("_terms", None)
    return rows


def score_rows(rows):
    max_demand = max([float(r["demand"] or 0) for r in rows] + [1.0])
    scored, skipped = [], []
    for r in rows:
        size = (r.get("size") or "").strip().upper()[:1]
        if size not in SIZE:
            skipped.append(r["id"])
            continue
        try:
            fit = min(2.0, max(0.0, float(r.get("fit") or 0)))
        except ValueError:
            fit = 0.0
        comps = len([c for c in (r.get("competitors") or "").split(";") if c])
        s = (0.2 + float(r["demand"] or 0) / max_demand) * SIZE[size] * (1 + 0.5 * fit) * (1 + 0.3 * min(comps, 3))
        flags = (r.get("flags") or "").split()
        if "maybe-shipped" in flags:
            s *= 0.3
        if "declined" in flags or "stalled" in flags:
            s *= 1.2
        scored.append(dict(r, score=round(s, 3)))
    scored.sort(key=lambda r: -r["score"])
    return scored, skipped


def apply(features_path, leaps):
    existing, header = [], None
    if os.path.exists(features_path):
        with open(features_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            existing = list(reader)
    header = header or ["id", "feature", "area", "priority", "original", "clone", "source", "notes"]
    have = {(r.get("source") or "") for r in existing}
    n = sum(1 for r in existing if (r.get("id") or "").startswith("L")) + 1
    added = 0
    with open(features_path, "a" if existing else "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        if not existing:
            w.writeheader()
        for i, r in enumerate(leaps):
            src = "%s:%s" % (r["kind"], r["id"])
            if src in have:
                continue
            w.writerow({
                "id": "L%02d" % n, "feature": r["feature"], "area": "leap",
                "priority": "must" if i < 3 else "should", "original": "no", "clone": "no",
                "source": src, "notes": r.get("evidence") or ("competitors: " + r.get("competitors", "")),
            })
            n += 1
            added += 1
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pick which wishes and gaps to build")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("draft")
    d.add_argument("wishes", help="wishes.json from wish_rank.py")
    d.add_argument("--gaps", help="gaps.csv")
    d.add_argument("--out", default="leapfrog/candidates.csv")
    d.add_argument("--max", type=int, default=25, help="wish clusters to include")
    s = sub.add_parser("score")
    s.add_argument("candidates")
    s.add_argument("--top", type=int, default=8)
    s.add_argument("--apply", metavar="FEATURES_CSV", help="append the top leaps to the feature matrix")
    args = ap.parse_args(argv)

    if args.cmd == "draft":
        rows = draft(args.wishes, args.gaps)
        wishes = [r for r in rows if r["kind"] == "wish"][: args.max]
        rows = wishes + [r for r in rows if r["kind"] == "gap"]
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rows)
        print("%d candidates (%d wishes, %d gaps) -> %s" % (
            len(rows), len(wishes), len(rows) - len(wishes), args.out))
        print("fill size (S/M/L) and fit (0-2), then: opportunity.py score %s" % args.out)
        return 0

    with open(args.candidates, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    scored, skipped = score_rows(rows)
    top = scored[: args.top]
    for r in top:
        print("  %-4s %-40s %5.2f  size %s fit %s  %s" % (
            r["id"], r["feature"][:40], r["score"], r["size"], r["fit"], r["flags"]))
    if skipped:
        print("skipped (no size): " + ", ".join(skipped))
    if args.apply:
        print("+%d leap rows -> %s" % (apply(args.apply, top), args.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
