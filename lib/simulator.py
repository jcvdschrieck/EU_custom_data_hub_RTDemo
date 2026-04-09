"""
Simulation engine state (shared between FastAPI and the background task).

The simulation replays the (rescaled) March-2026 transactions in chronological
order. All source timestamps are compressed at seed time into a 15-sim-minute
window, so speed is expressed as simulated **seconds** per real second:
  - 1    → 15 sim-min in 15 real-min   (real-time, default)
  - 10   → 15 sim-min in  1.5 real-min
  - 100  → 15 sim-min in  ~9 real-sec
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
    Continuous-clock simulation loop.

    On every tick (~50 ms):
      1. Advance state.sim_time by `(real elapsed since last tick) × state.speed`,
         so the simulated clock keeps moving forward smoothly even between
         events — the SIM TIME chip never freezes during quiet periods.
      2. Fire every pending event whose timestamp the clock has now reached
         (zero, one, or many per tick — at high speeds we can cross several
         events in a single 50 ms slice).
      3. Once all events are fired, keep advancing until SIM_END_DT and stop.

    On pause (`state.running == False`) the wall-clock anchor is dropped, so
    paused real-time does not count toward sim-time advance after resume.
    Speed changes take effect on the very next tick (max ~50 ms latency).

    Speed semantics: sim-seconds per real-second.
      1   → real-time playback (15 sim-min in 15 real-min)
      10  → 10× faster than real-time
      100 → 100× faster than real-time
    """
    from lib.database import get_next_sim_transaction, mark_fired, get_sim_counts

    state.total_count = get_sim_counts()["total"]

    _next_tx: dict | None    = None   # pre-loaded next event
    _last_real: float | None = None   # monotonic real time of the previous tick

    while True:
        await asyncio.sleep(0.05)

        if not state.running:
            # On pause: drop the wall-clock anchor so paused time isn't credited
            # to sim-time advance after resume. Keep _next_tx so we resume on
            # the same event.
            _last_real = None
            continue

        # ── Continuously advance sim_time ──────────────────────────────────────
        now = time.monotonic()
        if _last_real is None:
            _last_real = now
        real_dt    = now - _last_real
        _last_real = now
        if real_dt > 0:
            state.sim_time = state.sim_time + timedelta(seconds=real_dt * state.speed)
            if state.sim_time > SIM_END_DT:
                state.sim_time = SIM_END_DT

        # ── Fire every event whose timestamp has been reached ─────────────────
        while True:
            if _next_tx is None:
                _next_tx = get_next_sim_transaction()
                if _next_tx is None:
                    # No more events. Stop once the clock has reached the end.
                    if state.sim_time >= SIM_END_DT:
                        state.running = False
                    break

            next_time = datetime.fromisoformat(_next_tx["transaction_date"])
            if next_time.tzinfo is None:
                next_time = next_time.replace(tzinfo=timezone.utc)

            if state.sim_time < next_time:
                break   # not yet — wait for the clock to catch up

            mark_fired([_next_tx["transaction_id"]])
            await fire_callback([_next_tx])
            state.fired_count += 1
            state.add_recent(_next_tx)
            _next_tx = None
