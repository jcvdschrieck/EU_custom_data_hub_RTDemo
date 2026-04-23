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

---

## Per-order VAT Fraud Detection agent verdicts (batched invoice)

**Where:** `api.py::_build_agent_tx`, `api.py::_agent_worker`,
`vat_fraud_detection/_analyse_tx.py`, `vat_fraud_detection/lib/analyser.py`.

**Current implementation:** the agent runs **once per case** on a
single synthesized transaction built from the case's primary order
(seller, declared category, declared rate, product description). The
analyser returns exactly one `line_verdicts[0]` with one
`expected_rate` and one `verdict`. `_agent_worker` then applies that
single expected_rate to every linked order to compute a case-level
`VAT_Gap_Fee` as `sum(order.Product_Value × expected_rate −
order.VAT_Fee)`.

This is coherent today because orders within a case share seller,
category, and declared rate by construction (they're clustered by
`lib/database.py::find_similar_open_case` on those fields + description
Jaccard ≥ 0.4), so extrapolating a single rate across all orders is
faithful to what the agent observed.

**Limitation:** the verdict is a binary case-level signal. If the
primary order's verdict is `uncertain`, no gap is recorded even if the
other orders might have yielded definitive verdicts had they been
evaluated individually. The opposite also holds — a definitive verdict
on one order extrapolates to all, even if a hypothetical per-order run
would have flagged some as uncertain.

**Proposed improvement — batched invoice:**
1. Change `_build_agent_tx` to return a batched `Invoice` payload with
   all orders of the case as `LineItem`s (the analyser loops over
   `invoice.line_items` already; `_analyse_tx.py` builds a
   1-item invoice today but the downstream path supports N).
2. Teach `_agent_worker` to consume `line_verdicts` order-by-order:
   compute the gap only over orders whose verdict is definitive
   (`correct` / `incorrect` / `suspicious`), skip `uncertain` orders,
   and surface the uncertain count in the analysis text.
3. Decide the case-level `Recommended_VAT_Rate`: most-common
   definitive rate, with a note if verdicts disagree.
4. Persist the per-order verdicts (new column or structured entry in
   `Communication`) so the detail view can show the mix.

**Cost trade-off:** one batched subprocess call per case instead of
one-per-order — roughly the same wall-clock cost as today (RAG
retrieval dominates; N LineItems share the retrieval step), but with
correct semantics for the "9 definitive + 1 uncertain" scenario.

**When this matters:** the moment the sim produces cases whose linked
orders disagree on declared rate or product category (e.g. if
`find_similar_open_case`'s Jaccard threshold is lowered, or if
multiple sub-clusters merge into one case).

