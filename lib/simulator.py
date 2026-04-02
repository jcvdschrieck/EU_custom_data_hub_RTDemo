"""
Simulation engine state (shared between FastAPI and the background task).

The simulation replays March-2026 transactions in chronological order.
Speed is expressed as simulated minutes per real second:
  - 120  → 2 sim-hours / real-sec → full March in ~6 real minutes (default)
  - 1440 → 1 sim-day   / real-sec → full March in ~31 real seconds
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from lib.config import DEFAULT_SPEED, SIM_END_DT, SIM_START_DT

# ── Shared state (protected by asyncio — all access from the same event loop) ──

class SimState:
    def __init__(self):
        self.running: bool      = False
        self.speed: float       = DEFAULT_SPEED   # sim-minutes / real-second
        self.sim_time: datetime = SIM_START_DT    # current simulated clock
        self.last_tick: float | None = None       # monotonic real time of last tick
        self.fired_count: int   = 0
        self.total_count: int   = 0
        self.recent: list[dict] = []              # last N transactions fired this session
        self._max_recent: int   = 200

    def reset(self) -> None:
        self.running    = False
        self.speed      = DEFAULT_SPEED
        self.sim_time   = SIM_START_DT
        self.last_tick  = None
        self.fired_count = 0
        self.recent     = []

    def add_recent(self, tx: dict) -> None:
        self.recent.insert(0, tx)
        if len(self.recent) > self._max_recent:
            self.recent.pop()

    def to_dict(self) -> dict:
        return {
            "running":      self.running,
            "speed":        self.speed,
            "sim_time":     self.sim_time.isoformat(),
            "fired_count":  self.fired_count,
            "total_count":  self.total_count,
            "pct_complete": round(
                (self.fired_count / self.total_count * 100) if self.total_count else 0,
                1,
            ),
            "finished": self.sim_time >= SIM_END_DT,
        }


state = SimState()


# ── Background asyncio task ────────────────────────────────────────────────────

async def simulation_loop(fire_callback) -> None:
    """
    Tick every 50 ms. When running, advance simulated time and fire any
    pending transactions whose timestamp has passed.

    fire_callback(rows) must be an async coroutine function that writes rows
    to the European Custom DB and pushes them to the live queue.
    """
    from lib.database import get_pending_sim_transactions, mark_fired, get_sim_counts

    state.total_count = get_sim_counts()["total"]

    while True:
        await asyncio.sleep(0.05)

        if not state.running:
            state.last_tick = None
            continue

        now = time.monotonic()
        if state.last_tick is None:
            state.last_tick = now
            continue

        # Advance simulated clock
        elapsed_real   = now - state.last_tick
        state.last_tick = now
        advance_sec     = elapsed_real * state.speed * 60    # speed is sim-min/real-sec
        state.sim_time  = state.sim_time + timedelta(seconds=advance_sec)

        if state.sim_time >= SIM_END_DT:
            state.sim_time = SIM_END_DT
            state.running  = False

        # Fetch due transactions from simulation DB
        up_to = state.sim_time.strftime("%Y-%m-%dT%H:%M:%S")
        pending = get_pending_sim_transactions(up_to, batch=5)

        if pending:
            ids = [r["transaction_id"] for r in pending]
            mark_fired(ids)
            await fire_callback(pending)
            state.fired_count += len(pending)
            for tx in pending:
                state.add_recent(tx)
