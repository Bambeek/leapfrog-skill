#!/usr/bin/env python3
"""Find anything of the original left in your project. Standard library only.

    sweep.py . --config leapfrog/brand.json
    sweep.py . --avoid "Original App,Original Co" --domains original.example --colors "#0069ff"

Searches file contents and file names for:
  names    case-insensitive, also squashed or split: "Original App" also
           matches OriginalApp, original-app, original_app, ORIGINAL_APP
  domains  the domain anywhere, including subdomains and URLs
  colours  hex (#abc and #aabbcc forms) and rgb() of the same value

Skips dependencies, build output, VCS folders, binaries over a few bytes of
NUL, files over 2 MB, and the leapfrog/ planning folder. `allow` in the
config lists paths to skip on purpose. Exit 1 while anything is found.
"""

import argparse
import fnmatch
import json
import os
import re
import sys

SKIP_DIRS = {"node_modules", ".git", ".hg", ".svn", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit",
             ".turbo", ".vercel", ".expo", "coverage", "__pycache__", ".venv", "venv", "Pods", "DerivedData",
             "leapfrog", ".cache", "vendor", "target"}
MAX_BYTES = 2 * 1024 * 1024
SHOW = 25


def name_pattern(name):
    parts = [re.escape(p) for p in re.split(r"[\s_-]+", name.strip()) if p]
    if not parts:
        return None
    return re.compile(r"(?i)" + r"[\s_.-]?".join(parts))


def domain_pattern(d):
    d = d.strip().lower().replace("https://", "").replace("http://", "").strip("/")
    return re.compile(r"(?i)(?<![a-z0-9-])(?:[a-z0-9-]+\.)*" + re.escape(d) + r"(?![a-z0-9-])") if d else None


def color_patterns(c):
    c = c.strip().lower().lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if not re.fullmatch(r"[0-9a-f]{6}", c):
        raise ValueError("bad colour %r" % c)
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    pats = [r"#" + c + r"(?![0-9a-f])"]
    if c[0] == c[1] and c[2] == c[3] and c[4] == c[5]:
        pats.append(r"#" + c[0] + c[2] + c[4] + r"(?![0-9a-f])")
    pats.append(r"rgba?\(\s*%d\s*[, ]\s*%d\s*[, ]\s*%d\b" % (r, g, b))
    return [re.compile(r"(?i)" + p) for p in pats]


def build_checks(avoid, domains, colors):
    checks = []
    for n in avoid:
        p = name_pattern(n)
        if p:
            checks.append(("name", n, p))
    for d in domains:
        p = domain_pattern(d)
        if p:
            checks.append(("domain", d, p))
    for c in colors:
        for p in color_patterns(c):
            checks.append(("colour", c, p))
    return checks


def walk(root, allow):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if any(fnmatch.fnmatch(rel, a) or rel.startswith(a.rstrip("/") + "/") for a in allow):
                continue
            yield path, rel


def sweep(root, checks, allow=()):
    hits = []
    for path, rel in walk(root, allow):
        for kind, what, pat in checks:
            if kind != "colour" and pat.search(os.path.basename(rel)):
                hits.append((rel, 0, kind, what, "file name"))
        try:
            if os.path.getsize(path) > MAX_BYTES:
                continue
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if b"\x00" in data[:4096]:
            continue
        text = data.decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for kind, what, pat in checks:
                m = pat.search(line)
                if m:
                    hits.append((rel, n, kind, what, line.strip()[:120]))
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find the original's names, domains and colours in your project")
    ap.add_argument("root", nargs="?", default=".")
    ap.add_argument("--config", help="brand.json with avoid, domains, colors, allow")
    ap.add_argument("--avoid", default="", help="comma-separated names")
    ap.add_argument("--domains", default="")
    ap.add_argument("--colors", default="")
    ap.add_argument("--out", help="write every hit here")
    args = ap.parse_args(argv)

    cfg = {}
    if args.config:
        with open(args.config, encoding="utf-8") as f:
            cfg = json.load(f)
    split = lambda s: [x for x in (v.strip() for v in s.split(",")) if x]
    avoid = cfg.get("avoid", []) + split(args.avoid)
    domains = cfg.get("domains", []) + split(args.domains)
    colors = cfg.get("colors", []) + split(args.colors)
    if not (avoid or domains or colors):
        ap.error("nothing to look for: give --config or --avoid/--domains/--colors")
    try:
        checks = build_checks(avoid, domains, colors)
    except ValueError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2

    hits = sweep(args.root, checks, cfg.get("allow", []))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            for h in hits:
                f.write("%s:%d [%s %s] %s\n" % h)
    if not hits:
        print("clean: no names, domains or colours of the original found")
        return 0
    files = sorted({h[0] for h in hits})
    print("%d hits in %d files" % (len(hits), len(files)))
    for h in hits[:SHOW]:
        print("  %s:%d [%s %s] %s" % h)
    if len(hits) > SHOW:
        print("  ... %d more%s" % (len(hits) - SHOW, " in " + args.out if args.out else " (use --out)"))
    return 1


if __name__ == "__main__":
    sys.exit(main())
