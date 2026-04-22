"""Shared configuration."""
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent.parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

EUROPEAN_CUSTOM_DB = DATA_DIR / "european_custom.db"
SIMULATION_DB      = DATA_DIR / "simulation.db"
INVESTIGATION_DB   = DATA_DIR / "investigation.db"
# Persistent seed of pre-existing open cases. Loaded into investigation.db
# at simulation start when the latter is empty. Built by
# scripts/build_seed_cases.py.
SEED_CASES_DB      = DATA_DIR / "seed_cases.db"
# Historical closed cases — the "past investigations" surface that powers
# the Previous Cases / retPct-based recommendations in the C&T UI. Same
# 3-table schema as investigation.db; all cases have Status = 'Closed'
# and Country_Destination = 'IE'. Built by lib.historical_seeder.
HISTORICAL_CASES_DB = DATA_DIR / "historical_cases.db"

API_PORT     = 8505
API_BASE_URL = f"http://localhost:{API_PORT}"

# Simulation time window
#
# All March-2026 source transactions are rescaled at seed time so their
# timestamps fall inside this 15-minute window starting at March 1st 00:00.
# That way ×1 playback runs in real time (1 sim-second per real-second) and
# the SIM TIME chip ticks visibly second-by-second through the 15-minute
# window instead of jumping across days.
SIM_START_STR = "2026-04-01T00:00:00"
SIM_END_STR   = "2026-04-01T00:15:00"
SIM_START_DT  = datetime.fromisoformat(SIM_START_STR).replace(tzinfo=timezone.utc)
SIM_END_DT    = datetime.fromisoformat(SIM_END_STR).replace(tzinfo=timezone.utc)
SIM_WINDOW_SECONDS = int((SIM_END_DT - SIM_START_DT).total_seconds())   # 900

# Speed: simulated seconds that advance per real second.
# ×1 plays the 15-sim-minute window in 15 real minutes (real-time playback).
#   ×1   →   1 sim-sec/real-sec → 15 sim-min in 15 real-min  (default)
#   ×10  →  10 sim-sec/real-sec → 15 sim-min in 1.5 real-min
#   ×100 → 100 sim-sec/real-sec → 15 sim-min in   9 real-sec
DEFAULT_SPEED = 1.0
MIN_SPEED     = 0.1
MAX_SPEED     = 100.0

QUEUE_SIZE = 30   # transactions shown in live queue
