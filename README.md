# Plastics Policy Tracker

A tracker for plastics laws and regulations worldwide, published as a newsletter every other Monday. Every published fact is
traced to an official source and passes four layers of review before it reaches the site.

**Site:** <https://rethinksci-gif.github.io/plastics-policy-tracker/> · **Setup:** [SETUP.md](SETUP.md) ·
**How we verify:** [/verification/](https://rethinksci-gif.github.io/plastics-policy-tracker/verification/)

## How it works

```
sources/feeds.yaml ──fetch──▶ data/raw/ (text snapshots + SHA-256)
                      │
                      ├─triage (FAST model)──▶ data/candidates/   (relevance, dossier match)
                      ├─draft  (PRO model) ──▶ draft update with a verbatim source_quote
                      └─review ──▶ L1 deterministic checks → L2 quote must exist in snapshot
                                   → L3 independent sceptical reviewer ──▶ reviews/items/
biweekly: L1+L2 re-check → L4 editorial review → publish gate ──▶ issues/ + dossiers/ → site
```

- `dossiers/*.yaml` — the fact base: one file per instrument. `updates` are append-only, newest first.
- `sources/feeds.yaml` — sources with type, frequency, jurisdiction and trust level. `sources/trusted_domains.yaml` —
  the domain whitelist. `sources/unreachable.md` — official sites that block automated access.
- `prompts/*.md` — every LLM prompt (triage, drafter, reviewer, editor, highlights).
- `pipeline/` — Python 3.12 (`uv`, pydantic, httpx, feedparser, trafilatura, openai SDK against DeepSeek).
- `reviews/` — every review record (JSON + Markdown), published on the site under `/reviews/<id>/`.
- `site/` — Astro static site with Pagefind search, RSS (`/rss.xml`) and an iCalendar feed (`/calendar.ics`).

## Review layers

1. **Deterministic (code):** pydantic schema; every `source_url` returns HTTP 200 and is on the official-domain whitelist;
   event dates not in the future; past next steps marked *to be confirmed*; stage moves only forward (backward or a jump of
   more than two stages goes to a human); no duplicate events.
2. **Provenance (code):** the `source_quote`, normalised for whitespace, quotation marks and case, must be found in a saved
   snapshot of the cited URL. Otherwise the update is rejected.
3. **Independent reviewer (LLM):** sees only the snapshot and the claim. It passes an update only if it rates it
   `supported` with confidence ≥ 0.8. Items with `impact: high` that pass also need the same verdict from a second,
   independent reviewer on the pro model.
4. **Editorial (LLM, per issue):** checks for contradictions, conflicts with dossier history, translation fidelity and
   fact vs. interpretation; these hold an item back. Terminology and spelling (British English) are reported only.

### Models per stage (`llm.stage_models` in `config.yaml`)

| Stage | Tier | Why |
|---|---|---|
| triage | fast | Most calls (~100+/day); a miss is cheap |
| draft | fast | Invented quotes are caught by layer 2 (code) |
| review (layer 3) | fast | Every drafted item |
| review_high_confirm | pro | Second opinion, only for `impact: high` items that passed the fast review |
| editor (layer 4) | pro | Once per issue |
| highlights | fast | Rewrites already verified items |

`fast` = `DEEPSEEK_MODEL_FAST` (default `deepseek-flash`), `pro` = `DEEPSEEK_MODEL_PRO` (default `deepseek-v4-pro`).

Anything that fails is quarantined: it is not published, it is written to `reviews/`, and it is opened as a GitHub issue
labelled `needs-human-review`. If more than 30% of an issue's items are quarantined, or any high-impact item is, the issue
waits for manual approval.

## Commands

```bash
uv run python -m pipeline daily [--dry-run]           # fetch → triage → draft → review
uv run python -m pipeline biweekly [--force] [--dry-run] [--force-publish]
uv run python -m pipeline validate [--urls]           # layer 1+2 over all dossiers
uv run python -m pipeline capture URL... --source-id X --jurisdiction EU [--mode full] [--lang fr]
uv run python -m pipeline review-seeds                # layers 1–3 for hand-seeded dossier updates
uv run pytest -q
```

Not legal advice.
