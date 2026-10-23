#!/usr/bin/env python3
"""Find an app's useful public pages without browsing. Standard library only.

Reads robots.txt and the sitemaps it lists (or /sitemap.xml), never page
bodies, and groups URLs by what they are good for. Respects robots.txt.

    probe.py https://app.example --out leapfrog/sources
    probe.py --text https://app.example/pricing        # one page as plain text

Writes pages.md (counts and the first URLs per group) and pages.json.
"""

import argparse
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import urllib.robotparser
import xml.etree.ElementTree as ET

UA = "leapfrog-skill/1.0 (+https://github.com/Bambeek/leapfrog-skill)"
MAX_URLS = 5000
MAX_SITEMAPS = 40
SHOW_PER_GROUP = 25

# Order matters: first match wins.
GROUPS = [
    ("wish-board", r"(feature-?requests?|/ideas?\b|roadmap|feedback|/requests?\b|upvote|canny|wishlist)"),
    ("changelog", r"(changelog|release-?notes|what-?s-?new|/releases?\b|/updates?\b|product-?updates)"),
    ("pricing", r"(pricing|/plans?\b|/price)"),
    ("help", r"(/help|/support|/docs?\b|/documentation|/kb\b|knowledge|/guides?\b|/faq|/learn|/academy|/tutorials?)"),
    ("api", r"(/api\b|developers?|/reference|/sdk)"),
    ("integrations", r"(integrations?|/apps?\b|marketplace|/connect)"),
    ("community", r"(community|forum|/discuss|/questions?\b)"),
    ("features", r"(/features?\b|/product\b|/solutions?|/use-?cases?|/how-it-works|/tour)"),
    ("compare", r"(/vs\b|-vs-|alternative|compare|comparison)"),
    ("legal", r"(/terms|/privacy|/legal|/security|/gdpr|/dpa\b)"),
    ("blog", r"(/blog|/articles?|/news\b|/stories)"),
]


def fetch(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip" or url.endswith(".gz"):
            try:
                data = gzip.decompress(data)
            except OSError:
                pass
        charset = r.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def classify(url):
    u = urllib.parse.urlparse(url)
    # Host labels become path-like so help.example.com reads as /help.
    path = u.path.lower() + " /" + u.netloc.lower().replace(".", "/")
    for name, pattern in GROUPS:
        if re.search(pattern, path):
            return name
    return "other"


def parse_sitemap(text):
    """Return (child sitemaps, page urls) from sitemap or sitemap index XML."""
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except ET.ParseError:
        return [], re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", text)
    children, pages = [], []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag in ("sitemap", "url"):
            loc = next((c.text.strip() for c in el if c.tag.split("}")[-1] == "loc" and c.text), None)
            if loc:
                (children if tag == "sitemap" else pages).append(loc)
    return children, pages


def probe(base, delay=0.5, log=print):
    base = base.rstrip("/")
    if not re.match(r"https?://", base):
        base = "https://" + base
    rp = urllib.robotparser.RobotFileParser()
    sitemaps = []
    try:
        robots = fetch(base + "/robots.txt")
        rp.parse(robots.splitlines())
        sitemaps = [l.split(":", 1)[1].strip() for l in robots.splitlines() if l.lower().startswith("sitemap:")]
    except Exception as e:  # no robots.txt is fine
        log("robots.txt: %s" % e)
        rp.parse([])
    if not sitemaps:
        sitemaps = [base + "/sitemap.xml"]

    seen_maps, urls, queue = set(), [], list(sitemaps)
    while queue and len(seen_maps) < MAX_SITEMAPS and len(urls) < MAX_URLS:
        sm = queue.pop(0)
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        try:
            children, pages = parse_sitemap(fetch(sm))
        except Exception as e:
            log("sitemap %s: %s" % (sm, e))
            continue
        # Help and changelog sitemaps first: they matter most.
        children.sort(key=lambda u: 0 if re.search(r"help|doc|support|change|release", u) else 1)
        queue.extend(children)
        urls.extend(u for u in pages if rp.can_fetch(UA, u))
        time.sleep(delay)

    groups = {}
    for u in dict.fromkeys(urls[:MAX_URLS]):
        groups.setdefault(classify(u), []).append(u)
    return {"base": base, "sitemaps_read": len(seen_maps), "total": sum(map(len, groups.values())), "groups": groups}


def to_markdown(result):
    order = [g for g, _ in GROUPS] + ["other"]
    out = ["# Pages for %s" % result["base"], "",
           "%d URLs from %d sitemaps. Read the ones you need with `probe.py --text URL`." %
           (result["total"], result["sitemaps_read"]), ""]
    for g in order:
        items = result["groups"].get(g)
        if not items:
            continue
        out.append("## %s (%d)" % (g, len(items)))
        out += ["- " + u for u in sorted(items, key=len)[:SHOW_PER_GROUP]]
        if len(items) > SHOW_PER_GROUP:
            out.append("- ... %d more in pages.json" % (len(items) - SHOW_PER_GROUP))
        out.append("")
    return "\n".join(out)


class _Text(object):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "iframe"}
    BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "br", "td", "th", "dt", "dd"}


def html_to_text(page):
    page = re.sub(r"(?is)<!--.*?-->", " ", page)
    for tag in _Text.SKIP:
        page = re.sub(r"(?is)<%s\b.*?</%s\s*>" % (tag, tag), " ", page)
    page = re.sub(r"(?is)<h([1-6])\b[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", page)
    page = re.sub(r"(?is)<li\b[^>]*>", "\n- ", page)
    page = re.sub(r"(?is)</?(%s)\b[^>]*>" % "|".join(_Text.BLOCK), "\n", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html.unescape(page)
    lines = [re.sub(r"[ \t\r\f\v]+", " ", l).strip() for l in page.split("\n")]
    out, blank = [], False
    for l in lines:
        if not l or l in ("-", "#"):
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(l)
        blank = False
    return "\n".join(out).strip() + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find an app's public pages from its sitemaps")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--out", default="leapfrog/sources", help="folder for pages.md and pages.json")
    ap.add_argument("--text", metavar="URL", help="print one page as plain text and exit")
    ap.add_argument("--delay", type=float, default=0.5, help="seconds between sitemap requests")
    args = ap.parse_args(argv)

    if args.text:
        sys.stdout.write(html_to_text(fetch(args.text)))
        return 0
    if not args.url:
        ap.error("give a URL or --text URL")

    result = probe(args.url, delay=args.delay, log=lambda m: print(m, file=sys.stderr))
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "pages.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1)
    with open(os.path.join(args.out, "pages.md"), "w", encoding="utf-8") as f:
        f.write(to_markdown(result))

    print("%d URLs, %d sitemaps -> %s" % (result["total"], result["sitemaps_read"], os.path.join(args.out, "pages.md")))
    for g, items in sorted(result["groups"].items(), key=lambda kv: -len(kv[1])):
        print("  %-13s %d" % (g, len(items)))
    if not result["groups"].get("wish-board"):
        print("no wish board found in sitemaps: search '<app> feature requests' or '<app> roadmap'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
