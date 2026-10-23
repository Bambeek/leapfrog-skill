---
name: leapfrog-ship
description: >-
  Leapfrog step 4. Makes the rebuild yours and puts it live: name with checks
  to run, new palette, logo brief, voice, leftover sweep, landing page led by
  the leaps, pricing, store listing lint, preflight and deploy. Use for "leapfrog ship".
---

# leapfrog-ship

Read `../leapfrog-shared/RULES.md` first. `<dir>` is this skill's folder.
Reads `leapfrog/leaps.md` (the angle and evidence) and `leapfrog/state.json`.

## 1. Name

Twenty candidates across styles (descriptive, compound, invented, metaphor,
verb), cut to five: not confusingly similar to the original or anything in
its category, spellable after hearing it once, fits the angle. For each, a
row per check marked **to run** or with its result and date: USPTO, EUIPO or
TMview, WIPO Global Brand Database, domain (`whois`), App Store and Play,
handles, a web search of "name + category". These are screens, not legal
clearance; a trademark lawyer clears a name before money is spent on it.

Write `leapfrog/brand.json` from `templates/brand.example.json`: `avoid`
(the original's names), `domains`, `colors` (its brand colours).

## 2. Look and voice

- Palette: a primary from a different hue family than the original's,
  written into the same token roles, then
  `python3 <dir>/../leapfrog-build/tokens.py all leapfrog/design/tokens.json --out src/styles`.
  Zero AA failures.
- Logo brief, not a logo: the idea in one line, mark type, works at 16px and
  1024px, deliverables (SVG, 1024 iOS icon with no transparency, favicons,
  1200x630 social image), and no shared shape, colour pair or letterform
  trick with the original's mark.
- Voice: three words with what each does not mean, five do and don't pairs,
  then rewrite the ten most-seen strings.

## 3. Sweep

```bash
python3 <dir>/sweep.py . --config leapfrog/brand.json
```

Finds the original's names (also inside identifiers like `AcmeEmbed`),
domains and colours in file contents and names, skipping dependencies, build
output and `leapfrog/`. Exit 1 until clean. Then check by eye: favicon,
titles, email templates, OG image, app icon.

## 4. Landing and pricing

`leapfrog/launch/landing.md`, then build it: hero from the angle, the problem
(top pain clusters, paraphrased, never quoted), how it works in three steps,
features **led by the leaps** ("asked for for years, here on day one"),
pricing, FAQ, call to action. No fake proof; an empty proof section beats a
fake one.

Pricing: read the original's and 2 or 3 alternatives' public pricing with
`python3 <dir>/../leapfrog-scout/probe.py --text <url>`; table with URL and
date read. Use the billing complaints from `wishes.md`. At most three tiers,
named for who they serve, one-click cancel. List the Stripe products for the
user to create.

## 5. Store listing

```bash
python3 <dir>/listing.py leapfrog/launch/listing.json --brand leapfrog/brand.json
```

Checks Apple (name 30, subtitle 30, promo 170, keywords 100, description
4000) and Play (title 30, short 80, full 4000) limits, ranking or price
claims, emoji in short fields, wasted keyword characters, and any `avoid`
name. Apple guideline 4.1 rejects copycats: make the leaps visible in the
first screenshots and lines. Template: `templates/listing.example.json`.

## 6. Preflight and deploy

```bash
python3 <dir>/preflight.py --project . --features leapfrog/features.csv --brand leapfrog/brand.json
```

One table: Playwright, parity must-haves, sweep, listing (if present),
production build. Any fail stops the deploy. By hand: no open S1 or S2,
privacy policy and terms live and listing every processor, account deletion
works, cookie banner if non-essential cookies in the EU or UK.

Then show the results and wait for the user's go. Setup the user does, with
exact values from you:

- separate production database, backups on, migrations run by the deploy
- host env vars matching `.env.example`; live keys only there
- Stripe live mode: products, prices, production webhook and secret, one
  real purchase refunded
- OAuth redirect URIs and origins for the production domain
- DNS: apex A or ALIAS and `www` CNAME from the host, one canonical host with
  a redirect; email SPF, DKIM, and DMARC starting at `p=none` then
  `quarantine`
- error tracking, uptime checks on the home page and core API, an alert
- mobile: `eas build` and `eas submit` to TestFlight and Play internal
  testing; developer accounts belong to the user

Run the core flow on the live site and ask the user to do it on a phone.

## Done

`state.py done ship`, then: live URL, records set, what to watch in week one,
and where to post first: the threads the wishes came from (`wishes.md`
sources), leading with the leap they asked for.
