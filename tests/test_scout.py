import csv
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(__file__))
from _load import load

rank = load("leapfrog-scout/wish_rank.py")
opp = load("leapfrog-scout/opportunity.py")
probe = load("leapfrog-scout/probe.py")
fetch = load("leapfrog-scout/wish_fetch.py")

ROWS = [
    ("app-store", "https://a/1", "2026-09-01", "2", "", "", "Great app. I wish it had a dark mode, my eyes hurt at night."),
    ("reddit", "https://r/2", "2026-08-01", "", "14", "", "Please add dark mode already! Otherwise solid."),
    ("hacker-news", "https://h/3", "2026-07-01", "", "", "", "Still no dark mode in 2026, why can't they ship it."),
    ("app-store", "https://a/4", "2026-09-02", "1", "", "", "I have to export everything to Google Sheets to build a report every week."),
    ("g2", "https://g/5", "2026-06-01", "3", "", "", "We switched to Calbird because of the per seat pricing jump."),
    ("app-store", "https://a/6", "2026-09-03", "5", "", "", "Love it. Works perfectly for me."),
    ("board", "", "2026-09-03", "", "", "", "row without a url must be dropped, please add it"),
    ("board", "https://b/7", "2022-01-01", "", "120", "planned", "Please add an offline mode for flights."),
    ("github", "https://gh/8", "2025-01-01", "", "40", "declined", "Feature request: offline mode so it works without internet."),
]


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["source", "url", "date", "rating", "votes", "status", "text"])
        w.writerows(rows)


class WishRankTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.csv = os.path.join(self.tmp, "wishes.csv")
        write_csv(self.csv, ROWS)
        self.out = os.path.join(self.tmp, "wishes.md")
        with redirect_stdout(io.StringIO()):
            rank.main([self.csv, "--out", self.out, "--today", "2026-10-01", "--app", "Calbird"])
        with open(os.path.join(self.tmp, "wishes.json"), encoding="utf-8") as f:
            self.data = json.load(f)

    def cluster(self, label):
        return next(c for c in self.data["clusters"] if c["label"] == label)

    def test_drops_rows_without_url_and_keeps_only_wish_sentences(self):
        self.assertEqual(self.data["meta"]["dropped"], 1)
        quotes = [q["text"] for c in self.data["clusters"] for q in c["quotes"]]
        self.assertFalse(any("Works perfectly" in q for q in quotes))
        self.assertFalse(any(q.startswith("Great app") for q in quotes))

    def test_dark_mode_cluster_spans_sources_and_is_not_thin(self):
        c = self.cluster("dark mode")
        self.assertEqual(c["mentions"], 3)
        self.assertEqual(len(c["sources"]), 3)
        self.assertNotIn("thin", c["flags"])

    def test_quotes_are_verbatim_substrings_with_their_url(self):
        by_url = {r[1]: r[6] for r in ROWS}
        for c in self.data["clusters"]:
            for q in c["quotes"]:
                self.assertIn(q["text"].rstrip("."), by_url[q["url"]])

    def test_kinds_and_status_flags(self):
        sheets = next(c for c in self.data["clusters"] if any(q["url"] == "https://a/4" for q in c["quotes"]))
        self.assertIn("workaround", sheets["kinds"])
        self.assertIn("churn", self.cluster("pricing and billing")["kinds"])
        off = self.cluster("offline")
        self.assertIn("stalled", off["flags"])
        self.assertIn("declined", off["flags"])

    def test_changelog_marks_maybe_shipped(self):
        log = os.path.join(self.tmp, "changelog.txt")
        with open(log, "w", encoding="utf-8") as f:
            f.write("2026-05 New: dark mode for every screen\n")
        with redirect_stdout(io.StringIO()):
            rank.main([self.csv, "--out", self.out, "--today", "2026-10-01", "--changelog", log])
        with open(os.path.join(self.tmp, "wishes.json"), encoding="utf-8") as f:
            data = json.load(f)
        dm = next(c for c in data["clusters"] if c["label"] == "dark mode")
        self.assertIn("maybe-shipped", dm["flags"])


class OpportunityTest(unittest.TestCase):
    def test_draft_merges_gaps_and_score_applies_leaps(self):
        tmp = tempfile.mkdtemp()
        csvp = os.path.join(tmp, "w.csv")
        write_csv(csvp, ROWS)
        with redirect_stdout(io.StringIO()):
            rank.main([csvp, "--out", os.path.join(tmp, "w.md"), "--today", "2026-10-01"])
        gaps = os.path.join(tmp, "gaps.csv")
        with open(gaps, "w", newline="", encoding="utf-8") as f:
            f.write("feature,original,Calbird,Slotty\nOffline mode,no,yes,no\nSMS reminders,no,yes,yes\nBooking page,yes,yes,yes\n")
        cand = os.path.join(tmp, "cand.csv")
        with redirect_stdout(io.StringIO()):
            opp.main(["draft", os.path.join(tmp, "w.json"), "--gaps", gaps, "--out", cand])
        with open(cand, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        offline = next(r for r in rows if r["feature"].startswith("offline"))
        self.assertEqual(offline["competitors"], "Calbird")
        self.assertTrue(any(r["kind"] == "gap" and r["feature"] == "SMS reminders" for r in rows))
        self.assertFalse(any(r["feature"] == "Booking page" for r in rows))

        for r in rows:
            r["size"], r["fit"] = ("S", "2") if r["kind"] == "wish" else ("M", "1")
        with open(cand, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=opp.FIELDS)
            w.writeheader()
            w.writerows(rows)
        feats = os.path.join(tmp, "features.csv")
        with open(feats, "w", encoding="utf-8") as f:
            f.write("id,feature,area,priority,original,clone,source,notes\nF001,Booking page,booking,must,yes,no,recon,\n")
        with redirect_stdout(io.StringIO()):
            opp.main(["score", cand, "--top", "3", "--apply", feats])
            opp.main(["score", cand, "--top", "3", "--apply", feats])  # second run adds nothing
        with open(feats, newline="", encoding="utf-8") as f:
            out = list(csv.DictReader(f))
        leaps = [r for r in out if r["id"].startswith("L")]
        self.assertEqual(len(leaps), 3)
        self.assertTrue(all(r["original"] == "no" and r["clone"] == "no" for r in leaps))
        self.assertEqual(leaps[0]["priority"], "must")


class ProbeTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(probe.classify("https://x.com/feature-requests/123"), "wish-board")
        self.assertEqual(probe.classify("https://x.com/changelog/2026-01"), "changelog")
        self.assertEqual(probe.classify("https://help.x.com/article/9"), "help")
        self.assertEqual(probe.classify("https://x.com/pricing"), "pricing")

    def test_sitemap_index_and_urlset(self):
        idx = ('<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
               '<sitemap><loc>https://x.com/s1.xml</loc></sitemap></sitemapindex>')
        self.assertEqual(probe.parse_sitemap(idx), (["https://x.com/s1.xml"], []))
        urls = ('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc> https://x.com/a </loc></url>'
                '<url><loc>https://x.com/b</loc></url></urlset>')
        self.assertEqual(probe.parse_sitemap(urls)[1], ["https://x.com/a", "https://x.com/b"])

    def test_html_to_text_drops_scripts_and_nav(self):
        page = "<nav>Menu</nav><h1>Pricing</h1><script>x=1</script><p>Pro &amp; Team</p><ul><li>One</li></ul>"
        text = probe.html_to_text(page)
        self.assertIn("# Pricing", text)
        self.assertIn("Pro & Team", text)
        self.assertIn("- One", text)
        self.assertNotIn("Menu", text)
        self.assertNotIn("x=1", text)


class FetchDedupeTest(unittest.TestCase):
    def test_append_skips_rows_already_there(self):
        p = os.path.join(tempfile.mkdtemp(), "w.csv")
        row = {"source": "hn", "url": "https://h/1", "date": "", "rating": "", "votes": "", "status": "", "text": "please add x"}
        self.assertEqual(fetch.append_rows(p, [row, row]), 1)
        self.assertEqual(fetch.append_rows(p, [row]), 0)


if __name__ == "__main__":
    unittest.main()
