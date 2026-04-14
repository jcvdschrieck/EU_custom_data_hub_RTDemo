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
    SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
    RT_SCORE, ORDER_VALIDATION, ARRIVAL_NOTIFICATION,
    RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
    AGENT_RETAIN_EVENT, AGENT_RELEASE_EVENT, RELEASE_AFTER_INVESTIGATION_EVENT,
    AI_ANALYSIS_EVENT,
)
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
_customs_queue: dict[str, dict] = {}
_tax_queue:     dict[str, dict] = {}
_customs_sse:   set[asyncio.Queue] = set()
_tax_sse:       set[asyncio.Queue] = set()

_manual_agent_executor = None   # lazy-initialised ThreadPoolExecutor for manual agent runs

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
    Publishes outcome to RT_risk_monitoring_1_outcome_broker.
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

        await broker.publish(RT_RISK_1_OUTCOME, {
            "tx":       tx,
            "flagged":  flagged,
            "alarm_id": alarm_id,
            "alarm":    new_alarm or next(
                (a for a in _live_alarms if a.get("id") == alarm_id), {}
            ) if flagged else None,
        })


# ── RT Risk Monitoring 2 Factory (watchlist check) ───────────────────────────

async def _RT_risk_monitoring_2_factory() -> None:
    """
    Subscriber of Sales-order Event Broker.
    Checks whether the (seller_id, seller_country) pair — supplier × country
    of origin — appears in the configured watchlist (lib/watchlist.py).
    Publishes outcome to RT_risk_monitoring_2_outcome_broker.
    """
    from lib.watchlist import is_watchlisted

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        flagged = is_watchlisted(tx["seller_id"], tx["seller_country"])

        await broker.publish(RT_RISK_2_OUTCOME, {
            "tx":      tx,
            "flagged": flagged,
            "reason":  "watchlist_match" if flagged else "clear",
        })


# ── RT Consolidation Factory ──────────────────────────────────────────────────

async def _RT_consolidation_factory() -> None:
    """
    Subscribes to RT_risk_monitoring_1_outcome_broker AND
    RT_risk_monitoring_2_outcome_broker.
    Correlates both outcomes by transaction_id and computes a risk score:
      • both flagged  → RED
      • one flagged   → AMBER
      • neither       → GREEN
    Publishes to RT_score_broker.
    """
    _buffer: dict[str, dict] = {}   # tx_id → {"r1": ..., "r2": ...}

    async def _emit_if_ready(tx_id: str) -> None:
        entry = _buffer.get(tx_id, {})
        if "r1" not in entry or "r2" not in entry:
            return
        del _buffer[tx_id]

        r1, r2   = entry["r1"], entry["r2"]
        flag_1   = r1["flagged"]
        flag_2   = r2["flagged"]

        if flag_1 and flag_2:
            risk_score = "red"
        elif flag_1 or flag_2:
            risk_score = "amber"
        else:
            risk_score = "green"

        await broker.publish(RT_SCORE, {
            "tx":             r1["tx"],
            "risk_score":     risk_score,
            "risk_1_flagged": flag_1,
            "risk_2_flagged": flag_2,
            "alarm_id":       r1.get("alarm_id"),
            "alarm":          r1.get("alarm"),
        })

    async def _drain_r1() -> None:
        q = broker.subscribe(RT_RISK_1_OUTCOME)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            _buffer.setdefault(tx_id, {})["r1"] = item
            await _emit_if_ready(tx_id)

    async def _drain_r2() -> None:
        q = broker.subscribe(RT_RISK_2_OUTCOME)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            _buffer.setdefault(tx_id, {})["r2"] = item
            await _emit_if_ready(tx_id)

    await asyncio.gather(_drain_r1(), _drain_r2())


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


# ── Arrival Notification Factory ─────────────────────────────────────────────

async def _arrival_notification_factory() -> None:
    """
    Subscribes to Sales-order Event Broker.
    For each sales order, spawns an independent asyncio task that waits an
    exponentially-distributed delay (mean 30 sim-seconds) before publishing
    to ARRIVAL_NOTIFICATION. The wait is expressed in sim-time via
    _sleep_until_sim_time so arrivals stay tightly coupled to their orders
    in sim-time and naturally pause/resume/reset alongside the simulation.

    Unlimited concurrency — each order is scheduled independently; no order
    ever blocks behind another in this factory.
    """
    import random
    from lib.message_factory import build_arrival_notification
    from lib.simulator import state as _state

    MEAN_SIM_SECONDS = 30.0

    async def _schedule(tx: dict) -> None:
        sim_delay = random.expovariate(1.0 / MEAN_SIM_SECONDS)
        target    = _state.sim_time + timedelta(seconds=sim_delay)
        await _sleep_until_sim_time(target)
        payload = build_arrival_notification(tx, _state.sim_time)
        await broker.publish(ARRIVAL_NOTIFICATION, payload)

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()
        _track_factory_task(_schedule(tx))


# ── Release Factory (GREEN path) ─────────────────────────────────────────────

async def _release_factory() -> None:
    """
    GREEN path: validation + green RT score + arrival notification → RELEASE_EVENT.
    Non-green scores are ignored (handled by _retain_factory / _investigate_dispatch_factory).
    """
    _buffer: dict[str, dict] = {}
    _skip:   set[str]        = set()

    async def _emit_if_ready(tx_id: str) -> None:
        entry = _buffer.get(tx_id, {})
        if "validation" not in entry or "score" not in entry or "arrival" not in entry:
            return
        del _buffer[tx_id]
        _skip.discard(tx_id)
        val, score = entry["validation"], entry["score"]
        await broker.publish(RELEASE_EVENT, {
            "tx":                val["tx"],
            "validated":         val["validated"],
            "validation_errors": val["validation_errors"],
            "risk_score":        score["risk_score"],
            "risk_1_flagged":    score["risk_1_flagged"],
            "risk_2_flagged":    score["risk_2_flagged"],
            "alarm_id":          score["alarm_id"],
            "alarm":             score["alarm"],
        })

    async def _drain_validation() -> None:
        q = broker.subscribe(ORDER_VALIDATION)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            if tx_id not in _skip:
                _buffer.setdefault(tx_id, {})["validation"] = item
                await _emit_if_ready(tx_id)

    async def _drain_score() -> None:
        q = broker.subscribe(RT_SCORE)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            if item["risk_score"] == "green":
                _buffer.setdefault(tx_id, {})["score"] = item
                await _emit_if_ready(tx_id)
            else:
                _skip.add(tx_id)
                _buffer.pop(tx_id, None)

    async def _drain_arrival() -> None:
        q = broker.subscribe(ARRIVAL_NOTIFICATION)
        while True:
            item = await q.get()
            tx_id = (
                item.get("orderIdentifier")
                or item.get("transaction_id")
                or item.get("sales_order_id")
                or ((item.get("HouseConsignment") or {}).get("Order") or {}).get("orderIdentifier")
            )
            if tx_id and tx_id not in _skip:
                _buffer.setdefault(tx_id, {})["arrival"] = item
                await _emit_if_ready(tx_id)

    await asyncio.gather(_drain_validation(), _drain_score(), _drain_arrival())


# ── Retain Factory (RED path — immediate) ────────────────────────────────────

async def _retain_factory() -> None:
    """
    RED path: red RT score → RETAIN_EVENT immediately, no other conditions needed.
    """
    q = broker.subscribe(RT_SCORE)
    while True:
        item = await q.get()
        if item["risk_score"] != "red":
            continue
        tx = item["tx"]
        await broker.publish(RETAIN_EVENT, {
            "tx":             tx,
            "risk_score":     "red",
            "risk_1_flagged": item["risk_1_flagged"],
            "risk_2_flagged": item["risk_2_flagged"],
            "alarm_id":       item["alarm_id"],
            "alarm":          item["alarm"],
        })


# ── Investigate Dispatch Factory (AMBER path) ─────────────────────────────────

async def _investigate_dispatch_factory() -> None:
    """
    AMBER path: amber RT score + order validation → INVESTIGATE_EVENT.
    Non-amber scores are discarded immediately.
    """
    _buffer: dict[str, dict] = {}
    _skip:   set[str]        = set()

    async def _emit_if_ready(tx_id: str) -> None:
        entry = _buffer.get(tx_id, {})
        if "validation" not in entry or "score" not in entry:
            return
        del _buffer[tx_id]
        _skip.discard(tx_id)
        val, score = entry["validation"], entry["score"]
        await broker.publish(INVESTIGATE_EVENT, {
            "tx":                val["tx"],
            "validated":         val["validated"],
            "validation_errors": val["validation_errors"],
            "risk_score":        "amber",
            "alarm_id":          score["alarm_id"],
            "alarm":             score["alarm"],
        })

    async def _drain_validation() -> None:
        q = broker.subscribe(ORDER_VALIDATION)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            if tx_id not in _skip:
                _buffer.setdefault(tx_id, {})["validation"] = item
                await _emit_if_ready(tx_id)

    async def _drain_score() -> None:
        q = broker.subscribe(RT_SCORE)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            if item["risk_score"] == "amber":
                _buffer.setdefault(tx_id, {})["score"] = item
                await _emit_if_ready(tx_id)
            else:
                _skip.add(tx_id)
                _buffer.pop(tx_id, None)

    await asyncio.gather(_drain_validation(), _drain_score())


# ── Two-entity manual workflow (Customs Office + Tax Office) ─────────────────
#
# Two independent listeners — one per entity. Each listener subscribes to its
# own broker topic and populates its own in-memory queue. Inter-entity
# transfers (Customs escalates → Tax, Tax recommends → Customs) physically
# move the entry between dicts and broadcast updates on BOTH SSE streams so
# both UIs refresh simultaneously.

def _flat_tx_view(tx: dict) -> dict:
    """Common transaction-shaped fields surfaced on every queue entry view.
    Used by both _customs_entry_view and _tax_entry_view."""
    return {
        "transaction_id":   tx.get("transaction_id"),
        "transaction_date": tx.get("transaction_date"),
        "seller_id":        tx.get("seller_id"),
        "seller_name":      tx.get("seller_name"),
        "seller_country":   tx.get("seller_country"),
        "buyer_country":    tx.get("buyer_country"),
        "item_category":    tx.get("item_category"),
        "item_description": tx.get("item_description"),
        "value":            tx.get("value"),
        "vat_rate":         tx.get("vat_rate"),
        "vat_amount":       tx.get("vat_amount"),
        "correct_vat_rate": tx.get("correct_vat_rate"),
        "has_error":        tx.get("has_error"),
        "producer_id":      tx.get("producer_id"),
        "producer_name":    tx.get("producer_name"),
        "producer_country": tx.get("producer_country"),
        "producer_city":    tx.get("producer_city"),
    }


def _customs_entry_view(entry: dict) -> dict:
    return {
        **_flat_tx_view(entry.get("tx", {}) or {}),
        "risk_score":          entry.get("risk_score"),
        "alarm":               entry.get("alarm") or {},
        "route":               entry.get("route"),
        "tax_recommendation":  entry.get("tax_recommendation"),
        "tax_recommended_at":  entry.get("tax_recommended_at"),
        "created_at":          entry.get("created_at"),
        "updated_at":          entry.get("updated_at"),
    }


def _tax_entry_view(entry: dict) -> dict:
    return {
        **_flat_tx_view(entry.get("tx", {}) or {}),
        "risk_score":             entry.get("risk_score"),
        "alarm":                  entry.get("alarm") or {},
        "route":                  entry.get("route"),
        "escalated_from_customs": bool(entry.get("escalated_from_customs")),
        "agent_status":           entry.get("agent_status") or "pending",
        "agent_verdict":          entry.get("agent_verdict"),
        "created_at":             entry.get("created_at"),
        "updated_at":             entry.get("updated_at"),
    }


def _customs_snapshot() -> list[dict]:
    items = [_customs_entry_view(e) for e in _customs_queue.values()]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items


def _tax_snapshot() -> list[dict]:
    items = [_tax_entry_view(e) for e in _tax_queue.values()]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items


def _broadcast_to(sse_set: set[asyncio.Queue], payload_str: str) -> None:
    """Synchronous fan-out via put_nowait. Drops frames for lagging subscribers."""
    if not sse_set:
        return
    dead = set()
    for q in sse_set:
        try:
            q.put_nowait(payload_str)
        except asyncio.QueueFull:
            pass   # subscriber lagging; next change will produce another snapshot
        except Exception:
            dead.add(q)
    sse_set.difference_update(dead)


def _broadcast_customs_update() -> None:
    if not _customs_sse:
        return
    try:
        payload = _json.dumps(_customs_snapshot())
    except Exception:
        return
    _broadcast_to(_customs_sse, payload)


def _broadcast_tax_update() -> None:
    if not _tax_sse:
        return
    try:
        payload = _json.dumps(_tax_snapshot())
    except Exception:
        return
    _broadcast_to(_tax_sse, payload)


async def _customs_listener_factory() -> None:
    """
    Customs Office listener.

    Subscribes to RETAIN_EVENT (the RED routing path). Every retain event
    becomes an entry in _customs_queue with route="red", awaiting the
    Customs operator's review on the Revenue Guardian Customs page.

    The Customs operator can:
      - Decide release/retain directly (terminal)
      - Escalate to Tax (transfer entry to _tax_queue)
    """
    q = broker.subscribe(RETAIN_EVENT)
    while True:
        msg   = await q.get()
        tx    = msg.get("tx") or {}
        tx_id = tx.get("transaction_id")
        if not tx_id:
            continue
        if tx_id in _customs_queue or tx_id in _tax_queue:
            # Idempotent: don't double-route the same transaction.
            continue
        now_iso = datetime.now(timezone.utc).isoformat()
        _customs_queue[tx_id] = {
            "tx":                  tx,
            "alarm":               msg.get("alarm") or {},
            "risk_score":          msg.get("risk_score") or "red",
            "route":               "red",
            "tax_recommendation":  None,
            "tax_recommended_at":  None,
            "created_at":          now_iso,
            "updated_at":          now_iso,
        }
        _broadcast_customs_update()


async def _tax_listener_factory() -> None:
    """
    Tax Office listener.

    Subscribes to INVESTIGATE_EVENT (the AMBER routing path). Every
    investigate event becomes an entry in _tax_queue with route="amber",
    awaiting the Tax operator's review on the Revenue Guardian Tax page.

    The Tax operator can:
      - Run the VAT fraud detection agent (Tax-side tool only)
      - Recommend release/retain (transfer entry back to _customs_queue
        with tax_recommendation set; Customs takes the final decision)
    """
    q = broker.subscribe(INVESTIGATE_EVENT)
    while True:
        msg   = await q.get()
        tx    = msg.get("tx") or {}
        tx_id = tx.get("transaction_id")
        if not tx_id:
            continue
        if tx_id in _customs_queue or tx_id in _tax_queue:
            continue
        now_iso = datetime.now(timezone.utc).isoformat()
        _tax_queue[tx_id] = {
            "tx":                     tx,
            "alarm":                  msg.get("alarm") or {},
            "risk_score":             msg.get("risk_score") or "amber",
            "route":                  "amber",
            "escalated_from_customs": False,
            "agent_status":           "pending",
            "agent_verdict":          None,
            "created_at":             now_iso,
            "updated_at":             now_iso,
        }
        _broadcast_tax_update()


# ── Release After Investigation Factory ──────────────────────────────────────

async def _release_after_investigation_factory() -> None:
    """
    Subscribes to AGENT_RELEASE_EVENT, ORDER_VALIDATION, ARRIVAL_NOTIFICATION.
    Correlates all three by order identifier → RELEASE_AFTER_INVESTIGATION_EVENT.

    Validation and arrival typically arrive well before the agent verdict, so
    they are pre-buffered and matched when AGENT_RELEASE_EVENT eventually arrives.
    """
    _buffer:          dict[str, dict] = {}
    _pre_validation:  dict[str, dict] = {}
    _pre_arrival:     dict[str, dict] = {}

    async def _emit_if_ready(tx_id: str) -> None:
        entry = _buffer.get(tx_id, {})
        if "agent_release" not in entry or "validation" not in entry or "arrival" not in entry:
            return
        del _buffer[tx_id]
        ar  = entry["agent_release"]
        val = entry["validation"]
        await broker.publish(RELEASE_AFTER_INVESTIGATION_EVENT, {
            "tx":         ar["tx"],
            "verdict":    ar.get("verdict"),
            "reasoning":  ar.get("reasoning"),
            "validated":  val["validated"],
            "risk_score": "cleared",
        })

    async def _drain_agent_release() -> None:
        q = broker.subscribe(AGENT_RELEASE_EVENT)
        while True:
            item  = await q.get()
            tx_id = item["tx"]["transaction_id"]
            _buffer[tx_id] = {"agent_release": item}
            if tx_id in _pre_validation:
                _buffer[tx_id]["validation"] = _pre_validation.pop(tx_id)
            if tx_id in _pre_arrival:
                _buffer[tx_id]["arrival"] = _pre_arrival.pop(tx_id)
            await _emit_if_ready(tx_id)

    async def _drain_validation() -> None:
        q = broker.subscribe(ORDER_VALIDATION)
        while True:
            item  = await q.get()
            tx_id = item["tx"]["transaction_id"]
            if tx_id in _buffer:
                _buffer[tx_id]["validation"] = item
                await _emit_if_ready(tx_id)
            else:
                _pre_validation[tx_id] = item

    async def _drain_arrival() -> None:
        q = broker.subscribe(ARRIVAL_NOTIFICATION)
        while True:
            item  = await q.get()
            tx_id = (
                item.get("orderIdentifier")
                or item.get("transaction_id")
                or item.get("sales_order_id")
                or ((item.get("HouseConsignment") or {}).get("Order") or {}).get("orderIdentifier")
            )
            if not tx_id:
                continue
            if tx_id in _buffer:
                _buffer[tx_id]["arrival"] = item
                await _emit_if_ready(tx_id)
            else:
                _pre_arrival[tx_id] = item

    await asyncio.gather(_drain_agent_release(), _drain_validation(), _drain_arrival())


# ── DB Store Worker (all terminal event topics) ───────────────────────────────

async def _db_store_worker() -> None:
    """
    Terminal worker — persists fully processed transactions to the European
    Custom DB, live queue, and SSE clients.

    Subscribes to the terminal event topics:
      RELEASE_EVENT                     — green path  (no suspicious flag)
      RELEASE_AFTER_INVESTIGATION_EVENT — cleared     (no suspicious flag)
      AGENT_RETAIN_EVENT                — retained after Customs decision  (flag set)

    NOTE: RETAIN_EVENT is no longer terminal in the two-entity model. Items
    routed to the RED path are now picked up by _customs_listener_factory and
    parked in the Customs queue for the operator's final decision. They reach
    DB storage via AGENT_RETAIN_EVENT (Customs retains) or
    RELEASE_AFTER_INVESTIGATION_EVENT (Customs releases) once the operator
    has acted.
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

    await asyncio.gather(
        _drain(RELEASE_EVENT,                     False),
        _drain(RELEASE_AFTER_INVESTIGATION_EVENT,  False),
        _drain(AGENT_RETAIN_EVENT,                True),
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
    ai_q   = broker.subscribe(AI_ANALYSIS_EVENT)

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
    asyncio.create_task(_RT_consolidation_factory())
    asyncio.create_task(_order_validation_factory())
    asyncio.create_task(_arrival_notification_factory())
    asyncio.create_task(_release_factory())
    asyncio.create_task(_retain_factory())
    asyncio.create_task(_investigate_dispatch_factory())
    # Two-entity model: each office has its own listener.
    #   RED   → RETAIN_EVENT      → _customs_listener → _customs_queue
    #   AMBER → INVESTIGATE_EVENT → _tax_listener     → _tax_queue
    asyncio.create_task(_customs_listener_factory())
    asyncio.create_task(_tax_listener_factory())
    asyncio.create_task(_release_after_investigation_factory())
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
        RT_SCORE, ORDER_VALIDATION, ARRIVAL_NOTIFICATION,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
        AGENT_RETAIN_EVENT, AGENT_RELEASE_EVENT, RELEASE_AFTER_INVESTIGATION_EVENT,
    ]
    pipeline = {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: _broker.qsize(t) for t in topics},
        "stored_count":       get_transaction_count(),
        # Two-entity model: separate counters for the Customs and Tax queues
        # plus how many tax items are currently being analysed by the agent.
        "customs_queue":          len(_customs_queue),
        "tax_queue":              len(_tax_queue),
        "tax_queue_agent_running": sum(
            1 for v in _tax_queue.values() if v.get("agent_status") == "agent_running"
        ),
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


# ── Two-entity manual workflow API (revenue-guardian UI on :8080) ────────────
#
# Customs and Tax are exposed as two completely separate API surfaces, each
# with its own queue endpoint and SSE stream. The only inter-entity hops are
# /api/customs/{id}/escalate-to-tax and /api/tax/{id}/recommend, both of
# which physically transfer the entry between dicts and broadcast on both
# SSE streams so both UIs refresh together.

class CustomsDecisionPayload(BaseModel):
    action: str   # "release" | "retain"


class TaxRecommendationPayload(BaseModel):
    recommendation: str   # "release" | "retain"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Customs Office endpoints ─────────────────────────────────────────────────

@app.get("/api/customs/queue")
def api_customs_queue():
    """Snapshot of every transaction currently in the Customs queue,
    newest first. Includes RED items routed directly from RETAIN_EVENT
    AND items returned from Tax with a recommendation."""
    return _customs_snapshot()


@app.post("/api/customs/{transaction_id}/escalate-to-tax")
async def api_customs_escalate_to_tax(transaction_id: str):
    """
    Customs operator transfers a Customs queue item to the Tax queue
    requesting a Tax recommendation.

    Idempotency:
      404 — unknown transaction_id
      409 — item already in the Tax queue (or returned from Tax already)
    """
    entry = _customs_queue.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "transaction not found in Customs queue"})
    if entry.get("tax_recommendation"):
        return JSONResponse(status_code=409, content={"detail": "item already has a Tax recommendation; cannot re-escalate"})

    now = _now_iso()
    # Build a fresh Tax queue entry from the Customs entry. Mark the
    # escalation provenance so the Tax UI can display a small badge.
    _tax_queue[transaction_id] = {
        "tx":                     entry["tx"],
        "alarm":                  entry.get("alarm") or {},
        "risk_score":             entry.get("risk_score"),
        "route":                  entry.get("route"),
        "escalated_from_customs": True,
        "agent_status":           "pending",
        "agent_verdict":          None,
        "created_at":             now,
        "updated_at":             now,
    }
    # Remove from Customs queue.
    _customs_queue.pop(transaction_id, None)
    _broadcast_customs_update()
    _broadcast_tax_update()
    return _tax_entry_view(_tax_queue[transaction_id])


@app.post("/api/customs/{transaction_id}/decide")
async def api_customs_decide(transaction_id: str, payload: CustomsDecisionPayload):
    """
    Customs operator's terminal release / retain decision.

      release → publish AGENT_RELEASE_EVENT (the existing
                _release_after_investigation_factory correlates with
                validation + arrival and emits the terminal
                RELEASE_AFTER_INVESTIGATION_EVENT for storage)
      retain  → publish AGENT_RETAIN_EVENT directly (terminal)

    If the entry carries a Tax recommendation that disagrees with the
    operator's chosen action, custom_override=true is set on the published
    terminal event for downstream audit.
    """
    action = (payload.action or "").lower().strip()
    if action not in ("release", "retain"):
        return JSONResponse(status_code=400, content={"detail": "action must be 'release' or 'retain'"})

    entry = _customs_queue.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "transaction not found in Customs queue"})

    tx       = entry["tx"]
    alarm    = entry.get("alarm") or {}
    tax_rec  = entry.get("tax_recommendation")
    custom_override = bool(tax_rec and tax_rec != action)

    if action == "release":
        await broker.publish(AGENT_RELEASE_EVENT, {
            "tx":                  tx,
            "verdict":             "human_release",
            "reasoning":           "Released by Customs operator",
            "legislation_refs":    [],
            "decided_by":          "customs",
            "tax_recommendation":  tax_rec,
            "custom_override":     custom_override,
        })
    else:
        update_suspicion_level(transaction_id, "high")
        insert_ireland_queue({
            "transaction_id":   transaction_id,
            "seller_name":      tx.get("seller_name", ""),
            "seller_country":   tx.get("seller_country", ""),
            "item_description": tx.get("item_description", ""),
            "item_category":    tx.get("item_category", ""),
            "value":            tx.get("value"),
            "vat_rate":         tx.get("vat_rate"),
            "correct_vat_rate": tx.get("correct_vat_rate"),
            "vat_amount":       tx.get("vat_amount"),
            "transaction_date": tx.get("transaction_date", ""),
            "alarm_key":        alarm.get("alarm_key", ""),
            "deviation_pct":    alarm.get("deviation_pct"),
            "ratio_current":    alarm.get("ratio_current"),
            "ratio_historical": alarm.get("ratio_historical"),
            "agent_verdict":    "human_retain",
            "agent_reasoning":  "Retained by Customs operator",
            "queued_at":        _now_iso(),
        })
        await broker.publish(AGENT_RETAIN_EVENT, {
            "tx":                  tx,
            "verdict":             "human_retain",
            "reasoning":           "Retained by Customs operator",
            "risk_score":          "retained",
            "alarm_id":            alarm.get("id"),
            "alarm":               alarm,
            "decided_by":          "customs",
            "tax_recommendation":  tax_rec,
            "custom_override":     custom_override,
        })

    _customs_queue.pop(transaction_id, None)
    _broadcast_customs_update()
    return {
        "ok": True,
        "action": action,
        "transaction_id": transaction_id,
        "tax_recommendation": tax_rec,
        "custom_override": custom_override,
    }


# ── Tax Office endpoints ─────────────────────────────────────────────────────

@app.get("/api/tax/queue")
def api_tax_queue():
    """Snapshot of every transaction currently in the Tax queue, newest
    first. Includes AMBER items routed directly from INVESTIGATE_EVENT
    AND items escalated from Customs."""
    return _tax_snapshot()


@app.post("/api/tax/{transaction_id}/recommend")
async def api_tax_recommend(transaction_id: str, payload: TaxRecommendationPayload):
    """
    Tax operator publishes a non-binding recommendation. The entry is
    transferred from the Tax queue back to the Customs queue with the
    tax_recommendation field set. Customs makes the final call.
    """
    rec = (payload.recommendation or "").lower().strip()
    if rec not in ("release", "retain"):
        return JSONResponse(status_code=400, content={"detail": "recommendation must be 'release' or 'retain'"})

    entry = _tax_queue.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "transaction not found in Tax queue"})

    now = _now_iso()
    _customs_queue[transaction_id] = {
        "tx":                  entry["tx"],
        "alarm":               entry.get("alarm") or {},
        "risk_score":          entry.get("risk_score"),
        "route":               entry.get("route"),
        "tax_recommendation":  rec,
        "tax_recommended_at":  now,
        "created_at":          entry.get("created_at"),
        "updated_at":          now,
    }
    _tax_queue.pop(transaction_id, None)
    _broadcast_tax_update()
    _broadcast_customs_update()
    return _customs_entry_view(_customs_queue[transaction_id])


@app.post("/api/tax/{transaction_id}/run-agent")
async def api_tax_run_agent(transaction_id: str):
    """
    Trigger the VAT fraud detection agent on a Tax queue item.

    Returns immediately (202) after flipping agent_status → "agent_running";
    the verdict lands via the SSE stream when ready.

      404 — unknown transaction_id
      409 — agent already running, or item is no longer in Tax queue
    """
    global _manual_agent_executor

    entry = _tax_queue.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "transaction not found in Tax queue"})
    if entry.get("agent_status") == "agent_running":
        return JSONResponse(status_code=409, content={"detail": "agent already running"})

    if _manual_agent_executor is None:
        import concurrent.futures
        _manual_agent_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    now = _now_iso()
    entry["agent_status"] = "agent_running"
    entry["updated_at"]   = now
    _broadcast_tax_update()

    async def _run() -> None:
        from lib.agent_bridge import analyse_transaction_sync
        tx = entry["tx"]
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                _manual_agent_executor, analyse_transaction_sync, tx,
            )
            verdict = {
                "verdict":          result.get("verdict", "uncertain"),
                "reasoning":        result.get("reasoning", ""),
                "legislation_refs": result.get("legislation_refs", []),
                "line_verdicts":    result.get("line_verdicts", []),
                "completed_at":     _now_iso(),
            }
            insert_agent_log({
                "transaction_id":   tx.get("transaction_id"),
                "seller_name":      tx.get("seller_name", ""),
                "buyer_country":    tx.get("buyer_country", ""),
                "item_description": tx.get("item_description", ""),
                "item_category":    tx.get("item_category", ""),
                "value":            tx.get("value"),
                "vat_rate":         tx.get("vat_rate"),
                "correct_vat_rate": tx.get("correct_vat_rate"),
                "verdict":          verdict["verdict"],
                "reasoning":        verdict["reasoning"],
                "legislation_refs": _json.dumps(verdict["legislation_refs"]),
                "sent_to_ireland":  0,
                "processed_at":     verdict["completed_at"],
            })
            # Publish to AI_ANALYSIS_EVENT so the data hub writer can populate
            # line_item_ai_analysis. This is the only entry point that produces
            # an AI verdict — agent runs are tax-officer-triggered, not every
            # transaction gets one (matching the user's intent that AI analysis
            # is selectively applied).
            await broker.publish(AI_ANALYSIS_EVENT, {
                "tx":               tx,
                "verdict":          verdict["verdict"],
                "reasoning":        verdict["reasoning"],
                "legislation_refs": verdict["legislation_refs"],
                "line_verdicts":    verdict["line_verdicts"],
                "completed_at":     verdict["completed_at"],
            })
        except Exception as exc:
            import traceback
            print(f"[tax_agent] error: {exc}\n{traceback.format_exc()}")
            verdict = {
                "verdict":          "uncertain",
                "reasoning":        f"Agent error: {exc}",
                "legislation_refs": [],
                "line_verdicts":    [],
                "completed_at":     _now_iso(),
                "error":            True,
            }
        # Re-fetch in case the entry was moved/removed mid-run.
        live = _tax_queue.get(transaction_id)
        if live is None:
            return
        live["agent_verdict"] = verdict
        live["agent_status"]  = "agent_done"
        live["updated_at"]    = _now_iso()
        _broadcast_tax_update()

    _track_factory_task(_run())
    return JSONResponse(status_code=202, content=_tax_entry_view(entry))


@app.get("/api/transactions/{transaction_id}/timeline")
def api_transaction_timeline(transaction_id: str):
    """
    Full chronological event history for a single transaction. Walks the
    persisted event store (data/events/<topic>/<order_id>_<topic>.json) and
    returns every event sharing this transaction_id, sorted oldest-first.

    Used by the revenue-guardian case-detail page so the operator can see the
    full lifecycle of an investigation (sales order → risk scores → validation
    → arrival → routing → investigate event → eventual decision).
    """
    from lib.event_store import get_events_for_order
    return get_events_for_order(transaction_id)


def _make_sse_stream(snapshot_fn, sse_set: set[asyncio.Queue]):
    """Build an SSE StreamingResponse around a snapshot function and a
    subscriber set. Used by both the Customs and Tax queue streams."""
    async def _stream(request: Request):
        q: asyncio.Queue = asyncio.Queue(maxsize=20)
        sse_set.add(q)
        try:
            initial = _json.dumps(snapshot_fn())
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
                sse_set.discard(q)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    return _stream


@app.get("/api/customs/queue/stream")
async def api_customs_queue_stream(request: Request):
    """SSE stream of the Customs queue. Initial snapshot on connect, plus
    a fresh snapshot whenever the queue changes (new RED listener arrival,
    escalation to Tax removing an entry, recommendation back from Tax,
    or terminal Customs decision)."""
    return await _make_sse_stream(_customs_snapshot, _customs_sse)(request)


@app.get("/api/tax/queue/stream")
async def api_tax_queue_stream(request: Request):
    """SSE stream of the Tax queue. Initial snapshot on connect, plus
    a fresh snapshot whenever the queue changes (new AMBER listener
    arrival, escalation from Customs adding an entry, agent run start/
    finish, or recommendation back to Customs removing an entry)."""
    return await _make_sse_stream(_tax_snapshot, _tax_sse)(request)


# ── Simulation control ────────────────────────────────────────────────────────

@app.get("/api/simulation/pipeline")
def sim_pipeline():
    """Return per-topic event counts (persisted files) and live broker queue sizes."""
    from lib.event_store import event_count, count_field_value
    from lib.broker import broker as _broker
    topics = [
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ARRIVAL_NOTIFICATION,
        RELEASE_EVENT, RETAIN_EVENT, INVESTIGATE_EVENT,
        AGENT_RETAIN_EVENT, AGENT_RELEASE_EVENT, RELEASE_AFTER_INVESTIGATION_EVENT,
    ]
    return {
        "events":             {t: event_count(t) for t in topics},
        "queues":             {t: _broker.qsize(t) for t in topics},
        "stored_count":       get_transaction_count(),
        # Two-entity model: separate counters for Customs and Tax queues.
        "customs_queue":          len(_customs_queue),
        "tax_queue":              len(_tax_queue),
        "tax_queue_agent_running": sum(
            1 for v in _tax_queue.values() if v.get("agent_status") == "agent_running"
        ),
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
    # Clear both entity queues and push fresh empty snapshots on each SSE
    # stream so the Revenue Guardian Customs and Tax Authority pages drop
    # all the stale rows immediately.
    _customs_queue.clear()
    _tax_queue.clear()
    _broadcast_customs_update()
    _broadcast_tax_update()
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
