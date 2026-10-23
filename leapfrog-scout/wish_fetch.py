#!/usr/bin/env python3
"""Collect user feedback from official public feeds. Standard library only.

    wish_fetch.py --out leapfrog/wishes.csv --apple 123456789 --country us
    wish_fetch.py --out leapfrog/wishes.csv --hn "AppName" --hn "AppName alternative"
    wish_fetch.py --out leapfrog/wishes.csv --github owner/repo

Sources and their terms:
  apple   Apple's customer reviews RSS feed (up to 10 pages of 50).
  hn      Hacker News Algolia search API, comments only.
  github  GitHub issue search, feature-like labels, with reaction counts and
          close reason (not_planned becomes status "declined"). Set
          GITHUB_TOKEN for a higher rate limit.

Appends to the CSV (source,url,date,rating,votes,status,text) and skips rows
already there. Other sources (feature boards, Reddit, review sites) are added
to the same CSV by hand or by a subagent; this tool never scrapes them.
"""

import argparse
import csv
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

UA = "leapfrog-skill/1.0 (+https://github.com/Bambeek/leapfrog-skill)"
FIELDS = ["source", "url", "date", "rating", "votes", "status", "text"]
GITHUB_LABELS = ["enhancement", "feature", "feature request", "feature-request", "idea"]


def get_json(url, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def strip_html(s):
    s = re.sub(r"(?i)<p>|<br\s*/?>", "\n", s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def label(d, key):
    v = d.get(key) or {}
    return v.get("label", "") if isinstance(v, dict) else ""


def apple(app_id, country="us", pages=10, delay=1.0):
    rows = []
    for page in range(1, pages + 1):
        url = "https://itunes.apple.com/%s/rss/customerreviews/page=%d/id=%s/sortby=mostrecent/json" % (country, page, app_id)
        try:
            entries = get_json(url).get("feed", {}).get("entry", [])
        except Exception as e:
            print("apple page %d: %s" % (page, e), file=sys.stderr)
            break
        if isinstance(entries, dict):
            entries = [entries]
        entries = [e for e in entries if "im:rating" in e]  # first entry can be the app itself
        if not entries:
            break
        for e in entries:
            rid = label(e, "id")
            title, body = label(e, "title"), label(e, "content")
            rows.append({
                "source": "app-store",
                "url": "https://apps.apple.com/%s/app/id%s?see-all=reviews#%s" % (country, app_id, rid),
                "date": label(e, "updated")[:10],
                "rating": label(e, "im:rating"),
                "votes": label(e, "im:voteSum"),
                "status": "",
                "text": (title + ". " + body).strip(". ") if title else body,
            })
        time.sleep(delay)
    return rows


def hn(query, pages=2, delay=1.0):
    rows = []
    for page in range(pages):
        url = "https://hn.algolia.com/api/v1/search?" + urllib.parse.urlencode(
            {"query": query, "tags": "comment", "hitsPerPage": 100, "page": page})
        try:
            data = get_json(url)
        except Exception as e:
            print("hn %r: %s" % (query, e), file=sys.stderr)
            break
        for h in data.get("hits", []):
            text = strip_html(h.get("comment_text"))
            if text:
                rows.append({
                    "source": "hacker-news",
                    "url": "https://news.ycombinator.com/item?id=%s" % h.get("objectID"),
                    "date": (h.get("created_at") or "")[:10],
                    "rating": "",
                    "votes": h.get("points") or "",
                    "status": "",
                    "text": text,
                })
        if page + 1 >= data.get("nbPages", 0):
            break
        time.sleep(delay)
    return rows


def github(repo, delay=2.0):
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    rows, seen = [], set()
    for lab in GITHUB_LABELS:
        q = 'repo:%s is:issue label:"%s"' % (repo, lab)
        url = "https://api.github.com/search/issues?" + urllib.parse.urlencode(
            {"q": q, "sort": "reactions", "order": "desc", "per_page": 100})
        try:
            items = get_json(url, headers).get("items", [])
        except Exception as e:
            print("github %s %r: %s" % (repo, lab, e), file=sys.stderr)
            items = []
        for it in items:
            if it["html_url"] in seen:
                continue
            seen.add(it["html_url"])
            if it.get("state_reason") == "not_planned":
                status = "declined"
            elif it.get("state") == "closed":
                status = "done"
            else:
                status = "open"
            body = (it.get("body") or "")[:3000]
            rows.append({
                "source": "github",
                "url": it["html_url"],
                "date": (it.get("created_at") or "")[:10],
                "rating": "",
                "votes": (it.get("reactions") or {}).get("+1", ""),
                "status": status,
                "text": (it.get("title", "") + ". " + body).strip(),
            })
        time.sleep(delay)
    return rows


def row_key(r):
    return hashlib.sha1((r.get("url", "") + "\0" + (r.get("text") or "")[:200]).encode("utf-8")).hexdigest()


def append_rows(path, rows):
    existing = set()
    if os.path.exists(path):
        with open(path, newline="", encoding="utf-8") as f:
            existing = {row_key(r) for r in csv.DictReader(f)}
    write_header = not os.path.exists(path) or os.path.getsize(path) == 0
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    added = 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for r in rows:
            k = row_key(r)
            if k in existing:
                continue
            existing.add(k)
            w.writerow(r)
            added += 1
    return added


def main(argv=None):
    ap = argparse.ArgumentParser(description="Collect feedback from official public feeds")
    ap.add_argument("--out", default="leapfrog/wishes.csv")
    ap.add_argument("--apple", action="append", default=[], metavar="APP_ID")
    ap.add_argument("--country", default="us")
    ap.add_argument("--apple-pages", type=int, default=10)
    ap.add_argument("--hn", action="append", default=[], metavar="QUERY")
    ap.add_argument("--hn-pages", type=int, default=2)
    ap.add_argument("--github", action="append", default=[], metavar="OWNER/REPO")
    args = ap.parse_args(argv)

    if not (args.apple or args.hn or args.github):
        ap.error("give at least one of --apple, --hn, --github")

    counts = []
    for a in args.apple:
        counts.append(("app-store " + a, append_rows(args.out, apple(a, args.country, args.apple_pages))))
    for q in args.hn:
        counts.append(("hn " + q, append_rows(args.out, hn(q, args.hn_pages))))
    for g in args.github:
        counts.append(("github " + g, append_rows(args.out, github(g))))

    for name, n in counts:
        print("%-40s +%d rows" % (name, n))
    print("-> %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
