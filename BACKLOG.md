# Backlog

---

## Three-outcome risk engine results (flagged / clear / insufficient_data)

Currently each risk engine returns a binary `flagged: true | false`.
When the engine skips a transaction due to insufficient data (e.g.
fewer than `MIN_CURRENT_TX` transactions in the 7-day window), it
returns `False` — indistinguishable from "checked and clean."

**Proposed change:** each engine publishes a `status` field with three
possible values:

| Status | Meaning |
|---|---|
| `flagged` | Deviation detected / watchlist match |
| `clear` | Checked, within threshold |
| `insufficient_data` | Skipped — not enough transactions to evaluate |

**Impact on the Assessment Factory:**
- `flagged` counts toward the numerator (flagged_count)
- `clear` counts toward the denominator (total_outcomes) but not numerator
- `insufficient_data` does NOT count toward the denominator — effectively
  excluded from the score, keeping confidence lower

This means a new supplier with no history would get `confidence < 100%`
instead of a false "clean" signal, giving downstream consumers (C&T
Risk Management, DB Store) a more honest picture of the assessment
quality.
