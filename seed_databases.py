#!/usr/bin/env python3
"""
Seed both databases. Run once before launching the API and dashboard.

    python seed_databases.py
"""
import sys
import time


def main():
    print("European Custom Data Hub — Database Seeder")
    print("=" * 50)

    from lib.seeder             import seed_european_custom_db
    from lib.new_seeder          import seed_simulation_db_from_xlsx
    from lib.historical_seeder   import seed_historical_cases_db
    from lib.config              import EUROPEAN_CUSTOM_DB, SIMULATION_DB, HISTORICAL_CASES_DB

    # ── European Custom DB (historical: Sep 2025 – Feb 2026) ──────────────────
    print(f"\n[1/3] Seeding European Custom Database ({EUROPEAN_CUSTOM_DB.name})…")
    t0 = time.perf_counter()
    n1 = seed_european_custom_db()
    print(f"      ✓ {n1:,} transactions inserted ({time.perf_counter()-t0:.1f}s)")

    # ── Simulation DB (April 1st 2026 — 15-min window from xlsx) ──────────────
    print(f"\n[2/3] Seeding Simulation Database ({SIMULATION_DB.name}) from xlsx…")
    t0 = time.perf_counter()
    n2 = seed_simulation_db_from_xlsx()
    print(f"      ✓ {n2:,} transactions inserted ({time.perf_counter()-t0:.1f}s)")

    # ── Historical cases (IE closed) — reference data for /previous ──────────
    print(f"\n[3/3] Seeding Historical Cases ({HISTORICAL_CASES_DB.name})…")
    t0 = time.perf_counter()
    n3 = seed_historical_cases_db()
    print(f"      ✓ {n3} cases inserted ({time.perf_counter()-t0:.1f}s)")

    print(f"\nDone. Total: {n1+n2:,} transactions + {n3} historical cases.")
    print("\nNext steps:")
    print("  Terminal 1: uvicorn api:app --port 8505")
    print("  Terminal 2: streamlit run app.py --server.port 8501")


if __name__ == "__main__":
    main()
