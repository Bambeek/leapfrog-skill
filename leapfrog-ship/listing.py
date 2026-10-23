#!/usr/bin/env python3
"""Lint an App Store and Google Play listing. Standard library only.

    listing.py leapfrog/launch/listing.json --brand leapfrog/brand.json

Errors (exit 1): over a store limit, the original's name (from brand.json
`avoid`) anywhere, ranking or price claims in name/title/subtitle/short text.
Warnings: emoji in short fields, wasted keyword characters (spaces, repeats,
words already in the name or subtitle, plural twins), keywords near empty.

Lengths are counted in user-perceived characters (an emoji with modifiers
counts once), which is how the stores show them.
"""

import argparse
import json
import re
import sys
import unicodedata

LIMITS = {
    "apple": {"name": 30, "subtitle": 30, "promotional_text": 170, "keywords": 100, "description": 4000},
    "play": {"title": 30, "short_description": 80, "full_description": 4000},
}
SHORT = {("apple", "name"), ("apple", "subtitle"), ("play", "title"), ("play", "short_description")}
CLAIMS = re.compile(r"(?i)(#\s?1\b|\bno\.?\s?1\b|\bnumber one\b|\bbest\b|\btop\b|\bleading\b|\bfree\b|\bsale\b|"
                    r"\bdiscount\b|\d+\s?% off|\bcheapest\b|\bapp of the (day|year)\b|\baward)")
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
JOINERS = {"‍", "️", "︎"}


def length(s):
    """Approximate grapheme count: combining marks, joiners, skin tones and joined emoji don't add."""
    s = unicodedata.normalize("NFC", s)
    n, join_next = 0, False
    for ch in s:
        if ch in JOINERS:
            join_next = ch == "‍"
            continue
        if unicodedata.combining(ch) or 0x1F3FB <= ord(ch) <= 0x1F3FF:
            continue
        if join_next:
            join_next = False
            continue
        n += 1
    return n


def lint(listing, avoid):
    errors, warnings = [], []
    for store, fields in LIMITS.items():
        data = listing.get(store)
        if not data:
            continue
        for field, limit in fields.items():
            text = data.get(field, "") or ""
            n = length(text)
            if n > limit:
                errors.append("%s.%s is %d chars, limit %d" % (store, field, n, limit))
            if (store, field) in SHORT:
                m = CLAIMS.search(text)
                if m:
                    errors.append("%s.%s has a ranking or price claim: %r" % (store, field, m.group(0)))
                if EMOJI.search(text):
                    warnings.append("%s.%s has emoji; stores often reject them in short fields" % (store, field))
        for field, text in data.items():
            for name in avoid:
                pat = r"(?i)" + r"[\s_.-]?".join(re.escape(p) for p in name.split())
                if name.strip() and re.search(pat, text or ""):
                    errors.append("%s.%s mentions %r" % (store, field, name))

    apple = listing.get("apple") or {}
    kw = apple.get("keywords")
    if kw is not None:
        if re.search(r",\s", kw) or kw.startswith(" ") or kw.endswith(" "):
            warnings.append("apple.keywords: spaces around commas waste characters")
        words = [w.strip().lower() for w in kw.split(",") if w.strip()]
        dupes = sorted({w for w in words if words.count(w) > 1})
        if dupes:
            warnings.append("apple.keywords repeats: " + ", ".join(dupes))
        shown = set(re.findall(r"[a-z0-9]+", (apple.get("name", "") + " " + apple.get("subtitle", "")).lower()))
        already = [w for w in words if w in shown]
        if already:
            warnings.append("apple.keywords already in name or subtitle (indexed anyway): " + ", ".join(already))
        twins = sorted({w for w in words if w.endswith("s") and w[:-1] in words})
        if twins:
            warnings.append("apple.keywords has singular and plural (one is enough): " + ", ".join(twins))
        if length(kw) < 60:
            warnings.append("apple.keywords uses %d of 100 characters" % length(kw))
    return errors, warnings


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lint a store listing")
    ap.add_argument("listing")
    ap.add_argument("--brand", help="brand.json, for the avoid list")
    ap.add_argument("--avoid", default="", help="comma-separated names (added to brand.json's)")
    args = ap.parse_args(argv)
    with open(args.listing, encoding="utf-8") as f:
        listing = json.load(f)
    avoid = [a.strip() for a in args.avoid.split(",") if a.strip()]
    if args.brand:
        with open(args.brand, encoding="utf-8") as f:
            avoid += json.load(f).get("avoid", [])
    errors, warnings = lint(listing, avoid)
    for e in errors:
        print("ERROR " + e)
    for w in warnings:
        print("warn  " + w)
    print("listing: %d errors, %d warnings" % (len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
