#!/usr/bin/env python3
"""One go/no-go table before deploy. Standard library only.

    preflight.py --project . --features leapfrog/features.csv --brand leapfrog/brand.json
    preflight.py --skip e2e,build

Checks: e2e (Playwright, if configured), bugs (no open S1 or S2 in
leapfrog/bugs.md), parity (must-haves done, score 80+), sweep (clean),
listing (if leapfrog/launch/listing.json exists), build (npm run build, if
package.json has one). Prints one line per check; exit 1 if any fails.
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)


def run(cmd, cwd, shell=False):
    try:
        p = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True, timeout=1800)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, str(e)
    tail = [l for l in (p.stdout + "\n" + p.stderr).splitlines() if l.strip()]
    return p.returncode == 0, (tail[-1] if tail else "")[:100]


def open_bugs(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        text = f.read()
    found = []
    for block in re.split(r"(?m)^##\s+", text)[1:]:
        title = block.splitlines()[0].strip()
        sev = re.search(r"(?im)^severity:\s*(S[1-4])", block)
        fixed = re.search(r"(?im)fixed:\s*(\S+)", block)
        if sev and sev.group(1) in ("S1", "S2") and (not fixed or fixed.group(1).lower() in ("open", "<commit", "-", "no")):
            found.append(title.split()[0] if title else "?")
    return found


def main(argv=None):
    ap = argparse.ArgumentParser(description="Go/no-go checks before deploy")
    ap.add_argument("--project", default=".")
    ap.add_argument("--features", default="leapfrog/features.csv")
    ap.add_argument("--brand", default="leapfrog/brand.json")
    ap.add_argument("--listing", default="leapfrog/launch/listing.json")
    ap.add_argument("--bugs", default="leapfrog/bugs.md")
    ap.add_argument("--min-parity", type=float, default=80)
    ap.add_argument("--skip", default="", help="comma-separated checks to skip")
    args = ap.parse_args(argv)
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    proj = os.path.abspath(args.project)
    at = lambda p: p if os.path.isabs(p) else os.path.join(proj, p)
    py = sys.executable
    results = []

    def check(name, fn):
        if name in skip:
            results.append((name, "skip", "skipped by --skip"))
            return
        status, detail = fn()
        results.append((name, status, detail))

    def e2e():
        if not any(os.path.exists(os.path.join(proj, "playwright.config" + ext)) for ext in (".ts", ".js", ".mjs")):
            return "fail", "no playwright.config: write the flow specs first"
        ok, d = run("npx playwright test --reporter=line", proj, shell=True)
        return ("pass" if ok else "fail"), d

    def bugs():
        found = open_bugs(at(args.bugs))
        if found is None:
            return "fail", "no %s: run leapfrog-verify" % args.bugs
        return ("fail", "open S1/S2: " + ", ".join(found)) if found else ("pass", "no open S1 or S2")

    def parity():
        if not os.path.exists(at(args.features)):
            return "fail", "no " + args.features
        ok, d = run([py, os.path.join(PACK, "leapfrog-verify", "parity.py"), at(args.features),
                     "--fail-under", str(args.min_parity)], proj)
        return ("pass" if ok else "fail"), d

    def sweep():
        if not os.path.exists(at(args.brand)):
            return "fail", "no %s: rebrand first" % args.brand
        ok, d = run([py, os.path.join(HERE, "sweep.py"), proj, "--config", at(args.brand)], proj)
        return ("pass" if ok else "fail"), d

    def listing():
        if not os.path.exists(at(args.listing)):
            return "skip", "no store listing (web only)"
        cmd = [py, os.path.join(HERE, "listing.py"), at(args.listing)]
        if os.path.exists(at(args.brand)):
            cmd += ["--brand", at(args.brand)]
        ok, d = run(cmd, proj)
        return ("pass" if ok else "fail"), d

    def build():
        pj = os.path.join(proj, "package.json")
        if not os.path.exists(pj):
            return "skip", "no package.json"
        with open(pj, encoding="utf-8") as f:
            if "build" not in json.load(f).get("scripts", {}):
                return "skip", "no build script"
        ok, d = run("npm run build", proj, shell=True)
        return ("pass" if ok else "fail"), d

    for name, fn in (("e2e", e2e), ("bugs", bugs), ("parity", parity), ("sweep", sweep),
                     ("listing", listing), ("build", build)):
        check(name, fn)

    for name, status, detail in results:
        print("%-8s %-5s %s" % (name, status.upper(), detail))
    failed = [r for r in results if r[1] == "fail"]
    print("preflight: %s" % ("NO GO (%d failing)" % len(failed) if failed else "GO, ask the user before deploying"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
