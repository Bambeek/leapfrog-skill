import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(__file__))
from _load import load, ROOT

sql = load("leapfrog-build/model_to_sql.py")
tokens = load("leapfrog-build/tokens.py")
parity = load("leapfrog-verify/parity.py")
ld = load("leapfrog-verify/layout_diff.py")
sweep = load("leapfrog-ship/sweep.py")
listing = load("leapfrog-ship/listing.py")
state = load("leapfrog-shared/state.py")


class ModelToSqlTest(unittest.TestCase):
    def test_template_model(self):
        with open(os.path.join(ROOT, "leapfrog-scout/templates/model.md"), encoding="utf-8") as f:
            out = sql.to_sql(sql.parse(f.read()))
        self.assertLess(out.index("create table users"), out.index("create table event_types"))
        self.assertLess(out.index("create table event_types"), out.index("create table bookings"))
        self.assertIn("event_type_id uuid not null references event_types(id)", out)
        self.assertIn("create index on bookings (event_type_id);", out)
        self.assertIn("user_id uuid not null references users(id)", out)
        self.assertIn("price_cents integer check", out)  # nullable money
        self.assertIn("status text not null default 'confirmed' check (status in ('confirmed','cancelled','rescheduled'))", out)
        self.assertIn("answers jsonb not null default '{}'", out)
        self.assertIn("start_at timestamptz not null", out)

    def test_unknown_type_is_an_error(self):
        with self.assertRaises(ValueError):
            sql.to_sql(sql.parse("entity A\n  x weird\n"))


class TokensTest(unittest.TestCase):
    def test_ratio_and_template_passes(self):
        self.assertAlmostEqual(tokens.ratio("#000", "#fff"), 21.0, places=1)
        with open(os.path.join(ROOT, "leapfrog-build/templates/tokens.json"), encoding="utf-8") as f:
            t = json.load(f)
        self.assertTrue(all(r[4] == "ok" for r in tokens.contrast(t)), tokens.contrast(t))

    def test_failure_and_css(self):
        t = {"color": {"text": "#999999", "bg": "#ffffff"}, "pairs": [["text", "bg", "body"]], "text": {"md": [16, 24]}}
        self.assertEqual(tokens.contrast(t)[0][4], "FAIL")
        css = tokens.to_css(t)
        self.assertIn("--color-text: #999999;", css)
        self.assertIn("--leading-md: 24px;", css)


class ParityTest(unittest.TestCase):
    def rows(self, text):
        p = os.path.join(tempfile.mkdtemp(), "f.csv")
        with open(p, "w", encoding="utf-8") as f:
            f.write("id,feature,area,priority,original,clone,source,notes\n" + text)
        return parity.score(parity.read(p))

    def test_weights_skip_and_leaps(self):
        res = self.rows("A,a,x,must,yes,yes,,\nB,b,x,should,yes,partial,,\nC,c,y,could,yes,no,,\n"
                        "D,d,y,must,yes,skip,,\nL01,l,leap,must,no,yes,wish:W01,\n")
        self.assertAlmostEqual(res["score"], 100 * (3 + 1) / 6.0, places=1)
        self.assertEqual((res["musts"], res["musts_done"]), (1, 1))
        self.assertEqual((res["leaps"], res["leaps_done"]), (1, 1))
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(res["missing"][0]["id"], "B")

    def test_verdicts(self):
        self.assertEqual(parity.verdict(self.rows("A,a,x,must,yes,no,,\n"), {})[0], "not shippable")
        self.assertEqual(parity.verdict(self.rows("A,a,x,must,yes,yes,,\n"), {})[0], "shippable")
        leaps = "".join("L%d,l,leap,should,no,yes,,\n" % i for i in range(3))
        self.assertEqual(parity.verdict(self.rows("A,a,x,must,yes,yes,,\n" + leaps), {})[0], "leapfrogged")


def png(path, w, h, pixel):
    rows = [bytearray(b"".join(bytes(pixel(x, y)) for x in range(w))) for y in range(h)]
    ld.write_png(path, rows)


class LayoutDiffTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        box = lambda c, x0: (lambda x, y: c if x0 <= x < x0 + 40 and 20 <= y < 60 else (255, 255, 255))
        png(os.path.join(self.d, "a.png"), 160, 100, box((20, 60, 200), 20))
        png(os.path.join(self.d, "recolour.png"), 160, 100, box((200, 40, 40), 20))
        png(os.path.join(self.d, "moved.png"), 160, 100, box((20, 60, 200), 100))

    def test_colour_change_still_matches(self):
        r = ld.compare_layout(os.path.join(self.d, "a.png"), os.path.join(self.d, "recolour.png"))
        self.assertGreaterEqual(r["score"], 90)

    def test_moved_block_differs_and_reports_region(self):
        r = ld.compare_layout(os.path.join(self.d, "a.png"), os.path.join(self.d, "moved.png"),
                              os.path.join(self.d, "diff.png"))
        self.assertLess(r["score"], 50)
        self.assertTrue(r["regions"])
        self.assertTrue(ld.read_png(os.path.join(self.d, "diff.png"))["w"] > 0)

    def test_pixel_mode_and_batch(self):
        self.assertEqual(ld.compare_pixel(os.path.join(self.d, "a.png"), os.path.join(self.d, "a.png"))["score"], 100.0)
        a, b = os.path.join(self.d, "orig"), os.path.join(self.d, "clone")
        os.makedirs(a)
        os.makedirs(b)
        for n in ("S01", "S02"):
            png(os.path.join(a, n + ".png"), 40, 40, lambda x, y: (0, 0, 0) if x > 20 else (255, 255, 255))
        png(os.path.join(b, "S01.png"), 40, 40, lambda x, y: (0, 0, 0) if x > 20 else (255, 255, 255))
        res, missing = ld.batch(a, b)
        self.assertEqual([r["screen"] for r in res], ["S01"])
        self.assertEqual(missing, ["S02"])


class SweepTest(unittest.TestCase):
    def test_finds_names_domains_colours_and_skips_folders(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, "src"))
        os.makedirs(os.path.join(d, "node_modules", "x"))
        os.makedirs(os.path.join(d, "leapfrog"))
        files = {
            "src/embed.tsx": "export function AcmeCalEmbed() { return null }",
            "src/theme.css": ".btn { color: #06f; background: rgb(0, 102, 255); }",
            "src/links.ts": "const u = 'https://help.acmecal.example/x'",
            "src/acme-cal-logo.svg": "<svg/>",
            "src/clean.ts": "export const ok = 1 // acmecalendar-like but not it? no",
            "node_modules/x/i.js": "AcmeCal",
            "leapfrog/notes.md": "AcmeCal research",
        }
        for rel, text in files.items():
            with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
                f.write(text)
        checks = sweep.build_checks(["Acme Cal"], ["acmecal.example"], ["#0066ff"])
        hits = sweep.sweep(d, checks)
        where = {(h[0], h[2]) for h in hits}
        self.assertIn(("src/embed.tsx", "name"), where)
        self.assertIn(("src/theme.css", "colour"), where)
        self.assertIn(("src/links.ts", "domain"), where)
        self.assertIn(("src/acme-cal-logo.svg", "name"), where)
        self.assertFalse(any(h[0].startswith(("node_modules", "leapfrog")) for h in hits))
        self.assertEqual(len([h for h in hits if h[0] == "src/theme.css"]), 2)


class ListingTest(unittest.TestCase):
    def test_example_is_clean(self):
        with open(os.path.join(ROOT, "leapfrog-ship/templates/listing.example.json"), encoding="utf-8") as f:
            errors, warnings = listing.lint(json.load(f), ["Acme Cal"])
        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_limits_claims_names_keywords(self):
        bad = {"apple": {"name": "Best Booking App for Acme Cal users!!", "subtitle": "x",
                         "keywords": "booking, calendar,calendar,meetings,meeting"}}
        errors, warnings = listing.lint(bad, ["Acme Cal"])
        text = " ".join(errors + warnings)
        self.assertIn("apple.name is", text)
        self.assertIn("claim", text)
        self.assertIn("mentions 'Acme Cal'", text)
        self.assertIn("spaces around commas", text)
        self.assertIn("repeats: calendar", text)
        self.assertIn("singular and plural", text)

    def test_length_counts_emoji_once(self):
        self.assertEqual(listing.length("a\U0001F44D\U0001F3FDb"), 3)
        self.assertEqual(listing.length("é"), 1)


class StateTest(unittest.TestCase):
    def test_init_done_log(self):
        d = tempfile.mkdtemp()
        with redirect_stdout(io.StringIO()):
            state.main(["--root", d, "init", "--app", "Acme", "--url", "https://acme.example"])
            state.main(["--root", d, "done", "scout"])
            state.main(["--root", d, "log", "scout", "1200", "mining"])
        s = state.load(d)
        self.assertEqual((s["step"], s["next"], s["done"]), ("build", "leapfrog-build", ["scout"]))
        self.assertEqual(s["ledger"][0]["tokens"], 1200)


if __name__ == "__main__":
    unittest.main()
