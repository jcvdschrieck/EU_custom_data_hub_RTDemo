# Backlog

---

## Review event statuses / values of the Automated Assessment Factory

The Release Factory (Automated Assessment) publishes `ASSESSMENT_OUTCOME`
with a `route` field (`release` / `retain` / `investigate`) and an
`Overall_Risk_Level` field (`green` / `amber` / `red`). These values are
**not centralised** in a reference table or constants module — they're
inline strings in `api.py::_publish_assessment`. Similarly the `status`
field on the `RT_SCORE` legacy counter carries `green` / `amber` / `red`
as raw strings.

**What to review:**
- Should these route/level labels live in a reference table (like
  `case_statuses` and `sales_order_statuses`) or a constants module
  (like `lib/case_statuses.py`)?
- Are the labels user-facing? If so, do they need human-readable
  equivalents (e.g. `"release"` → `"Automated Release"`)?
- The pipeline diagram currently colour-codes by these raw strings —
  a rename would need a coordinated frontend update.

**When this matters:** the moment a new route is added (e.g.
`escalate`) or the label vocabulary is exposed to the C&T Risk Management System
frontend.

---

## Third-party input loop — currently a workflow dead-end

When a Customs or Tax officer triggers **Request Input from Third Party**,
the case transitions to `Status = "Requested Input by Third Party"` and
sits there indefinitely. There is no:

- "Response received" action / endpoint to bring it back into a queue
- Audit field for *which third party* was contacted or *what was asked*
  (only an unstructured Communication entry)
- Reminder / escalation timer for stale input requests

The case remains visible on both Customs and Tax pages but has no
defined exit path other than the officer manually choosing a different
action (release / retain / submit-for-tax-review), which silently
overwrites the pending-input status.

**When this matters:** the moment the demo includes a real third-party
back-and-forth scenario, this gap will block the flow. Acceptable for
now; document if a stakeholder asks.

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


---

## Recommended-action when no historical cases exist

**Where:** customsandtaxriskmanagemensystem `src/pages/CaseReview.tsx`
— the case-open `useEffect` that computes the prefilled action and the
"AI Suggested Action" block in the right column.

**Rule source:** Context/Rules in App.pptx, slide 1 — row 4 (Customs).

**Situation:** the Customs rule buckets the prefilled action on
`retPct = retained / total_prev_cases`:
  - `> 75 %`  → Recommend Retainment
  - `25 – 75 %` → Submit for Tax Review
  - `< 25 %`  → Recommend Release

When `total_prev_cases = 0` (new seller, no prior investigations), the
arithmetic treats `retPct = 0`, which falls into the `< 25 %` bucket
and emits **Recommend Release**. The rule itself doesn't say how to
handle empty history.

**Current implementation:** pure rule-fidelity — we emit "Recommend
Release" on empty history. The earlier defensive approach (blank
prefill or fall back to backend `aiSuggestedAction`) was reverted to
keep the code aligned with the pptx verbatim.

**Open design question for review:** does a "0 prev cases → Recommend
Release" outcome make intuitive sense to the officer? Two alternatives
worth discussing:
  1. Explicit "insufficient history — no recommendation" prefill that
     forces the officer to choose.
  2. Keep Release but annotate the sentence: "No prior cases for this
     seller — default recommendation applies."

Not blocking; list here so the choice surfaces in the next rules
review.

