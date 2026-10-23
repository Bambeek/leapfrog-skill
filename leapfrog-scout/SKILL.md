---
name: leapfrog-scout
description: >-
  Leapfrog step 1. Maps an app you want to rebuild (screens, flows, data model,
  feature matrix) and mines what its users already ask for, to pick the
  features that make your version better. Use for "leapfrog <app>".
---

# leapfrog-scout

Read `../leapfrog-shared/RULES.md` first. `<dir>` below is this skill's
folder; tools are standard-library Python 3.8+ (`python3` or `python`).

Writes into the user's project:

```
leapfrog/state.json          progress, read first by every step
leapfrog/recon/index.md      one line per screen, flow, entity (template here)
leapfrog/recon/S07.md ...    one shard per screen, F01.md per flow
leapfrog/features.csv        the feature matrix (template here)
leapfrog/wishes.md           ranked user wishes with linked quotes
leapfrog/leaps.md            the chosen upgrades and the angle
```

## 0. Start or resume

```bash
python3 <dir>/../leapfrog-shared/state.py show
```

If it prints a step, continue from there. Else ask three things (or propose
and get a yes): which app and platform, which slice (default: the core loop
users pay for), who it is for. Then:

```bash
python3 <dir>/../leapfrog-shared/state.py init --app "Name" --url https://app.example
```

## 1. Find pages without browsing

```bash
python3 <dir>/probe.py https://app.example --out leapfrog/sources
```

Reads robots.txt and sitemaps only and prints counts per group: help, pricing,
changelog, api, integrations, wish boards, community. Pick pages from
`leapfrog/sources/pages.md`. Read one as text, no browser:

```bash
python3 <dir>/probe.py --text https://app.example/pricing > leapfrog/sources/pricing.txt
```

Save the changelog the same way (`changelog.txt`), step 4 needs it. Use the
browser only for what text cannot show: layout, the user's own account
(driven by the user), store screenshots.

## 2. Map it, in shards

From `templates/`: write `recon/index.md` (IDs and one line each) and one
shard per screen (`S07.md`) and flow (`F01.md`). Shards hold purpose,
components, states seen, edge cases, evidence URL. IDs never change; every
later step refers to them.

Data model goes in `recon/model.md` in the `model_to_sql.py` format (see
`../leapfrog-build/SKILL.md`), with evidence and a confidence per entity.

Fill `features.csv`: `id,feature,area,priority,original,clone,source,notes`.
Priority must/should/could. `clone` starts `no`. What cannot be rebuilt
(licensed content, the network, regulated licences) gets `clone=skip` and a
reason. Size it: S weekend, M weeks, L quarter, XL rescope.

## 3. Mine the wishes

The goal is free improvement ideas users already wrote down: requests,
workarounds and reasons they left. Fetch from official feeds:

```bash
python3 <dir>/wish_fetch.py --out leapfrog/wishes.csv \
  --apple 123456789 --hn "AppName" --hn "AppName alternative" \
  --github owner/competitor-repo
```

Sources without a feed (the original's feature board with votes, Reddit
threads like "AppName alternative" or "switched from AppName", G2 and
Capterra "dislikes", forums): send a subagent to read them like a person and
append only matching rows to the same CSV:
`source,url,date,rating,votes,status,text`. Its brief: copy verbatim, keep
only text that asks for something, describes a workaround or says why they
left, include vote counts and board status, return the row count.

## 4. Rank them

```bash
python3 <dir>/wish_rank.py leapfrog/wishes.csv --changelog leapfrog/sources/changelog.txt --out leapfrog/wishes.md
```

Keeps sentences that ask ("I wish", "please add", "would pay for"), work
around ("I export to Sheets to") or churn ("switched to X because").
Clusters them, scores votes x mentions x sources x recency, flags thin
clusters, flags ones the changelog suggests already shipped, and marks board
items stalled for 2+ years or declined: those are openings. Read the summary
it prints; open `wishes.md` for the top clusters only.

## 5. Competitor gaps

Pick 3 to 5 alternatives. Fill `leapfrog/gaps.csv`:
`feature,original,<competitor>...` with yes/no/partial, from their public
pricing and feature pages (use `probe.py --text`). A feature competitors have
and the original lacks is a free idea.

## 6. Pick the leaps

```bash
python3 <dir>/opportunity.py draft leapfrog/wishes.json --gaps leapfrog/gaps.csv --out leapfrog/candidates.csv
```

Fill the `size` (S/M/L) and `fit` (0 to 2, fits the angle) columns, then:

```bash
python3 <dir>/opportunity.py score leapfrog/candidates.csv --top 8 --apply leapfrog/features.csv
```

Appends the chosen leaps to `features.csv` with `original=no`. Write
`leaps.md`: the leaps with evidence, and three angles in this form, one
recommended:

```
For <who> who <pain, in plain words>, <your app> <does this instead>.
Evidence: <cluster>, <n> mentions across <n> sources.
```

## Done

`python3 <dir>/../leapfrog-shared/state.py done scout --next "leapfrog-build"`,
then a five-line summary: core loop, screen and flow counts, top three leaps
with their evidence, out of scope, size. Next: `/leapfrog-build`.
