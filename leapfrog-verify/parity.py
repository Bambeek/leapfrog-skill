#!/usr/bin/env python3
"""Feature parity and leap progress from the feature matrix. Standard library only.

    parity.py leapfrog/features.csv
    parity.py leapfrog/features.csv --layout leapfrog/diffs/layout.json --markdown leapfrog/parity.md
    parity.py leapfrog/features.csv --fail-under 80          # exit 1 below 80 or with must-haves missing

features.csv: id,feature,area,priority,original,clone,source,notes
  priority  must 3, should 2, could 1
  clone     yes 1, partial 0.5, no 0, skip (left out of the score)
  original  "no" marks a leap: something you add that the original lacks.
            Leaps are scored on their own and never count against parity.
"""

import argparse
import csv
import json
import sys

WEIGHT = {"must": 3, "should": 2, "could": 1}
DONE = {"yes": 1.0, "y": 1.0, "done": 1.0, "partial": 0.5, "no": 0.0, "": 0.0}
LEAPS_FOR_VERDICT = 3


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def score(rows):
    parity, leaps, skipped, bad = [], [], [], []
    for r in rows:
        clone = r.get("clone", "").lower()
        prio = r.get("priority", "").lower()
        if clone == "skip":
            skipped.append(r)
            continue
        if clone not in DONE or prio not in WEIGHT:
            bad.append(r)
            continue
        (leaps if r.get("original", "").lower() == "no" else parity).append(r)

    def pct(group):
        total = sum(WEIGHT[r["priority"].lower()] for r in group)
        got = sum(WEIGHT[r["priority"].lower()] * DONE[r["clone"].lower()] for r in group)
        return (100.0 * got / total) if total else 0.0

    areas = {}
    for r in parity:
        areas.setdefault(r.get("area") or "-", []).append(r)
    musts = [r for r in parity if r["priority"].lower() == "must"]
    must_done = [r for r in musts if DONE[r["clone"].lower()] == 1.0]
    order = {"must": 0, "should": 1, "could": 2}
    missing = sorted((r for r in parity if DONE[r["clone"].lower()] < 1.0),
                     key=lambda r: (order[r["priority"].lower()], DONE[r["clone"].lower()]))
    return {
        "score": round(pct(parity), 1),
        "musts": len(musts), "musts_done": len(must_done),
        "areas": sorted(((a, round(pct(g), 1), len(g)) for a, g in areas.items()), key=lambda x: x[1]),
        "missing": missing,
        "leaps": len(leaps), "leaps_done": sum(1 for r in leaps if DONE[r["clone"].lower()] == 1.0),
        "leap_score": round(pct(leaps), 1),
        "skipped": len(skipped), "bad": bad,
    }


def layout_scores(paths):
    scores = {}
    for p in paths:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        for item in data if isinstance(data, list) else data.get("screens", [data]):
            if "score" in item:
                scores[item.get("screen") or item.get("original", p)] = item["score"]
    return scores


def verdict(res, layout):
    if res["musts_done"] < res["musts"]:
        return "not shippable", "%d must-have(s) missing" % (res["musts"] - res["musts_done"])
    if res["score"] < 80:
        return "not shippable", "parity %.1f is under 80" % res["score"]
    if res["leaps_done"] >= LEAPS_FOR_VERDICT:
        return "leapfrogged", "%d leaps done on top of parity" % res["leaps_done"]
    return "shippable", "only %d of %d leaps needed to leapfrog done" % (res["leaps_done"], LEAPS_FOR_VERDICT)


def report_lines(res, layout, md=False):
    v, why = verdict(res, layout)
    h = "## " if md else ""
    out = ["%sVerdict: %s (%s)" % (h, v, why), "",
           "parity %.1f   must-haves %d/%d   leaps %d/%d (%.1f)   skipped %d" % (
               res["score"], res["musts_done"], res["musts"], res["leaps_done"], res["leaps"],
               res["leap_score"], res["skipped"])]
    if layout:
        avg = sum(layout.values()) / len(layout)
        low = sorted(layout.items(), key=lambda kv: kv[1])[:5]
        out.append("layout avg %.1f over %d screens; lowest: %s" % (
            avg, len(layout), ", ".join("%s %.0f" % kv for kv in low)))
    out.append("")
    out.append("%sweakest areas" % h)
    out += ["  %-18s %5.1f  (%d rows)" % a for a in res["areas"][:5]]
    out.append("")
    out.append("%smissing, in build order" % h)
    for r in res["missing"][: 50 if md else 10]:
        out.append("  %-6s %-6s %-8s %s" % (r.get("id", ""), r["priority"], r["clone"] or "no", r.get("feature", "")))
    if not md and len(res["missing"]) > 10:
        out.append("  ... %d more (use --markdown)" % (len(res["missing"]) - 10))
    if res["bad"]:
        out.append("")
        out.append("rows with an unknown priority or clone value: " + ", ".join(r.get("id") or r.get("feature", "?") for r in res["bad"]))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Feature parity and leap progress")
    ap.add_argument("features")
    ap.add_argument("--layout", nargs="*", default=[], help="layout_diff.py JSON files")
    ap.add_argument("--markdown", metavar="FILE", help="write the full report here")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-under", type=float)
    args = ap.parse_args(argv)

    res = score(read(args.features))
    layout = layout_scores(args.layout) if args.layout else {}
    if args.json:
        res_out = dict(res, missing=[r.get("id") or r.get("feature") for r in res["missing"]], bad=len(res["bad"]))
        res_out["verdict"] = verdict(res, layout)[0]
        res_out["layout"] = layout
        print(json.dumps(res_out, indent=1))
    else:
        print("\n".join(report_lines(res, layout)))
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as f:
            f.write("# Parity report\n\n" + "\n".join(report_lines(res, layout, md=True)) + "\n")
    if args.fail_under is not None and (res["score"] < args.fail_under or res["musts_done"] < res["musts"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
