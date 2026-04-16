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

The Customs Officer console (Revenue Guardian /customs page) is master:
its release/retain decision is the terminal event. The Tax Officer console
(Revenue Guardian /tax page) only issues a recommendation that the Customs
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
    RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_RISK_3_OUTCOME, RT_SCORE,  # legacy counters
    RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,   # legacy counters
)

# Total number of risk monitoring engines. The release factory waits
# for this many outcomes (or times out) before computing the score.
# Adding a new risk engine = increment this + write the factory.
TOTAL_RISK_ENGINES = 3
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
_rg_case_sse:         set[asyncio.Queue] = set()   # Revenue Guardian case stream subscribers

# ── VAT Fraud Detection agent queue ─────────────────────────────────────────
# Single asyncio queue + single worker. LM Studio serializes inference
# internally; running >1 worker would just stack up locally with no gain.
AGENT_WORKERS         = 1
_agent_queue:         asyncio.Queue[str] | None = None  # case_ids awaiting AI analysis
_agent_in_progress:   str | None = None                  # case_id currently processing

from lib import case_statuses as STATUS


def _push_rg_case_sse(payload: dict) -> None:
    """Push a case event to all connected Revenue Guardian SSE clients."""
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
# own listener, queue, SSE subscribers and UI page on the revenue-guardian UI.
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
# (Revenue Guardian queues + SSE sets removed)

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


# ── RT Risk Monitoring 1 Factory (VAT ratio deviation) ───────────────────────

async def _RT_risk_monitoring_1_factory() -> None:
    """
    Subscriber of Sales-order Event Broker.
    Runs the VAT/value ratio deviation check (7-day vs 8-week baseline).
    Publishes to the unified RT_RISK_OUTCOME topic with engine="vat_ratio".
    """
    from lib.alarm_checker import check_alarm

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        result = check_alarm(tx)   # None | {"suspicious", "alarm_id", "new_alarm"}

        flagged   = bool(result and result.get("suspicious"))
        alarm_id  = result.get("alarm_id")  if result else None
        new_alarm = result.get("new_alarm") if result else None

        if new_alarm:
            _live_alarms.insert(0, new_alarm)

        expire_old_alarms(tx["transaction_date"][:19])

        await broker.publish(RT_RISK_OUTCOME, {
            "engine":   "vat_ratio",
            "tx":       tx,
            "flagged":  flagged,
            "alarm_id": alarm_id,
            "alarm":    new_alarm or next(
                (a for a in _live_alarms if a.get("id") == alarm_id), {}
            ) if flagged else None,
        })
        # Legacy counter
        await broker.publish(RT_RISK_1_OUTCOME, {"tx": tx, "flagged": flagged})


# ── RT Risk Monitoring 2 Factory (watchlist check) ───────────────────────────

async def _RT_risk_monitoring_2_factory() -> None:
    """
    Subscriber of Sales-order Event Broker.
    Checks whether the (seller_id, seller_country) pair — supplier × country
    of origin — appears in the configured watchlist (lib/watchlist.py).
    Publishes to the unified RT_RISK_OUTCOME topic with engine="watchlist".
    """
    from lib.watchlist import is_watchlisted

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        flagged = is_watchlisted(tx["seller_id"], tx["seller_country"])

        await broker.publish(RT_RISK_OUTCOME, {
            "engine":  "watchlist",
            "tx":      tx,
            "flagged": flagged,
            "reason":  "watchlist_match" if flagged else "clear",
        })
        # Legacy counter
        await broker.publish(RT_RISK_2_OUTCOME, {"tx": tx, "flagged": flagged})


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
            continue   # not applicable — third-party server is not invoked

        async def _process(tx=tx):
            # Run each IE evaluation in its own task so a slow remote
            # response doesn't block the next event.
            await asyncio.sleep(_random.uniform(1.0, 5.0))
            seller_id      = tx.get("seller_id", "")
            seller_country = (tx.get("seller_country") or "").upper()
            flagged = (seller_id, seller_country) in IE_WATCHLIST
            await broker.publish(RT_RISK_OUTCOME, {
                "engine":  "ireland_watchlist",
                "tx":      tx,
                "flagged": flagged,
                "reason":  "ie_watchlist_match" if flagged else "clear",
            })
            # Legacy counter
            await broker.publish(RT_RISK_3_OUTCOME, {"tx": tx, "flagged": flagged})

        # Fire-and-forget so the engine can pick up the next event immediately.
        asyncio.create_task(_process())


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
#   - risk_score  = flagged_count / total_outcomes (50% if no outcomes)
#   - confidence  = outcomes_received / TOTAL_RISK_ENGINES (0%, 50%, 100%)
#   - route:  score < 33.33% → release
#             33.33% ≤ score ≤ 66.66% → investigate
#             score > 66.66% → retain
#
# GREEN path (release) additionally requires validation + arrival notification.
# RED path (retain) fires immediately once the score exceeds 66.66%.
# AMBER path (investigate) requires validation before dispatch.

THRESHOLD_RELEASE    = 1.0 / 3.0   # < 33.33% → release
THRESHOLD_RETAIN     = 2.0 / 3.0   # > 66.66% → retain
ASSESSMENT_TIMER_S   = 3.0         # seconds after validation before forced publish

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
        """Return (score, confidence, route)."""
        outcomes = entry["risk_outcomes"]
        n_received = len(outcomes)
        confidence = n_received / TOTAL_RISK_ENGINES if TOTAL_RISK_ENGINES > 0 else 0

        if n_received == 0:
            score = 0.5   # no outcomes → 50% (uncertain)
        else:
            flagged = sum(1 for o in outcomes.values() if o.get("flagged"))
            score = flagged / n_received

        if score > THRESHOLD_RETAIN:
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

        # Collect alarm info
        alarm_id = None
        alarm = None
        for o in outcomes.values():
            if o.get("alarm_id"):
                alarm_id = o["alarm_id"]
                alarm = o.get("alarm")
                break

        # Get tx data
        tx = None
        for o in outcomes.values():
            tx = o.get("tx")
            if tx:
                break
        if tx is None and entry["validation"]:
            tx = entry["validation"]["tx"]
        if tx is None:
            _buffer.pop(tx_id, None)
            return

        val = entry["validation"]
        import uuid
        now_iso = datetime.now(timezone.utc).isoformat()

        # Uniformized field names matching the data model
        so_bk = f"{tx['transaction_id']}-001"  # business key
        risk_id = f"RISK-{uuid.uuid4().hex[:12].upper()}"

        risk_payload = {
            # Data model fields
            "Sales_Order_Risk_ID":         risk_id,
            "Sales_Order_Business_Key":    so_bk,
            "Sales_Order_ID":              tx["transaction_id"],
            "Risk_Type":                   "VAT",
            "Overall_Risk_Score":          round(score * 100, 1),
            "Overall_Risk_Level":          route,
            "Confidence_Score":            round(confidence, 2),
            "Proposed_Risk_Action":        {"red": "retain", "amber": "investigate", "green": "release"}[route],
            # Dimensional scores (populated where available, None otherwise)
            "Seller_Risk_Score":           None,
            "Country_Risk_Score":          None,
            "Product_Category_Risk_Score": None,
            "Manufacturer_Risk_Score":     None,
            "Overall_Risk_Description":    None,
            "Risk_Comment":                None,
            "Evaluation_by":               None,
            "Update_time":                 now_iso,
            "Updated_by":                  None,
            # Internal fields for downstream processing
            "engines":      {eng: o.get("flagged", False)
                             for eng, o in outcomes.items()},
            "alarm_id":     alarm_id,
            "alarm":        alarm,
            # Legacy fields
            "risk_score":   score,
            "risk_route":   route,
            "confidence":   round(confidence, 2),
        }

        # Legacy RT_SCORE event for pipeline counter compatibility
        await broker.publish(RT_SCORE, {
            "tx": tx,
            "risk_score": route,
            "risk_1_flagged": outcomes.get("vat_ratio", {}).get("flagged", False),
            "risk_2_flagged": outcomes.get("watchlist", {}).get("flagged", False),
            "alarm_id": alarm_id,
            "alarm": alarm,
        })

        # Route label for the payload
        route_label = {"red": "retain", "amber": "investigate", "green": "release"}[route]
        payload = {
            "tx": tx,
            "route": route_label,
            "validated": val["validated"],
            "validation_errors": val["validation_errors"],
            # Uniformized Sales_Order fields
            "Sales_Order_ID":           tx["transaction_id"],
            "Sales_Order_Business_Key": so_bk,
            "HS_Product_Category":      tx.get("item_category"),
            "Product_Description":      tx.get("item_description"),
            "Product_Value":            tx.get("value"),
            "VAT_Rate":                 tx.get("vat_rate"),
            "VAT_Fee":                  tx.get("vat_amount"),
            "Seller_Name":              tx.get("seller_name"),
            "Country_Origin":           tx.get("seller_country"),
            "Country_Destination":      tx.get("buyer_country"),
            "Status":                   route_label,
            "Update_time":              now_iso,
            **risk_payload,
        }

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
            tx_id = item["tx"]["transaction_id"]
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
    investigation.db and pushes the hydrated case to Revenue Guardian
    SSE subscribers.

    Does NOT publish INVESTIGATION_OUTCOME at creation. That event is the
    factory's exit signal and fires only when an officer closes the case
    (see customs-action retainment/release and final-decision endpoints).
    """
    from lib.database import upsert_investigation_set, get_case_hydrated
    import uuid as _uuid

    q = broker.subscribe(ASSESSMENT_OUTCOME)
    while True:
        msg = await q.get()
        route = msg.get("route")
        # Only investigation cases require human review. Automated retain
        # decisions are now finalised directly by the Exit Process Factory.
        if route != "investigate":
            continue

        now_iso = datetime.now(timezone.utc).isoformat()
        bk = msg.get("Sales_Order_Business_Key", "")
        case_id = f"CASE-{_uuid.uuid4().hex[:12].upper()}"

        # Derive VAT problem type from risk engine flags
        engines = msg.get("engines", {}) or {}
        if engines.get("vat_ratio") and engines.get("watchlist"):
            problem_type = "VAT Rate Deviation + Watchlist Match"
        elif engines.get("vat_ratio"):
            problem_type = "VAT Rate Deviation"
        elif engines.get("watchlist"):
            problem_type = "Watchlist Match"
        else:
            problem_type = "Risk Pattern"

        so_row = {
            "Sales_Order_ID":           msg.get("Sales_Order_ID"),
            "Sales_Order_Business_Key": bk,
            "HS_Product_Category":      msg.get("HS_Product_Category"),
            "Product_Description":      msg.get("Product_Description"),
            "Product_Value":            msg.get("Product_Value"),
            "VAT_Rate":                 msg.get("VAT_Rate"),
            "VAT_Fee":                  msg.get("VAT_Fee"),
            "Seller_Name":              msg.get("Seller_Name"),
            "Country_Origin":           msg.get("Country_Origin"),
            "Country_Destination":      msg.get("Country_Destination"),
            "Status":                   route,
            "Update_time":              now_iso,
            "Updated_by":               "system",
        }
        sor_row = {
            "Sales_Order_Risk_ID":         msg.get("Sales_Order_Risk_ID"),
            "Sales_Order_Business_Key":    bk,
            "Risk_Type":                   msg.get("Risk_Type", "VAT"),
            "Overall_Risk_Score":          msg.get("Overall_Risk_Score"),
            "Overall_Risk_Level":          msg.get("Overall_Risk_Level"),
            "Seller_Risk_Score":           msg.get("Seller_Risk_Score"),
            "Country_Risk_Score":          msg.get("Country_Risk_Score"),
            "Product_Category_Risk_Score": msg.get("Product_Category_Risk_Score"),
            "Manufacturer_Risk_Score":     msg.get("Manufacturer_Risk_Score"),
            "Confidence_Score":            msg.get("Confidence_Score"),
            "Overall_Risk_Description":    msg.get("Overall_Risk_Description"),
            "Proposed_Risk_Action":        msg.get("Proposed_Risk_Action"),
            "Risk_Comment":                msg.get("Risk_Comment"),
            "Evaluation_by":               msg.get("Evaluation_by"),
            "Update_time":                 now_iso,
            "Updated_by":                  "system",
        }
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
            # Frozen at insert; never bumped by officer actions. Drives the
            # FIFO ordering on the Customs / Tax queues.
            "Created_time":                     now_iso,
        }

        upsert_investigation_set(so_row, sor_row, soc_row)

        # Push hydrated case so frontends render without a follow-up fetch
        hydrated = get_case_hydrated(case_id) or {"Case_ID": case_id}
        _push_rg_case_sse({"event": "new_case", "case": hydrated})


# ── (Revenue Guardian two-entity workflow removed — replaced by
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
                order_id = msg.get("Sales_Order_ID") or msg.get("Sales_Order_Business_Key", "")
                await _emit(order_id, "automated_release")
            elif route == "retain":
                # Automated retain: no human review needed — finalise here.
                order_id = msg.get("Sales_Order_ID") or msg.get("Sales_Order_Business_Key", "")
                await _emit(order_id, "automated_retain")

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
    from lib.database import init_european_custom_db, init_simulation_db, init_investigation_db, reset_simulation_db
    init_european_custom_db()
    init_simulation_db()
    init_investigation_db()
    # Auto-reset: clear the fired flags so the simulation is always
    # ready to run on startup. Without this, a previous completed run
    # leaves all transactions marked fired=1 and the simulation loop
    # has nothing to replay after a restart.
    reset_simulation_db()

    asyncio.create_task(simulation_loop(_fire_transactions))
    asyncio.create_task(_RT_risk_monitoring_1_factory())
    asyncio.create_task(_RT_risk_monitoring_2_factory())
    asyncio.create_task(_RT_risk_monitoring_3_factory())
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
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_RISK_3_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
        CUSTOM_OUTCOME,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    ]
    pipeline = {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: _broker.qsize(t) for t in topics},
        "stored_count":       get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "outcome.flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "outcome.flagged", True),
            "rt_risk_3_flagged": count_field_value(RT_RISK_3_OUTCOME, "outcome.flagged", True),
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
# triggered exclusively from the Tax officer's Revenue Guardian page via
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
    """Bundled reference data consumed by the Revenue Guardian SPA at startup.

    Returns the four lookup tables seeded in european_custom.db. Static-ish
    data — refresh by re-fetching, no SSE channel.
    """
    from lib.database import (
        get_vat_categories, get_risk_levels, get_eu_regions, get_suspicion_types,
    )
    return {
        "vat_categories":  get_vat_categories(),
        "risk_levels":     get_risk_levels(),
        "regions":         get_eu_regions(),
        "suspicion_types": get_suspicion_types(),
    }


# ── Revenue Guardian: REST + SSE endpoints ────────────────────────────────────

@app.get("/api/rg/cases")
def api_rg_cases(status: str | None = Query(None), limit: int = Query(200, ge=1, le=1000)):
    """List all cases for Revenue Guardian, hydrated with Sales_Order +
    Sales_Order_Risk fields. Optionally filter by Status."""
    from lib.database import get_all_cases_hydrated
    return {"items": get_all_cases_hydrated(status=status, limit=limit)}


@app.get("/api/rg/cases/stream")
async def api_rg_cases_stream(request: Request):
    """SSE stream: pushes case events (new_case, case_updated) to Revenue Guardian."""
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


# ── VAT Fraud Detection agent: queue + worker ───────────────────────────────

async def _enqueue_for_agent(case_id: str) -> None:
    """Push a case_id onto the agent queue. No-op if the queue isn't ready."""
    if _agent_queue is None:
        return
    await _agent_queue.put(case_id)


def _build_agent_tx(case: dict) -> dict:
    """Shape the case as the tx dict the analyser expects."""
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

            destination = (case.get("Country_Destination") or "").upper()
            if destination == "IE":
                tx = _build_agent_tx(case)
                # Acquire the shared LM Studio slot so any future second
                # agent queues against the same semaphore, not against
                # LM Studio's invisible internal queue.
                async with acquire_slot():
                    result = await asyncio.to_thread(analyse_transaction_sync, tx)
            else:
                # Out-of-scope country: short-circuit with a fixed delay so
                # the UI still shows the AI step taking visible time.
                await asyncio.sleep(5)
                result = {
                    "verdict":   "uncertain",
                    "reasoning": f"Model for country '{destination or 'unknown'}' failed to run.",
                    "success":   False,
                }

            verdict   = result.get("verdict", "uncertain")
            reasoning = result.get("reasoning", "")
            now_iso   = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

            comm = case.get("Communication", []) or []
            comm.append({
                "date":    now_iso,
                "from":    "VAT Fraud Detection Agent",
                "action":  f"verdict: {verdict}",
                "message": reasoning,
            })
            update_case(case_id, {
                "Status":        STATUS.UNDER_REVIEW_BY_TAX,
                "AI_Analysis":   f"[{verdict}] {reasoning}",
                # AI_Confidence intentionally left null — agent does not
                # currently emit a numeric confidence value.
                "Update_time":   now_iso,
                "Updated_by":    "VAT Fraud Detection Agent",
                "Communication": comm,
            })
            _emit_case_updated_sse(case_id, "ai_complete")
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
    if action in ("retainment", "release"):
        updates["Proposed_Action_Customs"] = "retain" if action == "retainment" else "release"

    # Append to communication log
    comm = case.get("Communication", [])
    if not isinstance(comm, list):
        comm = []
    comm.append({"date": now_iso, "from": "Customs Authority", "action": action, "message": comment})
    updates["Communication"] = comm

    update_case(case_id, updates)

    _emit_case_updated_sse(case_id, action)
    if action in ("retainment", "release"):
        await _publish_investigation_outcome(
            case_id, "retained" if action == "retainment" else "released"
        )
    if action == "tax_review":
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


@app.post("/api/rg/cases/{case_id}/final-decision")
async def api_rg_final_decision(case_id: str, body: dict):
    """
    Final investigation decision.
    body: {decision: "released"|"retained"|"refused", officer?: str}
    """
    from lib.database import get_case_by_id, update_case

    case = get_case_by_id(case_id)
    if not case:
        return JSONResponse(status_code=404, content={"detail": "Case not found"})

    decision = body.get("decision", "")
    officer = body.get("officer", "Senior Officer")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

    if decision not in ("released", "retained", "refused"):
        return JSONResponse(status_code=400, content={"detail": f"Unknown decision: {decision}"})

    updates: dict = {
        "Status": STATUS.CLOSED,
        "Proposed_Action_Customs": {"released": "release", "retained": "retain", "refused": "refuse"}[decision],
        "Update_time": now_iso,
        "Updated_by": officer,
    }

    comm = case.get("Communication", [])
    if not isinstance(comm, list):
        comm = []
    comm.append({"date": now_iso, "from": officer, "action": f"Final decision: {decision}", "message": ""})
    updates["Communication"] = comm

    update_case(case_id, updates)

    _emit_case_updated_sse(case_id, f"final_{decision}")
    await _publish_investigation_outcome(case_id, decision)
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
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_RISK_3_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
        CUSTOM_OUTCOME,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    ]
    return {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: _broker.qsize(t) for t in topics},
        "stored_count":       get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "outcome.flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "outcome.flagged", True),
            "rt_risk_3_flagged": count_field_value(RT_RISK_3_OUTCOME, "outcome.flagged", True),
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
def sim_reset():
    from lib.event_store import flush_events
    from lib.seeder import seed_european_custom_db
    from lib.alarm_checker import bootstrap_scenario_alarm
    state.reset()
    reset_simulation_db()
    reset_alarms()          # removes March+ rows, keeps Sep–Feb history
    from lib.database import reset_cases
    reset_cases()           # clear investigation cases
    _push_rg_case_sse({"event": "cases_reset"})  # notify Revenue Guardian clients
    flush_events()
    # Re-seed historical data if it was wiped (e.g. first run or manual DB delete)
    if historical_transaction_count() == 0:
        seed_european_custom_db()
    bootstrap_scenario_alarm()   # pre-seed SUP001→IE alarm from day 1
    _live_queue.clear()
    _live_alarms.clear()
    # Cancel every in-flight delayed factory task (Order Validation, Arrival
    # Notification, manual agent runs) so no residual events fire after the
    # reset has emptied the pipeline. Tasks already in the middle of an
    # `await broker.publish(...)` will still complete that single publish,
    # but anything still inside `asyncio.sleep(...)` cancels cleanly.
    for t in list(_inflight_factory_tasks):
        if not t.done():
            t.cancel()
    _inflight_factory_tasks.clear()
    for sse_q in list(_sse_queues):
        try:
            sse_q.put_nowait("__reset__")
        except asyncio.QueueFull:
            pass
    _push_rg_case_sse({"event": "reset"})
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
