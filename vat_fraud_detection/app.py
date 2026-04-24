"""Entry point — configures the Streamlit multipage navigation."""
from __future__ import annotations

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="VAT Compliance Checker",
    page_icon="🧾",
    layout="wide",
)

# Ensure data directories exist (runs on every page load)
for _d in ["data/legislation", "data/chroma_db"]:
    Path(_d).mkdir(parents=True, exist_ok=True)
_history_file = Path("data/history.json")
if not _history_file.exists():
    _history_file.write_text("[]", encoding="utf-8")

pg = st.navigation([
    st.Page("pages/1_Invoice_Analyzer.py",        title="Invoice Analyzer",          icon="🧾"),
    st.Page("pages/2_Prioritization_Dashboard.py", title="Prioritization Dashboard",  icon="📊"),
    st.Page("pages/3_Case_View.py",               title="Case View",                 icon="🔍"),
    st.Page("pages/4_History.py",                  title="History",                   icon="📋"),
    st.Page("pages/5_EU_Query.py",                title="EU Query",                  icon="🌍"),
])
pg.run()
