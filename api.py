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
    ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
    RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME, RT_SCORE,  # legacy counters
    RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,   # legacy counters
)

# Total number of risk monitoring engines. The release factory waits
# for this many outcomes (or times out) before computing the score.
# Adding a new risk engine = increment this + write the factory.
TOTAL_RISK_ENGINES = 2
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
    upsert_sales_order_line_item,
    upsert_line_item_risk,
    upsert_line_item_ai_analysis,
)
from lib.regions import country_region
from lib.simulator import state, simulation_loop
from lib.catalog import SUPPLIERS, COUNTRY_NAMES

# ── In-memory state ───────────────────────────────────────────────────────────

_live_queue:          deque[dict]        = deque(maxlen=QUEUE_SIZE)
_live_alarms:         list[dict]         = []
_sse_queues:          set[asyncio.Queue] = set()   # live-transaction stream subscribers
_sim_state_sse:       set[asyncio.Queue] = set()   # pipeline + status stream subscribers

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

async def _release_factory() -> None:
    """Unified routing factory: collects risk outcomes, computes
    consolidated score, and routes to RELEASE / INVESTIGATE / RETAIN."""

    # Per-transaction buffer: tx_id → {
    #   "risk_outcomes": {engine_name: item, ...},
    #   "validation": item | None,
    #   "routed": bool,
    # }
    _buffer: dict[str, dict] = {}

    def _get(tx_id: str) -> dict:
        return _buffer.setdefault(tx_id, {
            "risk_outcomes": {},
            "validation": None,
            "routed": False,
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

    async def _try_route(tx_id: str) -> None:
        entry = _get(tx_id)
        if entry["routed"]:
            return

        score, confidence, route = _compute_score(entry)
        outcomes = entry["risk_outcomes"]

        # Collect alarm info from risk outcomes (first alarm found)
        alarm_id = None
        alarm = None
        for o in outcomes.values():
            if o.get("alarm_id"):
                alarm_id = o["alarm_id"]
                alarm = o.get("alarm")
                break

        # Build the common payload fields
        tx = None
        for o in outcomes.values():
            tx = o.get("tx")
            if tx:
                break
        if tx is None and entry["validation"]:
            tx = entry["validation"]["tx"]
        if tx is None:
            return   # no transaction data yet

        risk_payload = {
            "risk_score":   score,
            "risk_route":   route,
            "confidence":   round(confidence, 2),
            "engines":      {eng: o.get("flagged", False)
                             for eng, o in outcomes.items()},
            "alarm_id":     alarm_id,
            "alarm":        alarm,
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

        # ── RED path: retain immediately once score > 66.66% ──
        if route == "red":
            if entry["validation"] is None:
                return   # wait for validation even on RED
            entry["routed"] = True
            val = entry["validation"]
            payload = {
                "tx": tx, "route": "retain",
                "validated": val["validated"],
                "validation_errors": val["validation_errors"],
                **risk_payload,
            }
            await broker.publish(ASSESSMENT_OUTCOME, payload)
            await broker.publish(RETAIN_EVENT, payload)   # legacy counter
            _buffer.pop(tx_id, None)
            return

        # ── AMBER path: investigate — needs validation ──
        if route == "amber":
            if entry["validation"] is None:
                return   # wait for validation
            entry["routed"] = True
            val = entry["validation"]
            payload = {
                "tx": tx, "route": "investigate",
                "validated": val["validated"],
                "validation_errors": val["validation_errors"],
                **risk_payload,
                "alarm_id": alarm_id,
                "alarm": alarm,
            }
            await broker.publish(ASSESSMENT_OUTCOME, payload)
            await broker.publish(INVESTIGATE_EVENT, payload)  # legacy counter
            _buffer.pop(tx_id, None)
            return

        # ── GREEN path: release — needs validation ──
        if route == "green":
            if entry["validation"] is None:
                return   # wait for validation
            entry["routed"] = True
            val = entry["validation"]
            payload = {
                "tx": tx, "route": "release",
                "validated": val["validated"],
                "validation_errors": val["validation_errors"],
                **risk_payload,
            }
            await broker.publish(ASSESSMENT_OUTCOME, payload)
            await broker.publish(RELEASE_EVENT, payload)  # legacy counter
            _buffer.pop(tx_id, None)
            return

    # ── Drain: risk outcomes ──
    async def _drain_risk() -> None:
        q = broker.subscribe(RT_RISK_OUTCOME)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            engine = item.get("engine", "unknown")
            entry = _get(tx_id)
            entry["risk_outcomes"][engine] = item
            await _try_route(tx_id)

    # ── Drain: order validation ──
    async def _drain_validation() -> None:
        q = broker.subscribe(ORDER_VALIDATION)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            entry = _get(tx_id)
            entry["validation"] = item
            await _try_route(tx_id)

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

    Subscribes to ASSESSMENT_OUTCOME (retain + investigate routes) and
    SALES_ORDER_EVENT. For retain and investigate events, produces an
    INVESTIGATION_OUTCOME event. Currently echoes the assessment input
    (placeholder for future investigation logic).
    """
    async def _drain_assessment() -> None:
        q = broker.subscribe(ASSESSMENT_OUTCOME)
        while True:
            msg = await q.get()
            route = msg.get("route")
            if route not in ("retain", "investigate"):
                continue
            # Produce investigation outcome (echo for now)
            await broker.publish(INVESTIGATION_OUTCOME, {
                "tx":             msg.get("tx"),
                "route":          route,
                "risk_score":     msg.get("risk_score"),
                "risk_route":     msg.get("risk_route"),
                "confidence":     msg.get("confidence"),
                "engines":        msg.get("engines"),
                "alarm_id":       msg.get("alarm_id"),
                "alarm":          msg.get("alarm"),
                "investigation":  "auto",   # placeholder
                "outcome":        route,     # echoes assessment for now
            })

    async def _drain_sales_order() -> None:
        # Subscribe to Sales Order Event for future enrichment
        q = broker.subscribe(SALES_ORDER_EVENT)
        while True:
            await q.get()  # consumed but not acted on yet (placeholder)

    await asyncio.gather(_drain_assessment(), _drain_sales_order())


# ── (Revenue Guardian two-entity workflow removed — replaced by
# _ct_risk_management_factory above.) ──


_REMOVED_FLAT_TX_VIEW = True  # marker — old _flat_tx_view and related
# customs/tax queue helpers, listeners, SSE streams, and REST endpoints
# have been removed. The C&T Risk Management factory replaces them.


# ── DB Store Worker (all terminal event topics) ───────────────────────────────

async def _db_store_worker() -> None:
    """
    Terminal worker — persists transactions to the European Custom DB,
    live queue, and SSE clients.

    Subscribes to:
      ASSESSMENT_OUTCOME   — release-routed events (green path, no suspicious flag)
      INVESTIGATION_OUTCOME — all investigation results (suspicious flag set)
      SALES_ORDER_EVENT    — raw sales orders for historical storage
    """
    async def _push_sse(row: dict) -> None:
        if not _sse_queues:
            return
        payload = _json.dumps(row)
        dead    = set()
        for sse_q in _sse_queues:
            try:
                sse_q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.add(sse_q)
        _sse_queues.difference_update(dead)

    async def _store(msg: dict, suspicious: bool) -> None:
        tx         = msg["tx"]
        risk_score = msg.get("risk_score", "green")
        alarm_id   = msg.get("alarm_id")

        insert_transaction(tx)

        if suspicious:
            flag_transaction_suspicious(tx["transaction_id"], alarm_id, risk_score)

        row = dict(tx)
        row["suspicious"]     = 1 if suspicious else 0
        row["risk_score"]     = risk_score
        row["risk_1_flagged"] = msg.get("risk_1_flagged", False)
        row["risk_2_flagged"] = msg.get("risk_2_flagged", False)
        _live_queue.appendleft(row)
        await _push_sse(row)

    async def _drain(topic: str, suspicious: bool) -> None:
        q = broker.subscribe(topic)
        while True:
            msg = await q.get()
            await _store(msg, suspicious)

    async def _drain_assessment() -> None:
        """Only store release-routed assessments (green path)."""
        q = broker.subscribe(ASSESSMENT_OUTCOME)
        while True:
            msg = await q.get()
            if msg.get("route") == "release":
                await _store(msg, suspicious=False)
            # Legacy counter compatibility
            await broker.publish(RELEASE_EVENT, msg)

    async def _drain_investigation() -> None:
        """Store all investigation outcomes (retain + investigate)."""
        q = broker.subscribe(INVESTIGATION_OUTCOME)
        while True:
            msg = await q.get()
            await _store(msg, suspicious=True)

    async def _drain_sales_order() -> None:
        """Store raw sales orders for historical purposes."""
        q = broker.subscribe(SALES_ORDER_EVENT)
        while True:
            msg = await q.get()
            tx = msg if isinstance(msg, dict) and "transaction_id" in msg else msg
            insert_transaction(tx)

    await asyncio.gather(
        _drain_assessment(),
        _drain_investigation(),
        _drain_sales_order(),
    )


# ── Data Hub Writer (3 dark-purple tables, 30-s polling worker) ──────────────

# Tick interval — how often the writer drains its in-memory buffer and upserts
# into the data hub tables. The user spec says "every 30 sec".
_DATA_HUB_TICK_S = 30.0

# Per-key buffers populated by the topic listeners between ticks. Each maps
# sales_order_line_item_SKU → row dict ready to be upserted. The polling tick
# moves them out of the buffer; if a topic re-fires for the same key before
# the tick, the buffer entry is replaced (latest wins).
_data_hub_so_buffer: dict[str, dict] = {}
_data_hub_risk_buffer: dict[str, dict] = {}
_data_hub_ai_buffer: dict[str, dict] = {}


def _line_sku(tx: dict, line_number: int = 1) -> str:
    """Compute the deterministic per-line SKU. Today every order has exactly
    one synthetic line so line_number is always 1; the helper exists to make
    the multi-line migration trivial later."""
    so_id = tx.get("orderIdentifier") or tx.get("transaction_id") or "unknown"
    return f"{so_id}-{line_number:03d}"


def _build_sales_order_line_item_row(tx: dict) -> dict | None:
    """Convert a SALES_ORDER_EVENT message into a sales_order_line_item row.
    Returns None if essential fields are missing."""
    so_id = tx.get("orderIdentifier") or tx.get("transaction_id")
    if not so_id:
        return None
    sku = _line_sku(tx, 1)

    # The simplified_order.json schema carries:
    #   DeemedImporter (order header)         = the EU reseller
    #   SalesLineItem[i].Seller (line level)  = the non-EU producer
    # Pull both from the message; fall back to flat compat fields if needed.
    deemed_importer = tx.get("DeemedImporter") or {}
    importer_addr   = deemed_importer.get("Address") or {}

    sales_lines = tx.get("SalesLineItem") or []
    li          = sales_lines[0] if sales_lines else {}
    li_seller   = li.get("Seller") or {}
    li_addr     = li_seller.get("Address") or {}
    li_desc     = ((li.get("DescriptionOfGoods") or {}).get("descriptionOfGoods")
                   or tx.get("item_description") or "")

    dest_country = (
        ((tx.get("CountryOfDestination") or {}).get("country"))
        or tx.get("buyer_country")
        or ""
    )

    return {
        "sales_order_line_item_SKU": sku,
        "so_id":                     so_id,
        "line_item_name":            sku,
        "line_item_SKU":             sku,
        "line_item_description":     li_desc,
        "line_item_price":           li.get("itemAmountPrice") or tx.get("value") or 0.0,
        "product_category":          tx.get("item_category") or "",
        # Order-header party — DeemedImporter (EU reseller)
        "deemed_importer_id":        deemed_importer.get("identificationNumber") or tx.get("seller_id") or "",
        "deemed_importer_name":      deemed_importer.get("name")                 or tx.get("seller_name") or "",
        "deemed_importer_country":   importer_addr.get("country")                or tx.get("seller_country") or "",
        # Per-line party — Seller (non-EU producer)
        "seller_id":                 li_seller.get("identificationNumber") or tx.get("producer_id"),
        "seller_name":               li_seller.get("name")                 or tx.get("producer_name"),
        "seller_city":               li_addr.get("cityName")                or tx.get("producer_city"),
        "origin_country":            li_addr.get("country")                 or tx.get("producer_country"),
        "destination_country":       dest_country,
        "dest_country_region":       country_region(dest_country),
        "VAT_pct":                   tx.get("vat_rate") or 0.0,
        "VAT_paid":                  tx.get("vat_amount") or 0.0,
        "date":                      (tx.get("orderCreationDate")
                                      or tx.get("transaction_date") or ""),
    }


# Mapping from RT_SCORE categorical → numeric / level / suggested action.
# Locked in with the user: High=100, Medium=50, Low=0.
_RT_SCORE_TO_RISK = {
    "red":   {"score": 100, "level": "High",   "action": "retain"},
    "amber": {"score":  50, "level": "Medium", "action": "investigate"},
    "green": {"score":   0, "level": "Low",    "action": "release"},
}


def _build_line_item_risk_row(msg: dict) -> dict | None:
    """Convert an RT_SCORE message into a line_item_risk row. Every transaction
    that passes through the pipeline produces an RT_SCORE event so this fires
    for every line — matching the user's rule that risk is always populated."""
    tx = msg.get("tx") or {}
    sku = _line_sku(tx, 1)
    if not tx.get("orderIdentifier") and not tx.get("transaction_id"):
        return None

    rt_color = (msg.get("risk_score") or "green").lower()
    mapping  = _RT_SCORE_TO_RISK.get(rt_color, _RT_SCORE_TO_RISK["green"])

    # risk_description = "; "-joined names of failed checks (RT Risk 1 / 2),
    # empty when nothing flagged. The two flags travel with the RT_SCORE
    # message published by RT Consolidation.
    failed: list[str] = []
    if msg.get("risk_1_flagged"):
        failed.append("vat_ratio_deviation")
    if msg.get("risk_2_flagged"):
        failed.append("watchlist_hit")
    description = "; ".join(failed)

    return {
        "sales_order_line_item_SKU": sku,
        "risk_score_numeric":        mapping["score"],
        "risk_level":                mapping["level"],
        "risk_description":          description,
        "suggested_risk_action":     mapping["action"],
    }


def _build_line_item_ai_row(msg: dict) -> dict | None:
    """Convert an AI_ANALYSIS_EVENT into a line_item_ai_analysis row. Only
    fires when the Tax officer manually runs the agent — most transactions
    will never appear in this table, by design."""
    tx = msg.get("tx") or {}
    sku = _line_sku(tx, 1)
    if not tx.get("orderIdentifier") and not tx.get("transaction_id"):
        return None

    verdict   = (msg.get("verdict") or "uncertain").lower()
    reasoning = msg.get("reasoning") or ""

    # Confidence derivation (locked in with user): correct→1.0, uncertain→0.5,
    # incorrect→0.0. Cheap and consistent until the analyser produces a real
    # confidence number.
    confidence = {"correct": 1.0, "uncertain": 0.5, "incorrect": 0.0}.get(verdict, 0.5)

    # source = "; "-joined unique source names from the legislation refs.
    refs = msg.get("legislation_refs") or []
    seen: set[str] = set()
    sources: list[str] = []
    for r in refs:
        s = (r.get("source") or "").strip() if isinstance(r, dict) else str(r)
        if s and s not in seen:
            seen.add(s)
            sources.append(s)
    source_str = "; ".join(sources)

    # Per-line verdicts carry the corrected VAT rate (`expected_rate`) and the
    # rate that was actually applied. Today there is exactly one synthetic
    # line per transaction so we use line_verdicts[0]; this generalises
    # cleanly when multi-line orders arrive (we'd loop and emit one row per
    # line_item_id).
    line_verdicts = msg.get("line_verdicts") or []
    expected_rate = None
    if line_verdicts:
        expected_rate = line_verdicts[0].get("expected_rate")

    line_price = tx.get("value") or 0.0
    vat_paid   = tx.get("vat_amount") or 0.0

    if expected_rate is not None and line_price:
        # The analyser returns expected_rate as a fraction (0.21 = 21%).
        correct_vat_value = round(line_price * float(expected_rate), 2)
        vat_exposure      = round(correct_vat_value - vat_paid, 2)
        correct_vat_pct   = float(expected_rate)
    else:
        correct_vat_value = None
        vat_exposure      = None
        correct_vat_pct   = None

    return {
        "sales_order_line_item_SKU": sku,
        "analysis_outcome":          verdict,
        "analysis_description":      reasoning,
        "confidence_score":          confidence,
        "source":                    source_str,
        # No source for category correction today (the agent doesn't return
        # one and the simulator never seeds wrong-category fraud).
        "correct_product_category":  None,
        "correct_vat_pct":           correct_vat_pct,
        "correct_vat_value":         correct_vat_value,
        "vat_exposure":              vat_exposure,
    }


async def _data_hub_writer() -> None:
    """
    Polling worker that populates the three data hub tables.

    Architecture:
      1. Subscribe ONCE at startup to SALES_ORDER_EVENT, RT_SCORE, and
         AI_ANALYSIS_EVENT. Listener coroutines accumulate the latest row per
         (sales_order_line_item_SKU) into the three module-level buffers.
      2. Tick every _DATA_HUB_TICK_S seconds: drain each buffer and upsert
         into its target table inside a single transaction.

    Idempotency: every upsert keys on sales_order_line_item_SKU and uses
    INSERT ... ON CONFLICT DO UPDATE, so re-receiving the same line is safe.

    Lifecycle: matches the user's rule —
      • every transaction → 1 row in sales_order_line_item + 1 in line_item_risk
      • only tax-officer-triggered analyses → 1 row in line_item_ai_analysis
    """
    so_q   = broker.subscribe(SALES_ORDER_EVENT)
    risk_q = broker.subscribe(RT_SCORE)
    ai_q   = broker.subscribe(INVESTIGATION_OUTCOME)

    async def _drain_so() -> None:
        while True:
            msg = await so_q.get()
            row = _build_sales_order_line_item_row(msg)
            if row:
                _data_hub_so_buffer[row["sales_order_line_item_SKU"]] = row

    async def _drain_risk() -> None:
        while True:
            msg = await risk_q.get()
            row = _build_line_item_risk_row(msg)
            if row:
                _data_hub_risk_buffer[row["sales_order_line_item_SKU"]] = row

    async def _drain_ai() -> None:
        while True:
            msg = await ai_q.get()
            row = _build_line_item_ai_row(msg)
            if row:
                _data_hub_ai_buffer[row["sales_order_line_item_SKU"]] = row

    async def _tick() -> None:
        while True:
            await asyncio.sleep(_DATA_HUB_TICK_S)
            # Snapshot + clear so the listeners can keep accepting messages
            # while we write. Race window is harmless — anything that arrives
            # during the writes lands in the next tick.
            so_snap   = list(_data_hub_so_buffer.values());   _data_hub_so_buffer.clear()
            risk_snap = list(_data_hub_risk_buffer.values()); _data_hub_risk_buffer.clear()
            ai_snap   = list(_data_hub_ai_buffer.values());   _data_hub_ai_buffer.clear()

            # Sales Order + Line Item rows MUST land before Risk / AI rows
            # for that SKU because the latter two FK back to it. Within a
            # single tick we drain all three so this ordering matters only
            # if the same SKU appears in both buffers (which is the common
            # case): the SO row gets inserted first, then the FK rows resolve.
            for row in so_snap:
                try:
                    upsert_sales_order_line_item(row)
                except Exception as exc:
                    print(f"[data_hub] SO upsert failed for {row.get('sales_order_line_item_SKU')}: {exc}")
            for row in risk_snap:
                try:
                    upsert_line_item_risk(row)
                except Exception as exc:
                    print(f"[data_hub] risk upsert failed for {row.get('sales_order_line_item_SKU')}: {exc}")
            for row in ai_snap:
                try:
                    upsert_line_item_ai_analysis(row)
                except Exception as exc:
                    print(f"[data_hub] AI upsert failed for {row.get('sales_order_line_item_SKU')}: {exc}")

            if so_snap or risk_snap or ai_snap:
                print(f"[data_hub] tick: SO={len(so_snap)} risk={len(risk_snap)} ai={len(ai_snap)}")

    await asyncio.gather(_drain_so(), _drain_risk(), _drain_ai(), _tick())


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    from lib.database import init_european_custom_db, init_simulation_db, reset_simulation_db
    init_european_custom_db()
    init_simulation_db()
    # Auto-reset: clear the fired flags so the simulation is always
    # ready to run on startup. Without this, a previous completed run
    # leaves all transactions marked fired=1 and the simulation loop
    # has nothing to replay after a restart.
    reset_simulation_db()

    asyncio.create_task(simulation_loop(_fire_transactions))
    asyncio.create_task(_RT_risk_monitoring_1_factory())
    asyncio.create_task(_RT_risk_monitoring_2_factory())
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
    asyncio.create_task(_data_hub_writer())
    asyncio.create_task(_sim_state_broadcaster())

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
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    ]
    pipeline = {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: _broker.qsize(t) for t in topics},
        "stored_count":       get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "outcome.flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "outcome.flagged", True),
            "rt_score_green":    count_field_value(RT_SCORE, "outcome.risk_score", "green"),
            "rt_score_amber":    count_field_value(RT_SCORE, "outcome.risk_score", "amber"),
            "rt_score_red":      count_field_value(RT_SCORE, "outcome.risk_score", "red"),
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



# ── (Revenue Guardian API endpoints removed) ──

# ── Simulation control ────────────────────────────────────────────────────────

@app.get("/api/simulation/pipeline")
def sim_pipeline():
    """Return per-topic event counts (persisted files) and live broker queue sizes."""
    from lib.event_store import event_count, count_field_value
    from lib.broker import broker as _broker
    topics = [
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ASSESSMENT_OUTCOME, INVESTIGATION_OUTCOME,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    ]
    return {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: _broker.qsize(t) for t in topics},
        "stored_count":       get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "outcome.flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "outcome.flagged", True),
            "rt_score_green":    count_field_value(RT_SCORE, "outcome.risk_score", "green"),
            "rt_score_amber":    count_field_value(RT_SCORE, "outcome.risk_score", "amber"),
            "rt_score_red":      count_field_value(RT_SCORE, "outcome.risk_score", "red"),
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
    if state.sim_time >= SIM_END_DT:
        return {"ok": False, "reason": "simulation already finished — reset first"}
    # Flush persisted events and bootstrap alarm on first launch (fired_count == 0).
    # Pause → resume does not flush (fired_count > 0 at that point).
    if state.fired_count == 0:
        flush_events()
        bootstrap_scenario_alarm()
    state.running = True
    return {"ok": True, "status": state.to_dict()}


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
