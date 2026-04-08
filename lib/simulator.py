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
    Event-driven simulation loop — fires exactly one transaction at a time.

    For each event:
      1. Load the next unfired transaction.
      2. Compute the real-time delay proportional to the simulated time gap
         between the current clock and that event's timestamp.
      3. Sleep (in 50 ms slices so pause/speed changes take effect promptly).
      4. Advance the simulated clock to the event timestamp and fire it.

    Speed semantics: sim-minutes per real-second.
      120  → 2 sim-hours/real-sec  (~6 min for full March)
      1440 → 1 sim-day/real-sec    (~31 sec for full March)
    """
    from lib.database import get_next_sim_transaction, mark_fired, get_sim_counts

    state.total_count = get_sim_counts()["total"]

    _next_tx: dict | None = None      # pre-loaded next event
    _wait_start: float | None = None  # real monotonic time when we started waiting

    while True:
        await asyncio.sleep(0.05)

        if not state.running:
            # On pause: keep _next_tx so we resume on the same event,
            # but reset _wait_start so the inter-event delay restarts.
            _wait_start = None
            continue

        # ── Load next event if needed ──────────────────────────────────────────
        if _next_tx is None:
            _next_tx = get_next_sim_transaction()
            if _next_tx is None:
                state.sim_time = SIM_END_DT
                state.running  = False
                continue
            _wait_start = time.monotonic()

        elif _wait_start is None:
            # Resumed after a pause
            _wait_start = time.monotonic()

        # ── Compute real-time delay for this event ─────────────────────────────
        next_time = datetime.fromisoformat(_next_tx["transaction_date"])
        if next_time.tzinfo is None:
            next_time = next_time.replace(tzinfo=timezone.utc)

        sim_gap_sec   = max(0.0, (next_time - state.sim_time).total_seconds())
        real_delay_sec = max(0.05, sim_gap_sec / (state.speed * 60))

        if time.monotonic() - _wait_start < real_delay_sec:
            continue   # not yet — keep waiting

        # ── Fire ──────────────────────────────────────────────────────────────
        state.sim_time = next_time
        mark_fired([_next_tx["transaction_id"]])
        await fire_callback([_next_tx])
        state.fired_count += 1
        state.add_recent(_next_tx)
        _next_tx    = None
        _wait_start = None
