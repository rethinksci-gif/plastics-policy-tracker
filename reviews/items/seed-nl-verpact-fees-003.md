# Review seed-nl-verpact-fees-003

- **Dossier:** `nl-verpact-fees` (impact: high)
- **Outcome:** **passed**
- **Source:** <https://www.verpact.nl/nl/tarieven> (trust: official; snapshot `(seed)`)
- **Reviewed:** 2026-10-14 10:28 UTC

## Claim

**2026-07** — Verpact published a forecast of its 2027 rates in July 2026; it states that the final 2027 rates, now set, largely follow that forecast.

> In juli 2026 publiceerden we al een prognose voor de tarieven van 2027. De definitieve tarieven sluiten hier grotendeels op aan.

> *(translation)* In July 2026 we already published a forecast of the 2027 rates. The final rates largely follow it.

## Layers 1–2: deterministic checks

| Layer | Check | Result | Detail |
|---|---|---|---|
| 1 | event-date | pass | 2026-07 <= today 2026-10-14 |
| 1 | trusted-domain | pass | domain trust: official |
| 2 | quote-provenance | pass | verbatim quote found in snapshot |

## Layer 3: independent reviewer

Verdict **supported**, confidence 1.00.

- quote_supports_summary: yes
- dates_match: yes
- numbers_match: yes
- bodies_match: yes
- references_match: yes
- no_exaggeration: yes
- stage_supported: yes
- next_steps_supported: yes
- translation_faithful: yes
