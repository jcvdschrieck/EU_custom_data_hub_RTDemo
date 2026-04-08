"""
European Custom Data Hub — Real-Time Demo API  (v4.0)
FastAPI backend on port 8505.

Message flow (publish-subscribe)
─────────────────────────────────────────────────────────────────────────────

 Simulation loop
     │  publishes each raw transaction (120 ms inter-message delay)
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
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from lib.broker import (
    broker,
    SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
    RT_SCORE, ORDER_VALIDATION, ARRIVAL_NOTIFICATION, RELEASE_EVENT,
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

# ── In-memory state ───────────────────────────────────────────────────────────

_live_queue:       deque[dict]        = deque(maxlen=QUEUE_SIZE)
_live_alarms:      list[dict]         = []
_agent_processing: dict[str, dict]    = {}   # tx_id → snapshot while analysing
_sse_queues:       set[asyncio.Queue] = set()
_agent_queue:      asyncio.Queue | None = None  # populated by POST /api/agent/analyse


# ── Simulation: publish to Sales-order Event Broker ──────────────────────────

async def _fire_transactions(rows: list[dict]) -> None:
    """
    Entry point called by the simulation loop (always called with a single row).
    Publishes the transaction to the Sales-order Event Broker.
    Inter-event pacing is handled entirely by the simulation loop.
    """
    for row in rows:
        await broker.publish(SALES_ORDER_EVENT, row)


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
    Checks whether the (seller_id, buyer_country) pair appears in the
    configured watchlist (lib/watchlist.py).
    Publishes outcome to RT_risk_monitoring_2_outcome_broker.
    """
    from lib.watchlist import is_watchlisted

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

        flagged = is_watchlisted(tx["seller_id"], tx["buyer_country"])

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
    known country code).  Produces a copy of the sales order enriched
    with a validation_flag and any validation_errors.
    Publishes to Order_validation_broker.
    """
    from lib.catalog import COUNTRIES

    q = broker.subscribe(SALES_ORDER_EVENT)
    while True:
        tx = await q.get()

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
            "tx":               tx,
            "validated":        len(errors) == 0,
            "validation_errors": errors,
        })


# ── Arrival Notification Factory ─────────────────────────────────────────────

async def _arrival_notification_factory() -> None:
    """
    Subscribes to Sales-order Event Broker.
    For each sales order, schedules an arrival notification after an
    exponentially-distributed sim-time delay (mean = 12 sim-hours, cap 48h).
    Monitors state.sim_time and publishes to ARRIVAL_NOTIFICATION when due.
    No visual link to the sales order broker is shown in the UI.
    """
    import random
    from lib.simulator import state as _state

    MEAN_SIM_HOURS = 12.0
    MAX_SIM_HOURS  = 48.0

    # pending: list of (target_sim_datetime, payload)
    pending: list[tuple[datetime, dict]] = []

    q = broker.subscribe(SALES_ORDER_EVENT)

    async def _schedule_listener():
        while True:
            tx = await q.get()
            tx_time_str = tx.get("transaction_date", "")
            try:
                tx_time = datetime.fromisoformat(tx_time_str)
                if tx_time.tzinfo is None:
                    tx_time = tx_time.replace(tzinfo=timezone.utc)
            except Exception:
                tx_time = _state.sim_time
            delay_hours = min(random.expovariate(1.0 / MEAN_SIM_HOURS), MAX_SIM_HOURS)
            from datetime import timedelta
            target_time = tx_time + timedelta(hours=delay_hours)
            payload = {
                "sales_order_id":   tx.get("transaction_id") or tx.get("sales_order_id"),
                "transaction_id":   tx.get("transaction_id") or tx.get("sales_order_id"),
                "arrival_notif_at": target_time.isoformat(),
                "seller_id":        tx.get("seller_id"),
                "buyer_country":    tx.get("buyer_country"),
            }
            pending.append((target_time, payload))

    async def _clock_emitter():
        while True:
            await asyncio.sleep(0.1)
            if not _state.running:
                continue
            now = _state.sim_time
            due = [(t, p) for (t, p) in pending if t <= now]
            for item in due:
                pending.remove(item)
                await broker.publish(ARRIVAL_NOTIFICATION, item[1])

    await asyncio.gather(_schedule_listener(), _clock_emitter())


# ── Release Factory ───────────────────────────────────────────────────────────

async def _release_factory() -> None:
    """
    Subscribes to Order_validation_broker, RT_score_broker, and
    Arrival_notification_broker.
    Correlates all three by transaction_id and publishes to Release_Event_Broker.
    """
    _buffer: dict[str, dict] = {}

    async def _emit_if_ready(tx_id: str) -> None:
        entry = _buffer.get(tx_id, {})
        if "validation" not in entry or "score" not in entry or "arrival" not in entry:
            return
        del _buffer[tx_id]

        val   = entry["validation"]
        score = entry["score"]

        await broker.publish(RELEASE_EVENT, {
            "tx":               val["tx"],
            "validated":        val["validated"],
            "validation_errors": val["validation_errors"],
            "risk_score":       score["risk_score"],
            "risk_1_flagged":   score["risk_1_flagged"],
            "risk_2_flagged":   score["risk_2_flagged"],
            "alarm_id":         score["alarm_id"],
            "alarm":            score["alarm"],
        })

    async def _drain_validation() -> None:
        q = broker.subscribe(ORDER_VALIDATION)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            _buffer.setdefault(tx_id, {})["validation"] = item
            await _emit_if_ready(tx_id)

    async def _drain_score() -> None:
        q = broker.subscribe(RT_SCORE)
        while True:
            item = await q.get()
            tx_id = item["tx"]["transaction_id"]
            _buffer.setdefault(tx_id, {})["score"] = item
            await _emit_if_ready(tx_id)

    async def _drain_arrival() -> None:
        q = broker.subscribe(ARRIVAL_NOTIFICATION)
        while True:
            item = await q.get()
            tx_id = item.get("transaction_id") or item.get("sales_order_id")
            if tx_id:
                _buffer.setdefault(tx_id, {})["arrival"] = item
                await _emit_if_ready(tx_id)

    await asyncio.gather(_drain_validation(), _drain_score(), _drain_arrival())


# ── DB Store Worker (subscriber of Release_Event_Broker) ─────────────────────

async def _db_store_worker() -> None:
    """
    Subscriber of Release_Event_Broker.
    Persists the fully validated and scored transaction in the European
    Custom DB, then updates the in-memory live queue and SSE clients.
    If risk_score is amber or red the suspicious flag is set via identifier.
    """
    q = broker.subscribe(RELEASE_EVENT)
    while True:
        msg = await q.get()
        tx         = msg["tx"]
        risk_score = msg["risk_score"]
        alarm_id   = msg.get("alarm_id")

        insert_transaction(tx)

        if risk_score in ("amber", "red"):
            flag_transaction_suspicious(tx["transaction_id"], alarm_id, risk_score)

        # Enrich row for live queue and SSE
        row = dict(tx)
        row["suspicious"]    = 1 if risk_score in ("amber", "red") else 0
        row["risk_score"]    = risk_score
        row["risk_1_flagged"] = msg["risk_1_flagged"]
        row["risk_2_flagged"] = msg["risk_2_flagged"]
        _live_queue.appendleft(row)

        if _sse_queues:
            payload = _json.dumps(row)
            dead = set()
            for sse_q in _sse_queues:
                try:
                    sse_q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.add(sse_q)
            _sse_queues.difference_update(dead)


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
    global _agent_queue
    from lib.database import init_european_custom_db, init_simulation_db
    init_european_custom_db()
    init_simulation_db()

    _agent_queue = asyncio.Queue()

    asyncio.create_task(simulation_loop(_fire_transactions))
    asyncio.create_task(_RT_risk_monitoring_1_factory())
    asyncio.create_task(_RT_risk_monitoring_2_factory())
    asyncio.create_task(_RT_consolidation_factory())
    asyncio.create_task(_order_validation_factory())
    asyncio.create_task(_arrival_notification_factory())
    asyncio.create_task(_release_factory())
    asyncio.create_task(_db_store_worker())
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


# ── Simulation control ────────────────────────────────────────────────────────

@app.get("/api/simulation/pipeline")
def sim_pipeline():
    """Return per-topic event counts (persisted files) and live broker queue sizes."""
    from lib.event_store import event_count, count_field_value
    from lib.broker import (
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ARRIVAL_NOTIFICATION, RELEASE_EVENT,
        broker as _broker,
    )
    topics = [
        SALES_ORDER_EVENT, RT_RISK_1_OUTCOME, RT_RISK_2_OUTCOME,
        RT_SCORE, ORDER_VALIDATION, ARRIVAL_NOTIFICATION, RELEASE_EVENT,
    ]
    return {
        "events": {t: event_count(t) for t in topics},
        "queues": {t: _broker.qsize(t) for t in topics},
        "stored_count": get_transaction_count(),
        "risk_flags": {
            "rt_risk_1_flagged": count_field_value(RT_RISK_1_OUTCOME, "flagged", True),
            "rt_risk_2_flagged": count_field_value(RT_RISK_2_OUTCOME, "flagged", True),
            "rt_score_green":    count_field_value(RT_SCORE, "risk_score", "green"),
            "rt_score_amber":    count_field_value(RT_SCORE, "risk_score", "amber"),
            "rt_score_red":      count_field_value(RT_SCORE, "risk_score", "red"),
        },
    }


@app.get("/api/simulation/status")
def sim_status():
    counts = get_sim_counts()
    s = state.to_dict()
    s.update(counts)
    s["active_alarms"]    = len(get_alarms(active_only=True))
    s["agent_queue_len"]  = _agent_queue.qsize() if _agent_queue else 0
    s["agent_processing"] = len(_agent_processing)
    return s


@app.post("/api/simulation/start")
def sim_start():
    from lib.config import SIM_END_DT
    from lib.event_store import flush_events
    if state.sim_time >= SIM_END_DT:
        return {"ok": False, "reason": "simulation already finished — reset first"}
    # Flush persisted events on first launch (fired_count == 0).
    # Pause → resume does not flush (fired_count > 0 at that point).
    if state.fired_count == 0:
        flush_events()
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
    state.reset()
    reset_simulation_db()
    reset_alarms()          # removes March+ rows, keeps Sep–Feb history
    flush_events()
    # Re-seed historical data if it was wiped (e.g. first run or manual DB delete)
    if historical_transaction_count() == 0:
        seed_european_custom_db()
    _live_queue.clear()
    _live_alarms.clear()
    _agent_processing.clear()
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
