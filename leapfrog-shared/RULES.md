# Leapfrog rules

Every Leapfrog skill follows these. Read once per session, not per step.

## Build what it does, never what it owns

- Rebuild features, flows and UX patterns. Write all code, copy and assets fresh.
- Never copy the target's source, bundles, SVGs, images, logos, fonts, copy or
  private API calls. Never load anything from its domain or CDN in the product.
- Public sources and the user's own account only. No logging into other
  accounts, no paywall or login tricks, no scraping against a site's terms.
- Official feeds and public APIs are fine within their terms. Everything else
  is read like a person reads it, at human speed.
- If the user's account terms forbid building a competitor, say so and use
  public sources only.
- Reference screenshots live in `leapfrog/screens/` and never ship.

## Never invent evidence

- No made-up reviews, quotes, votes, counts, users or sources. Every quote is
  verbatim with its URL. Say the sample size. Thin evidence is labelled thin.
- No fake testimonials, ratings, user counts or "trusted by" logos. Users'
  public complaints are research, not testimonials.
- Never write "available" or "clear" for a check nobody ran.

## The user owns accounts and money

- The user signs up for services, buys domains, enters cards and pastes live
  keys. Claude writes `.env.example` with names only.
- Test mode until ship. Nothing goes live without the user's explicit go.

## Ship only as your own

- New name, palette, logo and words before launch. `sweep.py` must be clean.
- The original's name stays out of the app name, listing, keywords and ads.

## Token discipline

- Run the tools and read their summary. Open full reports only when needed.
- Load only the recon shard you are working on, never the whole folder.
- Screenshots go to disk. Look at one only when its diff fails.
- Hand bulk reading (boards, forums, per-screen builds) to a subagent that
  returns only the filtered result.
- Update `leapfrog/state.json` after each step so the next session resumes
  from one small file.
