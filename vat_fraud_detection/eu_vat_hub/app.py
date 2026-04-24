"""EU VAT Hub — Streamlit dashboard entry point (port 8502).

Start with:
    streamlit run app.py --server.port 8502
from the eu_vat_hub/ directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# Ensure lib/ is importable
sys.path.insert(0, str(Path(__file__).parent))

st.set_page_config(
    page_title="EU VAT Hub",
    page_icon="🇪🇺",
    layout="wide",
)

from lib.database import init_db, total_count
from lib.seeder import seed_if_empty

init_db()
if total_count() < 100:
    with st.spinner("Seeding EU invoice database — one-time setup (~15 s)…"):
        added = seed_if_empty()
    if added:
        st.toast(f"Seeded {added:,} records into the EU VAT database.", icon="✅")

pg = st.navigation([
    st.Page("pages/1_Overview.py",       title="Overview",        icon="🌍"),
    st.Page("pages/2_Invoice_Browser.py",title="Invoice Browser", icon="🗂️"),
    st.Page("pages/3_Analytics.py",      title="Analytics",       icon="📈"),
    st.Page("pages/4_Activity_Log.py",   title="Activity Log",    icon="📡"),
])
pg.run()
