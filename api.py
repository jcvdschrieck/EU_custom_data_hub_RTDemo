"""
European Custom Data Hub — Real-Time Demo API  (v4.0)
FastAPI backend on port 8505.

Message flow (publish-subscribe)
─────────────────────────────────────────────────────────────────────────────

 Simulation loop
     │  publishes each raw transaction (inter-event pacing per sim clock)
     ▼
 ┌────────────────────────────────────────────────────────────────────────┐
 │  Sales-order Event Broker  (topic: sales_order_event)                 │
 └───────────┬──────────────────────┬──────────────────────┬─────────────┘
             │                      │                      │
             ▼                      ▼                      ▼
 ┌────────────────────┐  ┌────────────────────┐  ┌──────────────────────┐
 │ _RT_risk_          │  │ _RT_risk_          │  │ _order_validation_   │
 │ monitoring_1_      │  │ monitoring_2_      │  │ factory              │
 │ factory            │  │ factory            │  │                      │
 │ (VAT ratio check)  │  │ (watchlist check)  │  │ validates fields     │
 └────────┬───────────┘  └────────┬───────────┘  └──────────┬───────────┘
          │                       │                          │
          ▼                       ▼                          │
 RT_risk_1_outcome_broker  RT_risk_2_outcome_broker          │
          │                       │                          │
          └──────────┬────────────┘                          │
                     ▼                                       │
          ┌──────────────────────┐                           │
          │ _RT_consolidation_   │                           │
          │ factory              │                           │
          │ green / amber / red  │                           │
          └──────────┬───────────┘                           │
                     │                                       │
                     ▼                                       ▼
                 RT_score_broker            Order_validation_broker
                     │                                       │
                     └──────────────┬────────────────────────┘
                                    ▼
                          ┌──────────────────────┐
                          │  _release_factory    │
                          │  combines score +    │
                          │  validation          │
                          └──────────┬───────────┘
                                     │
                                     ▼
                          Release_Event_Broker  (topic: release_event)
                                     │
                                     ▼
                          ┌──────────────────────┐
                          │  _db_store_worker    │
                          │  INSERT + flag       │
                          │  live queue + SSE    │
                          └──────────────────────┘

 AI Agent — triggered manually from the dashboard
 ─────────────────────────────────────────────────
 POST /api/agent/analyse/{transaction_id}  →  _agent_worker  →  verdict
   • incorrect → suspicion_level='high', insert ireland_queue
   • correct/uncertain → clear suspicious flag

Endpoints
─────────
GET  /health
GET  /api/queue                     latest 30 live transactions (REST snapshot)
GET  /api/queue/stream              SSE stream — one transaction per event
GET  /api/transactions              paginated historical query
GET  /api/metrics                   VAT aggregates with filters
GET  /api/alarms                    alarm list (active_only optional)
GET  /api/suspicious                last 50 suspicious transactions
GET  /api/agent-log                 agent analysis history (with legislation_refs)
GET  /api/agent-processing          transactions currently being analysed
POST /api/agent/analyse/{tx_id}     trigger AI agent from dashboard
GET  /api/ireland-queue             cases forwarded to Ireland investigation
GET  /api/ireland-case/{tx_id}      full case detail
GET  /api/simulation/status
POST /api/simulation/start
POST /api/simulation/pause
POST /api/simulation/resume
POST /api/simulation/speed          body: {"speed": <float>}
POST /api/simulation/reset
GET  /api/catalog/suppliers
GET  /api/catalog/countries
Static: /ireland-app/               standalone Irish Revenue investigation app
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
    clear_suspicious_flag,
)
from lib.simulator import state, simulation_loop
from lib.catalog import SUPPLIERS, COUNTRY_NAMES

# ── Feature flags ─────────────────────────────────────────────────────────────

# When True, _investigator_factory + _investigation_agent_worker run as
# before — INVESTIGATE_EVENT items are auto-routed to the LM Studio agent and
# their verdict published as AGENT_RELEASE_EVENT / AGENT_RETAIN_EVENT.
#
# When False (current state), those two tasks are NOT started, and the new
# _investigation_holding_worker takes their place: every INVESTIGATE_EVENT
# lands in _pending_investigations and waits for a human operator (the
# revenue-guardian UI on :8080) to manually trigger the agent + decide.
# The original code is kept in place so this can be flipped back trivially.
AUTO_INVESTIGATION_AGENT: bool = False

# ── In-memory state ───────────────────────────────────────────────────────────

_live_queue:          deque[dict]        = deque(maxlen=QUEUE_SIZE)
_live_alarms:         list[dict]         = []
_agent_processing:    dict[str, dict]    = {}   # tx_id → snapshot while analysing
_sse_queues:          set[asyncio.Queue] = set()   # live-transaction stream subscribers
_sim_state_sse:       set[asyncio.Queue] = set()   # pipeline + status stream subscribers
_agent_queue:         asyncio.Queue | None = None  # manual POST /api/agent/analyse
_investigation_queue: asyncio.Queue | None = None  # legacy auto investigation pipeline

# Pending investigations awaiting manual agent run + decision (managed from
# the revenue-guardian UI). Keyed by transaction_id. Lost on server restart —
# intentional, single-operator demo. Each entry:
#   {
#     "tx":              <full sales-order tx dict>,
#     "alarm":           <alarm metadata or {}>,
#     "status":          "pending" | "agent_running" | "agent_done" | "decided",
#     "agent_verdict":   None | {"verdict", "reasoning", "legislation_refs"},
#     "decision":        None | "release" | "retain",
#     "created_at":      ISO8601,
#     "updated_at":      ISO8601,
#   }
_pending_investigations: dict[str, dict] = {}
_pending_sse:            set[asyncio.Queue] = set()   # subscribers to pending-list updates
_manual_agent_executor   = None   # lazy-initialised ThreadPoolExecutor for manual agent runs

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


# ── Investigator Factory ──────────────────────────────────────────────────────

async def _investigator_factory() -> None:
    """
    Subscribes to INVESTIGATE_EVENT.
    IE-bound orders → pushed to _investigation_queue for VAT agent processing.
    Non-IE orders   → auto-released via AGENT_RELEASE_EVENT (uncertain verdict).
    """
    q = broker.subscribe(INVESTIGATE_EVENT)
    while True:
        msg = await q.get()
        tx = msg["tx"]
        buyer_country = tx.get("buyer_country") or (
            (tx.get("CountryOfDestination") or {}).get("country", "")
        )
        item = {"tx": tx, "alarm": msg.get("alarm", {})}
        if buyer_country == "IE" and _investigation_queue is not None:
            await _investigation_queue.put(item)
        else:
            # Non-IE amber orders: auto-release without deep investigation
            await broker.publish(AGENT_RELEASE_EVENT, {
                "tx":               tx,
                "verdict":          "uncertain",
                "reasoning":        "Non-IE order: auto-released without deep investigation.",
                "legislation_refs": [],
            })


# ── Investigation Agent Worker ────────────────────────────────────────────────

async def _investigation_agent_worker() -> None:
    """
    Processes _investigation_queue (FIFO) with the VAT fraud detection agent.
      incorrect        → AGENT_RETAIN_EVENT + ireland_queue + agent_log
      correct/uncertain → AGENT_RELEASE_EVENT + agent_log
    """
    import concurrent.futures
    from lib.agent_bridge import analyse_transaction_sync

    loop     = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    while True:
        item  = await _investigation_queue.get()
        tx    = item["tx"]
        alarm = item.get("alarm", {})
        tx_id = tx["transaction_id"]

        if tx_id in _agent_processing:
            _investigation_queue.task_done()
            continue

        _agent_processing[tx_id] = {
            "transaction_id":   tx_id,
            "seller_name":      tx.get("seller_name", ""),
            "item_description": tx.get("item_description", ""),
            "value":            tx.get("value"),
            "vat_rate":         tx.get("vat_rate"),
            "started_at":       datetime.now(timezone.utc).isoformat(),
            "source":           "investigation_pipeline",
        }

        try:
            result           = await loop.run_in_executor(executor, analyse_transaction_sync, tx)
            verdict          = result.get("verdict", "uncertain")
            reasoning        = result.get("reasoning", "")
            legislation_refs = result.get("legislation_refs", [])
            now_str          = datetime.now(timezone.utc).isoformat()

            insert_agent_log({
                "transaction_id":   tx_id,
                "seller_name":      tx.get("seller_name", ""),
                "buyer_country":    tx.get("buyer_country", ""),
                "item_description": tx.get("item_description", ""),
                "item_category":    tx.get("item_category", ""),
                "value":            tx.get("value"),
                "vat_rate":         tx.get("vat_rate"),
                "correct_vat_rate": tx.get("correct_vat_rate"),
                "verdict":          verdict,
                "reasoning":        reasoning,
                "legislation_refs": _json.dumps(legislation_refs),
                "sent_to_ireland":  1 if verdict == "incorrect" else 0,
                "processed_at":     now_str,
            })

            if verdict == "incorrect":
                update_suspicion_level(tx_id, "high")
                insert_ireland_queue({
                    "transaction_id":   tx_id,
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
                    "agent_verdict":    verdict,
                    "agent_reasoning":  reasoning,
                    "queued_at":        now_str,
                })
                await broker.publish(AGENT_RETAIN_EVENT, {
                    "tx":         tx,
                    "verdict":    verdict,
                    "reasoning":  reasoning,
                    "risk_score": "retained",
                    "alarm_id":   alarm.get("id"),
                    "alarm":      alarm,
                })
            else:
                clear_suspicious_flag(tx_id)
                await broker.publish(AGENT_RELEASE_EVENT, {
                    "tx":               tx,
                    "verdict":          verdict,
                    "reasoning":        reasoning,
                    "legislation_refs": legislation_refs,
                })

        except Exception as exc:
            import traceback
            print(f"[investigation_agent_worker] error: {exc}\n{traceback.format_exc()}")
            await broker.publish(AGENT_RELEASE_EVENT, {
                "tx":               tx,
                "verdict":          "uncertain",
                "reasoning":        f"Agent error: {exc}",
                "legislation_refs": [],
            })
        finally:
            _agent_processing.pop(tx_id, None)
            _investigation_queue.task_done()


# ── Manual investigation flow (revenue-guardian UI on :8080) ─────────────────
#
# When AUTO_INVESTIGATION_AGENT is False, the holding worker below runs in
# place of _investigator_factory + _investigation_agent_worker. It subscribes
# to INVESTIGATE_EVENT and parks every item in _pending_investigations,
# waiting for the operator to manually trigger the agent and decide.

def _pending_entry_view(entry: dict) -> dict:
    """Flatten one _pending_investigations entry into the JSON shape the UI
    consumes. Strips heavy nested fields and exposes the flat tx columns the
    revenue-guardian dashboard already knows how to render."""
    tx = entry.get("tx", {}) or {}
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
        "risk_score":       entry.get("risk_score"),
        "alarm":            entry.get("alarm") or {},
        "status":           entry.get("status"),
        "agent_verdict":    entry.get("agent_verdict"),
        "decision":         entry.get("decision"),
        # Customs ↔ Tax workflow state machine. Initialised by the holding
        # worker as "customs_pending"; transitions are driven by the
        # /submit-to-tax and /recommend endpoints. Customs is master.
        "workflow_status":     entry.get("workflow_status") or "customs_pending",
        "tax_recommendation":  entry.get("tax_recommendation"),
        "tax_recommended_at":  entry.get("tax_recommended_at"),
        "submitted_to_tax_at": entry.get("submitted_to_tax_at"),
        "created_at":       entry.get("created_at"),
        "updated_at":       entry.get("updated_at"),
    }


def _pending_snapshot() -> list[dict]:
    """Return the full pending list as a JSON-serialisable list, newest first."""
    items = [_pending_entry_view(e) for e in _pending_investigations.values()]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items


def _broadcast_pending_update() -> None:
    """Push the current snapshot to every connected SSE subscriber.
    Synchronous fan-out via put_nowait so callers don't need to await."""
    if not _pending_sse:
        return
    try:
        payload = _json.dumps(_pending_snapshot())
    except Exception:
        return
    dead = set()
    for q in _pending_sse:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            # Subscriber is lagging — drop this frame, the next change will
            # produce another snapshot.
            pass
        except Exception:
            dead.add(q)
    _pending_sse.difference_update(dead)


async def _investigation_holding_worker() -> None:
    """
    Manual-mode replacement for _investigator_factory + _investigation_agent_worker.

    Subscribes to INVESTIGATE_EVENT and parks every incoming item in
    _pending_investigations with status="pending". The operator (revenue-
    guardian UI) is expected to GET /api/investigations/pending (or subscribe
    to /api/investigations/stream), trigger the agent via POST run-agent, and
    finally publish a release/retain decision via POST decide.
    """
    q = broker.subscribe(INVESTIGATE_EVENT)
    while True:
        msg   = await q.get()
        tx    = msg.get("tx") or {}
        tx_id = tx.get("transaction_id")
        if not tx_id:
            continue
        # Idempotent: if the same investigation is re-published, keep the
        # earliest entry so we don't reset operator state.
        if tx_id in _pending_investigations:
            continue
        now_iso = datetime.now(timezone.utc).isoformat()
        _pending_investigations[tx_id] = {
            "tx":              tx,
            "alarm":           msg.get("alarm") or {},
            "risk_score":      msg.get("risk_score"),
            "status":          "pending",
            "agent_verdict":   None,
            "decision":        None,
            # Customs ↔ Tax workflow always starts at customs_pending —
            # the Customs operator is the first to triage.
            "workflow_status":     "customs_pending",
            "tax_recommendation":  None,
            "tax_recommended_at":  None,
            "submitted_to_tax_at": None,
            "created_at":      now_iso,
            "updated_at":      now_iso,
        }
        _broadcast_pending_update()


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

    Subscribes to all four terminal event topics:
      RELEASE_EVENT                     — green path  (no suspicious flag)
      RETAIN_EVENT                      — red path    (suspicious flag set)
      RELEASE_AFTER_INVESTIGATION_EVENT — cleared     (no suspicious flag)
      AGENT_RETAIN_EVENT                — retained after investigation (flag set)
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
        _drain(RETAIN_EVENT,                      True),
        _drain(RELEASE_AFTER_INVESTIGATION_EVENT,  False),
        _drain(AGENT_RETAIN_EVENT,                True),
    )


# ── Agent Worker (triggered manually from dashboard) ─────────────────────────

async def _agent_worker() -> None:
    """
    Reads from _agent_queue, which is populated by POST /api/agent/analyse.
    Runs the Claude-powered VAT compliance analysis in a thread pool.
    verdict 'incorrect' → escalate to high + insert ireland_queue
    verdict 'correct'/'uncertain' → clear suspicious flag
    """
    import concurrent.futures
    from lib.agent_bridge import analyse_transaction_sync

    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    while True:
        item  = await _agent_queue.get()
        tx    = item["tx"]
        alarm = item.get("alarm", {})
        tx_id = tx["transaction_id"]

        _agent_processing[tx_id] = {
            "transaction_id":   tx_id,
            "seller_name":      tx["seller_name"],
            "item_description": tx["item_description"],
            "value":            tx["value"],
            "vat_rate":         tx["vat_rate"],
            "started_at":       datetime.now(timezone.utc).isoformat(),
        }

        try:
            result = await loop.run_in_executor(executor, analyse_transaction_sync, tx)

            verdict          = result.get("verdict", "uncertain")
            reasoning        = result.get("reasoning", "")
            legislation_refs = result.get("legislation_refs", [])
            now_str          = datetime.now(timezone.utc).isoformat()

            insert_agent_log({
                "transaction_id":   tx_id,
                "seller_name":      tx["seller_name"],
                "buyer_country":    tx["buyer_country"],
                "item_description": tx["item_description"],
                "item_category":    tx["item_category"],
                "value":            tx["value"],
                "vat_rate":         tx["vat_rate"],
                "correct_vat_rate": tx["correct_vat_rate"],
                "verdict":          verdict,
                "reasoning":        reasoning,
                "legislation_refs": _json.dumps(legislation_refs),
                "sent_to_ireland":  1 if verdict == "incorrect" else 0,
                "processed_at":     now_str,
            })

            if verdict == "incorrect":
                update_suspicion_level(tx_id, "high")
                insert_ireland_queue({
                    "transaction_id":   tx_id,
                    "seller_name":      tx["seller_name"],
                    "seller_country":   tx["seller_country"],
                    "item_description": tx["item_description"],
                    "item_category":    tx["item_category"],
                    "value":            tx["value"],
                    "vat_rate":         tx["vat_rate"],
                    "correct_vat_rate": tx["correct_vat_rate"],
                    "vat_amount":       tx["vat_amount"],
                    "transaction_date": tx["transaction_date"],
                    "alarm_key":        alarm.get("alarm_key", ""),
                    "deviation_pct":    alarm.get("deviation_pct"),
                    "ratio_current":    alarm.get("ratio_current"),
                    "ratio_historical": alarm.get("ratio_historical"),
                    "agent_verdict":    verdict,
                    "agent_reasoning":  reasoning,
                    "queued_at":        now_str,
                })
            else:
                clear_suspicious_flag(tx_id)

        except Exception as exc:
            import traceback
            print(f"[agent_worker] error: {exc}\n{traceback.format_exc()}")
        finally:
            _agent_processing.pop(tx_id, None)
            _agent_queue.task_done()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _agent_queue, _investigation_queue
    from lib.database import init_european_custom_db, init_simulation_db
    init_european_custom_db()
    init_simulation_db()

    _agent_queue         = asyncio.Queue()
    _investigation_queue = asyncio.Queue()

    asyncio.create_task(simulation_loop(_fire_transactions))
    asyncio.create_task(_RT_risk_monitoring_1_factory())
    asyncio.create_task(_RT_risk_monitoring_2_factory())
    asyncio.create_task(_RT_consolidation_factory())
    asyncio.create_task(_order_validation_factory())
    asyncio.create_task(_arrival_notification_factory())
    asyncio.create_task(_release_factory())
    asyncio.create_task(_retain_factory())
    asyncio.create_task(_investigate_dispatch_factory())
    if AUTO_INVESTIGATION_AGENT:
        # Legacy auto-pipeline: dispatcher + agent worker drive investigations
        # without human input. Disabled — see AUTO_INVESTIGATION_AGENT comment.
        asyncio.create_task(_investigator_factory())
        asyncio.create_task(_investigation_agent_worker())
    else:
        # Manual mode: investigations land in _pending_investigations and wait
        # for the revenue-guardian UI operator to trigger the agent + decide.
        asyncio.create_task(_investigation_holding_worker())
    asyncio.create_task(_release_after_investigation_factory())
    asyncio.create_task(_db_store_worker())
    asyncio.create_task(_agent_worker())
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
    s["active_alarms"]           = len(get_alarms(active_only=True))
    s["agent_queue_len"]         = _agent_queue.qsize() if _agent_queue else 0
    s["investigation_queue_len"] = _investigation_queue.qsize() if _investigation_queue else 0
    s["agent_processing"]        = len(_agent_processing)

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
        "investigation_queue": _investigation_queue.qsize() if _investigation_queue else 0,
        # Live depth of the manual-review holding dict — drives the
        # "Pending Investigations" node on the simulation diagram.
        "pending_investigations": len(_pending_investigations),
        # Number of pending entries currently being analysed by the agent
        # (status == "agent_running"). Drives the "under analysis" count on
        # the VAT Fraud Detection Agent block.
        "pending_investigations_running": sum(
            1 for v in _pending_investigations.values()
            if v.get("status") == "agent_running"
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


# ── Agent log, processing & dashboard trigger ─────────────────────────────────

@app.get("/api/agent-log")
def api_agent_log(limit: int = Query(100, ge=1, le=500)):
    return get_agent_log(limit=limit)


@app.get("/api/agent-processing")
def api_agent_processing():
    return list(_agent_processing.values())


@app.post("/api/agent/analyse/{transaction_id}")
def api_trigger_agent(transaction_id: str):
    """
    Dashboard endpoint — queues a transaction for AI agent analysis.
    Fetches the transaction and its alarm context from the DB, then
    pushes to _agent_queue for processing by _agent_worker.
    """
    if _agent_queue is None:
        return JSONResponse(status_code=503, content={"detail": "Agent not ready"})

    tx = get_transaction_by_id(transaction_id)
    if not tx:
        return JSONResponse(status_code=404, content={"detail": "Transaction not found"})

    if any(p["transaction_id"] == transaction_id for p in _agent_processing.values()):
        return {"ok": False, "reason": "already processing"}

    # Find alarm context from in-memory alarms or DB
    alarm_key = f"{tx['seller_id']}|{tx['buyer_country']}"
    alarm_ctx = next(
        (a for a in _live_alarms if a.get("alarm_key") == alarm_key),
        {},
    )

    _agent_queue.put_nowait({"tx": tx, "alarm": alarm_ctx})
    return {"ok": True, "queued": transaction_id}


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


# ── Manual investigations API (revenue-guardian UI on :8080) ──────────────────

@app.get("/api/investigations/pending")
def api_investigations_pending():
    """
    Snapshot of every investigation currently parked in the holding queue,
    awaiting manual agent run + release/retain decision. Newest first.
    Powered by _pending_investigations, populated by _investigation_holding_worker
    when AUTO_INVESTIGATION_AGENT is False.
    """
    return _pending_snapshot()


class InvestigationDecisionPayload(BaseModel):
    action: str   # "release" | "retain"


class InvestigationRecommendationPayload(BaseModel):
    recommendation: str   # "release" | "retain"


@app.post("/api/investigations/{transaction_id}/submit-to-tax")
async def api_investigations_submit_to_tax(transaction_id: str):
    """
    Customs operator escalates an investigation to the Tax Authority queue.

    Workflow transition: customs_pending → at_tax. The entry stays in the
    holding dict but disappears from the Customs Authority view (filtered to
    customs_pending + recommended_*) and starts appearing on the Tax
    Authority page (filtered to at_tax). Tax then runs the agent if needed
    and publishes a recommendation via /recommend, which moves the entry to
    recommended_release / recommended_retain — back at the Customs page for
    final decision.

    Idempotency: 404 if missing, 409 if already past customs_pending.
    """
    entry = _pending_investigations.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "investigation not found in pending queue"})
    if entry.get("workflow_status") != "customs_pending":
        return JSONResponse(status_code=409, content={"detail": f"investigation is in workflow state '{entry.get('workflow_status')}', expected 'customs_pending'"})

    now_iso = datetime.now(timezone.utc).isoformat()
    entry["workflow_status"]     = "at_tax"
    entry["submitted_to_tax_at"] = now_iso
    entry["updated_at"]          = now_iso
    _broadcast_pending_update()
    return _pending_entry_view(entry)


@app.post("/api/investigations/{transaction_id}/recommend")
async def api_investigations_recommend(transaction_id: str, payload: InvestigationRecommendationPayload):
    """
    Tax Authority operator publishes a non-binding recommendation on a
    transaction Customs has submitted for review.

    Workflow transition: at_tax → recommended_release / recommended_retain.
    The entry stays in the holding dict; it disappears from the Tax view
    and reappears on the Customs page with the recommendation displayed
    as a colored badge alongside the (now-only) Release / Retain action
    buttons. The Customs operator's call via /decide is what actually
    publishes the terminal event.
    """
    rec = (payload.recommendation or "").lower().strip()
    if rec not in ("release", "retain"):
        return JSONResponse(status_code=400, content={"detail": "recommendation must be 'release' or 'retain'"})

    entry = _pending_investigations.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "investigation not found in pending queue"})
    if entry.get("workflow_status") != "at_tax":
        return JSONResponse(status_code=409, content={"detail": f"investigation is in workflow state '{entry.get('workflow_status')}', expected 'at_tax'"})

    now_iso = datetime.now(timezone.utc).isoformat()
    entry["workflow_status"]    = f"recommended_{rec}"
    entry["tax_recommendation"] = rec
    entry["tax_recommended_at"] = now_iso
    entry["updated_at"]         = now_iso
    _broadcast_pending_update()
    return _pending_entry_view(entry)


@app.post("/api/investigations/{transaction_id}/decide")
async def api_investigations_decide(transaction_id: str, payload: InvestigationDecisionPayload):
    """
    Operator-driven release / retain decision for a pending investigation.

      release → publish AGENT_RELEASE_EVENT (the existing
                _release_after_investigation_factory correlates with
                validation + arrival and emits the terminal
                RELEASE_AFTER_INVESTIGATION_EVENT for storage)
      retain  → publish AGENT_RETAIN_EVENT directly (terminal)

    The entry is removed from _pending_investigations and an SSE update is
    broadcast so any listening UI can drop the row from its list.
    """
    action = (payload.action or "").lower().strip()
    if action not in ("release", "retain"):
        return JSONResponse(status_code=400, content={"detail": "action must be 'release' or 'retain'"})

    entry = _pending_investigations.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "investigation not found in pending queue"})
    if entry["status"] == "decided":
        return JSONResponse(status_code=409, content={"detail": "investigation already decided"})

    tx       = entry["tx"]
    alarm    = entry.get("alarm") or {}
    verdict  = entry.get("agent_verdict") or {}
    tax_rec  = entry.get("tax_recommendation")

    # Customs is master, but we record an audit flag when the Customs
    # operator overrides a Tax Authority recommendation. The flag is
    # included on the published terminal event so any downstream consumer
    # can flag the divergence.
    custom_override = bool(tax_rec and tax_rec != action)

    if action == "release":
        await broker.publish(AGENT_RELEASE_EVENT, {
            "tx":                  tx,
            "verdict":             verdict.get("verdict") or "human_release",
            "reasoning":           verdict.get("reasoning") or "Released by operator",
            "legislation_refs":    verdict.get("legislation_refs") or [],
            "decided_by":          "human",
            "tax_recommendation":  tax_rec,
            "custom_override":     custom_override,
        })
    else:   # retain
        # Mirror the auto-pipeline side effects so the suspicious flag and
        # the Ireland queue stay consistent with what the legacy worker did.
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
            "agent_verdict":    verdict.get("verdict") or "human_retain",
            "agent_reasoning":  verdict.get("reasoning") or "Retained by operator",
            "queued_at":        datetime.now(timezone.utc).isoformat(),
        })
        await broker.publish(AGENT_RETAIN_EVENT, {
            "tx":                  tx,
            "verdict":             verdict.get("verdict") or "human_retain",
            "reasoning":           verdict.get("reasoning") or "Retained by operator",
            "risk_score":          "retained",
            "alarm_id":            alarm.get("id"),
            "alarm":               alarm,
            "decided_by":          "human",
            "tax_recommendation":  tax_rec,
            "custom_override":     custom_override,
        })

    # Remove from pending and broadcast a final snapshot so listeners drop it.
    _pending_investigations.pop(transaction_id, None)
    _broadcast_pending_update()
    return {
        "ok": True,
        "action": action,
        "transaction_id": transaction_id,
        "tax_recommendation": tax_rec,
        "custom_override": custom_override,
    }


@app.post("/api/investigations/{transaction_id}/run-agent")
async def api_investigations_run_agent(transaction_id: str):
    """
    Trigger the VAT fraud detection agent on a pending investigation.

    The endpoint returns immediately (202) after marking the entry
    "agent_running"; the actual analysis runs in a background task and the
    UI receives the verdict via /api/investigations/stream when it is ready.

    Idempotency:
      404 — unknown transaction_id
      409 — entry is already agent_running or already decided
    """
    global _manual_agent_executor

    entry = _pending_investigations.get(transaction_id)
    if not entry:
        return JSONResponse(status_code=404, content={"detail": "investigation not found in pending queue"})
    if entry["status"] == "agent_running":
        return JSONResponse(status_code=409, content={"detail": "agent already running for this investigation"})
    if entry["status"] == "decided":
        return JSONResponse(status_code=409, content={"detail": "investigation already decided"})

    # Lazily build a small thread pool the first time we need it. Reused
    # across calls so we don't spawn a new pool on every request.
    if _manual_agent_executor is None:
        import concurrent.futures
        _manual_agent_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    now_iso = datetime.now(timezone.utc).isoformat()
    entry["status"]     = "agent_running"
    entry["updated_at"] = now_iso
    _broadcast_pending_update()

    # NOTE: this background runner is intentionally exempt from sim-time
    # pausing. The actual analysis is a synchronous LM Studio HTTP call
    # executed inside a thread pool, and the asyncio task only awaits its
    # completion — there is no factory delay to gate. If the user pauses or
    # resets mid-analysis the asyncio task is cancelled (the future's result
    # is then discarded) but the underlying LLM call finishes on its thread.
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
                "completed_at":     datetime.now(timezone.utc).isoformat(),
            }
            # Persist a row to agent_log so the audit trail matches the
            # auto-pipeline behaviour.
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
                "sent_to_ireland":  0,   # the human decision drives any forwarding
                "processed_at":     verdict["completed_at"],
            })
        except Exception as exc:
            import traceback
            print(f"[manual_agent] error: {exc}\n{traceback.format_exc()}")
            verdict = {
                "verdict":          "uncertain",
                "reasoning":        f"Agent error: {exc}",
                "legislation_refs": [],
                "completed_at":     datetime.now(timezone.utc).isoformat(),
                "error":            True,
            }
        # Re-fetch the entry in case it was decided/removed mid-run.
        live = _pending_investigations.get(transaction_id)
        if live is None:
            return
        live["agent_verdict"] = verdict
        live["status"]        = "agent_done"
        live["updated_at"]    = datetime.now(timezone.utc).isoformat()
        _broadcast_pending_update()

    _track_factory_task(_run())
    return JSONResponse(status_code=202, content=_pending_entry_view(entry))


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


@app.get("/api/investigations/stream")
async def api_investigations_stream(request: Request):
    """
    SSE stream carrying the full pending-investigations list. Pushed every
    time an item is added (new INVESTIGATE_EVENT), an agent run starts/finishes,
    or a decision removes an item. Initial snapshot delivered on connect.
    """
    q: asyncio.Queue = asyncio.Queue(maxsize=20)
    _pending_sse.add(q)

    try:
        initial = _json.dumps(_pending_snapshot())
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
            _pending_sse.discard(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        "investigation_queue": _investigation_queue.qsize() if _investigation_queue else 0,
        # Live depth of the manual-review holding dict — drives the
        # "Pending Investigations" node on the simulation diagram.
        "pending_investigations": len(_pending_investigations),
        # Number of pending entries currently being analysed by the agent
        # (status == "agent_running"). Drives the "under analysis" count on
        # the VAT Fraud Detection Agent block.
        "pending_investigations_running": sum(
            1 for v in _pending_investigations.values()
            if v.get("status") == "agent_running"
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
    s["active_alarms"]           = len(get_alarms(active_only=True))
    s["agent_queue_len"]         = _agent_queue.qsize() if _agent_queue else 0
    s["investigation_queue_len"] = _investigation_queue.qsize() if _investigation_queue else 0
    s["agent_processing"]        = len(_agent_processing)
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
    _agent_processing.clear()
    if _investigation_queue:
        while not _investigation_queue.empty():
            try: _investigation_queue.get_nowait()
            except Exception: break
    # Cancel every in-flight delayed factory task (Order Validation, Arrival
    # Notification, manual agent runs) so no residual events fire after the
    # reset has emptied the pipeline. Tasks already in the middle of an
    # `await broker.publish(...)` will still complete that single publish,
    # but anything still inside `asyncio.sleep(...)` cancels cleanly.
    for t in list(_inflight_factory_tasks):
        if not t.done():
            t.cancel()
    _inflight_factory_tasks.clear()
    # Clear the manual-mode holding dict and push a fresh (empty) snapshot
    # to every SSE subscriber so the Revenue Guardian Tax Authority page
    # drops all the stale rows immediately instead of keeping them around
    # until the next individual decide/run-agent event.
    _pending_investigations.clear()
    _broadcast_pending_update()
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
