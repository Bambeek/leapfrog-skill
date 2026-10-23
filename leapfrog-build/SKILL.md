---
name: leapfrog-build
description: >-
  Leapfrog step 2. Turns a leapfrog-scout map into a working app: stack, SQL
  schema, design tokens from computed CSS, screens with every state, auth,
  payments and integrations. Use for "leapfrog build" or "build screen S07".
---

# leapfrog-build

Read `../leapfrog-shared/RULES.md` first. `<dir>` is this skill's folder.
Start with `python3 <dir>/../leapfrog-shared/state.py show` and resume from
the step it names. Load `leapfrog/recon/index.md`, then only the shards for
the screen or flow in hand.

## 1. Stack and schema

Use the user's stack if they have one. Default, all managed and cheap at zero
users: Next.js + TypeScript, Tailwind, Postgres on Supabase or Neon, Drizzle,
Supabase Auth or Auth.js, Stripe Checkout + Billing, Resend, Vercel. Expo for
mobile. One database, no microservices.

Draft the schema from the scout model instead of writing boilerplate:

```bash
python3 <dir>/model_to_sql.py leapfrog/recon/model.md --out leapfrog/schema.sql
```

It adds uuid ids, timestamps, owner columns, foreign keys with indexes, enum
checks, money as cents plus currency. Then review by hand: every
`on delete` marked TODO, unique and exclusion constraints the flows need
(two guests on one slot is a database problem), and access rules (row level
security, or one authorisation check per query; write which).

Write `leapfrog/plan.md`: stack with one line of why each, routes per flow
(`method path | does | who | input | output | flow`), webhooks, jobs, the
risky parts (time zones, idempotency, races, rate limits, GDPR deletion), and
the build order: vertical slice, must-haves, leaps, should, could.

## 2. Design tokens, no screenshots

From a public page of the original (never behind its login unless the user
drives it):

```bash
node <dir>/extract_tokens.mjs https://app.example/pricing --out leapfrog/design
```

Needs Playwright (`npm i -D playwright && npx playwright install chromium`).
Reads computed styles and writes `tokens.json` (roles: bg, surface, border,
text, text-muted, accent, on-accent, danger, success; type scale; spacing
base; radius; shadow) plus `raw-styles.json`. Values are a starting point:
the brand colour is replaced in ship, licensed fonts become open ones (Inter,
Geist, IBM Plex, Manrope), icons come from Lucide, Phosphor or Tabler.

```bash
python3 <dir>/tokens.py all leapfrog/design/tokens.json --out src/styles
```

Writes `tokens.css` and `tailwind.tokens.js`, then checks every `pairs`
entry for WCAG AA (4.5 body, 3 large text and UI). Exit 1 on a failure: fix
the token, not the component. Build the primitives once on a `/design`
route (Radix, shadcn/ui or React Aria as base) before any screen.

## 3. Screens

Shell first (routes for every screen, layout, tokens, seed data), then the
core flow end to end with a fake data layer that has the real function
signatures. Then screen by screen, in plan order. Per screen:

- read its shard, build with primitives and real data from the data layer
- every state: empty, loading, filled, error, no permission, 60-char names,
  390px and 1440px
- semantic HTML, labelled inputs, keyboard path, visible focus, alt text
- tokens only, no raw hex or px in components
- set its rows in `features.csv` to yes or partial (with a note)
- save a screenshot to `leapfrog/clone-screens/S07.png` with Playwright at
  the reference viewport. Do not open it; verify diffs it
- one commit: `build: S07 booking page`

Big builds: give each screen to a subagent with its shard, the tokens path
and the definition above; it returns files changed and states covered.

## 4. Backend

- Auth: email with verification, reset, OAuth with the user's own apps,
  roles if the map has them, account deletion that deletes.
- Database: migrations checked in, access rules on every table, a test that
  a second user gets nothing back, realistic fake seed data.
- Payments: Stripe Checkout and Customer Portal, webhooks that verify the
  signature, store the event id and are idempotent, status kept in your
  database. Cancel is one click.
- Email and jobs: provider on your own domain, retries, times in UTC.
- Integrations: official APIs, fewest scopes, note review times (Google
  OAuth verification takes weeks, start early).
- Security: secrets only in env, server validation on every route, rate
  limits on auth and anything that sends, upload limits, no user data in
  URLs or logs, `npm audit`.

## Done

Update `state.py done build --next leapfrog-verify` and summarise: screens
done of total, must-haves done of total, leaps done, what is still fake.
