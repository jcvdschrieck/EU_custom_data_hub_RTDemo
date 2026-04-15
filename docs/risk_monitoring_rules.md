# Risk Monitoring Rules

The EU Custom Data Hub runs two independent real-time risk monitoring
engines. Each subscribes to the Sales Order Event broker and publishes
its result to the unified **RT Risk Outcome** broker. The Automated
Assessment Factory collects both outcomes and computes a consolidated
risk score.

---

## RT Risk Monitoring 1 — VAT Ratio Deviation

**Source:** `lib/alarm_checker.py`
**Engine ID:** `vat_ratio`

### What it detects

Detects sudden shifts in a supplier's VAT-to-value ratio for a specific
destination country — a strong indicator of VAT fraud (e.g. a supplier
that normally charges 23% VAT suddenly submits invoices at 0%).

### Algorithm

For each incoming Sales Order:

1. **Current window** — compute the aggregate VAT/value ratio for the
   same `(seller_id, buyer_country)` pair over the **last 7 days**
   (including the new transaction).

2. **Historical baseline** — compute the same ratio over the preceding
   **8 weeks** (days −63 to −7), excluding the current window.

3. **Deviation check** — if the absolute deviation exceeds **25%**
   of the historical ratio:

   ```
   |current_ratio − historical_ratio| / historical_ratio > 0.25
   ```

   AND no active alarm already exists for this pair → **raise a new
   alarm** with a 7-day expiry.

4. **Ongoing flagging** — while an alarm is active, every new
   transaction from the same `(seller_id, buyer_country)` is tagged
   as suspicious. No duplicate alarms are raised.

### Parameters

| Parameter | Value | Description |
|---|---|---|
| `MIN_CURRENT_TX` | 3 | Minimum transactions in the 7-day window |
| `MIN_HISTORICAL_TX` | 5 | Minimum transactions in the 8-week baseline |
| `DEVIATION_THRESHOLD` | 0.25 (25%) | Trigger threshold |
| `SUSPICIOUS_COUNTRIES` | `{"IE"}` | Only Ireland-bound transactions enter the suspicious queue |

### Seeded scenario

TechZone GmbH (`SUP001`, Germany) → Ireland is seeded with zero-rate
fraud in week 2 of March 2026 (8–14 Mar): electronics billed at 0%
instead of the correct 23%. This drives the 7-day ratio from ~19% to
~0%, triggering the alarm on the first affected transaction.

---

## RT Risk Monitoring 2 — Supplier/Origin Watchlist

**Source:** `lib/watchlist.py`
**Engine ID:** `watchlist`

### What it detects

Flags transactions from known-suspicious supplier × country-of-origin
pairs maintained in a static watchlist. This covers scenarios where
intelligence identifies a supplier as high-risk regardless of their
current VAT behaviour.

### Algorithm

For each incoming Sales Order:

1. Look up the `(seller_id, seller_country)` pair in the **WATCHLIST**
   set.

2. If the pair is present → **flag** the transaction.

3. If not → **clear**.

This is a simple binary lookup with no statistical analysis.

### Current watchlist

| Seller ID | Country | Supplier Name |
|---|---|---|
| `SUP001` | DE | TechZone GmbH |
| `SUP002` | FR | FashionHub Paris |
| `SUP005` | NL | SportsPro Amsterdam |

The watchlist is editable in `lib/watchlist.py`. Adding or removing
entries takes effect immediately on the next transaction.

---

## Consolidation (Automated Assessment Factory)

The two engines publish independently to the **RT Risk Outcome** broker.
The Automated Assessment Factory collects outcomes per transaction and
computes:

```
score = flagged_count / total_outcomes_received
```

If no outcomes have arrived (both engines timed out):

```
score = 50% (uncertain)
```

### Confidence

```
confidence = outcomes_received / TOTAL_RISK_ENGINES
```

With 2 engines: 0% (none), 50% (one), 100% (both).

### Routing thresholds

| Score range | Route | Action |
|---|---|---|
| < 33.33% | **Green** → Release | Auto-released, stored in DB |
| 33.33% – 66.66% | **Amber** → Investigate | Sent to C&T Risk Management |
| > 66.66% | **Red** → Retain | Sent to C&T Risk Management |

With 2 engines the effective mapping is:

| Flagged | Score | Route |
|---|---|---|
| 0 of 2 | 0% | Release |
| 1 of 2 | 50% | Investigate |
| 2 of 2 | 100% | Retain |

### Assessment timer

A **3-second timer** starts when the Order Validation event arrives.
The assessment publishes either:
- **Immediately** if all engine outcomes arrive before the timer, or
- **On timer expiry** with whatever risk data is available (lower
  confidence).

Late-arriving engine outcomes after publication are discarded.
