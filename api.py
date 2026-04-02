"""
European Custom Data Hub — Real-Time Demo API
FastAPI backend on port 8505.

Endpoints
─────────
GET  /health
GET  /api/queue                     latest 30 live transactions
GET  /api/transactions              paginated historical query
GET  /api/metrics                   VAT aggregates with filters
GET  /api/alarms                    alarm list (active_only optional)
GET  /api/suspicious                last 50 suspicious transactions
GET  /api/agent-log                 agent processing history (with legislation_refs)
GET  /api/agent-processing          currently-processing transactions (in-memory)
GET  /api/ireland-queue             transactions forwarded to Ireland investigation
GET  /api/ireland-case/{tx_id}      full case detail (queue + agent log merged)
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

from lib.config import DEFAULT_SPEED, MIN_SPEED, MAX_SPEED, QUEUE_SIZE
from lib.database import (
    get_latest_transactions,
    get_transaction_count,
    get_vat_metrics,
    insert_transaction,
    query_transactions,
    reset_simulation_db,
    get_sim_counts,
    get_alarms,
    get_suspicious_transactions,
    expire_old_alarms,
    reset_alarms,
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

_live_queue:       deque[dict] = deque(maxlen=QUEUE_SIZE)
_live_alarms:      list[dict]  = []
_agent_processing: dict[str, dict] = {}   # tx_id → {seller, item, started_at}
_agent_queue:      asyncio.Queue   = None  # type: ignore — initialised in lifespan
_sse_queues:       set[asyncio.Queue] = set()  # SSE clients


# ── Simulation fire callback ──────────────────────────────────────────────────

async def _fire_transactions(rows: list[dict]) -> None:
    from lib.alarm_checker import check_alarm

    for row in rows:
        insert_transaction(row)

        alarm = check_alarm(row)
        if alarm:
            _live_alarms.insert(0, alarm)

        row["suspicious"] = 0
        if any(a["alarm_key"] == f"{row['seller_id']}|{row['buyer_country']}"
               for a in _live_alarms):
            row["suspicious"] = 1

        _live_queue.appendleft(row)

        # Push to SSE clients — one transaction at a time
        if _sse_queues:
            payload = _json.dumps(row)
            dead = set()
            for q in _sse_queues:
                try:
                    q.put_nowait(payload)
                except asyncio.QueueFull:
                    dead.add(q)
            _sse_queues.difference_update(dead)

        if row.get("suspicious") and _agent_queue is not None:
            alarm_context = next(
                (a for a in _live_alarms
                 if a["alarm_key"] == f"{row['seller_id']}|{row['buyer_country']}"),
                {},
            )
            _agent_queue.put_nowait({"tx": row, "alarm": alarm_context})

        # Small delay so each transaction arrives individually on the client
        await asyncio.sleep(0.12)

    if rows:
        expire_old_alarms(rows[-1]["transaction_date"][:19])


# ── Agent worker ──────────────────────────────────────────────────────────────

async def _agent_worker() -> None:
    import concurrent.futures
    from lib.agent_bridge import analyse_transaction_sync

    loop = asyncio.get_event_loop()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=2)

    while True:
        item  = await _agent_queue.get()
        tx    = item["tx"]
        alarm = item["alarm"]
        tx_id = tx["transaction_id"]

        # Mark as in-progress for the /api/agent-processing endpoint
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
            sent_to_ireland  = 1 if verdict == "incorrect" else 0

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
                "sent_to_ireland":  sent_to_ireland,
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
    sim_task   = asyncio.create_task(simulation_loop(_fire_transactions))
    agent_task = asyncio.create_task(_agent_worker())
    yield
    sim_task.cancel()
    agent_task.cancel()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="European Custom Data Hub — RTDemo",
    version="2.1.0",
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
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
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


# ── Agent log & processing ────────────────────────────────────────────────────

@app.get("/api/agent-log")
def api_agent_log(limit: int = Query(100, ge=1, le=500)):
    return get_agent_log(limit=limit)


@app.get("/api/agent-processing")
def api_agent_processing():
    """In-memory snapshot of transactions currently being analysed."""
    return list(_agent_processing.values())


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

@app.get("/api/simulation/status")
def sim_status():
    counts = get_sim_counts()
    s = state.to_dict()
    s.update(counts)
    s["active_alarms"]       = len(get_alarms(active_only=True))
    s["agent_queue_len"]     = _agent_queue.qsize() if _agent_queue else 0
    s["agent_processing"]    = len(_agent_processing)
    return s


@app.post("/api/simulation/start")
def sim_start():
    from lib.config import SIM_END_DT
    if state.sim_time >= SIM_END_DT:
        return {"ok": False, "reason": "simulation already finished — reset first"}
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
    state.reset()
    reset_simulation_db()
    reset_alarms()
    _live_queue.clear()
    _live_alarms.clear()
    _agent_processing.clear()
    # Notify SSE clients to clear their local queue
    for q in list(_sse_queues):
        try:
            q.put_nowait("__reset__")
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


# ── Ireland app static files (must be last) ───────────────────────────────────

_ireland_app_dir = Path(__file__).parent / "ireland_app"
if _ireland_app_dir.exists():
    app.mount("/ireland-app", StaticFiles(directory=str(_ireland_app_dir), html=True),
              name="ireland_app")
