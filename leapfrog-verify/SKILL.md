---
name: leapfrog-verify
description: >-
  Leapfrog step 3. Tests the rebuilt app and scores it: Playwright tests from
  the flows, bug log with severity, feature parity plus leap progress, and a
  layout diff that ignores colour. Use for "leapfrog verify" or "how close is it".
---

# leapfrog-verify

Read `../leapfrog-shared/RULES.md` first. `<dir>` is this skill's folder.
Test the rebuild only. Never load test, fuzz or script the original's
servers.

## 1. Test plan

For each flow shard `F01.md`: the happy path (H), edge cases (E) and negative
cases (N), numbered `F01-H1`, `F01-E3`. Go down this list for edges: empty
and very long input, emoji and accents, double submit, back and refresh
mid-flow, two tabs, slow network, expired session, a second user's data
(must be invisible), time zones and DST, 390px, keyboard only. Negatives:
wrong password, declined card (Stripe test card `4000 0000 0000 0002`),
permission denied, deleted record. Write `leapfrog/test-plan.md`.

## 2. Automate

Playwright, one spec per flow, local dev server, seed data. Select by role
and label, never CSS classes. Every spec fails on console errors and 5xx
responses and runs an axe scan (`@axe-core/playwright`). Start from
`templates/flow.spec.ts`.

```bash
npx playwright test --reporter=line
```

What cannot be automated (real email, real OAuth, payments end to end): a
short manual checklist for the user, or a subagent driving a browser that
returns pass or fail per step.

## 3. Bugs

`leapfrog/bugs.md`, format in `templates/bug.md`. Only reproduced bugs; maybes
go in a "to check" list. S1 data loss, security, payments, core flow blocked.
S2 feature broken, no workaround. S3 workaround exists or visibly wrong. S4
cosmetic. Fix S1 and S2 first: failing test, fix, keep the test.

## 4. Score

```bash
python3 <dir>/parity.py leapfrog/features.csv
```

Weights must 3, should 2, could 1, partial counts half, `skip` is left out.
Rows with `original=no` are your leaps and are scored separately. Prints the
score, must-haves done of total, weakest areas and the missing list.

Layout, all screens in one run (pairs files by name across the two folders):

```bash
python3 <dir>/layout_diff.py batch leapfrog/screens leapfrog/clone-screens --json leapfrog/diffs/layout.json
```

Compares edge maps on a grid, so new colours do not count against you.
Prints one line per screen; open a screenshot only for screens under 75.
After changes, re-run only what changed:

```bash
python3 <dir>/layout_diff.py batch leapfrog/screens leapfrog/clone-screens --since HEAD~3 --map leapfrog/screen-map.json
```

`screen-map.json` maps screen ids to source globs:
`{"S07": ["app/book/**"]}`. `--mode pixel` is for your own regressions,
never against the original.

Full report with the layout scores folded in:

```bash
python3 <dir>/parity.py leapfrog/features.csv --layout leapfrog/diffs/layout.json --markdown leapfrog/parity.md
```

Verdict: **not shippable** (a must-have missing or an open S1), **shippable**
(must-haves done, score 80+, no open S1 or S2), **leapfrogged** (shippable
and at least three leaps done). Give the real number.

## Done

`state.py done verify --next leapfrog-ship` (or back to leapfrog-build with
the gap list), plus a summary: cases run and passed, bugs by severity, score,
verdict, the top five gaps.
