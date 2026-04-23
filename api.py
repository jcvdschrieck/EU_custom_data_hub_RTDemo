"""
European Custom Data Hub — Real-Time Demo API
FastAPI backend on port 8000.

Message flow (publish-subscribe)
─────────────────────────────────────────────────────────────────────────────

 simulation_loop
     │  publishes one raw transaction per sim-clock tick
     ▼
 Sales-order Event Broker  (topic: sales_order_event)
     │
     ├──────────────────────┬─────────────────────────┬─────────────────────┐
     ▼                      ▼                         ▼                     ▼
 _RT_risk_              _RT_risk_                 _order_              _arrival_
 monitoring_1_          monitoring_2_             validation_          notification_
 factory                factory                   factory              factory
 (VAT-ratio rule)       (watchlist rule)          (field check)        (~60 s delay)
     │                      │                         │                     │
     ▼                      ▼                         │                     │
 rt_risk_1_outcome     rt_risk_2_outcome              │                     │
     │                      │                         │                     │
     └──────────┬───────────┘                         │                     │
                ▼                                     │                     │
        _RT_consolidation_factory                     │                     │
        (green / amber / red)                         │                     │
                │                                     │                     │
                ▼                                     ▼                     ▼
            rt_score                          order_validation       arrival_notification
                │                                     │                     │
                └─────────────────┬───────────────────┴─────────────────────┘
                                  ▼
                         _release_factory
                         (joins all signals, routes by colour)
                                  │
                ┌─────────────────┼─────────────────┐
                ▼                 ▼                 ▼
         release_event       retain_event     investigate_event
            (GREEN)             (RED)             (AMBER)
                │                 │                 │
                │                 ▼                 ▼
                │         _customs_listener    _tax_listener
                │         _factory             _factory
                │                 │                 │
                │                 ▼                 ▼
                │           _customs_queue     _tax_queue
                │                 │                 │
                │                 │                 │  Tax officer triggers
                │                 │                 │  the VAT Fraud Detection
                │                 │                 │  Agent → ai_analysis_event
                │                 │                 │
                │                 │  ◄── recommend ─┤  (back to Customs)
                │                 │                 │
                │                 │  ── escalate ─► │
                │                 │                 │
                │                 ▼                 │
                │         Customs Officer terminal decision
                │                 │
                │     ┌───────────┴───────────┐
                │     ▼                       ▼
                │  release_after_      agent_retain_event
                │  investigation_event  (officer retained)
                │                       │
                ▼                       ▼
              _db_store_worker  →  european_custom.db (legacy flat table)
                                      + live queue + /api/queue SSE
              _data_hub_writer  →  sales_order_line_item +
              (30-s polling tick)    line_item_risk +
                                      line_item_ai_analysis

The Customs Officer console (C&T Risk Management System /customs page) is master:
its release/retain decision is the terminal event. The Tax Officer console
(C&T Risk Management System /tax page) only issues a recommendation that the Customs
Officer can accept or override (audited via the custom_override flag).

Key endpoints
─────────────
GET  /health
GET  /api/queue                          live tail (REST snapshot)
GET  /api/queue/stream                   SSE — one transaction per event
GET  /api/transactions                   paginated historical query
GET  /api/metrics                        VAT aggregates with filters
GET  /api/suspicious                     historical suspicious transactions
GET  /api/alarms                         VAT-ratio alarm list

GET  /api/customs/queue                  live Customs queue (REST snapshot)
GET  /api/customs/queue/stream           SSE — Customs queue updates
POST /api/customs/{id}/escalate-to-tax   move item from Customs to Tax queue
POST /api/customs/{id}/decide            terminal release / retain decision

GET  /api/tax/queue                      live Tax queue (REST snapshot)
GET  /api/tax/queue/stream               SSE — Tax queue updates
POST /api/tax/{id}/run-agent             trigger VAT Fraud Detection Agent
POST /api/tax/{id}/recommend             release / retain recommendation back to Customs

GET  /api/transactions/{id}/timeline     full event history for a transaction
GET  /api/simulation/status
GET  /api/simulation/pipeline            event counters + queue depths + risk flags
POST /api/simulation/start
POST /api/simulation/pause
POST /api/simulation/resume
POST /api/simulation/speed               body: {"speed": <float>}
POST /api/simulation/reset
GET  /api/catalog/suppliers
GET  /api/catalog/countries
"""
from __future__ import annotations

import asyncio
import json as _json
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lib.broker import (
    broker,
    SALES_ORDER_EVENT, RT_RISK_OUTCOME, ORDER_VALIDATION,
    ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME, CUSTOM_OUTCOME,
    RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_RISK_3_OUTCOME, RT_RISK_4_OUTCOME, RT_SCORE,  # legacy counters
    RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,   # legacy counters
)

# Total number of risk monitoring engines. The release factory waits
# for this many outcomes (or times out) before computing the score.
# Adding a new risk engine = increment this + write the factory.
TOTAL_RISK_ENGINES = 4
from lib.config import DEFAULT_SPEED, MIN_SPEED, MAX_SPEED, QUEUE_SIZE
from lib.database import (
    get_latest_transactions,
    get_transaction_count,
    get_transaction_by_id,
    get_vat_metrics,
    insert_transaction,
    query_transactions,
    reset_simulation_db,
    get_sim_counts,
    get_alarms,
    get_suspicious_transactions,
    expire_old_alarms,
    reset_alarms,
    historical_transaction_count,
    flag_transaction_suspicious,
    insert_agent_log,
    get_agent_log,
    insert_ireland_queue,
    get_ireland_queue,
    get_ireland_case,
    update_suspicion_level,
)
# from lib.regions import country_region  # removed with data hub writer
from lib.simulator import state, simulation_loop
from lib.catalog import SUPPLIERS, COUNTRY_NAMES

# ── In-memory state ───────────────────────────────────────────────────────────

_live_queue:          deque[dict]        = deque(maxlen=QUEUE_SIZE)
_live_alarms:         list[dict]         = []
_sse_queues:          set[asyncio.Queue] = set()   # live-transaction stream subscribers
_sim_state_sse:       set[asyncio.Queue] = set()   # pipeline + status stream subscribers
_rg_case_sse:         set[asyncio.Queue] = set()   # C&T Risk Management System case stream subscribers

# ── VAT Fraud Detection agent queue ─────────────────────────────────────────
# Single asyncio queue + single worker. LM Studio serializes inference
# internally; running >1 worker would just stack up locally with no gain.
AGENT_WORKERS         = 1
_agent_queue:         asyncio.Queue[str] | None = None  # case_ids awaiting AI analysis
_agent_in_progress:   str | None = None                  # case_id currently processing

from lib import case_statuses as STATUS


def _push_rg_case_sse(payload: dict) -> None:
    """Push a case event to all connected C&T Risk Management System SSE clients."""
    if not _rg_case_sse:
        return
    import json as _json
    data = _json.dumps(payload)
    dead: set[asyncio.Queue] = set()
    for q in _rg_case_sse:
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            dead.add(q)
    _rg_case_sse.difference_update(dead)


# ── Two-entity workflow queues ───────────────────────────────────────────────
#
# Customs and Tax are modelled as two completely separate offices with their
# own listener, queue, SSE subscribers and UI page on the C&T Risk Management System UI.
# They communicate via two well-defined inter-entity transfers:
#
#   AMBER  → Tax Office  (initial entry)
#   RED    → Customs Office  (initial entry)
#
#   Customs operator can ESCALATE a Customs item to Tax (transfer).
#   Tax operator publishes a RECOMMENDATION which sends the item back
#   to Customs (transfer). The recommendation is non-binding.
#   Only the Customs operator can publish a TERMINAL decide (release/retain).
#
# All entries are in-memory dicts keyed by transaction_id. Both queues are
# wiped on simulation reset.
#
# Customs queue entry shape:
#   {
#     "tx":                 <full sales-order tx dict>,
#     "alarm":              <alarm metadata or {}>,
#     "risk_score":         "red" | "amber",
#     "route":              "red" | "amber",
#     "tax_recommendation": None | "release" | "retain",  (set when item came back from Tax)
#     "tax_recommended_at": None | ISO8601,
#     "created_at":         ISO8601,
#     "updated_at":         ISO8601,
#   }
#
# Tax queue entry shape:
#   {
#     "tx":                       <full sales-order tx dict>,
#     "alarm":                    <alarm metadata or {}>,
#     "risk_score":               "amber" | "red",
#     "route":                    "amber" | "red",
#     "escalated_from_customs":   bool,
#     "agent_status":             "pending" | "agent_running" | "agent_done",
#     "agent_verdict":            None | {"verdict", "reasoning", "legislation_refs", ...},
#     "created_at":               ISO8601,
#     "updated_at":               ISO8601,
#   }
# (C&T Risk Management System queues + SSE sets removed)

# Registry of in-flight delayed factory tasks (Order Validation + Arrival
# Notification + manual agent runs). Each factory adds its newly-created task
# here and removes it on completion. /api/simulation/reset cancels every task
# still in the set so no residual events fire after a reset has emptied the
# pipeline.
_inflight_factory_tasks: set[asyncio.Task] = set()


def _track_factory_task(coro) -> asyncio.Task:
    """Schedule *coro* as a background task and register it for cancellation
    on simulation reset. The task auto-removes itself from the registry when
    it finishes (so the set doesn't grow unbounded)."""
    task = asyncio.create_task(coro)
    _inflight_factory_tasks.add(task)
    task.add_done_callback(_inflight_factory_tasks.discard)
    return task


async def _sleep_until_sim_time(target_dt: datetime) -> None:
    """
    Wait until ``state.sim_time`` reaches ``target_dt``.

    Polls ``state.sim_time`` every 50 ms instead of doing a single fixed
    real-time ``asyncio.sleep`` so factory delays naturally:
      - **pause** when the user pauses the simulation (sim_time freezes,
        the loop just keeps spinning, no event fires until resume),
      - **adapt to speed changes** (a ×100 boost makes sim_time advance
        20× faster, the wait shortens automatically),
      - **cancel cleanly** on simulation reset (CancelledError raised inside
        the inner ``asyncio.sleep`` propagates out and the task dies).

    Use this in any factory whose delay should be expressed in sim-time
    rather than wall-clock time (Order Validation, Arrival Notification, …).
    """
    from lib.simulator import state as _state
    # 100 ms polling slice (was 50 ms). Halves the CPU spent polling per
    # in-flight factory task — meaningful when ~1500 tasks are queued during
    # heavy demos under screen-share encoding load. Visible latency on event
    # firing remains imperceptible at this scale (max ~100 ms drift).
    while _state.sim_time < target_dt:
        await asyncio.sleep(0.1)


# ── Simulation: publish to Sales-order Event Broker ──────────────────────────

async def _fire_transactions(rows: list[dict]) -> None:
    """
    Entry point called by the simulation loop (always called with a single row).
    Transforms each flat DB row into a Sales Order Event (simplified_order.json schema)
    and publishes it to the Sales-order Event Broker.
    Inter-event pacing is handled entirely by the simulation loop.
    """
    from lib.message_factory import build_sales_order_event
    for row in rows:
        await broker.publish(SALES_ORDER_EVENT, build_sales_order_event(row))


# ── RT Risk Monitoring 1 Factory (VAT rate misclassification) ────────────────

async def _RT_risk_monitoring_1_factory() -> None:
    """
    Subscriber of Sales-order Event Broker.

    Three resolution paths, tried in order:

      1. Pre-baked: tx carries ``_engine_vat_ratio_risk`` (set by the new
         seeder). Used as-is. Lets the seeder pin per-tx outcomes.
      2. Subcategory check (NEW dataset): tx carries
         ``vat_subcategory_code`` and ``vat_rate``. Look up the expected
         rate via vat_dataset.expected_rate_for and emit binary risk
         (1.0 mismatch / 0.0 match).
      3. Legacy volume-ratio: 7-day vs 8-week deviation alarm. Kept for
         the old seeder until it's retired in Stage 3.

    Publishes to RT_RISK_OUTCOME with engine="vat_ratio" and risk in [0, 1].
    """
    from lib.alarm_checker import check_alarm
    from lib import vat_dataset

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        prebaked    = tx.get("_engine_vat_ratio_risk")
        subcat_code = tx.get("vat_subcategory_code")
        declared    = tx.get("vat_rate")

        risk: float
        alarm_id = None
        new_alarm = None
        reason: str

        if prebaked is not None:
            risk = float(prebaked)
            reason = "prebaked"
        elif subcat_code and declared is not None:
            expected = vat_dataset.expected_rate_for(
                tx.get("buyer_country", ""), subcat_code
            )
            if expected is None:
                risk = 0.0
                reason = "unknown_subcategory"
            else:
                mismatch = abs(float(declared) - expected) > 1e-9
                risk = 1.0 if mismatch else 0.0
                reason = "rate_mismatch" if mismatch else "rate_match"
        else:
            # Legacy path — volume ratio + alarms
            result = check_alarm(tx)
            suspicious = bool(result and result.get("suspicious"))
            risk = 1.0 if suspicious else 0.0
            alarm_id = result.get("alarm_id") if result else None
            new_alarm = result.get("new_alarm") if result else None
            if new_alarm:
                _live_alarms.insert(0, new_alarm)
            expire_old_alarms(tx["transaction_date"][:19])
            reason = "alarm_match" if suspicious else "alarm_clear"

        flagged = risk >= 0.5

        await broker.publish(RT_RISK_OUTCOME, {
            "engine":     "vat_ratio",
            "order_id":   tx["transaction_id"],
            "risk":       risk,
            "applicable": True,
            "reason":     reason,
            "alarm_id":   alarm_id,
            "alarm":      new_alarm or (next(
                (a for a in _live_alarms if a.get("id") == alarm_id), {}
            ) if flagged and alarm_id else None),
        })
        # Legacy counter
        await broker.publish(RT_RISK_1_OUTCOME, {"order_id": tx["transaction_id"], "risk": risk, "flagged": flagged})


# ── RT Risk Monitoring 2 Factory (ML watchlist — 4-tuple + per-dim weights) ──

# Overall-risk threshold above which the engine flags the transaction.
ML_RISK_FLAG_THRESHOLD = 0.5


async def _RT_risk_monitoring_2_factory() -> None:
    """
    Subscriber of Sales-order Event Broker — ML / supplier-risk engine.

    Resolution paths, tried in order:
      1. Pre-baked: tx carries ``_engine_ml_risk`` plus optional
         ``_engine_ml_seller_contribution`` etc. (set by the new seeder).
         Per-tx exact outputs — required for the new dataset to land each
         row on its target route.
      2. 4-tuple rule lookup (legacy): ml_risk_rules in european_custom.db
         keyed on (seller, country_origin, vat_product_category,
         country_destination). Used by the old seeder.

    In either path the payload includes the four per-dimension contributor
    weights (seller_risk / country_risk / product_category_risk /
    destination_risk) which the release factory propagates into
    ASSESSMENT_OUTCOME and the C&T factory writes onto Sales_Order_Risk
    at case creation.
    """
    from lib.database import lookup_ml_risk_rule

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        prebaked = tx.get("_engine_ml_risk")
        if prebaked is not None:
            risk    = float(prebaked)
            flagged = risk >= ML_RISK_FLAG_THRESHOLD
            payload: dict = {
                "engine":                "watchlist",
                "order_id":              tx["transaction_id"],
                "risk":                  risk,
                "applicable":            True,
                "reason":                "prebaked_match" if flagged else "prebaked_clear",
                "description":           tx.get("_engine_ml_description"),
                "seller_risk":           tx.get("_engine_ml_seller_contribution",      0.0),
                "country_risk":          tx.get("_engine_ml_origin_contribution",      0.0),
                "product_category_risk": tx.get("_engine_ml_category_contribution",    0.0),
                "destination_risk":      tx.get("_engine_ml_destination_contribution", 0.0),
            }
        else:
            rule = lookup_ml_risk_rule(
                seller               = tx.get("seller_name", ""),
                country_origin       = tx.get("seller_country", ""),
                vat_product_category = tx.get("item_category", ""),
                country_destination  = tx.get("buyer_country", ""),
            )
            if rule is None:
                risk    = 0.0
                flagged = False
                payload = {
                    "engine":     "watchlist",
                    "order_id":   tx["transaction_id"],
                    "risk":       risk,
                    "applicable": True,
                    "reason":     "clear",
                }
            else:
                risk    = float(rule.get("risk", 0.0) or 0.0)
                flagged = risk >= ML_RISK_FLAG_THRESHOLD
                payload = {
                    "engine":                "watchlist",
                    "order_id":              tx["transaction_id"],
                    "risk":                  risk,
                    "applicable":            True,
                    "reason":                "ml_watchlist_match" if flagged else "ml_watchlist_low_risk",
                    "description":           rule.get("description"),
                    "seller_risk":           rule.get("seller_weight"),
                    "country_risk":          rule.get("country_origin_weight"),
                    "product_category_risk": rule.get("vat_product_category_weight"),
                    "destination_risk":      rule.get("country_destination_weight"),
                }

        await broker.publish(RT_RISK_OUTCOME, payload)
        # Legacy counter
        await broker.publish(RT_RISK_2_OUTCOME, {"order_id": tx["transaction_id"], "risk": risk, "flagged": flagged})


# ── RT Risk Monitoring 3 Factory (Ireland-specific watchlist) ───────────────
#
# Hosted (in real life) on a server managed by the Irish authority. This
# factory subscribes to SALES_ORDER_EVENT but only PROCESSES events whose
# country of destination is "IE" — events for other destinations are
# silently dropped (no publish at all). Adds a uniform 1–5 s latency to
# simulate the round-trip to the remote server.
#
# Watchlist is intentionally empty for now — fill IE_WATCHLIST below to
# start flagging matches.

import random as _random

# Watchlist of (seller_id, seller_country) tuples that the Irish authority
# has flagged. Empty by design — nothing is currently flagged.
IE_WATCHLIST: set[tuple[str, str]] = set()


async def _RT_risk_monitoring_3_factory() -> None:
    """
    Subscriber of Sales-order Event Broker, country-specific (IE).

    For each event:
      - if Country_Destination != "IE" → drop silently (engine doesn't apply)
      - otherwise: sleep uniform(1, 5) s, run the IE_WATCHLIST check,
        publish to RT_RISK_OUTCOME with engine="ireland_watchlist".

    Because the latency can exceed ASSESSMENT_TIMER_S (3 s by design),
    some IE outcomes legitimately arrive too late to influence the
    Release Factory's consolidation. That is the intended behaviour.
    """
    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()
        if (tx.get("buyer_country") or "").upper() != "IE":
            await broker.publish(RT_RISK_OUTCOME, {
                "engine":     "ireland_watchlist",
                "order_id":   tx["transaction_id"],
                "risk":       0.0,
                "applicable": False,
                "reason":     "not_applicable",
            })
            continue

        async def _process(tx=tx):
            await asyncio.sleep(_random.uniform(1.0, 5.0))
            prebaked = tx.get("_engine_ie_watchlist_risk")
            if prebaked is not None:
                risk = float(prebaked)
                reason = "prebaked_match" if risk >= 0.5 else "prebaked_clear"
            else:
                seller_id      = tx.get("seller_id", "")
                seller_country = (tx.get("seller_country") or "").upper()
                matched = (seller_id, seller_country) in IE_WATCHLIST
                risk    = 1.0 if matched else 0.0
                reason  = "ie_watchlist_match" if matched else "clear"
            await broker.publish(RT_RISK_OUTCOME, {
                "engine":     "ireland_watchlist",
                "order_id":   tx["transaction_id"],
                "risk":       risk,
                "applicable": True,
                "reason":     reason,
            })
            await broker.publish(RT_RISK_3_OUTCOME, {"order_id": tx["transaction_id"], "risk": risk, "flagged": risk >= 0.5})

        asyncio.create_task(_process())


# ── RT Risk Monitoring 4 Factory (Description Vagueness) ─────────────────────
#
# Scores how vague/generic the product description is. Uses sentence
# embeddings (all-MiniLM-L6-v2) and cosine similarity to a set of vague
# anchor texts. Higher similarity → higher risk (the description says
# almost nothing useful for classification).

_vagueness_model = None
_vague_anchor_embedding = None

def _get_vagueness_model():
    global _vagueness_model, _vague_anchor_embedding
    if _vagueness_model is None:
        from sentence_transformers import SentenceTransformer
        _vagueness_model = SentenceTransformer("all-MiniLM-L6-v2")
        vague_anchors = [
            "general goods", "miscellaneous items", "various products",
            "stuff", "goods", "items", "products", "materials",
            "other", "mixed", "assorted", "sample", "test",
        ]
        embs = _vagueness_model.encode(vague_anchors, normalize_embeddings=True)
        _vague_anchor_embedding = embs.mean(axis=0)
        _vague_anchor_embedding /= (_vague_anchor_embedding ** 2).sum() ** 0.5
    return _vagueness_model, _vague_anchor_embedding


async def _RT_risk_monitoring_4_factory() -> None:
    """
    Subscriber of Sales-order Event Broker.

    Scores each product description on a vagueness scale [0, 1].

    Resolution paths, tried in order:
      1. Pre-baked: tx carries ``_engine_vagueness_risk`` (set by the new
         seeder). Used as-is so per-tx targets are honoured exactly.
      2. Embedding model: cosine similarity between the description
         embedding and a pre-computed "vague text" anchor. Slow path,
         only used when no pre-baked value is supplied.

    Flagged when risk >= 0.5.
    """
    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        prebaked    = tx.get("_engine_vagueness_risk")
        description = (tx.get("item_description") or tx.get("product_description") or "").strip()

        if prebaked is not None:
            risk = float(prebaked)
            reason_clear = "prebaked_clear"
            reason_flag  = "prebaked_vague"
        elif not description:
            risk = 1.0
            reason_clear = "clear"
            reason_flag  = "missing_description"
        else:
            model, anchor = _get_vagueness_model()
            emb = model.encode([description], normalize_embeddings=True)[0]
            similarity = float((emb * anchor).sum())
            risk = max(0.0, min(1.0, similarity))
            reason_clear = "clear"
            reason_flag  = "vague_description"

        flagged = risk >= 0.5

        await broker.publish(RT_RISK_OUTCOME, {
            "engine":     "description_vagueness",
            "order_id":   tx["transaction_id"],
            "risk":       risk,
            "applicable": True,
            "reason":     reason_flag if flagged else reason_clear,
        })
        await broker.publish(RT_RISK_4_OUTCOME, {"order_id": tx["transaction_id"], "risk": risk, "flagged": flagged})


# ── (RT Consolidation Factory removed — its logic is now inside
# _release_factory which subscribes to RT_RISK_OUTCOME directly.) ──


# ── Order Validation Factory ──────────────────────────────────────────────────

async def _order_validation_factory() -> None:
    """
    Subscriber of Sales-order Event Broker.
    Validates the incoming sales order (required fields, numeric sanity,
    known country code) after a uniformly-distributed delay of 3–5 sim-seconds.
    The wait is expressed in sim-time via _sleep_until_sim_time so it
    naturally pauses with the simulation, adapts to speed changes, and
    cancels cleanly on reset.

    Each order is handled by an independent asyncio task — unlimited concurrency,
    no order waits behind another in this factory.
    Publishes to Order_validation_broker.
    """
    import random
    from lib.catalog import COUNTRIES
    from lib.simulator import state as _state

    async def _validate(tx: dict) -> None:
        sim_delay = random.uniform(3.0, 5.0)
        target = _state.sim_time + timedelta(seconds=sim_delay)
        await _sleep_until_sim_time(target)
        errors: list[str] = []
        for field in ("transaction_id", "seller_id", "seller_name",
                      "buyer_country", "value", "vat_rate", "vat_amount"):
            if tx.get(field) is None:
                errors.append(f"missing field: {field}")
        if tx.get("value", 0) <= 0:
            errors.append("value must be positive")
        if tx.get("vat_rate", -1) < 0:
            errors.append("vat_rate must be >= 0")
        if tx.get("buyer_country") not in COUNTRIES:
            errors.append(f"unknown buyer_country: {tx.get('buyer_country')}")
        await broker.publish(ORDER_VALIDATION, {
            "tx":                tx,
            "validated":         len(errors) == 0,
            "validation_errors": errors,
        })

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()
        _track_factory_task(_validate(tx))


# ── (Arrival Notification Factory removed — Goods Transport flow eliminated.) ──


# ── Release Factory (unified routing: consolidation + release/retain/investigate) ─
#
# Replaces the old RT Consolidation Factory + three separate routing factories.
# Subscribes to:
#   - RT_RISK_OUTCOME (all risk engines publish here with an "engine" field)
#   - ORDER_VALIDATION
#   - ARRIVAL_NOTIFICATION
#
# For each transaction, collects risk outcomes and computes:
#   - risk_score  = weighted-sum of applicable engine risks, capped at 1.0
#                   (matches the xlsx Overall Risk Score model: Score 1 +
#                   Score 2 + Score 3, capped at 100)
#   - confidence  = outcomes_received / TOTAL_RISK_ENGINES (0%, 50%, 100%)
#   - route:  score < 33.33% → release
#             33.33% ≤ score < 80% → investigate
#             score >= 80% → retain
#
# GREEN path (release) additionally requires validation + arrival notification.
# RED path (retain) fires immediately once the score crosses the retain threshold.
# AMBER path (investigate) requires validation before dispatch.

THRESHOLD_RELEASE    = 1.0 / 3.0   # < 33.33% → release
THRESHOLD_RETAIN     = 0.80        # >= 80%   → retain (xlsx: 75 still investigate, 90+ retain)
ASSESSMENT_TIMER_S   = 3.0         # seconds after validation before forced publish

# Per-engine weights for the score consolidation. Tuned against the new
# dataset (Context/Fake_ML.xlsx, 191 rows): 189/191 (99.0%) land on their
# xlsx target with these values + the vat_ratio floor in _compute_score.
# Both residual mismatches (tx#70 → FR, tx#146 → NL) are rate-match
# cases where supplier_risk Score 3=40 alone makes us emit Investigate
# while xlsx says Release. Both have non-IE destinations so they are
# filtered out at the frontend (see customsandtaxriskmanagemensystem
# backendCaseStore IE filter) and don't affect the demo. Stage 3's
# seeder can override the pre-baked engine outputs on these rows if
# pixel-perfect alignment matters.
ENGINE_WEIGHTS: dict[str, float] = {
    "vat_ratio":             0.5,
    "watchlist":             0.9,    # ML / supplier-risk engine
    "ireland_watchlist":     1.0,
    "description_vagueness": 0.8,
}


def case_risk_level(score: float) -> str:
    """Compute Low/Medium/High for a case-level risk score.

    Only investigate-routed transactions (score in [THRESHOLD_RELEASE,
    THRESHOLD_RETAIN]) become cases. The Low/Medium/High classification
    maps the score within that interval using the same 1/3 and 2/3
    percentile boundaries, so the labels adapt if the thresholds change.

      Low:    score < THRESHOLD_RELEASE + interval × 1/3
      Medium: score < THRESHOLD_RELEASE + interval × 2/3
      High:   score >= THRESHOLD_RELEASE + interval × 2/3
    """
    interval = THRESHOLD_RETAIN - THRESHOLD_RELEASE
    low_high_boundary = THRESHOLD_RELEASE + interval * (1.0 / 3.0)
    medium_high_boundary = THRESHOLD_RELEASE + interval * (2.0 / 3.0)
    if score >= medium_high_boundary:
        return "High"
    if score >= low_high_boundary:
        return "Medium"
    return "Low"

async def _release_factory() -> None:
    """Automated Assessment Factory.

    Collects risk outcomes + validation for each transaction. Once
    validation arrives, a 3-second timer starts. The assessment is
    published either:
      (a) immediately, if all TOTAL_RISK_ENGINES outcomes arrive
          before the timer fires, OR
      (b) when the timer fires, with whatever risk info is available
          at that point.

    Once published, the transaction is marked "routed" and any late
    risk outcomes are discarded."""

    # Per-transaction buffer: tx_id → {
    #   "risk_outcomes": {engine_name: item, ...},
    #   "validation": item | None,
    #   "routed": bool,
    #   "timer_task": asyncio.Task | None,
    # }
    _buffer: dict[str, dict] = {}

    def _get(tx_id: str) -> dict:
        return _buffer.setdefault(tx_id, {
            "risk_outcomes": {},
            "validation": None,
            "routed": False,
            "timer_task": None,
        })

    def _compute_score(entry: dict) -> tuple[float, float, str]:
        """Return (score, confidence, route).

        Score is the weighted sum of per-engine ``risk`` values for
        applicable engines, capped at 1.0. This matches the xlsx Overall
        Risk Score model (Score 1 + Score 2 + Score 3, capped at 100).
        Non-applicable engines (e.g. IE watchlist for a non-IE tx) are
        excluded from the sum.

        vat_ratio floor: if the vat_ratio engine reports raw risk >=
        VAT_RATIO_FLOOR_TRIGGER (xlsx-internal cut between Score 1=25
        which xlsx releases and Score 1>=37.5 which xlsx investigates),
        its weighted contribution is floored at THRESHOLD_RELEASE + ε
        so the tx lands at least in Investigate. Policy stance: a
        rate mismatch above this severity deserves an investigation
        regardless of weight. Without this floor tx#42 (IE, S1=40
        alone) would mis-route to Release and disappear from the C&T
        queue. The trigger threshold (0.30) is below all "real"
        Score 1 values (37.5..75) and above the xlsx's release tier
        (Score 1=25), so no rate-match release row is affected.

        Confidence = applicable engines received / total applicable engines
        expected. An engine that self-reports applicable=False counts toward
        "received" (we know its status) but not toward the score or the
        expected count.
        """
        outcomes = entry["risk_outcomes"]

        applicable = {eng: o for eng, o in outcomes.items()
                      if o.get("applicable", True)}
        n_applicable = len(applicable)
        n_not_applicable = sum(1 for o in outcomes.values()
                               if not o.get("applicable", True))
        n_expected = TOTAL_RISK_ENGINES - n_not_applicable
        confidence = n_applicable / n_expected if n_expected > 0 else 0

        if n_applicable == 0:
            score = 0.5
        else:
            VAT_RATIO_FLOOR_TRIGGER = 0.30                 # raw risk threshold to engage floor
            VAT_RATIO_FLOOR         = THRESHOLD_RELEASE + 1e-3  # floored contribution value

            def _contrib(eng: str, o: dict) -> float:
                raw = float(o.get("risk", 0.0) or 0.0)
                weighted = ENGINE_WEIGHTS.get(eng, 1.0) * raw
                if (eng == "vat_ratio"
                        and raw >= VAT_RATIO_FLOOR_TRIGGER
                        and weighted < VAT_RATIO_FLOOR):
                    return VAT_RATIO_FLOOR
                return weighted

            score = min(1.0, sum(_contrib(eng, o) for eng, o in applicable.items()))

        if score >= THRESHOLD_RETAIN:
            route = "red"
        elif score >= THRESHOLD_RELEASE:
            route = "amber"
        else:
            route = "green"

        return score, confidence, route

    async def _publish_assessment(tx_id: str) -> None:
        """Publish the assessment outcome for a transaction using
        whatever risk info is available now."""
        entry = _buffer.get(tx_id)
        if entry is None or entry["routed"]:
            return
        if entry["validation"] is None:
            return   # should not happen — timer starts after validation

        entry["routed"] = True
        # Cancel the timer if it hasn't fired yet
        timer = entry.get("timer_task")
        if timer and not timer.done():
            timer.cancel()

        score, confidence, route = _compute_score(entry)
        outcomes = entry["risk_outcomes"]
        val = entry["validation"]
        import uuid
        now_iso = datetime.now(timezone.utc).isoformat()

        so_bk = f"{tx_id}-001"  # business key
        risk_id = f"RISK-{uuid.uuid4().hex[:12].upper()}"

        route_label = {"red": "retain", "amber": "investigate", "green": "release"}[route]

        # Build per-engine outcome dict: engine_name → outcome fields
        # (strip order_id since it's already at the top level)
        engine_outcomes = {}
        for eng, o in outcomes.items():
            entry_out = {k: v for k, v in o.items() if k not in ("order_id",)}
            engine_outcomes[eng] = entry_out

        payload = {
            "order_id":                    tx_id,
            "Sales_Order_ID":              tx_id,
            "Sales_Order_Business_Key":    so_bk,
            "route":                       route_label,
            "validated":                   val["validated"],
            "validation_errors":           val["validation_errors"],
            # Risk assessment fields
            "Sales_Order_Risk_ID":         risk_id,
            "Risk_Type":                   "VAT",
            "Overall_Risk_Score":          round(score, 4),
            "Overall_Risk_Level":          route,
            "Confidence_Score":            round(confidence, 2),
            "Proposed_Risk_Action":        route_label,
            "engine_outcomes":             engine_outcomes,
            "Update_time":                 now_iso,
        }

        # Legacy RT_SCORE event for pipeline counter compatibility
        await broker.publish(RT_SCORE, {
            "order_id":      tx_id,
            "risk_score":    route,
        })

        await broker.publish(ASSESSMENT_OUTCOME, payload)

        # Legacy counter
        legacy_topic = {
            "retain": RETAIN_EVENT,
            "investigate": INVESTIGATE_EVENT,
            "release": RELEASE_EVENT,
        }[route_label]
        await broker.publish(legacy_topic, payload)

        _buffer.pop(tx_id, None)

    async def _timer_callback(tx_id: str) -> None:
        """Fires ASSESSMENT_TIMER_S seconds after validation. Publishes
        the assessment with whatever risk info has accumulated."""
        try:
            await asyncio.sleep(ASSESSMENT_TIMER_S)
            await _publish_assessment(tx_id)
        except asyncio.CancelledError:
            pass  # timer cancelled because all risk outcomes arrived early

    def _start_timer(tx_id: str) -> None:
        """Start the assessment timer for a transaction."""
        entry = _get(tx_id)
        if entry["timer_task"] is None and not entry["routed"]:
            entry["timer_task"] = asyncio.create_task(_timer_callback(tx_id))

    async def _try_early_publish(tx_id: str) -> None:
        """Check if all risk outcomes have arrived. If so, publish
        immediately (cancelling the timer)."""
        entry = _get(tx_id)
        if entry["routed"] or entry["validation"] is None:
            return
        if len(entry["risk_outcomes"]) >= TOTAL_RISK_ENGINES:
            await _publish_assessment(tx_id)

    # ── Drain: risk outcomes ──
    async def _drain_risk() -> None:
        q = broker.subscribe(RT_RISK_OUTCOME)
        while True:
            item = await q.get()
            tx_id = item["order_id"]
            entry = _get(tx_id)
            if entry["routed"]:
                continue   # late arrival — discard
            engine = item.get("engine", "unknown")
            entry["risk_outcomes"][engine] = item
            await _try_early_publish(tx_id)

    # ── Drain: order validation ──
    async def _drain_validation() -> None:
        q = broker.subscribe(ORDER_VALIDATION)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            entry = _get(tx_id)
            if entry["routed"]:
                continue
            entry["validation"] = item
            # Start the timer — assessment publishes in 3s or sooner
            _start_timer(tx_id)
            # Check if all risk outcomes already arrived
            await _try_early_publish(tx_id)

    await asyncio.gather(_drain_risk(), _drain_validation())


# ── Custom & Tax Risk Management System ──────────────────────────────────────
#
# Subscribes to ASSESSMENT_OUTCOME (retain + investigate routes) and
# SALES_ORDER_EVENT. For now, produces an INVESTIGATION_OUTCOME event
# that echoes the assessment input (placeholder for future human-in-the-loop
# or AI-driven investigation logic).

async def _ct_risk_management_factory() -> None:
    """
    Custom & Tax Risk Management System.

    Subscribes to ASSESSMENT_OUTCOME (retain + investigate routes only).
    For each such event, atomically writes the 3-row case dataset
    (Sales_Order + Sales_Order_Risk + Sales_Order_Case) into
    investigation.db and pushes the hydrated case to C&T Risk Management System
    SSE subscribers.

    Does NOT publish INVESTIGATION_OUTCOME at creation. That event is the
    factory's exit signal and fires only when an officer closes the case
    (see customs-action retainment/release endpoint).
    """
    from lib.database import (
        upsert_investigation_set, get_case_hydrated,
        find_similar_open_case, append_order_to_case,
        update_case_engine_scores, get_case_transaction_count,
    )
    from lib import sales_order_statuses as SO_STATUS
    import uuid as _uuid

    # Buffer transactions from SALES_ORDER_EVENT by order_id so that when
    # an ASSESSMENT_OUTCOME arrives we can look up the original tx data.
    _tx_buffer: dict[str, dict] = {}

    async def _drain_tx() -> None:
        q = broker.subscribe(SALES_ORDER_EVENT)
        while True:
            tx = await q.get()
            _tx_buffer[tx["transaction_id"]] = tx

    async def _drain_assessment() -> None:
        q = broker.subscribe(ASSESSMENT_OUTCOME)
        while True:
            msg = await q.get()
            route = msg.get("route")
            if route != "investigate":
                _tx_buffer.pop(msg.get("order_id", ""), None)
                continue
            try:
                order_id = msg.get("order_id", "")
                tx = _tx_buffer.pop(order_id, None) or {}
                now_iso = datetime.now(timezone.utc).isoformat()
                bk = msg.get("Sales_Order_Business_Key", "")

                # Per-order overall risk score (0-1) from the assessment
                order_risk_score = float(msg.get("Overall_Risk_Score") or 0)

                # Extract per-engine risk scores (0-1)
                eo = msg.get("engine_outcomes", {}) or {}
                eng_scores = {
                    "Engine_VAT_Ratio":             float(eo.get("vat_ratio", {}).get("risk", 0) or 0),
                    "Engine_ML_Watchlist":           float(eo.get("watchlist", {}).get("risk", 0) or 0),
                    "Engine_IE_Seller_Watchlist":    float(eo.get("ireland_watchlist", {}).get("risk", 0) or 0),
                    "Engine_Description_Vagueness":  float(eo.get("description_vagueness", {}).get("risk", 0) or 0),
                }

                # Derive VAT problem type from engine outcomes
                vat_flagged = eo.get("vat_ratio", {}).get("risk", 0) >= 0.5
                wl_flagged  = eo.get("watchlist", {}).get("risk", 0) >= 0.5
                if vat_flagged and wl_flagged:
                    problem_type = "VAT Rate Deviation + Watchlist Match"
                elif vat_flagged:
                    problem_type = "VAT Rate Deviation"
                elif wl_flagged:
                    problem_type = "Watchlist Match"
                else:
                    problem_type = "Risk Pattern"

                ml = eo.get("watchlist", {})
                def _pct(v):
                    return round(float(v) * 100, 1) if v is not None else None

                so_row = {
                    "Sales_Order_ID":           order_id,
                    "Sales_Order_Business_Key": bk,
                    "HS_Product_Category":      tx.get("item_category"),
                    "Product_Description":      tx.get("item_description"),
                    "Product_Value":            tx.get("value"),
                    "VAT_Rate":                 tx.get("vat_rate"),
                    "VAT_Fee":                  tx.get("vat_amount"),
                    "Seller_Name":              tx.get("seller_name"),
                    "Country_Origin":           tx.get("seller_country"),
                    "Country_Destination":      tx.get("buyer_country"),
                    "Status":                   SO_STATUS.UNDER_INVESTIGATION,
                    "Update_time":              now_iso,
                    "Updated_by":               "system",
                }
                sor_row = {
                    "Sales_Order_Risk_ID":         msg.get("Sales_Order_Risk_ID"),
                    "Sales_Order_Business_Key":    bk,
                    "Risk_Type":                   msg.get("Risk_Type", "VAT"),
                    "Overall_Risk_Score":          msg.get("Overall_Risk_Score"),
                    "Overall_Risk_Level":          msg.get("Overall_Risk_Level"),
                    "Seller_Risk_Score":           _pct(ml.get("seller_risk")),
                    "Country_Risk_Score":          _pct(ml.get("country_risk")),
                    "Product_Category_Risk_Score": _pct(ml.get("product_category_risk")),
                    "Manufacturer_Risk_Score":     _pct(ml.get("destination_risk")),
                    "Confidence_Score":            msg.get("Confidence_Score"),
                    "Overall_Risk_Description":    ml.get("description"),
                    "Proposed_Risk_Action":        msg.get("Proposed_Risk_Action"),
                    "Risk_Comment":                None,
                    "Evaluation_by":               None,
                    "Update_time":                 now_iso,
                    "Updated_by":                  "system",
                }

                existing = find_similar_open_case(
                    seller      = tx.get("seller_name", ""),
                    destination = tx.get("buyer_country", ""),
                    category    = tx.get("item_category", ""),
                    description = tx.get("item_description", ""),
                )

                if existing:
                    existing_case_id = existing["Case_ID"]
                    append_order_to_case(existing_case_id, so_row, sor_row)
                    # Recompute averages across all orders in the case
                    n = get_case_transaction_count(existing_case_id)
                    old = get_case_hydrated(existing_case_id) or {}
                    avg = {}
                    for field in ("Engine_VAT_Ratio", "Engine_ML_Watchlist",
                                  "Engine_IE_Seller_Watchlist", "Engine_Description_Vagueness"):
                        old_val = float(old.get(field) or 0)
                        new_val = eng_scores[field]
                        avg[field] = ((old_val * (n - 1)) + new_val) / n if n > 0 else new_val
                    old_overall = float(old.get("Overall_Case_Risk_Score") or 0)
                    new_overall = ((old_overall * (n - 1)) + order_risk_score) / n if n > 0 else order_risk_score
                    update_case_engine_scores(
                        existing_case_id, avg,
                        overall_score=new_overall,
                        risk_level=case_risk_level(new_overall))
                    hydrated = get_case_hydrated(existing_case_id)
                    _push_rg_case_sse({"event": "case_updated", "action": "tx_appended", "case": hydrated})
                else:
                    case_id = f"CASE-{_uuid.uuid4().hex[:12].upper()}"
                    so_row["Case_ID"] = case_id
                    soc_row = {
                        "Case_ID":                          case_id,
                        "Sales_Order_Business_Key":         bk,
                        "Status":                           STATUS.NEW,
                        "VAT_Problem_Type":                 problem_type,
                        "Recommended_Product_Value":        None,
                        "Recommended_VAT_Product_Category": None,
                        "Recommended_VAT_Rate":             None,
                        "Recommended_VAT_Fee":              None,
                        "AI_Analysis":                      None,
                        "AI_Confidence":                    None,
                        "VAT_Gap_Fee":                      None,
                        "Evaluation_by":                    None,
                        "Proposed_Action_Tax":              None,
                        "Proposed_Action_Customs":          None,
                        "Communication":                    "[]",
                        "Additional_Evidence":              None,
                        "Update_time":                      now_iso,
                        "Updated_by":                       "system",
                        "Created_time":                     now_iso,
                        "Overall_Case_Risk_Score":          order_risk_score,
                        "Overall_Case_Risk_Level":          case_risk_level(order_risk_score),
                        **eng_scores,
                    }
                    upsert_investigation_set(so_row, sor_row, soc_row)
                    hydrated = get_case_hydrated(case_id) or {"Case_ID": case_id}
                    _push_rg_case_sse({"event": "new_case", "case": hydrated})
                    print(f"  [C&T] case {case_id} created for {tx.get('seller_name','?')}")
                    insert_agent_log({
                        "transaction_id": case_id,
                        "seller_name": tx.get("seller_name"),
                        "buyer_country": tx.get("buyer_country"),
                        "item_description": tx.get("item_description"),
                        "item_category": tx.get("item_category"),
                        "value": tx.get("value"),
                        "vat_rate": tx.get("vat_rate"),
                        "correct_vat_rate": None,
                        "verdict": "case_created",
                        "reasoning": f"Case {case_id} created — {problem_type}",
                        "legislation_refs": "[]", "sent_to_ireland": 0,
                        "processed_at": now_iso,
                    })
            except Exception as e:
                print(f"  [C&T] ERROR processing assessment: {e}")
                import traceback; traceback.print_exc()

    await asyncio.gather(_drain_tx(), _drain_assessment())


# ── (C&T Risk Management System two-entity workflow removed — replaced by
# _ct_risk_management_factory above.) ──


_REMOVED_FLAT_TX_VIEW = True  # marker — old _flat_tx_view and related
# customs/tax queue helpers, listeners, SSE streams, and REST endpoints
# have been removed. The C&T Risk Management factory replaces them.


# ── Exit Process Worker (all terminal event topics) ──────────────────────────

async def _db_store_worker() -> None:
    """
    Exit Process Factory — emits a single terminal CUSTOM_OUTCOME event
    per completed order. Persistence to the legacy data hub is deactivated.

    Subscribes to:
      ASSESSMENT_OUTCOME    — release route  → CUSTOM_OUTCOME automated_release
                            — retain route   → CUSTOM_OUTCOME automated_retain
      INVESTIGATION_OUTCOME — outcome released/retained →
                            CUSTOM_OUTCOME custom_release / custom_retain

    Each emitted event carries: order_id, timestamp, status.
    """
    async def _emit(order_id: str, status: str) -> None:
        await broker.publish(CUSTOM_OUTCOME, {
            "order_id":  order_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status":    status,
        })

    async def _drain_assessment() -> None:
        q = broker.subscribe(ASSESSMENT_OUTCOME)
        while True:
            msg = await q.get()
            route = msg.get("route")
            if route == "release":
                await _emit(msg.get("order_id", ""), "automated_release")
            elif route == "retain":
                await _emit(msg.get("order_id", ""), "automated_retain")

    async def _drain_investigation() -> None:
        q = broker.subscribe(INVESTIGATION_OUTCOME)
        while True:
            msg = await q.get()
            outcome = msg.get("outcome") or msg.get("route") or ""
            if outcome == "released":
                status = "custom_release"
            elif outcome == "retained":
                status = "custom_retain"
            else:
                continue   # ignore refused / other terminal states for now
            order_id = msg.get("Sales_Order_ID") or msg.get("Sales_Order_Business_Key", "")
            await _emit(order_id, status)

    await asyncio.gather(_drain_assessment(), _drain_investigation())



# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from lib.database import (
        init_european_custom_db, init_simulation_db, init_investigation_db,
        init_historical_cases_db,
        reset_simulation_db, reset_cases,
    )
    from lib.event_store import flush_events
    init_european_custom_db()
    init_simulation_db()
    init_investigation_db()
    init_historical_cases_db()
    # Auto-reset on every boot. Without this, a previous run's state
    # survives across restarts and shows up in the frontend:
    #   - fired=1 on every tx → simulation_loop has nothing to replay
    #   - cases in investigation.db → frontend lists stale cases
    #   - alarms in european_custom.db → alarm chip lights up from
    #     last run's pipeline activity
    #   - pending broker events in event_store → replay emits ghost
    #     outcomes on first real tx.
    # Mirrors the data-layer half of POST /api/simulation/reset; the
    # in-memory state (live_queue, SSE subscribers, in-flight factory
    # tasks) is already empty at boot so we don't need to drain it.
    reset_simulation_db()
    reset_cases()
    reset_alarms()
    flush_events()

    # Pre-load the vagueness NLP model in a thread so it doesn't block
    # the event loop when the first transaction arrives at Engine 4.
    import concurrent.futures
    _model_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    _model_pool.submit(_get_vagueness_model)

    asyncio.create_task(simulation_loop(_fire_transactions))
    asyncio.create_task(_RT_risk_monitoring_1_factory())
    asyncio.create_task(_RT_risk_monitoring_2_factory())
    asyncio.create_task(_RT_risk_monitoring_3_factory())
    asyncio.create_task(_RT_risk_monitoring_4_factory())
    # Consolidation is now handled inside _release_factory (unified routing).
    asyncio.create_task(_order_validation_factory())
    # _arrival_notification_factory removed (Goods Transport flow eliminated)
    asyncio.create_task(_release_factory())
    # _retain_factory and _investigate_dispatch_factory are removed —
    # the unified _release_factory handles all three routes.
    # Two-entity model: each office has its own listener.
    #   RED   → RETAIN_EVENT      → _customs_listener → _customs_queue
    #   AMBER → INVESTIGATE_EVENT → _tax_listener     → _tax_queue
    asyncio.create_task(_ct_risk_management_factory())
    asyncio.create_task(_db_store_worker())

    # Note: broker queues are NOT drained on startup — the factories need
    # their subscriber queues intact. Queue depths are masked in the UI
    # (show_queues=False) when the simulation hasn't started yet.
    # _data_hub_writer removed — DB Store Factory now writes directly
    # to the new data model tables (Sales_Order + Sales_Order_Risk)
    asyncio.create_task(_sim_state_broadcaster())

    # VAT Fraud Detection agent queue + worker(s). Initialise the queue
    # inside the running loop so put/get bind to the right loop.
    global _agent_queue
    _agent_queue = asyncio.Queue()
    for _ in range(AGENT_WORKERS):
        asyncio.create_task(_agent_worker())

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="European Custom Data Hub — RTDemo",
    version="4.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "records_in_db": get_transaction_count()}


# ── Live queue ────────────────────────────────────────────────────────────────

@app.get("/api/queue")
def get_queue():
    if not _live_queue:
        return {"items": get_latest_transactions(QUEUE_SIZE), "source": "db"}
    return {"items": list(_live_queue)[:QUEUE_SIZE], "source": "live"}


@app.get("/api/queue/stream")
async def queue_stream(request: Request):
    """Server-Sent Events stream — one transaction per event."""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _sse_queues.add(q)

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _sse_queues.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Simulation state stream (pushed to the Simulation page — replaces polling) ─

def _compute_sim_state_snapshot() -> dict:
    """Full sim status + pipeline snapshot in a single JSON-serialisable dict.

    Consumers (the SSE broadcaster below) use this to push a consolidated
    state update to the Simulation page several times per second, so the UI
    can render smooth event-by-event progress instead of polling every 2-3 s.
    """
    from lib.event_store import event_count, count_field_value
    from lib.broker import broker as _broker

    # ── Status block (same shape as GET /api/simulation/status) ──
    counts = get_sim_counts()
    s = state.to_dict()
    s.update(counts)
    s["active_alarms"] = len(get_alarms(active_only=True))

    # ── Pipeline block (same shape as GET /api/simulation/pipeline) ──
    topics = [
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_RISK_3_OUTCOME, RT_RISK_4_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
        CUSTOM_OUTCOME,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    ]
    show_queues = state.fired_count > 0 or state.running
    pipeline = {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: (_broker.qsize(t) if show_queues else 0) for t in topics},
        "stored_count":       get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "outcome.flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "outcome.flagged", True),
            "rt_risk_3_flagged": count_field_value(RT_RISK_3_OUTCOME, "outcome.flagged", True),
            "rt_risk_4_flagged": count_field_value(RT_RISK_4_OUTCOME, "outcome.flagged", True),
            "rt_score_green":    count_field_value(RT_SCORE, "outcome.risk_score", "green"),
            "rt_score_amber":    count_field_value(RT_SCORE, "outcome.risk_score", "amber"),
            "rt_score_red":      count_field_value(RT_SCORE, "outcome.risk_score", "red"),
        },
        "custom_outcome_status": {
            "automated_release": count_field_value(CUSTOM_OUTCOME, "outcome.status", "automated_release"),
            "automated_retain":  count_field_value(CUSTOM_OUTCOME, "outcome.status", "automated_retain"),
            "custom_release":    count_field_value(CUSTOM_OUTCOME, "outcome.status", "custom_release"),
            "custom_retain":     count_field_value(CUSTOM_OUTCOME, "outcome.status", "custom_retain"),
        },
    }

    return {"status": s, "pipeline": pipeline}


async def _sim_state_broadcaster() -> None:
    """Push a sim-state snapshot to every connected SSE subscriber at ~2 Hz.

    Replaces the frontend's 2 s / 3 s setInterval polling so the UI reflects
    events (sim_time, fired_count, per-topic counters) as they happen, not in
    2–3-second batches. Only runs if there's at least one subscriber to avoid
    reading the event store filesystem when no one is listening.

    500 ms cadence (was 200 ms) — fewer React re-renders of the pipeline
    diagram, meaningful CPU savings during demos under screen-share load.
    The simulation clock is still buttery-smooth at ×1 because each push
    advances sim_time by 500 ms, well within human perception.
    """
    while True:
        await asyncio.sleep(0.5)
        if not _sim_state_sse:
            continue
        try:
            snapshot = _compute_sim_state_snapshot()
            payload  = _json.dumps(snapshot)
        except Exception:
            continue
        dead = set()
        for q in _sim_state_sse:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Subscriber can't keep up — drop this frame; next one will follow.
                pass
            except Exception:
                dead.add(q)
        _sim_state_sse.difference_update(dead)


@app.get("/api/simulation/stream")
async def simulation_stream(request: Request):
    """SSE stream carrying consolidated sim status + pipeline state."""
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    _sim_state_sse.add(q)

    # Snapshot the current state immediately so reconnects / fresh subscribers
    # get a full frame without waiting up to 200 ms for the broadcaster tick.
    try:
        initial = _json.dumps(_compute_sim_state_snapshot())
    except Exception:
        initial = None

    async def event_generator():
        try:
            if initial is not None:
                yield f"data: {initial}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            _sim_state_sse.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Historical transactions ───────────────────────────────────────────────────

@app.get("/api/transactions")
def get_transactions(
    seller_name:    str | None = Query(None),
    buyer_country:  str | None = Query(None),
    seller_country: str | None = Query(None),
    date_from:      str | None = Query(None),
    date_to:        str | None = Query(None),
    limit:          int        = Query(200, ge=1, le=1000),
    offset:         int        = Query(0,   ge=0),
):
    rows = query_transactions(
        seller_name=seller_name,
        buyer_country=buyer_country,
        seller_country=seller_country,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    return {"total": len(rows), "items": rows}


# ── Metrics ───────────────────────────────────────────────────────────────────

@app.get("/api/metrics")
def get_metrics(
    seller_name:    str | None = Query(None),
    buyer_country:  str | None = Query(None),
    seller_country: str | None = Query(None),
    date_from:      str | None = Query(None),
    date_to:        str | None = Query(None),
):
    return get_vat_metrics(
        seller_name=seller_name,
        buyer_country=buyer_country,
        seller_country=seller_country,
        date_from=date_from,
        date_to=date_to,
    )


# ── Alarms ────────────────────────────────────────────────────────────────────

@app.get("/api/alarms")
def api_get_alarms(active_only: bool = Query(False)):
    return get_alarms(active_only=active_only)


@app.get("/api/suspicious")
def api_get_suspicious(limit: int = Query(50, ge=1, le=200)):
    return get_suspicious_transactions(limit=limit)


# ── Agent log (historical) ────────────────────────────────────────────────────
#
# Read-only audit log of every VAT Fraud Detection Agent run, populated by
# api_tax_run_agent on the new two-entity flow. The agent itself is now
# triggered exclusively from the Tax officer's C&T Risk Management System page via
# POST /api/tax/{transaction_id}/run-agent.

@app.get("/api/agent-log")
def api_agent_log(limit: int = Query(100, ge=1, le=500)):
    return get_agent_log(limit=limit)


# ── Ireland queue & case detail ───────────────────────────────────────────────

@app.get("/api/ireland-queue")
def api_ireland_queue(limit: int = Query(100, ge=1, le=500)):
    return get_ireland_queue(limit=limit)


@app.get("/api/ireland-case/{transaction_id}")
def api_ireland_case(transaction_id: str):
    case = get_ireland_case(transaction_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})
    return case



# ── Reference data (lookups for dropdowns / categories / regions) ───────────

@app.get("/api/reference")
def api_reference():
    """Bundled reference data consumed by the C&T Risk Management System SPA at startup.

    Returns the four lookup tables seeded in european_custom.db. Static-ish
    data — refresh by re-fetching, no SSE channel.
    """
    from lib.database import (
        get_vat_categories, get_risk_levels, get_eu_regions, get_suspicion_types,
        get_sales_order_statuses, get_case_statuses, get_risk_engine_signals,
    )
    return {
        "vat_categories":        get_vat_categories(),
        "risk_levels":           get_risk_levels(),
        "regions":               get_eu_regions(),
        "suspicion_types":       get_suspicion_types(),
        "sales_order_statuses":  get_sales_order_statuses(),
        "case_statuses":         get_case_statuses(),
        "risk_engine_signals":   get_risk_engine_signals(),
        "risk_thresholds": {
            "release": round(THRESHOLD_RELEASE, 4),
            "retain":  round(THRESHOLD_RETAIN, 4),
        },
    }


# ── C&T Risk Management System: REST + SSE endpoints ──────────────────────────

@app.get("/api/rg/cases")
def api_rg_cases(status: str | None = Query(None), limit: int = Query(200, ge=1, le=1000)):
    """List all cases for C&T Risk Management System, hydrated with Sales_Order +
    Sales_Order_Risk fields. Optionally filter by Status."""
    from lib.database import get_all_cases_hydrated
    return {"items": get_all_cases_hydrated(status=status, limit=limit)}


@app.get("/api/rg/cases/stream")
async def api_rg_cases_stream(request: Request):
    """SSE stream: pushes case events (new_case, case_updated) to C&T Risk Management System."""
    q: asyncio.Queue = asyncio.Queue(maxsize=100)
    _rg_case_sse.add(q)
    async def _gen():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _rg_case_sse.discard(q)
    return StreamingResponse(_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/rg/cases/{case_id}")
def api_rg_case_detail(case_id: str):
    """Single case detail (hydrated with Sales_Order + Sales_Order_Risk)."""
    from lib.database import get_case_hydrated
    case = get_case_hydrated(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})
    return case


async def _publish_investigation_outcome(case_id: str, outcome: str) -> None:
    """Emit the C&T factory's exit event when a case is closed."""
    from lib.database import get_case_hydrated
    case = get_case_hydrated(case_id)
    if not case:
        return
    await broker.publish(INVESTIGATION_OUTCOME, {
        "Case_ID":                  case_id,
        # order_id is used by build_file_payload to derive the filename
        # so each case gets its own persisted event file (not "unknown").
        "order_id":                 case.get("Sales_Order_Business_Key") or case_id,
        "Sales_Order_Business_Key": case.get("Sales_Order_Business_Key"),
        "Sales_Order_ID":           case.get("Sales_Order_ID"),
        "outcome":                  outcome,   # released | retained | refused
        "Proposed_Action_Customs":  case.get("Proposed_Action_Customs"),
        "Proposed_Action_Tax":      case.get("Proposed_Action_Tax"),
        "VAT_Gap_Fee":              case.get("VAT_Gap_Fee"),
        "Recommended_Product_Value":        case.get("Recommended_Product_Value"),
        "Recommended_VAT_Product_Category": case.get("Recommended_VAT_Product_Category"),
        "Recommended_VAT_Rate":             case.get("Recommended_VAT_Rate"),
        "Recommended_VAT_Fee":              case.get("Recommended_VAT_Fee"),
        "closed_by":                case.get("Updated_by"),
        "closed_at":                case.get("Update_time"),
    })


def _emit_case_updated_sse(case_id: str, action: str) -> None:
    """Push the hydrated case to RG SSE subscribers."""
    from lib.database import get_case_hydrated
    case = get_case_hydrated(case_id)
    _push_rg_case_sse({"event": "case_updated", "action": action, "case": case})


@app.get("/api/rg/cases/{case_id}/previous")
def api_rg_previous_cases(case_id: str, limit: int = Query(20, ge=1, le=50)):
    """Past closed cases matching (seller, declared category, destination).

    Slide 1 row 3 of Rules in App.pptx defines a historical case as
    same-seller / same-category / similar-description / same-destination.
    Description similarity is evaluated client-side by the rule engine
    that drives the recommended Customs action."""
    from lib.database import get_case_hydrated, get_previous_cases
    case = get_case_hydrated(case_id)
    if not case:
        return {"items": []}
    return {"items": get_previous_cases(
        seller      = case.get("Seller_Name", ""),
        category    = case.get("HS_Product_Category", ""),
        destination = case.get("Country_Destination", ""),
        exclude_case_id = case_id,
        limit       = limit,
    )}


@app.get("/api/rg/cases/{case_id}/correlated")
def api_rg_correlated_cases(case_id: str, limit: int = Query(20, ge=1, le=50)):
    """Open cases with the same (seller, declared category, destination)
    — tightened correlation key per Rules in App.pptx slide 1."""
    from lib.database import get_case_hydrated, get_correlated_cases
    case = get_case_hydrated(case_id)
    if not case:
        return {"items": []}
    return {"items": get_correlated_cases(
        seller=case.get("Seller_Name", ""),
        category=case.get("HS_Product_Category", ""),
        destination=case.get("Country_Destination", ""),
        exclude_case_id=case_id,
        limit=limit,
    )}


# ── VAT Fraud Detection agent: queue + worker ───────────────────────────────

async def _enqueue_for_agent(case_id: str) -> None:
    """Push a case_id onto the agent queue. No-op if the queue isn't ready."""
    if _agent_queue is None:
        return
    await _agent_queue.put(case_id)
    insert_agent_log({
        "transaction_id": case_id, "seller_name": None,
        "buyer_country": None, "item_description": None,
        "item_category": None, "value": None,
        "vat_rate": None, "correct_vat_rate": None,
        "verdict": "queued", "reasoning": "Case enqueued for AI agent analysis",
        "legislation_refs": "[]", "sent_to_ireland": 0,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    })


def _build_agent_tx(case: dict) -> dict:
    """Shape the case as the tx dict the analyser expects.

    The agent sees a SINGLE synthesized transaction per case — the
    case's primary order (first linked Sales_Order). The analyser
    returns one verdict and one `expected_rate`; _agent_worker then
    extrapolates that rate to every linked order to compute the
    case-level VAT gap.

    This is faithful today because orders inside one case share
    seller, declared category, declared rate, and a similar description
    by construction (find_similar_open_case groups them on those
    fields + Jaccard ≥ 0.4), so one verdict validly covers all orders.

    If that invariant ever weakens (lower Jaccard, manual multi-cluster
    merge, …), move to a batched invoice — see BACKLOG.md entry
    "Per-order VAT Fraud Detection agent verdicts (batched invoice)".
    """
    return {
        "transaction_id":   case.get("Sales_Order_ID") or case.get("Sales_Order_Business_Key"),
        "seller_name":      case.get("Seller_Name"),
        "seller_country":   case.get("Country_Origin"),
        "buyer_country":    case.get("Country_Destination"),
        "item_description": case.get("Product_Description"),
        "item_category":    case.get("HS_Product_Category"),
        "value":            case.get("Product_Value"),
        "vat_rate":         case.get("VAT_Rate"),
        "vat_amount":       case.get("VAT_Fee"),
    }


async def _agent_worker() -> None:
    """Single consumer of the agent queue. Country-of-destination gate:
    IE → real subprocess analyser; everything else → 5 s sleep + uncertain.
    On completion: write AI_Analysis, flip Status to "Under Review by Tax",
    append a Communication entry, and broadcast case_updated SSE.
    """
    global _agent_in_progress
    from lib.database import get_case_hydrated, update_case
    from lib.agent_bridge import analyse_transaction_sync
    from lib.llm_client import acquire_slot

    assert _agent_queue is not None
    while True:
        case_id = await _agent_queue.get()
        _agent_in_progress = case_id
        try:
            case = get_case_hydrated(case_id)
            if not case:
                continue

            tx = _build_agent_tx(case)
            insert_agent_log({
                "transaction_id": case_id,
                "seller_name": tx.get("seller_name"),
                "buyer_country": tx.get("buyer_country"),
                "item_description": tx.get("item_description"),
                "item_category": tx.get("item_category"),
                "value": tx.get("value"),
                "vat_rate": tx.get("vat_rate"),
                "correct_vat_rate": None,
                "verdict": "processing",
                "reasoning": f"Agent started analysing case {case_id}",
                "legislation_refs": "[]", "sent_to_ireland": 0,
                "processed_at": datetime.now(timezone.utc).isoformat(),
            })

            destination = (case.get("Country_Destination") or "").upper()
            if destination == "IE":
                tx = _build_agent_tx(case)
                async with acquire_slot():
                    result = await asyncio.to_thread(analyse_transaction_sync, tx)
            else:
                await asyncio.sleep(5)
                result = {
                    "verdict":   "uncertain",
                    "reasoning": f"Model for country '{destination or 'unknown'}' failed to run.",
                    "success":   False,
                }

            verdict   = result.get("verdict", "uncertain")
            reasoning = result.get("reasoning", "")
            now_iso   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

            # The analyser reports the VAT rate it believes should have
            # applied (per-line `expected_rate`). Today the agent sees
            # one synthetic line per case (see _build_agent_tx), so we
            # take the first verdict and apply its expected_rate to
            # every linked order on the case to derive a case-level
            # VAT gap: sum over orders of value × (expected − declared).
            #
            # Consequence: the `uncertain` verdict is case-wide. If the
            # primary order's verdict is uncertain, no gap is recorded
            # even when other orders might have yielded definitive
            # verdicts individually. That's acceptable as long as orders
            # in a case are homogeneous by construction (same seller,
            # category, declared rate) — which the C&T factory enforces
            # via find_similar_open_case. The full per-order evaluation
            # path is logged in BACKLOG.md under "Per-order VAT Fraud
            # Detection agent verdicts (batched invoice)".
            expected_rate: float | None = None
            line_verdicts = result.get("line_verdicts") or []
            # Only trust the analyser's rate when its verdict is
            # definitive. An `uncertain` top-level verdict means the
            # agent could not reach a confident conclusion — we leave
            # VAT_Gap_Fee as NULL rather than persist a tentative gap
            # the officer would read as authoritative.
            if verdict != "uncertain" and line_verdicts:
                er = line_verdicts[0].get("expected_rate")
                try:
                    expected_rate = float(er) if er is not None else None
                except (TypeError, ValueError):
                    expected_rate = None

            case_vat_gap: float | None = None
            if expected_rate is not None:
                from lib.database import get_case_orders
                orders = get_case_orders(case_id) or []
                total_gap = 0.0
                for o in orders:
                    value        = float(o.get("Product_Value") or 0.0)
                    declared_vat = float(o.get("VAT_Fee") or 0.0)
                    expected_vat = value * expected_rate
                    total_gap   += expected_vat - declared_vat
                case_vat_gap = round(total_gap, 2)

            comm = case.get("Communication", []) or []
            comm.append({
                "date":    now_iso,
                "from":    "VAT Fraud Detection Agent",
                "action":  f"verdict: {verdict}",
                "message": reasoning,
            })
            # Legislation refs surface in the Tax VAT Assessment panel,
            # so they are persisted on the case (JSON-serialised) rather
            # than kept only in the agent_log audit table.
            legislation_refs_raw = result.get("legislation_refs") if isinstance(result, dict) else None
            legislation_refs_json = (_json.dumps(legislation_refs_raw)
                                     if isinstance(legislation_refs_raw, list)
                                     else None)

            case_updates: dict = {
                "Status":        STATUS.UNDER_REVIEW_BY_TAX,
                "AI_Analysis":   f"[{verdict}] {reasoning}",
                "Update_time":   now_iso,
                "Updated_by":    "VAT Fraud Detection Agent",
                "Communication": comm,
            }
            if legislation_refs_json is not None:
                case_updates["AI_Legislation_Refs"] = legislation_refs_json
            if expected_rate is not None:
                case_updates["Recommended_VAT_Rate"] = expected_rate
                case_updates["VAT_Gap_Fee"]          = case_vat_gap
            update_case(case_id, case_updates)
            _emit_case_updated_sse(case_id, "ai_complete")
            insert_agent_log({
                "transaction_id": case_id,
                "seller_name": tx.get("seller_name"),
                "buyer_country": tx.get("buyer_country"),
                "item_description": tx.get("item_description"),
                "item_category": tx.get("item_category"),
                "value": tx.get("value"),
                "vat_rate": tx.get("vat_rate"),
                "correct_vat_rate": expected_rate,
                "verdict": verdict,
                "reasoning": reasoning,
                "legislation_refs": _json.dumps(result.get("legislation_refs", [])) if isinstance(result, dict) else "[]",
                "sent_to_ireland": 1 if verdict == "incorrect" or verdict == "suspicious" else 0,
                "processed_at": now_iso,
            })
        except Exception as e:
            # Don't crash the worker on a single bad case
            try:
                from lib.database import update_case
                now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
                update_case(case_id, {
                    "Status":      STATUS.UNDER_REVIEW_BY_TAX,
                    "AI_Analysis": f"[uncertain] Agent worker error: {e}",
                    "Update_time": now_iso,
                    "Updated_by":  "VAT Fraud Detection Agent",
                })
                _emit_case_updated_sse(case_id, "ai_complete")
            except Exception:
                pass
        finally:
            _agent_in_progress = None
            _agent_queue.task_done()


# Role → allowed action proposals emitted by the agentic chat.
# The LLM is instructed to use these exact backend ids. The frontend
# applies them via the existing /customs-action and /tax-action
# endpoints, so no new write path is introduced here — the chat is a
# thin proposal layer on top of what officers can already click.
_AGENTIC_TAX_ACTIONS = {
    "risk_confirmed":   "Confirm Risk (case returns to Customs with tax verdict)",
    "no_limited_risk":  "No/Limited Risk (case returns to Customs with tax verdict)",
    "input_requested":  "Request Input from Third Party",
}
_AGENTIC_CUSTOMS_ACTIONS = {
    "retainment":       "Recommend Retainment (closes case)",
    "release":          "Recommend Release (closes case)",
    "tax_review":       "Submit for Tax Review (triggers VAT Fraud Detection agent)",
    "input_requested":  "Request Input from Third Party",
}


def _parse_agent_proposal(raw: str, allowed: dict) -> tuple[str, dict | None]:
    """Split an LLM response into (visible_text, proposal_dict_or_none).

    The LLM is instructed to emit a fenced block like

        <<PROPOSE>>
        {"action": "risk_confirmed", "comment": "..."}
        <<END>>

    when it wants the officer to apply an action. We strip the fence
    from the text shown to the user and return the parsed proposal
    separately so the frontend can render an Apply/Cancel card. If the
    fence is missing or malformed, or the action isn't in *allowed*,
    the proposal is dropped and the raw text is returned unchanged.
    """
    import re, json as _json
    m = re.search(r"<<PROPOSE>>\s*(\{.*?\})\s*<<END>>", raw, flags=re.DOTALL)
    if not m:
        return raw.strip(), None
    try:
        data = _json.loads(m.group(1))
    except Exception:
        return raw.strip(), None
    action = data.get("action")
    comment = (data.get("comment") or "").strip()
    if not isinstance(action, str) or action not in allowed:
        return raw.strip(), None
    cleaned = (raw[:m.start()] + raw[m.end():]).strip()
    return cleaned, {"action": action, "comment": comment}


@app.post("/api/rg/cases/{case_id}/ask")
async def api_rg_case_ask(case_id: str, body: dict):
    """AI assistant: answer a question about a case using LM Studio.

    Returns ``{"answer": str, "proposal": {action, comment}|None}``.
    The proposal is optional — set when the LLM is confident the
    officer just asked to apply an action. The frontend renders it as
    an Apply/Cancel card and fires the existing customs/tax-action
    endpoint on Apply. No write happens server-side in this endpoint.
    """
    from lib.database import get_case_hydrated, get_case_orders
    from lib.llm_client import LMStudioClient, PRIORITY_INTERACTIVE

    case = get_case_hydrated(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})

    question = body.get("question", "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"detail": "No question provided"})

    orders = get_case_orders(case_id)
    order_lines = "\n".join(
        f"  - {o.get('Product_Description','?')} | €{o.get('Product_Value',0)} | "
        f"VAT {(o.get('VAT_Rate',0) or 0)*100:.0f}% | "
        f"{o.get('Country_Origin','?')} → {o.get('Country_Destination','?')}"
        for o in orders
    )
    engine_info = (
        f"Engine scores: VAT Ratio={case.get('Engine_VAT_Ratio',0):.2f}, "
        f"ML Watchlist={case.get('Engine_ML_Watchlist',0):.2f}, "
        f"IE Seller={case.get('Engine_IE_Seller_Watchlist',0):.2f}, "
        f"Vagueness={case.get('Engine_Description_Vagueness',0):.2f}"
    )
    ai_analysis = case.get("AI_Analysis") or "No AI analysis performed yet."
    comm = case.get("Communication", []) or []
    comm_text = "\n".join(
        f"  [{c.get('date','')}] {c.get('from','')}: {c.get('action','')} — {c.get('message','')}"
        for c in comm[-10:]
    ) if comm else "No communication log entries."

    role = body.get("role", "customs")

    case_context = f"""CASE: {case_id}
Status: {case.get('Status')}
Seller: {case.get('Seller_Name')} ({case.get('Country_Origin')})
Destination: {case.get('Country_Destination')}
Category: {case.get('HS_Product_Category')}
Overall Risk Score: {case.get('Overall_Case_Risk_Score',0):.2f} ({case.get('Overall_Case_Risk_Level','?')})
{engine_info}
VAT Problem Type: {case.get('VAT_Problem_Type','None')}

Orders ({len(orders)}):
{order_lines}

AI VAT Fraud Detection Analysis: {ai_analysis}

Communication log:
{comm_text}"""

    allowed_actions = _AGENTIC_TAX_ACTIONS if role == "tax" else _AGENTIC_CUSTOMS_ACTIONS
    actions_block = "\n".join(f'  - "{k}": {v}' for k, v in allowed_actions.items())

    # Tool-calling contract — the LLM is told to emit a JSON fence ONLY
    # when the officer has explicitly asked to apply/submit/execute an
    # action. A card appears in the UI for the officer to confirm; no
    # write happens until they press Apply.
    agentic_block = f"""
You can propose an action for the officer to apply. Only propose when the
officer's latest message is an explicit instruction to act (e.g. "proceed",
"apply the recommendation", "submit", "go ahead", "do it"). Do NOT propose
on general Q&A.

Allowed actions for this role:
{actions_block}

When you want to propose an action, include in your reply — at the END
of the message, after your explanation — a single JSON block wrapped in
the exact fences shown below, with no additional text around it:

<<PROPOSE>>
{{"action": "<one of the ids above>", "comment": "<short note to attach>"}}
<<END>>

The comment should be a concise 1–2 sentence summary justifying the
action, suitable to post in the case activity log.

Before the fence, write a plain-English sentence telling the officer
what you are about to apply and ask them to confirm by clicking Apply.
If the officer is just asking questions, answer normally and do NOT
emit the fence.
"""

    if role == "tax":
        system_prompt = f"""You are a Tax Authority AI assistant specialised in VAT compliance and tax fraud detection.
You work for the Irish Revenue Commissioners. Your expertise includes:
- EU VAT Directive (2006/112/EC) and its application to e-commerce
- Irish VAT rates (standard 23%, reduced 13.5%/9%, zero-rated, exempt categories)
- VAT MOSS/IOSS schemes for cross-border B2C e-commerce
- Common VAT fraud patterns: misclassification, undervaluation, carousel fraud
- Transfer pricing and arm's-length principles

When answering, focus on tax implications, applicable VAT rates, potential revenue loss,
and whether the declared VAT treatment is consistent with the product category and EU legislation.
Cite relevant VAT rules when possible. Be precise and analytical.

Answer based ONLY on the case data below. If the data doesn't contain the answer, say so.
{agentic_block}

{case_context}"""
    else:
        system_prompt = f"""You are a Customs Authority AI assistant specialised in border control and risk management.
You work for the Irish Customs service. Your expertise includes:
- EU customs regulations (Union Customs Code - UCC)
- Risk profiling of shipments and sellers
- Product classification (HS codes, Combined Nomenclature)
- Country-of-origin risk assessment
- Detection of smuggling, counterfeiting, and misdeclaration patterns
- Customs procedures: release, retention, investigation escalation

When answering, focus on whether goods should be released or retained, the risk profile
of the seller and route, whether the product description matches the declared category,
and any red flags for customs enforcement. Be direct and action-oriented.

Answer based ONLY on the case data below. If the data doesn't contain the answer, say so.
{agentic_block}

{case_context}"""

    # Merge system prompt into the user turn — Mistral-family prompt
    # templates loaded in LM Studio reject the separate "system" role
    # ("Only user and assistant roles are supported!"). Prepending the
    # instructions to the user message works with every chat template
    # we ship with.
    user_turn = (
        f"{system_prompt}\n\n"
        f"-----\n"
        f"Officer question: {question}"
    )

    try:
        client = LMStudioClient()
        raw_answer = await client.chat([
            {"role": "user", "content": user_turn},
        ], temperature=0.3, max_tokens=500, priority=PRIORITY_INTERACTIVE)
        await client.aclose()
        answer, proposal = _parse_agent_proposal(raw_answer, allowed_actions)
        return {"answer": answer, "proposal": proposal}
    except Exception as e:
        return {"answer": f"Unable to reach AI assistant: {e}", "proposal": None}


@app.get("/api/rg/agent/queue")
def api_rg_agent_queue():
    """Live queue depth + current case under analysis. UI feedback only."""
    depth = _agent_queue.qsize() if _agent_queue is not None else 0
    return {"depth": depth, "in_progress": _agent_in_progress}


@app.post("/api/rg/cases/{case_id}/customs-action")
async def api_rg_customs_action(case_id: str, body: dict):
    """
    Customs officer action on a case.
    body: {action: "tax_review"|"retainment"|"release"|"input_requested",
           comment?: str, officer?: str, risk_breakdown?: dict}
    """
    import json as _json
    from lib.database import get_case_by_id, update_case

    case = get_case_by_id(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})

    action = body.get("action", "")
    comment = body.get("comment", "")
    officer = body.get("officer", "Customs Officer")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    status_map = {
        # tax_review goes through the AI agent first; the worker will flip
        # status to UNDER_REVIEW_BY_TAX once it has produced a verdict.
        "tax_review":       STATUS.AI_INVESTIGATING,
        "retainment":       STATUS.CLOSED,
        "release":          STATUS.CLOSED,
        "refused":          STATUS.CLOSED,     # officer refuses Tax recommendation
        "input_requested":  STATUS.REQUESTED_INPUT,
    }
    new_status = status_map.get(action)
    if not new_status:
        return JSONResponse(status_code=400, content={"detail": f"Unknown action: {action}"})

    # Build updates
    updates: dict = {
        "Status":     new_status,
        "Update_time": now_iso,
        "Updated_by":  officer,
    }
    if action in ("retainment", "release", "refused"):
        action_map = {"retainment": "retain", "release": "release", "refused": "refuse"}
        updates["Proposed_Action_Customs"] = action_map[action]
        from lib.database import update_sales_order_status
        from lib import sales_order_statuses as SO_STATUS
        bk = case.get("Sales_Order_Business_Key")
        if bk:
            so_status = SO_STATUS.TO_BE_RELEASED if action == "release" else SO_STATUS.TO_BE_RETAINED
            update_sales_order_status(bk, so_status)

    # Append to communication log
    comm = case.get("Communication", [])
    if not isinstance(comm, list):
        comm = []
    comm.append({"date": now_iso, "from": "Customs Authority", "action": action, "message": comment})
    updates["Communication"] = comm

    update_case(case_id, updates)

    _emit_case_updated_sse(case_id, action)
    if action in ("retainment", "release", "refused"):
        outcome_map = {"retainment": "retained", "release": "released", "refused": "refused"}
        await _publish_investigation_outcome(case_id, outcome_map[action])
    if action == "tax_review":
        insert_agent_log({
            "transaction_id": case_id, "seller_name": case.get("Seller_Name"),
            "buyer_country": case.get("Country_Destination"),
            "item_description": case.get("Product_Description"),
            "item_category": case.get("HS_Product_Category"),
            "value": case.get("Product_Value"), "vat_rate": case.get("VAT_Rate"),
            "correct_vat_rate": None,
            "verdict": "sent_to_tax",
            "reasoning": f"Case {case_id} submitted for tax review by {officer}",
            "legislation_refs": "[]", "sent_to_ireland": 0,
            "processed_at": now_iso,
        })
        await _enqueue_for_agent(case_id)
    return {"ok": True}


@app.post("/api/rg/cases/{case_id}/tax-action")
def api_rg_tax_action(case_id: str, body: dict):
    """
    Tax officer action on a case.
    body: {action: "risk_confirmed"|"no_limited_risk"|"input_requested",
           comment?: str, officer?: str, vat_category?: str}
    """
    import json as _json
    from lib.database import get_case_by_id, update_case

    case = get_case_by_id(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})

    action = body.get("action", "")
    comment = body.get("comment", "")
    officer = body.get("officer", "Tax Officer")
    vat_category = body.get("vat_category")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    if action not in ("risk_confirmed", "no_limited_risk", "input_requested"):
        return JSONResponse(status_code=400, content={"detail": f"Unknown action: {action}"})

    updates: dict = {
        "Proposed_Action_Tax": action,
        "Update_time": now_iso,
        "Updated_by": officer,
    }
    if vat_category:
        updates["Recommended_VAT_Product_Category"] = vat_category

    # Propagate status back for customs visibility
    if action == "risk_confirmed":
        updates["Status"] = STATUS.UNDER_REVIEW_BY_CUSTOMS
    elif action == "no_limited_risk":
        updates["Status"] = STATUS.UNDER_REVIEW_BY_CUSTOMS
    elif action == "input_requested":
        updates["Status"] = STATUS.REQUESTED_INPUT

    comm = case.get("Communication", [])
    if not isinstance(comm, list):
        comm = []
    comm.append({"date": now_iso, "from": "Tax Authority", "action": action, "message": comment})
    updates["Communication"] = comm

    update_case(case_id, updates)

    _emit_case_updated_sse(case_id, action)
    return {"ok": True}


@app.post("/api/rg/cases/{case_id}/communication")
def api_rg_add_communication(case_id: str, body: dict):
    """
    Add a communication entry to a case.
    body: {from: str, action: str, message: str}
    """
    from lib.database import get_case_by_id, update_case

    case = get_case_by_id(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    comm = case.get("Communication", [])
    if not isinstance(comm, list):
        comm = []
    comm.append({
        "date": now_iso,
        "from": body.get("from", "System"),
        "action": body.get("action", ""),
        "message": body.get("message", ""),
    })

    update_case(case_id, {"Communication": comm, "Update_time": now_iso})

    _emit_case_updated_sse(case_id, "communication")
    return {"ok": True}


@app.get("/api/rg/cases/{case_id}/communication")
def api_rg_get_communication(case_id: str):
    """Get communication log for a case."""
    from lib.database import get_case_by_id
    case = get_case_by_id(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})
    return case.get("Communication", [])


# ── Simulation control ────────────────────────────────────────────────────────

@app.get("/api/simulation/pipeline")
def sim_pipeline():
    """Return per-topic event counts (persisted files) and live broker queue sizes."""
    from lib.event_store import event_count, count_field_value
    from lib.broker import broker as _broker
    topics = [
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_RISK_3_OUTCOME, RT_RISK_4_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
        CUSTOM_OUTCOME,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    ]
    # Show queue depths only when simulation has fired events; otherwise
    # report 0 so stale factory-internal buffers don't confuse the UI.
    show_queues = state.fired_count > 0 or state.running
    queues = {t: (_broker.qsize(t) if show_queues else 0) for t in topics}
    return {
        "events":             {t: event_count(t) for t in topics},
        "queues":             queues,
        "stored_count":       get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "outcome.flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "outcome.flagged", True),
            "rt_risk_3_flagged": count_field_value(RT_RISK_3_OUTCOME, "outcome.flagged", True),
            "rt_risk_4_flagged": count_field_value(RT_RISK_4_OUTCOME, "outcome.flagged", True),
            "rt_score_green":    count_field_value(RT_SCORE, "outcome.risk_score", "green"),
            "rt_score_amber":    count_field_value(RT_SCORE, "outcome.risk_score", "amber"),
            "rt_score_red":      count_field_value(RT_SCORE, "outcome.risk_score", "red"),
        },
        "custom_outcome_status": {
            "automated_release": count_field_value(CUSTOM_OUTCOME, "outcome.status", "automated_release"),
            "automated_retain":  count_field_value(CUSTOM_OUTCOME, "outcome.status", "automated_retain"),
            "custom_release":    count_field_value(CUSTOM_OUTCOME, "outcome.status", "custom_release"),
            "custom_retain":     count_field_value(CUSTOM_OUTCOME, "outcome.status", "custom_retain"),
        },
    }


@app.get("/api/simulation/status")
def sim_status():
    counts = get_sim_counts()
    s = state.to_dict()
    s.update(counts)
    s["active_alarms"] = len(get_alarms(active_only=True))
    return s


@app.post("/api/simulation/start")
def sim_start():
    from lib.config import SIM_END_DT
    from lib.event_store import flush_events
    from lib.alarm_checker import bootstrap_scenario_alarm
    from lib.database import seed_open_cases_if_empty, get_all_cases_hydrated
    if state.sim_time >= SIM_END_DT:
        return {"ok": False, "reason": "simulation already finished — reset first"}
    seeded = 0
    # Flush persisted events and bootstrap alarm on first launch (fired_count == 0).
    # Pause → resume does not flush (fired_count > 0 at that point).
    if state.fired_count == 0:
        flush_events()
        bootstrap_scenario_alarm()
        # Pre-load open cases from the persisted seed DB so officers
        # have something to triage from t=0. No-op if cases are already
        # present (e.g. resume after pause without reset).
        seeded = seed_open_cases_if_empty()
        if seeded:
            # Push each seeded case as a new_case event so the frontend
            # caseStore upserts them without needing a full re-fetch.
            for case in get_all_cases_hydrated(limit=seeded):
                _push_rg_case_sse({"event": "new_case", "case": case})
    state.running = True
    return {"ok": True, "status": state.to_dict(), "seeded_cases": seeded}


@app.post("/api/simulation/pause")
def sim_pause():
    state.running = False
    return {"ok": True, "status": state.to_dict()}


@app.post("/api/simulation/resume")
def sim_resume():
    state.running = True
    return {"ok": True, "status": state.to_dict()}


class SpeedPayload(BaseModel):
    speed: float


@app.post("/api/simulation/speed")
def sim_speed(payload: SpeedPayload):
    state.speed = max(MIN_SPEED, min(MAX_SPEED, payload.speed))
    return {"ok": True, "speed": state.speed}


@app.post("/api/simulation/reset")
async def sim_reset():
    from lib.event_store import flush_events
    from lib.seeder import seed_european_custom_db
    from lib.alarm_checker import bootstrap_scenario_alarm
    from lib.broker import broker as _b

    # 1) Freeze the sim clock and cancel any still-sleeping factory tasks
    #    (Order Validation, Arrival Notification, manual agent runs). They
    #    cancel cleanly from `asyncio.sleep(...)`; anything mid-publish
    #    completes that single call.
    state.reset()
    for t in list(_inflight_factory_tasks):
        if not t.done():
            t.cancel()
    _inflight_factory_tasks.clear()

    # 2) Wait for the pipeline to settle before flushing the events dir.
    #    A subscriber coroutine may already hold a dequeued message and be
    #    about to publish downstream, which re-fills another queue AND
    #    writes an event file (write_event() runs synchronously at the
    #    start of broker.publish()). So loop: drain subscriber queues,
    #    yield the event loop so in-flight coroutines can run, and stop
    #    only when drain returns 0 for several consecutive iterations —
    #    i.e. nothing is flowing anymore. Hard cap of 2 s keeps reset
    #    responsive even if something's stuck.
    total_drained = 0
    idle_streak = 0
    for _ in range(40):
        drained = _b.drain_all()
        total_drained += drained
        await asyncio.sleep(0.05)
        idle_streak = idle_streak + 1 if drained == 0 else 0
        if idle_streak >= 3:
            break
    if total_drained:
        print(f"  [reset] drained {total_drained} stale messages from broker queues")

    reset_simulation_db()
    reset_alarms()          # removes March+ rows, keeps Sep–Feb history
    from lib.database import reset_cases
    reset_cases()           # clear investigation cases
    _push_rg_case_sse({"event": "cases_reset"})  # notify C&T Risk Management System clients

    # 4) Flush the events directory last — everything upstream is now
    #    quiesced and cannot race against the rmtree.
    flush_events()

    # Re-seed historical data if it was wiped (e.g. first run or manual DB delete)
    if historical_transaction_count() == 0:
        seed_european_custom_db()
    bootstrap_scenario_alarm()   # pre-seed SUP001→IE alarm from day 1
    _live_queue.clear()
    _live_alarms.clear()

    # 5) Drain each sim-state SSE queue and push a fresh snapshot so a
    #    frame the broadcaster queued just before the reset cannot arrive
    #    at the client *after* the reset and re-populate the pipeline UI.
    try:
        fresh_snapshot = _json.dumps(_compute_sim_state_snapshot())
    except Exception:
        fresh_snapshot = None
    for sq in list(_sim_state_sse):
        while not sq.empty():
            try:
                sq.get_nowait()
            except asyncio.QueueEmpty:
                break
        if fresh_snapshot is not None:
            try:
                sq.put_nowait(fresh_snapshot)
            except asyncio.QueueFull:
                pass

    for sse_q in list(_sse_queues):
        try:
            sse_q.put_nowait("__reset__")
        except asyncio.QueueFull:
            pass
    _push_rg_case_sse({"event": "reset"})

    # 6) Background sweep: if the reset fires mid-pipeline (tight race where
    #    tail-end transactions from a just-finished sim are still being
    #    processed), a few event files may land on disk after the primary
    #    flush_events() above. Drain + flush again over the next ~4 s to
    #    mop them up and push a refreshed snapshot to SSE clients.
    #
    #    CRITICAL: bail out the moment a new sim has started — otherwise
    #    the sweep would wipe the new sim's in-flight events and produce
    #    the 73/2026 fired-tx corruption the demo hit. state.running flips
    #    to True on /start, and state.fired_count becomes >0 once any
    #    event fires, so either signal terminates the sweep.
    async def _followup_flush():
        for _ in range(4):
            await asyncio.sleep(1.0)
            if state.running or state.fired_count > 0:
                return
            _b.drain_all()
            flush_events()
        try:
            snap = _json.dumps(_compute_sim_state_snapshot())
        except Exception:
            return
        for sq in list(_sim_state_sse):
            while not sq.empty():
                try:
                    sq.get_nowait()
                except asyncio.QueueEmpty:
                    break
            try:
                sq.put_nowait(snap)
            except asyncio.QueueFull:
                pass
    asyncio.create_task(_followup_flush())

    return {"ok": True, "status": state.to_dict()}


# ── Catalog ───────────────────────────────────────────────────────────────────

@app.get("/api/catalog/suppliers")
def catalog_suppliers():
    return [{"id": s["id"], "name": s["name"], "country": s["country"]}
            for s in SUPPLIERS]


@app.get("/api/catalog/countries")
def catalog_countries():
    return [{"code": k, "name": v} for k, v in COUNTRY_NAMES.items()]


# ── Ireland app static files ──────────────────────────────────────────────────

_ireland_app_dir = Path(__file__).parent / "ireland_app"
if _ireland_app_dir.exists():
    app.mount("/ireland-app", StaticFiles(directory=str(_ireland_app_dir), html=True),
              name="ireland_app")


@app.get("/api/debug/queues")
def debug_queues():
    from lib.broker import broker as _b
    result = {}
    for topic, queues in _b._queues.items():
        if queues:
            result[topic] = [q.qsize() for q in queues]
    return result


# ── Main frontend (must be absolutely last) ───────────────────────────────────
# Serves the Vite build.  Static assets (JS/CSS) are served directly;
# all other GET requests fall back to index.html for client-side routing.

_frontend_dist = Path(__file__).parent / "frontend" / "dist"

if _frontend_dist.exists():
    from fastapi.responses import FileResponse as _FileResponse

    app.mount("/assets", StaticFiles(directory=str(_frontend_dist / "assets")),
              name="frontend_assets")

    @app.get("/{full_path:path}")
    async def _spa_fallback(full_path: str):
        candidate = _frontend_dist / full_path
        if candidate.is_file():
            return _FileResponse(str(candidate))
        return _FileResponse(str(_frontend_dist / "index.html"))

